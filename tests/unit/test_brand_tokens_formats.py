"""Брендбук, токены: форматы файлов (разбор замечаний ревью задачи 5) — списки палитры, серые примитивы и смысловые алиасы,
темы Tokens Studio, группа «fonts» и шрифты строками, hsl() и названия цветов, Style Dictionary и плоские файлы.
Входы ревьюера — `tests/fixtures/brand/tokens/`. Модель и сеть не нужны."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.brand.common import BrandReadError, ColorHit, make_palette, parse_color
from verstka.brand.read import read_brandbook
from verstka.brand.tokens import spec_from_tokens

ROOT = Path(__file__).resolve().parents[2]
TOK = ROOT / "tests" / "fixtures" / "brand" / "tokens"


def _read(name: str):
    return read_brandbook(TOK / name)


def _roles(spec) -> dict[str, str]:
    return {c.hex: c.role for c in spec.colors}


def _fonts(spec) -> dict[str, tuple]:
    return {f.role: (f.family, f.fallback, f.weight) for f in spec.fonts}


# ---- 4. списки палитры ---------------------------------------------------------------------------------------------------------
def test_palette_arrays_of_objects_strings_and_a_top_level_array_are_read():
    spec = _read("list_colors_obj.json")  # {"colors": [{"name": "Primary", "hex": …}, …, {"name": "Text", "value": …}]}
    assert _roles(spec) == {"#0077FF": "primary", "#FF3985": "accent", "#0B1220": "text"}
    spec = _read("list_colors_str.json")  # {"colors": ["#0077FF", …], "fonts": ["Inter", "Roboto"]}
    assert set(_roles(spec)) == {"#0077FF", "#FF3985", "#0B1220", "#FFFFFF"}
    assert _roles(spec)["#FFFFFF"] == "background" and _roles(spec)["#0B1220"] == "text"  # роли угаданы
    assert any("угадал" in w for w in spec.warnings)
    assert _fonts(spec) == {"heading": ("Inter", None, 700), "body": ("Roboto", None, 400)}  # «fonts» списком — два шрифта, а не стопка
    spec = _read("list_top.json")  # верхнеуровневый массив [{"name": "primary", "hex": …}, …]
    assert _roles(spec) == {"#0077FF": "primary", "#FF3985": "accent"}


def test_palette_objects_keep_name_role_and_fonts():
    spec = _read("list_palette.json")
    assert spec.name == "Acme"
    assert [(c.hex, c.role, c.name) for c in spec.colors] == [("#0044CC", "primary", "Acme Blue"), ("#FF5A4F", "accent", "Acme Coral"), ("#101820", "text", None)]
    assert spec.fonts[0].family == "PT Sans" and {f.role for f in spec.fonts} == {"heading", "body"}


def test_a_list_of_names_without_roles_is_still_a_palette():
    spec = spec_from_tokens({"palette": [{"name": "Acme Blue", "hex": "#0044CC"}, {"name": "Acme Coral", "hex": "#FF5A4F"}, {"name": "Paper", "hex": "#FFFFFF"}]})
    assert [c.hex for c in spec.colors] == ["#0044CC", "#FF5A4F", "#FFFFFF"]
    assert [c.name for c in spec.colors] == ["Acme Blue", "Acme Coral", "Paper"]
    assert spec_from_tokens({"colors": ["#fff", "navy", "#0B1220"]}).colors  # названия CSS в списке тоже цвета


# ---- 5. серые примитивы и смысловые алиасы ----------------------------------------------------------------------------------------------
def test_a_gray_primitive_does_not_block_the_semantic_text_role():
    spec = _read("w3c_alias.json")  # core.gray.900 (#202124) + color.text.default → text; muted не берёт «text»
    roles = _roles(spec)
    assert roles["#202124"] == "text" and roles["#5F6368"] == "neutral"
    assert roles["#1A73E8"] == "primary" and roles["#FBBC04"] == "accent" and roles["#F8F9FA"] == "surface"
    spec = _read("ts_core_semantic_theme.json")  # то же у Tokens Studio: core + semantic
    assert _roles(spec) == {"#111111": "text", "#FFFFFF": "surface", "#0055FF": "primary"}


def test_a_muted_text_colour_does_not_take_the_text_role_even_when_it_comes_first():
    spec = spec_from_tokens({"color": {"$type": "color", "text": {"muted": {"$value": "#5F6368"}, "default": {"$value": "#202124"}},
                                        "background": {"secondary": {"$value": "#F1F3F4"}, "default": {"$value": "#FFFFFF"}},
                                        "brand": {"primary": {"$value": "#1A73E8"}}}})
    roles = _roles(spec)
    assert roles["#202124"] == "text" and roles["#5F6368"] == "neutral"
    assert roles["#FFFFFF"] == "background" and roles["#F1F3F4"] == "neutral"
    colors, _ = make_palette([ColorHit("#111111", "neutral"), ColorHit("#111111", "text"), ColorHit("#999999", "text", rank=1)])
    assert [(c.hex, c.role) for c in colors] == [("#111111", "text"), ("#999999", "neutral")]


def test_material_style_on_colours_are_not_brand_colours():
    spec = _read("material.json")
    assert _roles(spec) == {"#6750A4": "primary", "#625B71": "secondary", "#FEF7FF": "surface", "#1D1B20": "text", "#B3261E": "danger"}


# ---- 6. темы Tokens Studio -----------------------------------------------------------------------------------------------------------------
def test_tokens_studio_reads_the_first_theme_not_every_set():
    spec = _read("ts_sets.json")  # global + light (Light) и global + dark (Dark)
    assert _roles(spec) == {"#0055FF": "primary", "#111111": "text", "#FFFFFF": "background", "#FF6A00": "accent"}
    assert "#4488FF" not in _roles(spec) and "#0B0B0B" not in _roles(spec)  # тёмный набор не добавляет цветов
    assert _fonts(spec) == {"heading": ("Inter", None, 700), "body": ("Inter", None, 400)}
    spec = _read("ts_dark_first.json")  # тёмный набор в tokenSetOrder первым, а первая тема — светлая
    assert _roles(spec) == {"#0055FF": "primary", "#FFFFFF": "background", "#111111": "text"}


def test_a_dark_theme_is_read_only_when_it_is_the_only_one():
    dark = {"dark": {"color": {"primary": {"value": "#4488FF", "type": "color"}, "background": {"value": "#0B0B0B", "type": "color"}}},
            "light": {"color": {"primary": {"value": "#0055FF", "type": "color"}}},
            "$themes": [{"name": "Dark", "selectedTokenSets": {"dark": "enabled", "light": "disabled"}}], "$metadata": {"tokenSetOrder": ["dark", "light"]}}
    assert _roles(spec_from_tokens(dark)) == {"#4488FF": "primary", "#0B0B0B": "background"}
    both = dict(dark, **{"$themes": [{"name": "Dark", "selectedTokenSets": {"dark": "enabled"}}, {"name": "Light", "selectedTokenSets": {"light": "enabled"}}]})
    assert _roles(spec_from_tokens(both)) == {"#0055FF": "primary"}  # светлая тема — раньше тёмной, даже если она вторая
    # без тем читаются все наборы, поздний перекрывает ранний
    no_themes = {"base": dark["light"], "over": {"color": {"primary": {"value": "#123456", "type": "color"}}}, "$metadata": {"tokenSetOrder": ["base", "over"]}}
    assert _roles(spec_from_tokens(no_themes)) == {"#123456": "primary"}


# ---- 7. шрифты: «fonts» и строки ----------------------------------------------------------------------------------------------------------------
def test_plural_fonts_group_and_plain_string_typography_are_read():
    spec = read_brandbook(TOK / "fonts_plural.json")  # {"fonts": {"heading": "Inter", "body": "Roboto"}}
    assert _fonts(spec) == {"heading": ("Inter", None, 700), "body": ("Roboto", None, 400)}
    spec = read_brandbook(TOK / "brand_obj_colors.json")  # typography: {"headings": "Inter Bold", "body": "Inter"} строками
    assert _fonts(spec) == {"heading": ("Inter", None, 700), "body": ("Inter", None, 400)}
    spec = spec_from_tokens({"color": {"primary": "#0077FF"}, "typography": {"headings": "Montserrat Bold", "body": "Roboto"}})
    assert _fonts(spec) == {"heading": ("Montserrat", None, 700), "body": ("Roboto", None, 400)}
    spec = read_brandbook(TOK / "typography_group.json")
    assert _fonts(spec) == {"heading": ("Inter", None, 700), "body": ("Roboto", None, 400)}


def test_font_properties_that_are_not_families_are_ignored():
    spec = spec_from_tokens({"color": {"primary": "#0077FF"}, "typography": {"h1": {"fontFamily": "Inter", "fontStyle": "italic", "textTransform": "uppercase", "letterSpacing": "2px"}},
                             "font": {"style": "italic", "weight": "bold"}})
    assert [f.family for f in spec.fonts] == ["Inter", "Inter"]


# ---- hsl(), названия и неподдерживаемые цвета ----------------------------------------------------------------------------------------------------
def test_hsl_and_css_names_are_read():
    spec = _read("hsl.json")
    assert _roles(spec) == {"#0062FF": "primary", "#0F1624": "text", "#FFFFFF": "background"}
    assert parse_color("hsl(120, 100%, 25%)") == "#008000" and parse_color("hsl(0 0% 100%)") == "#FFFFFF" and parse_color("blue") is None
    spec = spec_from_tokens({"color": {"$type": "color", "primary": {"$value": "blue"}, "accent": {"$value": "hotpink"}}})
    assert _roles(spec) == {"#0000FF": "primary", "#FF69B4": "accent"}
    # без типа название CSS читается только в группе цветов; «bold» и «left» цветами не становятся
    spec = spec_from_tokens({"color": {"primary": "navy", "text": "#0B1220"}, "font": {"weight": "bold"}, "layout": {"align": "left"}})
    assert _roles(spec) == {"#000080": "primary", "#0B1220": "text"}


def test_colours_in_formats_that_are_not_understood_are_reported_not_dropped_silently():
    spec = spec_from_tokens({"color": {"$type": "color", "primary": {"$value": "#0077FF"}, "accent": {"$value": "oklch(0.7 0.2 30)"},
                                        "chart": {"1": {"$value": "{color.missing}"}}}})
    assert _roles(spec) == {"#0077FF": "primary"}
    msg = next(w for w in spec.warnings if "Не прочитал цвета" in w)
    assert "color.accent" in msg and "oklch" in msg and "color.chart.1" in msg
    spec = _read("dtcg2025.json")  # display-p3 — другое цветовое пространство
    assert any("display-p3" in w for w in spec.warnings) and _roles(spec)["#0077FF"] == "primary"
    with pytest.raises(BrandReadError, match="ни цветов, ни шрифтов"):
        spec_from_tokens({"color": {"$type": "color", "accent": {"$value": "oklch(0.7 0.2 30)"}}})


# ---- Style Dictionary и плоские файлы ---------------------------------------------------------------------------------------------------------
def test_style_dictionary_font_colour_is_the_text_colour():
    spec = _read("sd_canonical.json")  # color.font.base — цвет текста, color.font.secondary — второй
    roles = _roles(spec)
    assert roles["#111111"] == "text" and roles["#999999"] == "neutral" and roles["#FFFFFF"] == "background"
    assert _fonts(spec)["heading"][0] == "Inter"


def test_flat_file_with_brand_colours_dark_and_light_keeps_text_and_background():
    spec = _read("flat2.json")  # brand-blue, brand-pink, dark, light
    roles = _roles(spec)
    assert roles["#0077FF"] == "primary" and roles["#0B1220"] == "text" and roles["#FFFFFF"] == "background"
    assert any("угадал" in w for w in spec.warnings)
    # оттенки шкал («blue.100») фоном не становятся, когда смысловые токены есть
    spec = spec_from_tokens({"color": {"$type": "color", "blue": {"100": {"$value": "#E5F1FF"}, "500": {"$value": "#0077FF"}},
                                        "primary": {"$value": "{color.blue.500}"}}})
    assert _roles(spec) == {"#0077FF": "primary"}



def test_a_theme_is_dark_only_by_a_whole_word_and_the_reader_says_which_theme_it_read():
    sets = {"a": {"color": {"primary": {"value": "#0055FF", "type": "color"}}}, "b": {"color": {"primary": {"value": "#4488FF", "type": "color"}}}}
    themes = [{"name": "Nightingale", "selectedTokenSets": {"a": "enabled"}}, {"name": "Dark mode", "selectedTokenSets": {"b": "enabled"}}]
    spec = spec_from_tokens({**sets, "$themes": themes, "$metadata": {"tokenSetOrder": ["a", "b"]}})
    assert _roles(spec) == {"#0055FF": "primary"}  # «Nightingale» — не тёмная, «Dark mode» — тёмная
    assert "В файле несколько тем — прочитана «Nightingale»." in spec.warnings
    spec = spec_from_tokens({**sets, "$themes": themes[::-1], "$metadata": {"tokenSetOrder": ["a", "b"]}})
    assert _roles(spec) == {"#0055FF": "primary"} and any("прочитана «Nightingale»" in w for w in spec.warnings)
    for name in ("Darkroom", "Midnightly", "Тёмная", "Night"):
        only = {**sets, "$themes": [{"name": name, "selectedTokenSets": {"b": "enabled"}}, {"name": "Light", "selectedTokenSets": {"a": "enabled"}}],
                "$metadata": {"tokenSetOrder": ["a", "b"]}}
        read = _roles(spec_from_tokens(only))
        assert read == ({"#0055FF": "primary"} if name in ("Тёмная", "Night") else {"#4488FF": "primary"}), name
    spec = _read("ts_sets.json")  # Light и Dark
    assert "В файле несколько тем — прочитана «Light»." in spec.warnings
    one = spec_from_tokens({**sets, "$themes": themes[:1], "$metadata": {"tokenSetOrder": ["a", "b"]}})
    assert not any("несколько тем" in w for w in one.warnings)  # одна тема — молчим
