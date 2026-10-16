"""Папка или ZIP-архив брендбука → `BrandSpec`.

В папке ищется всё сразу:
- токены JSON (`tokens.py`) — самый точный источник цветов, шрифтов и полей;
- PDF-гайдлайн (`pdf.py`) — цвета, шрифты и правила по тексту;
- пример презентации или шаблон PPTX/POTX — тема (цвета clrScheme и шрифты fontScheme), как при анализе шаблона;
- логотипы SVG/PNG/JPG — по папке или имени («logos/», «logo-white.svg», «знак.png»); версия (основной, белый, знак,
  монохром) — по словам в имени, иначе по самой картинке;
- примеры слайдов PNG/JPG — палитра по картинке (только если цветов нет ни в токенах, ни в PDF, ни в теме).

Источники сводятся по старшинству: токены → PDF → тема PPTX → картинки; правила собираются из всех без повторов.
Архив распаковывается во временную папку с проверкой путей и размера."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from verstka.brand.common import (
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    make_fonts,
    make_palette,
    name_from_path,
    rgb_distance,
    rgb_hex,
)
from verstka.schemas.brand import BrandLogo, BrandRule, BrandSpec

_IMAGE_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
_PPTX_EXT = {".pptx", ".potx", ".pptm"}
_LOGO_WORDS = re.compile(r"(?<![a-z])(logos?|logotypes?|lockups?|wordmarks?|emblems?|brandmark|marks?)(?![a-z])|логотип\w*|эмблем\w*|знак\w*", re.I)
_SLIDE_WORDS = re.compile(r"(?<![a-z])(slides?|examples?|samples?|mockups?|layouts?|screens?)(?![a-z])|слайд\w*|пример\w*|макет\w*", re.I)
_VARIANTS: list[tuple[str, str, re.Pattern]] = [
    ("white", "dark", re.compile(r"(?<![a-z])(white|negative|inverse|inverted|reversed?|knockout|on[\s_-]?dark)(?![a-z])|бел\w*|инверс\w*|негатив\w*", re.I)),
    ("mono", "light", re.compile(r"(?<![a-z])(mono\w*|black|blk|one[\s_-]?colou?r|grayscale|greyscale)(?![a-z])|монохром\w*|ч[её]рн\w*|одноцвет\w*", re.I)),
    ("mark", "any", re.compile(r"(?<![a-z])(mark|sign|symbol|icon|favicon|avatar|glyph)(?![a-z])|знак\w*|символ\w*|иконк\w*", re.I)),
    ("primary", "light", re.compile(r"(?<![a-z])(primary|main|default|colou?r|full|horizontal|basic)(?![a-z])|основн\w*|цветн\w*|горизонт\w*", re.I)),
]
LOGO_NAMES = {"primary": "Основной", "white": "Белый", "mark": "Знак", "mono": "Монохром"}
_MAX_FILES = 1000
_MAX_ZIP_FILES = 2000
_MAX_ZIP_BYTES = 300 * 1024 * 1024
# стандартные темы Office — не цвета бренда
_STOCK_ACCENTS = {("4472C4", "ED7D31"), ("4F81BD", "C0504D"), ("156082", "E97132"), ("5B9BD5", "ED7D31")}


# ---- логотипы ------------------------------------------------------------------------------------------------------------
def _svg_variant(path: Path) -> tuple[str, str]:
    """Версия SVG-логотипа по заливкам и пропорциям: все заливки белые — белый, один тёмный цвет — монохром."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "primary", "light"
    fills = {m.upper() for m in re.findall(r"(?:fill|stop-color)\s*[:=]\s*[\"']?\s*#([0-9A-Fa-f]{6})", text)}
    fills |= {"".join(c * 2 for c in m).upper() for m in re.findall(r"(?:fill|stop-color)\s*[:=]\s*[\"']?\s*#([0-9A-Fa-f]{3})(?![0-9A-Fa-f])", text)}
    vb = re.search(r"viewBox\s*=\s*[\"']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)", text)
    square = bool(vb) and 0.8 <= float(vb.group(1)) / max(float(vb.group(2)), 1e-6) <= 1.25
    if fills and all(f in ("FFFFFF", "FFF") for f in fills):
        return "white", "dark"
    if fills and len(fills) == 1 and not square:
        f = "#" + next(iter(fills))
        r, g, b = (int(f[i:i + 2], 16) for i in (1, 3, 5))
        if max(r, g, b) - min(r, g, b) <= 60 and max(r, g, b) <= 90:
            return "mono", "light"
    if square:
        return "mark", "any"
    return "primary", "light"


def logo_variant_of(path: Path) -> tuple[str, str]:
    """Версия логотипа: по словам в имени файла («white», «знак»), иначе по картинке."""
    stem = path.stem
    for variant, ground, rx in _VARIANTS:
        if rx.search(stem):
            return variant, ground
    if path.suffix.lower() == ".svg":
        return _svg_variant(path)
    try:
        from PIL import Image

        from verstka.brand.pdf import logo_variant

        with Image.open(path) as im:
            return logo_variant(im)
    except Exception:  # noqa: BLE001 — не картинка: считаем основным
        return "primary", "light"


def _is_logo(rel: PurePosixPath, path: Path) -> bool:
    if any(_LOGO_WORDS.search(p) for p in rel.parts):
        return True
    if any(_SLIDE_WORDS.search(p) for p in rel.parts):
        return False
    if path.suffix.lower() == ".svg":
        return True
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            alpha = "A" in im.getbands() or "transparency" in im.info
    except Exception:  # noqa: BLE001
        return False
    slide_like = w >= 800 and 1.2 <= w / max(h, 1) <= 2.0 and not alpha
    return not slide_like


def _collect_logos(logo_files: list[tuple[PurePosixPath, Path]], assets_dir: Optional[Path]) -> list[BrandLogo]:
    """Один логотип на пару «имя.svg + имя.png» (в презентацию вставляется PNG); не больше восьми."""
    by_stem: dict[tuple[str, str], list[tuple[PurePosixPath, Path]]] = {}
    for rel, p in logo_files:
        by_stem.setdefault((str(rel.parent), p.stem.lower()), []).append((rel, p))
    out: list[BrandLogo] = []
    used: dict[str, int] = {}
    if assets_dir is not None:
        (assets_dir / "logos").mkdir(parents=True, exist_ok=True)
    for group in by_stem.values():
        if len(out) >= 8:
            break
        group.sort(key=lambda x: {".png": 0, ".svg": 1}.get(x[1].suffix.lower(), 2))
        rel, p = group[0]
        variant, ground = logo_variant_of(p)  # растр — по картинке надёжнее, чем разбор заливок SVG
        used[variant] = used.get(variant, 0) + 1
        name = LOGO_NAMES[variant] + ("" if used[variant] == 1 else f" {used[variant]}")
        file = rel.as_posix()
        if assets_dir is not None:
            target = assets_dir / "logos" / p.name
            k = 2
            while target.exists():
                target = assets_dir / "logos" / f"{p.stem}-{k}{p.suffix}"
                k += 1
            shutil.copyfile(p, target)
            file = f"logos/{target.name}"
        out.append(BrandLogo(name=name, file=file, variant=variant, ground=ground))  # type: ignore[arg-type]
    order = {"primary": 0, "white": 1, "mark": 2, "mono": 3}
    out.sort(key=lambda lg: order.get(lg.variant, 9))
    return out


# ---- картинки и тема -----------------------------------------------------------------------------------------------------------
def image_colors(path: Path, *, max_colors: int = 8) -> list[tuple[str, float]]:
    """Основные цвета картинки (HEX, доля площади). Пиксели считаются как есть (уменьшение без сглаживания), близкие
    сливаются к самому частому; полутона краёв букв и линий встречаются редко и отсекаются порогом."""
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        step = max(1, max(im.size) // 480)
        small = im.resize((max(1, im.width // step), max(1, im.height // step)), Image.NEAREST)
    counts = sorted(small.getcolors(maxcolors=small.width * small.height) or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    clusters: list[list] = []  # [hex, count]
    for cnt, rgb in counts:
        hx = rgb_hex(*rgb)
        k = next((c for c in clusters if rgb_distance(c[0], hx) < 30), None)
        if k is not None:
            k[1] += cnt
        elif cnt / total >= 0.0015:
            clusters.append([hx, cnt])
    return [(hx, cnt / total) for hx, cnt in clusters[:max_colors]]


def slides_palette(paths: list[Path]) -> list[ColorHit]:
    merged: list[tuple[str, float]] = []
    for p in paths[:12]:
        try:
            cols = image_colors(p)
        except Exception:  # noqa: BLE001
            continue
        for hx, share in cols:
            k = next((i for i, (h, _) in enumerate(merged) if rgb_distance(h, hx) < 40), None)
            if k is None:
                merged.append((hx, share))
            else:
                merged[k] = (merged[k][0], merged[k][1] + share)
    merged.sort(key=lambda x: -x[1])
    return [ColorHit(hx) for hx, _ in merged[:6]]


def pptx_theme(path: Path) -> tuple[list[ColorHit], list[FontHit], list[str]]:
    """Тема примера PPTX/POTX: цвета схемы (dk1 — текст, lt1 — фон, accent1 — основной, accent2 — акцент, accent3–6 —
    графики) и шрифты (major — заголовки, minor — текст). Стандартная тема Office пропускается."""
    from verstka.analysis.theme import ThemeResolver
    from verstka.ingest.package import PptxPackage

    try:
        pkg = PptxPackage.open(path)
    except (zipfile.BadZipFile, OSError, KeyError):
        return [], [], [f"«{path.name}» не открылся как презентация — пропустил."]
    with pkg:
        masters = pkg.master_parts
        if not masters:
            return [], [], [f"В «{path.name}» нет мастер-слайдов — пропустил."]
        th = ThemeResolver(pkg, masters[0])
        sc = th.scheme
        if (sc.get("accent1", ""), sc.get("accent2", "")) in _STOCK_ACCENTS:
            return [], [], [f"В «{path.name}» стандартная тема Office — цвета и шрифты из неё не взял."]
        roles = [("accent1", "primary"), ("dk1", "text"), ("lt1", "background"), ("accent2", "accent"), ("accent3", "chart"),
                 ("accent4", "chart"), ("accent5", "chart"), ("accent6", "chart"), ("dk2", "neutral"), ("lt2", "surface")]
        colors = [ColorHit("#" + sc[k], role) for k, role in roles if sc.get(k)]  # type: ignore[arg-type]
        fonts = [FontHit(th.major_font, "heading"), FontHit(th.minor_font, "body")]
        return colors, fonts, []


# ---- сборка ---------------------------------------------------------------------------------------------------------------------
def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part.startswith(".") or part.startswith("__MACOSX") or part.startswith("~$") for part in rel.parts):
            continue
        if len(rel.parts) > 6 or not p.is_file():
            continue
        out.append(p)
        if len(out) >= _MAX_FILES:
            break
    return out


def read_collection(files: list[Path], base: Path, *, label: str, providers: Any = None, skills: Any = None,
                    use_vlm: bool = False, assets_dir: Optional[Path | str] = None, guess_name: bool = True) -> BrandSpec:
    """Набор файлов брендбука (папка, архив или один файл) → `BrandSpec`; пути логотипов — относительно `base`.
    `guess_name` — брать имя бренда из имени папки или архива, если его нет внутри (у одной картинки — нет)."""
    from verstka.brand.pdf import read_pdf
    from verstka.brand.tokens import read_tokens

    assets = Path(assets_dir) if assets_dir is not None else None
    warnings: list[str] = []
    specs: list[BrandSpec] = []  # по старшинству: токены, затем PDF
    theme_colors: list[ColorHit] = []
    theme_fonts: list[FontHit] = []
    logo_files: list[tuple[PurePosixPath, Path]] = []
    slide_images: list[Path] = []
    pdfs: list[Path] = []

    def rel(p: Path) -> PurePosixPath:
        try:
            return PurePosixPath(p.relative_to(base).as_posix())
        except ValueError:
            return PurePosixPath(p.name)

    for p in files:
        ext = p.suffix.lower()
        if ext == ".json":
            try:
                specs.append(read_tokens(p))
            except BrandReadError as e:
                warnings.append(f"«{rel(p)}»: {e}")
        elif ext == ".pdf":
            pdfs.append(p)
        elif ext in _PPTX_EXT:
            c, f, w = pptx_theme(p)
            warnings += w
            if c and not theme_colors:
                theme_colors, theme_fonts = c, f
        elif ext in _IMAGE_EXT:
            if _is_logo(rel(p), p):
                logo_files.append((rel(p), p))
            else:
                slide_images.append(p)
    pdf_spec: Optional[BrandSpec] = None
    for p in pdfs:
        try:
            s = read_pdf(p, providers=providers, skills=skills, use_vlm=use_vlm,
                         assets_dir=assets if (assets is not None and not logo_files) else None)
        except BrandReadError as e:
            warnings.append(f"«{rel(p)}»: {e}")
            continue
        if pdf_spec is None:
            pdf_spec = s
        specs.append(s)

    colors = next((s.colors for s in specs if s.colors), [])
    fonts = next((s.fonts for s in specs if s.fonts), [])
    if not colors and theme_colors:
        colors, w = make_palette(theme_colors)
        warnings += w
    if not fonts and theme_fonts:
        fonts, _ = make_fonts(theme_fonts)
    if not colors and slide_images:
        colors, _ = make_palette(slides_palette(slide_images))
        if colors:
            warnings.append("Цвета сняты с картинок примеров слайдов, роли угаданы по яркости — проверьте.")
    for s in specs:
        warnings += s.warnings
    rules: list[BrandRule] = []
    for s in specs:
        for r in s.rules:
            add_rule(rules, r.text, r.kind, limit=14)
    logos = _collect_logos(logo_files, assets)
    if not logos and pdf_spec is not None:
        logos = list(pdf_spec.logos)
    first = lambda attr: next((getattr(s, attr) for s in specs if getattr(s, attr)), None)  # noqa: E731
    name = first("name") or (name_from_path(Path(label).stem) if guess_name else None) or ""
    if not colors and not fonts and not logos:
        raise BrandReadError(
            f"В «{label}» не нашёл брендбука: нужны токены JSON, PDF-гайдлайн, логотипы SVG или PNG либо примеры слайдов."
        )
    if not colors:
        warnings.append("Цветов в брендбуке нет — палитра останется из шаблона.")
    if not fonts:
        warnings.append("Шрифтов в брендбуке нет — шрифты останутся из шаблона.")
    seen: set[str] = set()
    warnings = [w for w in warnings if not (w in seen or seen.add(w))]
    return BrandSpec(
        name=name,
        source="folder",
        file=label,
        pages=pdf_spec.pages if pdf_spec else 0,
        colors=colors,
        fonts=fonts,
        logos=logos,
        margins_px=first("margins_px"),
        grid=first("grid"),
        rules=rules,
        logo_place=first("logo_place"),
        warnings=warnings,
    )


def read_folder(root: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
                assets_dir: Optional[Path | str] = None, label: Optional[str] = None, base: Optional[Path] = None) -> BrandSpec:
    root = Path(root)
    files = _walk(root)
    if not files:
        raise BrandReadError(f"Папка «{label or root.name}» пустая.")
    return read_collection(files, base or root, label=label or root.name, providers=providers, skills=skills,
                           use_vlm=use_vlm, assets_dir=assets_dir)


def read_zip(path: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
             assets_dir: Optional[Path | str] = None) -> BrandSpec:
    """ZIP с брендбуком: распаковка во временную папку (без путей вне архива, до 2000 файлов и 300 МБ), затем — как папка.
    Пути логотипов — внутри архива; с `assets_dir` логотипы копируются в `<assets_dir>/logos/`."""
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise BrandReadError(f"Архив «{path.name}» повреждён или это не ZIP.") from None
    with zf, tempfile.TemporaryDirectory(prefix="brandbook-") as tmp:
        root = Path(tmp)
        n, total = 0, 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if not parts or info.filename.startswith("/") or ".." in parts or any(p.startswith("__MACOSX") for p in parts):
                continue
            n += 1
            total += info.file_size
            if n > _MAX_ZIP_FILES or total > _MAX_ZIP_BYTES:
                raise BrandReadError(f"Архив «{path.name}» слишком большой: брендбук — до {_MAX_ZIP_FILES} файлов и 300 МБ.")
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    while chunk := src.read(1 << 20):
                        written += len(chunk)
                        if written > info.file_size + (1 << 20) or total - info.file_size + written > _MAX_ZIP_BYTES:
                            raise BrandReadError(f"Архив «{path.name}» слишком большой: брендбук — до 300 МБ.")
                        dst.write(chunk)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                raise BrandReadError(f"Архив «{path.name}» повреждён или защищён паролем.") from None
        if n == 0:
            raise BrandReadError(f"Архив «{path.name}» пустой.")
        tops = [p for p in root.iterdir() if not p.name.startswith(".")]
        start = tops[0] if len(tops) == 1 and tops[0].is_dir() else root
        spec = read_folder(start, providers=providers, skills=skills, use_vlm=use_vlm, assets_dir=assets_dir,
                           label=path.name, base=root)
    return spec
