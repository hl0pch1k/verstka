"""Figma → `BrandSpec`: ссылка на файл (REST API с `FIGMA_TOKEN`) или экспорт переменных JSON.

По ссылке читаются переменные файла (`/v1/files/:key/variables/local` — цвета, шрифты, поля; доступны на тарифе Enterprise)
и стили (`/v1/files/:key` → `/v1/files/:key/nodes`: стили заливки — цвета, стили текста — шрифты). Роли — по именам
(«Brand/Primary», «Text/Default», «Heading/H1»). Токен — `FIGMA_TOKEN` в `.env` (Figma → Settings → Security → Personal access
tokens). Без токена и без доступа — понятная ошибка `BrandReadError`; файл `.fig` читает `fig.py` (без токена). Экспорт Tokens Studio читает
`tokens.py`; сюда приходит экспорт переменных (форма ответа REST или список переменных)."""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from verstka.brand.common import (
    PLACE_TEXT,
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    brand_name,
    color_role,
    font_role,
    grid_text,
    logo_place,
    looks_like_rule,
    make_fonts,
    make_palette,
    parse_color,
    usable_color_name,
    weight_of,
    words,
)
from verstka.schemas.brand import BrandRule, BrandSpec

API = "https://api.figma.com/v1"
# ссылки на файлы Figma: design, file (старый вид), proto, board (FigJam), slides, deck, make; у ветки — свой ключ
# («…/design/<ключ файла>/branch/<ключ ветки>/<название>»): читается ветка, а не основной файл
_URL_RE = re.compile(
    r"^https?://(?:[\w-]+\.)?figma\.com/(?:file|design|proto|board|slides|deck|make)/([A-Za-z0-9]{10,})(?:/branch/([A-Za-z0-9]{10,}))?", re.I
)
_HOST_RE = re.compile(r"^https?://(?:[\w-]+\.)?figma\.com/", re.I)
_STATE = re.compile(r"(?<![a-z])(hover|pressed|active|focus|disabled|overlay|shadow|border|stroke|divider)(?![a-z])")

NO_TOKEN = (
    "Чтобы прочитать файл Figma по ссылке, нужен токен доступа: добавьте FIGMA_TOKEN=… в файл .env "
    "(Figma → Settings → Security → Personal access tokens) и перезапустите Verstka. "
    "Без токена загрузите экспорт токенов JSON (Tokens Studio → Export или переменные Figma)."
)
FIG_FILE = (
    "Файл .fig — внутренний формат Figma, без самой Figma его не прочитать. Дайте ссылку на файл (нужен FIGMA_TOKEN) "
    "или экспортируйте токены в JSON: плагин Tokens Studio → Export или переменные Figma."
)


def normalize_url(s: object) -> Optional[str]:
    """Ссылка на Figma в привычном виде: пробелы, скобки «<…>», кавычки и отсутствие «https://» не мешают
    («figma.com/design/…» из адресной строки). Не ссылка на figma.com — None."""
    t = str(s).strip().strip("<>\"'«»").strip()
    if re.match(r"^(?:[\w-]+\.)?figma\.com/", t, re.I):
        t = "https://" + t
    return t if _HOST_RE.match(t) else None


def is_figma_url(s: str) -> bool:
    return normalize_url(s) is not None


def figma_key(url: str) -> str:
    """Ключ файла из ссылки; у ветки — ключ ветки (по нему REST API отдаёт именно ветку)."""
    m = _URL_RE.match(normalize_url(url) or "")
    if not m:
        raise BrandReadError("Не похоже на ссылку на файл Figma: нужна ссылка вида https://www.figma.com/design/<ключ>/<название>.")
    return m.group(2) or m.group(1)


# ---- переменные ---------------------------------------------------------------------------------------------------------
def _variables(data: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else data
    vars_ = meta.get("variables") or {}
    if isinstance(vars_, list):
        vars_ = {str(v.get("id") or i): v for i, v in enumerate(vars_) if isinstance(v, dict)}
    cols = meta.get("variableCollections") or meta.get("collections") or {}
    if isinstance(cols, list):
        cols = {str(c.get("id") or i): c for i, c in enumerate(cols) if isinstance(c, dict)}
    return vars_, cols


def _value(var: dict, vars_: dict, cols: dict, depth: int = 0) -> Any:
    """Значение переменной в режиме по умолчанию её коллекции; ссылки на другие переменные — раскрываются."""
    vbm = var.get("valuesByMode") or {}
    if not isinstance(vbm, dict) or not vbm:
        return var.get("value")
    col = cols.get(str(var.get("variableCollectionId"))) or {}
    mode = col.get("defaultModeId")
    v = vbm.get(mode) if mode in vbm else next(iter(vbm.values()))
    if isinstance(v, dict) and v.get("type") == "VARIABLE_ALIAS" and depth < 10:
        target = vars_.get(str(v.get("id")))
        return _value(target, vars_, cols, depth + 1) if target else None
    return v


class _Parts:
    """Что прочитано из переменных или стилей Figma — до сборки палитры и шрифтов."""

    def __init__(self) -> None:
        self.colors: list[ColorHit] = []
        self.fonts: list[FontHit] = []
        self.rules: list[BrandRule] = []
        self.margins: Optional[float] = None
        self.columns: Optional[int] = None
        self.gutter: Optional[float] = None
        self.place: Optional[str] = None


def _parse_variables(data: dict, parts: _Parts) -> None:
    vars_, cols = _variables(data)
    weights: dict[str, int] = {}
    fonts: list[FontHit] = []
    for var in vars_.values():
        if not isinstance(var, dict) or (var.get("remote") is True and var.get("hiddenFromPublishing")):
            continue
        nm = str(var.get("name") or "")
        w = words(nm)
        typ = str(var.get("resolvedType") or var.get("type") or "").upper()
        val = _value(var, vars_, cols)
        desc = str(var.get("description") or "")
        if typ == "COLOR":
            hx = parse_color(val)
            if hx and not _STATE.search(w):
                parts.colors.append(ColorHit(hx, color_role(w), usable_color_name(nm.split("/")[-1])))
                if desc and looks_like_rule(desc):
                    add_rule(parts.rules, desc)
        elif typ == "STRING" and isinstance(val, str):
            if re.search(r"font|famil|шрифт|typeface", w):
                fonts.append(FontHit(val, font_role(w)))
            elif re.search(r"logo|логотип", w) and parts.place is None:
                parts.place = logo_place(val, need_logo_word=False)
        elif typ == "FLOAT" and isinstance(val, (int, float)) and not isinstance(val, bool):
            if re.search(r"weight", w):
                r, wt = font_role(w), weight_of(val)
                if r and wt:
                    weights.setdefault(r, wt)
            elif re.search(r"(?<![a-z])(columns?|cols?)(?![a-z])", w) and parts.columns is None and 2 <= val <= 24:
                parts.columns = int(val)
            elif re.search(r"gutter|gap", w) and parts.gutter is None:
                parts.gutter = float(val)
            elif re.search(r"margin|safe area|page padding|slide padding", w) and parts.margins is None and 0 < val <= 400:
                parts.margins = float(val)
    for f in fonts:
        if f.role and f.role in weights:
            f.weight = weights[f.role]
    parts.fonts += fonts


def spec_from_variables(data: dict, *, file: Optional[str] = None, source: str = "figma", name: Optional[str] = None) -> BrandSpec:
    """Переменные Figma (ответ `variables/local` или экспорт) → `BrandSpec`."""
    parts = _Parts()
    _parse_variables(data, parts)
    return _assemble(parts, file=file, source=source, name=name)


def _assemble(parts: _Parts, *, file: Optional[str], source: str, name: Optional[str]) -> BrandSpec:
    palette, w1 = make_palette(parts.colors)
    font_list, w2 = make_fonts(parts.fonts)
    if not palette and not font_list:
        raise BrandReadError(
            "В файле Figma нет ни цветов, ни шрифтов: сохраните палитру и шрифты как стили или переменные "
            "либо экспортируйте токены JSON (Tokens Studio → Export)."
        )
    head: list[BrandRule] = []
    if parts.place:
        add_rule(head, f"Логотип — {PLACE_TEXT[parts.place]}", "logo")
    if parts.margins:
        add_rule(head, f"Поля — {parts.margins:g} px", "grid")
    for r in parts.rules:
        add_rule(head, r.text, r.kind)
    return BrandSpec(
        name=name or "",
        source=source,  # type: ignore[arg-type]
        file=file,
        colors=palette,
        fonts=font_list,
        margins_px=parts.margins,
        grid=grid_text(parts.columns, parts.gutter),
        rules=head,
        logo_place=parts.place,  # type: ignore[arg-type]
        warnings=w1 + w2,
    )


# ---- REST API -----------------------------------------------------------------------------------------------------------------
def _get(client: Any, url: str, token: str, *, allow: tuple[int, ...] = ()) -> Optional[dict]:
    import httpx

    try:
        r = client.get(url, headers={"X-Figma-Token": token})
    except httpx.HTTPError:
        raise BrandReadError("Не удалось связаться с Figma: проверьте подключение к интернету и попробуйте ещё раз.") from None
    if r.status_code in allow:
        return None
    if r.status_code in (401, 403):
        raise BrandReadError("Figma не дала доступ к файлу: проверьте FIGMA_TOKEN и что у владельца токена есть доступ к этому файлу.")
    if r.status_code == 404:
        raise BrandReadError("Файл Figma не найден: проверьте ссылку — возможно, файл удалён или ссылка неполная.")
    if r.status_code == 429:
        raise BrandReadError("Figma временно ограничила число запросов — попробуйте через минуту.")
    if r.status_code >= 400:
        raise BrandReadError(f"Figma ответила ошибкой {r.status_code} — попробуйте позже или загрузите экспорт токенов JSON.")
    try:
        return r.json()
    except ValueError:
        raise BrandReadError("Figma прислала ответ, который не удалось разобрать — попробуйте ещё раз.") from None


def _solid(fills: Any) -> Optional[str]:
    for f in fills or []:
        if isinstance(f, dict) and f.get("type") == "SOLID" and f.get("visible", True) is not False:
            return parse_color(f.get("color"))
    return None


def read_figma_url(url: str, *, token: Optional[str] = None, client: Any = None, timeout: float = 20.0) -> BrandSpec:
    """Ссылка на файл Figma → `BrandSpec` через REST API. `client` — для проверок (httpx.Client с подменным транспортом)."""
    key = figma_key(url)
    url = normalize_url(url) or url
    token = (token or os.environ.get("FIGMA_TOKEN") or "").strip()
    if not token:
        raise BrandReadError(NO_TOKEN)
    own = client is None
    if own:
        import httpx

        client = httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        doc = _get(client, f"{API}/files/{key}?depth=1", token) or {}
        file_name = str(doc.get("name") or "")
        name = brand_name(file_name)
        parts = _Parts()
        variables = _get(client, f"{API}/files/{key}/variables/local", token, allow=(400, 403, 404))
        if variables:
            _parse_variables(variables, parts)
        styles = doc.get("styles") or {}
        wanted = [sid for sid, s in styles.items() if isinstance(s, dict) and s.get("styleType") in ("FILL", "TEXT")][:200]
        if wanted:
            nodes = (_get(client, f"{API}/files/{key}/nodes?ids={','.join(wanted)}", token) or {}).get("nodes") or {}
            sized: list[tuple[float, FontHit]] = []
            for sid in wanted:
                st = styles[sid]
                node = ((nodes.get(sid) or {}).get("document")) or {}
                sname = str(st.get("name") or node.get("name") or "")
                w = words(sname)
                if st.get("styleType") == "FILL":
                    hx = _solid(node.get("fills"))
                    if hx and not _STATE.search(w):
                        parts.colors.append(ColorHit(hx, color_role(w), usable_color_name(sname.split("/")[-1])))
                else:
                    ts = node.get("style") or {}
                    fam = ts.get("fontFamily")
                    if fam:
                        hit = FontHit(str(fam), font_role(w), weight_of(ts.get("fontWeight")))
                        if hit.role:
                            parts.fonts.append(hit)
                        else:
                            sized.append((float(ts.get("fontSize") or 0), hit))
                desc = str(st.get("description") or "")
                if desc and looks_like_rule(desc):
                    add_rule(parts.rules, desc)
            # стили без роли в имени: самый крупный — заголовки, самый мелкий — основной текст
            if sized:
                sized.sort(key=lambda x: -x[0])
                sized[0][1].role = "heading"
                parts.fonts.append(sized[0][1])
                if len(sized) > 1:
                    sized[-1][1].role = "body"
                    parts.fonts.append(sized[-1][1])
        return _assemble(parts, file=url, source="figma", name=name)
    finally:
        if own:
            client.close()
