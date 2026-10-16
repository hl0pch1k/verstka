"""`read_brandbook(source)` — брендбук любого вида → `BrandSpec`.

- ссылка на Figma → REST API (`FIGMA_TOKEN`), см. `figma.py`;
- папка → `folder.read_folder`; `.zip` → `folder.read_zip`;
- `.json` → токены (W3C, Tokens Studio, Style Dictionary, плоский, переменные Figma), см. `tokens.py`;
- `.pdf` → гайдлайн по тексту, с `use_vlm` — ещё и моделью по картинкам страниц, см. `pdf.py`;
- `.pptx` / `.potx`, `.svg` / `.png` / `.jpg` — как папка из одного файла (тема презентации, логотип);
- `.fig` и прочее — понятная ошибка.

Ошибки — `BrandReadError` с текстом для человека. `on_step(что, итог)` получает шаги разбора для интерфейса
(«открыт файл: 12 страниц», «палитра: 6 цветов», «шрифты: VK Sans Display, VK Sans Text», «логотипы: 4», «правила: 13»)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from verstka.brand.common import BrandReadError
from verstka.brand.figma import FIG_FILE, is_figma_url, read_figma_url
from verstka.brand.folder import read_collection, read_folder, read_zip
from verstka.brand.pdf import read_pdf
from verstka.brand.tokens import read_tokens
from verstka.ru import ru_count
from verstka.schemas.brand import BrandSpec

SUPPORTED = ".json, .pdf, .zip, .pptx, .potx, .svg, .png, .jpg, папка или ссылка на Figma"
_IMAGE_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
_SINGLE_FILE_EXT = {".pptx", ".potx", ".pptm"} | _IMAGE_EXT

StepCallback = Callable[[str, str], None]


def brand_steps(spec: BrandSpec) -> list[tuple[str, str]]:
    """Шаги разбора словами — для ленты «Разбираю брендбук…»: (что, итог)."""
    first = {
        "pdf": ("открыт файл", ru_count(spec.pages, "страница", "страницы", "страниц") if spec.pages else "PDF"),
        "tokens": ("прочитаны токены", "цвета, шрифты, отступы"),
        "folder": ("открыта папка" if not (spec.file or "").lower().endswith(".zip") else "открыт архив", "логотипы и примеры слайдов"),
        "figma": ("открыт файл Figma", "стили и переменные"),
    }[spec.source]
    fonts = ", ".join(dict.fromkeys(f.family for f in spec.fonts)) or "нет"
    return [
        first,
        ("палитра", ru_count(len(spec.colors), "цвет", "цвета", "цветов") if spec.colors else "нет"),
        ("шрифты", fonts),
        ("логотипы", str(len(spec.logos)) if spec.logos else "нет"),
        ("правила", str(len(spec.rules)) if spec.rules else "нет"),
    ]


def read_brandbook(source: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
                   assets_dir: Optional[Path | str] = None, on_step: Optional[StepCallback] = None,
                   figma_token: Optional[str] = None, figma_client: Any = None) -> BrandSpec:
    """Брендбук (файл, папка, архив или ссылка Figma) → `BrandSpec`.

    `use_vlm` — PDF уточняется моделью (`providers` с ролью vlm, `skills` — реестр навыков; без них — чтение по тексту).
    `assets_dir` — куда сложить логотипы (из PDF, папки или архива); пути в `BrandSpec.logos` — относительно неё.
    `figma_token` / `figma_client` — для ссылок Figma (по умолчанию `FIGMA_TOKEN` из окружения и настоящий HTTP)."""
    kw = dict(providers=providers, skills=skills, use_vlm=use_vlm, assets_dir=assets_dir)
    if isinstance(source, str) and re.match(r"^\s*[a-z][a-z0-9+.-]*://", source, re.I):
        url = source.strip()
        if not is_figma_url(url):
            raise BrandReadError("По ссылке читаю только файлы Figma. Другой брендбук загрузите файлом: PDF, JSON с токенами, "
                                 "папку или ZIP с логотипами и примерами слайдов.")
        spec = read_figma_url(url, token=figma_token, client=figma_client)
    else:
        path = Path(source)
        if not path.exists():
            raise BrandReadError(f"Не нашёл «{path.name}» — проверьте путь к брендбуку.")
        if path.is_dir():
            spec = read_folder(path, **kw)
        else:
            ext = path.suffix.lower()
            if ext == ".fig":
                raise BrandReadError(FIG_FILE)
            if path.stat().st_size == 0:
                raise BrandReadError(f"Файл «{path.name}» пустой.")
            if ext == ".json":
                spec = read_tokens(path)
            elif ext == ".pdf":
                spec = read_pdf(path, **kw)
            elif ext == ".zip":
                spec = read_zip(path, **kw)
            elif ext in _SINGLE_FILE_EXT:
                spec = read_collection([path], path.parent, label=path.name, guess_name=ext not in _IMAGE_EXT, **kw)
            else:
                raise BrandReadError(f"Формат «{ext or path.name}» для брендбука не подходит. Подойдут: {SUPPORTED}.")
    if not spec.colors and not spec.fonts and not spec.logos:
        raise BrandReadError("Не нашёл в брендбуке ни цветов, ни шрифтов, ни логотипов — проверьте файл.")
    if on_step is not None:
        for what, result in brand_steps(spec):
            on_step(what, result)
    return spec
