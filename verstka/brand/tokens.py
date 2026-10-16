"""Токены дизайна (JSON) → `BrandSpec`.

Понимает:
- W3C Design Tokens (DTCG): группы, `$value` / `$type` / `$description`, тип группы наследуется, ссылки «{color.brand.primary}»,
  цвет строкой или объектом `{"colorSpace": "srgb", "components": […]}`, размер строкой «48px» или `{"value": 48, "unit": "px"}`;
- Tokens Studio (экспорт из Figma): наборы токенов верхнего уровня, `value` / `type` (`color`, `fontFamilies`, `fontWeights`,
  `typography`, `spacing`…), ссылки без имени набора, служебные `$themes` / `$metadata`;
- Style Dictionary: `value` без типа (тип — по значению и пути);
- плоский JSON: `{"primary": "#0077FF", "font-heading": "VK Sans Display"}`;
- экспорт переменных Figma (ответ REST `variables/local` или список переменных) — через `figma.parse_variables`.

Роли цветов — по словам пути («brand.primary», «text», «background», «chart»); если в файле есть такие «смысловые» токены,
берутся только они, а примитивы шкал («blue.500») — нет. Шрифты — из `fontFamily` / `typography` с ролью по пути («heading»,
«body»), замена — второе семейство в списке («VK Sans Display, Play, sans-serif»)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from verstka.brand.common import (
    PLACE_TEXT,
    ROLE_LABELS,
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    brand_name,
    color_role,
    font_role,
    font_stack,
    grid_text,
    logo_place,
    looks_like_rule,
    make_fonts,
    make_palette,
    name_from_path,
    parse_color,
    to_px,
    weight_of,
    words,
)
from verstka.schemas.brand import BrandRule, BrandSpec

_ALIAS = re.compile(r"\{([^{}]+)\}")
# состояния и служебные оттенки — не цвета бренда
_STATE_WORDS = re.compile(
    r"(?<![a-z])(hover|active|pressed|focus|focused|disabled|visited|selected|overlay|shadow|scrim|alpha|opacity|transparent|"
    r"border|outline|divider|stroke)(?![a-z])"
)
_FALLBACK_WORDS = re.compile(r"(?<![a-zа-яё])(fallback|substitute|запасн\w*|замен\w*|резервн\w*)(?![a-zа-яё])")
_MARGIN_PATH = re.compile(r"(?<![a-zа-яё])(margins?|safe area|page padding|slide padding|slide margin|пол[яе]|отступ\w*)(?![a-zа-яё])")
_COLUMNS_PATH = re.compile(r"(?<![a-z])(columns?|cols?|колон\w*)(?![a-z])")
_GUTTER_PATH = re.compile(r"(?<![a-z])(gutter|gap|промежут\w*)(?![a-z])")
_LOGO_PLACE_PATH = re.compile(r"logo.*(position|place|placement|corner|location)|логотип.*(мест|положен|угол)")


@dataclass
class Token:
    path: tuple[str, ...]
    value: Any
    type: Optional[str] = None
    description: str = ""
    alias_of: Optional[tuple[str, ...]] = None
    extensions: dict = field(default_factory=dict)

    @property
    def dotted(self) -> str:
        return ".".join(self.path)


def _is_token(node: dict) -> bool:
    if "$value" in node:
        return True
    if "value" not in node:
        return False
    if "type" in node:
        return True
    # Style Dictionary: «value» без типа; группа с потомком «value»-группой — не токен
    return not isinstance(node["value"], dict) or not any(isinstance(v, dict) for v in node["value"].values())


def flatten(data: Any) -> list[Token]:
    """Все токены файла (лист дерева или узел с `$value`/`value`) с путём, типом (своим или группы) и описанием."""
    out: list[Token] = []

    def walk(node: Any, path: tuple[str, ...], inherited: Optional[str], depth: int) -> None:
        if depth > 40:
            return
        if isinstance(node, dict):
            if _is_token(node):
                dollar = "$value" in node
                out.append(Token(
                    path=path,
                    value=node["$value"] if dollar else node["value"],
                    type=(node.get("$type") if dollar else node.get("type")) or inherited,
                    description=str(node.get("$description") or node.get("description") or node.get("comment") or ""),
                    extensions=node.get("$extensions") if isinstance(node.get("$extensions"), dict) else {},
                ))
                return
            group_type = node.get("$type") if isinstance(node.get("$type"), str) else inherited
            for k, v in node.items():
                if str(k).startswith("$"):
                    continue
                walk(v, path + (str(k),), group_type, depth + 1)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (str, int, float)):
            if path:
                out.append(Token(path=path, value=node, type=inherited))
        elif isinstance(node, list) and path and node and all(isinstance(x, str) for x in node):
            out.append(Token(path=path, value=list(node), type=inherited))

    walk(data, (), None, 0)
    return out


def _index(tokens: list[Token], sets: set[str]) -> dict[str, Token]:
    """Ссылки по полному пути и — для Tokens Studio — по пути без имени набора («global.color.x» → «color.x»)."""
    idx: dict[str, Token] = {}
    for t in tokens:
        idx.setdefault(t.dotted, t)
    for t in tokens:
        if len(t.path) > 1 and t.path[0] in sets:
            idx.setdefault(".".join(t.path[1:]), t)
    return idx


def _resolve(value: Any, idx: dict[str, Token], depth: int = 0) -> Any:
    if depth > 12:
        return value
    if isinstance(value, str):
        whole = _ALIAS.fullmatch(value.strip())
        if whole:
            t = idx.get(whole.group(1).strip())
            return _resolve(t.value, idx, depth + 1) if t is not None else value

        def sub(m: re.Match) -> str:
            t = idx.get(m.group(1).strip())
            if t is None:
                return m.group(0)
            v = _resolve(t.value, idx, depth + 1)
            return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

        return _ALIAS.sub(sub, value) if "{" in value else value
    if isinstance(value, dict):
        return {k: _resolve(v, idx, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, idx, depth + 1) for v in value]
    return value


def _alias_target(value: Any, idx: dict[str, Token]) -> Optional[Token]:
    if isinstance(value, str):
        m = _ALIAS.fullmatch(value.strip())
        if m:
            return idx.get(m.group(1).strip())
    return None


def _dimension_px(value: Any) -> Optional[float]:
    """«48px», 48, «36pt», {"value": 48, "unit": "px"} → px."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("value"), (int, float)):
        return to_px(float(value["value"]), str(value.get("unit") or "px"))
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(px|pt|rem|mm|пт|мм)?\s*", value)
        if m:
            return to_px(float(m.group(1).replace(",", ".")), m.group(2) or "px")
    return None


def _color_name(t: Token, idx: dict[str, Token]) -> Optional[str]:
    """Имя цвета: описание примитива («VK Blue») или его ключ, если он написан как имя («VK Blue»), а не «blue-500»."""
    for tok in (_alias_target(t.value, idx), t):
        if tok is None:
            continue
        d = tok.description.split("—")[0].split(" - ")[0].strip()
        if d and len(d) <= 30 and not looks_like_rule(d):
            return d
    target = _alias_target(t.value, idx)
    key = (target or t).path[-1] if (target or t).path else ""
    if key and (" " in key or any(c.isupper() for c in key)) and len(key) <= 30:
        return key
    return None


def _kind(t: Token, value: Any) -> Optional[str]:
    ty = (t.type or "").lower()
    w = words(t.dotted)
    if ty in ("color",):
        return "color"
    if ty in ("typography",) or (isinstance(value, dict) and ("fontFamily" in value or "font-family" in value)):
        return "typography"
    if ty in ("fontfamily", "fontfamilies") or re.search(r"(font\s*famil|famil|typeface|гарнитур)", w):
        return "family"
    if ty in ("fontweight", "fontweights") or re.search(r"(font\s*weight|weight|начертан)", w):
        return "weight"
    if ty in ("dimension", "spacing", "sizing", "number", "paragraphspacing", "other", "") and _dimension_px(value) is not None:
        return "dimension"
    if ty == "" and parse_color(value) is not None:
        return "color"
    if ty == "" and isinstance(value, (str, list)) and re.search(r"(?<![a-z])font(?![a-z])|шрифт", w):
        return "family"
    if isinstance(value, str):
        return "string"
    return None


def _root_meta(data: Any) -> tuple[Optional[str], list[str]]:
    """Имя бренда и правила из корня: `name` / `$name` / `$description`, `$extensions.<вендор>.name|rules`."""
    if not isinstance(data, dict):
        return None, []
    name: Optional[str] = None
    rules: list[str] = []
    ext = data.get("$extensions")
    if isinstance(ext, dict):
        for v in ext.values():
            if isinstance(v, dict):
                if isinstance(v.get("name"), str) and not name:
                    name = v["name"].strip()
                if isinstance(v.get("rules"), list):
                    rules += [str(x) for x in v["rules"] if isinstance(x, str)]
    for k in ("name", "$name", "brand", "title"):
        if not name and isinstance(data.get(k), str):
            name = brand_name(data[k])
    if not name:
        for k in ("$description", "description"):
            if isinstance(data.get(k), str):
                name = brand_name(data[k])
                break
    if isinstance(data.get("rules"), list):
        rules += [str(x) for x in data["rules"] if isinstance(x, str)]
    return name, rules


def _looks_like_figma_variables(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("variables"), dict):
        return True
    v = data.get("variables")
    if isinstance(v, (list, dict)):
        items = v if isinstance(v, list) else list(v.values())
        return any(isinstance(x, dict) and "valuesByMode" in x for x in items)
    return False


def spec_from_tokens(data: Any, *, file: Optional[str] = None, source: str = "tokens") -> BrandSpec:
    """Разобранный JSON токенов → `BrandSpec` (ошибка `BrandReadError`, если в нём нет ни цветов, ни шрифтов)."""
    if _looks_like_figma_variables(data):
        from verstka.brand.figma import spec_from_variables

        return spec_from_variables(data, file=file, source=source)
    if not isinstance(data, (dict, list)):
        raise BrandReadError("В JSON нет токенов дизайна: ожидался объект с цветами и шрифтами.")
    sets: set[str] = set()
    if isinstance(data, dict):
        meta = data.get("$metadata")
        if isinstance(meta, dict) and isinstance(meta.get("tokenSetOrder"), list):
            sets = {str(s) for s in meta["tokenSetOrder"]}
        elif "$themes" in data:
            sets = {k for k in data if not str(k).startswith("$")}
    tokens = flatten(data)
    if not tokens:
        raise BrandReadError("В JSON не нашёл токенов дизайна. Подойдут W3C Design Tokens, экспорт Tokens Studio или переменных Figma.")
    idx = _index(tokens, sets)
    warnings: list[str] = []

    semantic: list[ColorHit] = []
    primitive: list[ColorHit] = []
    font_hits: list[FontHit] = []
    weights: dict[str, int] = {}
    fallback: Optional[str] = None
    margins: Optional[float] = None
    columns: Optional[int] = None
    gutter: Optional[float] = None
    place = None
    color_rules: list[tuple[str, str]] = []

    for t in tokens:
        value = _resolve(t.value, idx)
        if t.type is None:
            target = _alias_target(t.value, idx)
            if target is not None and target.type:
                t.type = target.type
        kind = _kind(t, value)
        path_words = words(" ".join(t.path[1:] if sets and t.path and t.path[0] in sets else t.path))
        if kind == "color":
            hx = parse_color(value)
            if not hx or _STATE_WORDS.search(path_words):
                continue
            role = color_role(path_words)
            hit = ColorHit(hx, role, _color_name(t, idx))
            (semantic if role else primitive).append(hit)
            if role and t.description and looks_like_rule(t.description):
                color_rules.append((role, t.description.strip()))
        elif kind == "typography" and isinstance(value, dict):
            fam = font_stack(value.get("fontFamily") or value.get("font-family") or value.get("fontFamilies"))
            if fam:
                font_hits.append(FontHit(fam[0], font_role(path_words), weight_of(value.get("fontWeight") or value.get("font-weight")), fam[1] if len(fam) > 1 else None))
        elif kind == "family":
            fam = font_stack(value)
            if not fam:
                continue
            if _FALLBACK_WORDS.search(path_words):
                fallback = fallback or fam[0]
                continue
            font_hits.append(FontHit(fam[0], font_role(path_words), None, fam[1] if len(fam) > 1 else None))
        elif kind == "weight":
            w = weight_of(value)
            r = font_role(path_words)
            if w and r and r not in weights:
                weights[r] = w
        elif kind == "dimension":
            px = _dimension_px(value)
            if px is None:
                continue
            if _COLUMNS_PATH.search(path_words) and columns is None and float(px).is_integer() and 2 <= px <= 24:
                columns = int(px)
            elif _GUTTER_PATH.search(path_words) and gutter is None:
                gutter = px
            elif _MARGIN_PATH.search(path_words) and margins is None and 0 < px <= 400:
                margins = px
        elif kind == "string" and isinstance(value, str) and place is None and _LOGO_PLACE_PATH.search(path_words):
            place = logo_place(value, need_logo_word=False)

    for h in font_hits:
        if h.role and not h.weight and h.role in weights:
            h.weight = weights[h.role]
    # шкалы примитивов («blue.500») — сырьё для смысловых токенов: в палитру идут, только если смысловые токены не называют
    # цветов бренда (основной, дополнительный, акцент, графики)
    brand_roles = {"primary", "secondary", "accent", "chart"}
    pool = semantic if any(h.role in brand_roles for h in semantic) else semantic + primitive
    colors, w1 = make_palette(pool)
    fonts, w2 = make_fonts(font_hits, fallback=fallback)
    warnings += w1 + w2

    name, root_rules = _root_meta(data)
    rules: list[BrandRule] = []
    if place:
        add_rule(rules, f"Логотип — {PLACE_TEXT[place]}", "logo")
    if margins:
        add_rule(rules, f"Поля — {margins:g} px", "grid")
    for role, desc in color_rules:
        label = ROLE_LABELS.get(role, role)
        add_rule(rules, f"{label[:1].upper()}{label[1:]} — {desc[:1].lower()}{desc[1:]}", "color")
    for r in root_rules:
        add_rule(rules, r)
    if not colors and not fonts:
        raise BrandReadError("В JSON нет ни цветов, ни шрифтов. Подойдут W3C Design Tokens, экспорт Tokens Studio или переменных Figma.")
    return BrandSpec(
        name=name or (name_from_path(Path(file).stem) if file else None) or "",
        source=source,  # type: ignore[arg-type]
        file=file,
        colors=colors,
        fonts=fonts,
        margins_px=margins,
        grid=grid_text(columns, gutter),
        rules=rules,
        logo_place=place,
        warnings=warnings,
    )


def load_json(path: Path) -> Any:
    raw = path.read_bytes()
    if not raw.strip():
        raise BrandReadError(f"Файл «{path.name}» пустой.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BrandReadError(f"Файл «{path.name}» — не текст в UTF-8; токены должны быть JSON.") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise BrandReadError(f"Файл «{path.name}» — не JSON: ошибка в строке {e.lineno}, позиция {e.colno}.") from None


def read_tokens(path: Path | str, *, source: str = "tokens") -> BrandSpec:
    """JSON-файл токенов → `BrandSpec`; имя бренда — из самого файла, иначе из имени файла («VK Cloud.json»)."""
    path = Path(path)
    return spec_from_tokens(load_json(path), file=path.name, source=source)
