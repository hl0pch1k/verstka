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
    usable_color_name,
    weight_of,
    words,
)
from verstka.schemas.brand import BrandRule, BrandSpec
from verstka.schemas.common import relative_luminance

_ALIAS = re.compile(r"\{([^{}]+)\}")
# состояния и служебные оттенки — не цвета бренда («on-primary» — цвет текста на основном, «primary-container» — его тон)
_STATE_WORDS = re.compile(
    r"(?<![a-z])(hover|active|pressed|focus|focused|disabled|visited|selected|overlay|shadow|scrim|alpha|opacity|transparent|"
    r"border|outline|divider|stroke|container|on (?:primary|secondary|accent|tertiary|error|brand|main))(?![a-z])"
)
# «on-surface», «on-background» (Material) — цвет текста на подложке и на фоне
_ON_SURFACE = re.compile(r"(?<![a-z])on (?:surface|background)(?![a-z])")
# «второй» цвет роли: «text.secondary», «background.muted» — при двух цветах роли основным остаётся не он
_MINOR_WORDS = re.compile(
    r"(?<![a-zа-яё])(secondary|tertiary|muted|subtle|disabled|placeholder|caption|hint|inverse|inverted|alt|alternate|alternative|"
    r"variant|second|вторичн\w*|приглушённ\w*|приглушенн\w*)(?![a-zа-яё])"
)
_FONT_PATH = re.compile(r"(?<![a-z])(fonts?|typefaces?|typography|fontfamil\w*)(?![a-z])|шрифт\w*|гарнитур\w*")
# свойства шрифта, значения которых — не названия семейств
_NOT_FAMILY_PATH = re.compile(r"(?<![a-z])(size|weight|style|decoration|transform|spacing|height|case|align|variant|stretch|feature)s?$")
_NOT_FAMILY_VALUES = {"italic", "normal", "oblique", "uppercase", "lowercase", "capitalize", "none", "underline", "bold", "regular", "medium", "light", "inherit", "initial"}
_PLURAL_FONT_GROUP = re.compile(r"(?<![a-z])(fonts|typefaces|families|fontfamilies|font families|шрифты|гарнитуры)$")
_DARK_THEME = re.compile(r"(?<![a-zа-яё])(?:dark|night|тёмн\w*|темн\w*)(?![a-zа-яё])", re.I)


def _is_dark_theme(name: str) -> bool:
    """«Dark mode», «Night», «Тёмная», «DarkMode», «brandDark» — тёмная тема; «Nightingale» и «Darkroom» — нет (слова целиком)."""
    return bool(_DARK_THEME.search(re.sub(r"(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])", " ", name)))
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
    # имя из списка палитры: {"colors": [{"name": "Acme Blue", "hex": "#0044CC", "role": "primary"}]} — путь несёт роль, имя — здесь
    name: Optional[str] = None

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


_ITEM_VALUE_KEYS = ("$value", "value", "hex", "color", "colour", "family", "fontFamily", "font-family", "font")
_ITEM_NAME_KEYS = ("name", "label", "title", "id", "key")
_ITEM_ROLE_KEYS = ("role", "usage", "use", "purpose")


def _list_item(item: dict, path: tuple[str, ...], index: int, inherited: Optional[str]) -> Optional[Token]:
    """Элемент списка палитры или шрифтов {"name": "Acme Blue", "hex": "#0044CC", "role": "primary"} → токен: путь —
    роль (или имя, или номер), имя цвета — отдельно."""
    key = next((k for k in _ITEM_VALUE_KEYS if k in item and isinstance(item[k], (str, int, float, dict, list))), None)
    if key is None or isinstance(item[key], bool):
        return None
    role = next((str(item[k]) for k in _ITEM_ROLE_KEYS if isinstance(item.get(k), str) and item[k].strip()), None)
    name = next((str(item[k]).strip() for k in _ITEM_NAME_KEYS if isinstance(item.get(k), str) and item[k].strip()), None)
    label = role or name or str(index)
    return Token(path=path + (label,), value=item[key], type=(item.get("$type") or item.get("type")) if isinstance(item.get("$type") or item.get("type"), str) else inherited,
                 description=str(item.get("description") or item.get("$description") or ""), name=name if role else None)


def flatten(data: Any) -> list[Token]:
    """Все токены файла (лист дерева или узел с `$value`/`value`) с путём, типом (своим или группы) и описанием. Списки —
    палитра ({"colors": [{"name": …, "hex": …}]} или ["#0077FF", …]) и шрифты ({"fonts": ["Inter", "Roboto"]}), как и
    верхнеуровневый список."""
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
        elif isinstance(node, list) and node:
            strings = all(isinstance(x, str) for x in node)
            plural = bool(path) and bool(_PLURAL_FONT_GROUP.search(words(path[-1])))
            if strings and path and not plural and not all(parse_color(x, named=True) for x in node):
                out.append(Token(path=path, value=list(node), type=inherited))  # «font-body»: ["Golos Text", "Play"] — стопка шрифтов
                return
            for i, item in enumerate(node):
                if isinstance(item, dict):
                    tok = _list_item(item, path, i, inherited)
                    if tok is not None:
                        out.append(tok)
                    else:
                        walk(item, path + (str(item.get("name") or i),), inherited, depth + 1)
                elif isinstance(item, (str, int, float)) and not isinstance(item, bool):
                    out.append(Token(path=path + (str(i),), value=item, type=inherited))

    walk(data, (), None, 0)
    return out


def _index(tokens: list[Token], sets: set[str], active: Optional[set[str]] = None, order: Optional[list[str]] = None) -> dict[str, Token]:
    """Ссылки по полному пути и — для Tokens Studio — по пути без имени набора («global.color.x» → «color.x»). У Tokens Studio
    токен позднего набора перекрывает ранний, а наборы выбранной темы — остальные."""
    idx: dict[str, Token] = {}
    if not sets:
        for t in tokens:
            idx.setdefault(t.dotted, t)
        return idx
    pos = {name: i for i, name in enumerate(order or [])}
    inactive = [t for t in tokens if active is not None and t.path[0] in sets and t.path[0] not in active]
    rest = sorted((t for t in tokens if t not in inactive), key=lambda t: pos.get(t.path[0], 0) if t.path[0] in sets else -1)
    for t in inactive + rest:
        idx[t.dotted] = t
        if len(t.path) > 1 and t.path[0] in sets:
            idx[".".join(t.path[1:])] = t
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
    """Имя цвета: имя из списка палитры, описание примитива («VK Blue») или его ключ, если он написан как имя («VK Blue»), а не
    «blue-500» и не слово-роль («Основной»)."""
    if usable_color_name(t.name):
        return t.name
    for tok in (_alias_target(t.value, idx), t):
        if tok is None:
            continue
        d = tok.description.split("—")[0].split(" - ")[0].strip()
        if d and len(d) <= 30 and not looks_like_rule(d):
            return d
    target = _alias_target(t.value, idx)
    key = (target or t).path[-1] if (target or t).path else ""
    if key and (" " in key or any(c.isupper() for c in key)):
        return usable_color_name(key)
    return None


_COLOR_PATH = re.compile(r"(?<![a-z])(colou?rs?|palette|brand)(?![a-z])|цвет\w*|палитр\w*|бренд\w*")


def _kind(t: Token, value: Any) -> Optional[str]:
    ty = (t.type or "").lower()
    w = words(t.dotted)
    last = words(t.path[-1]) if t.path else ""
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
    if (ty in ("", "string", "text") and isinstance(value, (str, list)) and _FONT_PATH.search(w) and not _NOT_FAMILY_PATH.search(last)
            and not (isinstance(value, str) and value.strip().lower() in _NOT_FAMILY_VALUES)):
        return "family"
    # «primary»: «blue» в группе цветов — название CSS-цвета
    if ty == "" and isinstance(value, str) and (_COLOR_PATH.search(w) or color_role(w)) and parse_color(value, named=True) is not None:
        return "color"
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


def _chroma(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return (max(r, g, b) - min(r, g, b)) / 255


def _active_sets(data: Any) -> tuple[Optional[set[str]], str, int]:
    """Наборы токенов темы Tokens Studio, которые читаются: первая тема (светлая раньше тёмной), в которой есть наборы со
    статусом source или enabled; её название и число таких тем. Нет тем — (None, "", 0): читаются все наборы."""
    themes = data.get("$themes") if isinstance(data, dict) else None
    if not isinstance(themes, list):
        return None, "", 0
    cands: list[tuple[str, set[str]]] = []
    for th in themes:
        sel = th.get("selectedTokenSets") if isinstance(th, dict) else None
        if isinstance(sel, dict):
            on = {str(k) for k, v in sel.items() if str(v).lower() in ("source", "enabled")}
            if on:
                cands.append((str(th.get("name") or ""), on))
    if not cands:
        return None, "", 0
    name, on = next((c for c in cands if not _is_dark_theme(c[0])), cands[0])
    return on, name, len(cands)


def _unreadable(items: list[str]) -> str:
    shown = "; ".join(items[:3]) + (f"; и ещё {len(items) - 3}" if len(items) > 3 else "")
    return f"Не прочитал цвета: {shown}. Понимаю HEX, rgb(), hsl() и названия CSS — остальное пропустил."


def spec_from_tokens(data: Any, *, file: Optional[str] = None, source: str = "tokens") -> BrandSpec:
    """Разобранный JSON токенов → `BrandSpec` (ошибка `BrandReadError`, если в нём нет ни цветов, ни шрифтов)."""
    if _looks_like_figma_variables(data):
        from verstka.brand.figma import spec_from_variables

        return spec_from_variables(data, file=file, source=source)
    if not isinstance(data, (dict, list)):
        raise BrandReadError("В JSON нет токенов дизайна: ожидался объект с цветами и шрифтами.")
    sets: set[str] = set()
    order: list[str] = []
    active: Optional[set[str]] = None
    theme_name, n_themes = "", 0
    if isinstance(data, dict):
        meta = data.get("$metadata")
        if isinstance(meta, dict) and isinstance(meta.get("tokenSetOrder"), list):
            order = [str(s) for s in meta["tokenSetOrder"]]
            sets = set(order)
        elif "$themes" in data:
            order = [k for k in data if not str(k).startswith("$")]
            sets = set(order)
        if sets:
            # у Tokens Studio читается одна тема, а не все наборы подряд (тёмный набор — не основной)
            active, theme_name, n_themes = _active_sets(data)
    tokens = flatten(data)
    if not tokens:
        raise BrandReadError("В JSON не нашёл токенов дизайна. Подойдут W3C Design Tokens, экспорт Tokens Studio или переменных Figma.")
    idx = _index(tokens, sets, active, order)
    warnings: list[str] = []
    unreadable: list[str] = []
    if n_themes > 1:
        warnings.append(f"В файле несколько тем — прочитана «{theme_name or 'первая'}».")

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
        if sets and t.path and t.path[0] in sets:
            if active is not None and t.path[0] not in active:
                continue  # набор, которого нет в выбранной теме
            if len(t.path) > 1 and idx.get(".".join(t.path[1:])) is not t:
                continue  # токен позднего набора перекрыл этот
        value = _resolve(t.value, idx)
        if t.type is None:
            target = _alias_target(t.value, idx)
            if target is not None and target.type:
                t.type = target.type
        kind = _kind(t, value)
        path_words = words(" ".join(t.path[1:] if sets and t.path and t.path[0] in sets else t.path))
        if kind == "color":
            if _ON_SURFACE.search(path_words):
                path_words = _ON_SURFACE.sub("text", path_words)
            if _STATE_WORDS.search(path_words):
                continue
            hx = parse_color(value, named=True)
            if not hx:
                if isinstance(value, str) and t.type and t.type.lower() == "color":
                    unreadable.append(f"{t.dotted} (ссылка {value} не найдена)" if _ALIAS.fullmatch(value.strip()) else f"{t.dotted} («{value}»)")
                elif isinstance(value, dict):
                    unreadable.append(f"{t.dotted} (цветовое пространство {value.get('colorSpace', '?')})")
                continue
            path_words = re.sub(r"(?<![a-z])font(?![a-z])", "text", path_words)  # Style Dictionary: color.font.base — цвет текста
            role = color_role(path_words)
            rank = 1 if role in ("text", "background", "surface") and _MINOR_WORDS.search(path_words) else 0
            hit = ColorHit(hx, role, _color_name(t, idx), rank=rank)
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
    if any(h.role in brand_roles for h in semantic):
        pool = list(semantic)
        # «dark» и «light» плоского файла рядом с «brand-*»: белый и чёрный, если фон и текст не названы, берутся из примитивов
        have = {h.role for h in semantic}
        if "background" not in have:
            light = [h for h in primitive if relative_luminance(h.hex) >= 0.85 and _chroma(h.hex) <= 0.06]
            pool += sorted(light, key=lambda h: -relative_luminance(h.hex))[:1]
        if "text" not in have:
            dark = [h for h in primitive if relative_luminance(h.hex) <= 0.06 and _chroma(h.hex) <= 0.2]
            pool += sorted(dark, key=lambda h: relative_luminance(h.hex))[:1]
    else:
        pool = semantic + primitive
    colors, w1 = make_palette(pool)
    fonts, w2 = make_fonts(font_hits, fallback=fallback)
    warnings += w1 + w2
    if unreadable:
        warnings.append(_unreadable(unreadable))

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
        raise BrandReadError("В JSON нет ни цветов, ни шрифтов. " + (_unreadable(unreadable) + " " if unreadable else "")
                             + "Подойдут W3C Design Tokens, экспорт Tokens Studio или переменных Figma.")
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
