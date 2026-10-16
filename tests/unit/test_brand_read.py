"""Чтение брендбуков (вторая ступень, §5): токены W3C / Tokens Studio / Style Dictionary / плоские / переменные Figma,
PDF-гайдлайн по тексту и с моделью (подменной), папка и ZIP, ссылка Figma (REST подменён), понятные ошибки по-русски.
Модель и сеть не вызываются."""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from brand_helpers import pdf_bytes as _pdf_bytes
from verstka.brand.common import (
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    brand_name,
    color_role,
    make_fonts,
    make_palette,
    margins_px,
    parse_color,
)
from verstka.brand.figma import read_figma_url, spec_from_variables
from verstka.brand.folder import image_colors, logo_variant_of
from verstka.brand.pdf import BrandbookReading, logo_variant, pdf_colors, pdf_fonts, pdf_rules, read_pdf
from verstka.brand.read import brand_steps, read_brandbook
from verstka.brand.tokens import spec_from_tokens
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.brand import BrandSpec

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "brandbook-vk-cloud"
# палитра и шрифты из examples/data-sales-2026/SCENARIO.md
SCENARIO_COLORS = {"#0077FF": "primary", "#2787F5": "secondary", "#0B1220": "text", "#FFFFFF": "background", "#FF3985": "accent", "#00C2FF": "chart"}
SCENARIO_RULES = ("Логотип — в правом нижнем углу", "Поля — 48 px", "главного числа")


def _palette(spec: BrandSpec) -> dict[str, str]:
    return {c.hex: c.role for c in spec.colors}


def _fonts(spec: BrandSpec) -> dict[str, tuple]:
    return {f.role: (f.family, f.fallback, f.weight) for f in spec.fonts}


def _scenario_ok(spec: BrandSpec) -> None:
    assert _palette(spec) == SCENARIO_COLORS
    assert _fonts(spec) == {"heading": ("VK Sans Display", "Play", 700), "body": ("VK Sans Text", "Play", 400)}
    assert spec.margins_px == 48
    assert spec.logo_place == "bottom_right"
    texts = " | ".join(r.text for r in spec.rules)
    for rule in SCENARIO_RULES:
        assert rule in texts


# ---- пример брендбука ---------------------------------------------------------------------------------------------------------
def test_sample_brandbook_has_every_part():
    assert (SAMPLE / "guideline.pdf").is_file() and (SAMPLE / "README.md").is_file()
    assert (SAMPLE / "tokens.json").is_file() and (SAMPLE / "tokens-studio.json").is_file()
    for v in ("primary", "white", "mark", "mono"):
        assert (SAMPLE / "logos" / f"{v}.svg").is_file() and (SAMPLE / "logos" / f"{v}.png").is_file()
    assert len(list((SAMPLE / "slides").glob("*.png"))) == 3


def test_sample_pdf_reads_like_the_scenario_without_a_model():
    spec = read_brandbook(SAMPLE / "guideline.pdf")
    assert spec.source == "pdf" and spec.file == "guideline.pdf"
    assert spec.name == "VK Cloud"
    assert 8 <= spec.pages <= 12
    _scenario_ok(spec)
    assert {c.hex: c.name for c in spec.colors}["#0077FF"] == "VK Blue"
    assert spec.grid == "12 колонок, промежуток 24 px"
    assert spec.warnings == []
    # строки таблицы палитры и подписи «Как правильно и как нельзя» — не правила
    assert not any("#" in r.text or r.text.startswith("Как правильно") for r in spec.rules)
    assert len(spec.rules) <= 14


def test_sample_pdf_logos_are_saved_with_their_versions(tmp_path):
    spec = read_brandbook(SAMPLE / "guideline.pdf", assets_dir=tmp_path)
    assert sorted(lg.variant for lg in spec.logos) == ["mark", "mono", "primary", "white"]
    by = {lg.variant: lg for lg in spec.logos}
    assert by["white"].ground == "dark" and by["primary"].ground == "light"
    assert by["primary"].name == "Основной" and by["mono"].name == "Монохром"
    for lg in spec.logos:
        assert (tmp_path / lg.file).is_file()


def test_sample_w3c_tokens():
    spec = read_brandbook(SAMPLE / "tokens.json")
    assert spec.source == "tokens" and spec.name == "VK Cloud"
    _scenario_ok(spec)
    assert spec.grid == "12 колонок, промежуток 24 px"
    assert {c.hex: c.name for c in spec.colors}["#00C2FF"] == "Sky"


def test_sample_tokens_studio_export():
    spec = read_brandbook(SAMPLE / "tokens-studio.json")
    assert spec.source == "tokens"
    _scenario_ok(spec)


def test_sample_folder_reads_everything(tmp_path):
    steps: list[tuple[str, str]] = []
    spec = read_brandbook(SAMPLE, assets_dir=tmp_path, on_step=lambda a, b: steps.append((a, b)))
    assert spec.source == "folder" and spec.name == "VK Cloud" and spec.pages == 12
    _scenario_ok(spec)
    assert [lg.variant for lg in spec.logos] == ["primary", "white", "mark", "mono"]
    assert all(lg.file.endswith(".png") and (tmp_path / lg.file).is_file() for lg in spec.logos)
    assert steps[0] == ("открыта папка", "логотипы и примеры слайдов")
    assert ("палитра", "6 цветов") in steps and ("логотипы", "4") in steps
    assert ("шрифты", "VK Sans Display, VK Sans Text") in steps


def test_sample_zip_reads_like_the_folder(tmp_path):
    archive = tmp_path / "Брендбук VK Cloud.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for p in SAMPLE.rglob("*"):
            if p.is_file() and "source" not in p.parts:
                zf.write(p, Path("brandbook-vk-cloud") / p.relative_to(SAMPLE))
        zf.writestr("../../evil.txt", "outside")  # путь за пределы архива — пропускается
        zf.writestr("__MACOSX/._tokens.json", "junk")
    spec = read_brandbook(archive)
    assert spec.source == "folder" and spec.file == archive.name
    _scenario_ok(spec)
    # без assets_dir пути логотипов — внутри архива
    assert {lg.file for lg in spec.logos} == {f"brandbook-vk-cloud/logos/{v}.png" for v in ("primary", "white", "mark", "mono")}
    assert brand_steps(spec)[0] == ("открыт архив", "логотипы и примеры слайдов")
    assert not (tmp_path.parent / "evil.txt").exists()
    assets = tmp_path / "assets"
    spec2 = read_brandbook(archive, assets_dir=assets)
    assert all((assets / lg.file).is_file() for lg in spec2.logos)


# ---- токены --------------------------------------------------------------------------------------------------------------------
def test_flat_json_and_style_dictionary():
    flat = spec_from_tokens({"primary": "#0077ff", "accent": "#FF3985", "text": "#0B1220", "background": "#FFF",
                             "font-heading": "Inter", "font-body": "Inter"})
    assert _palette(flat) == {"#0077FF": "primary", "#FF3985": "accent", "#0B1220": "text", "#FFFFFF": "background"}
    assert _fonts(flat)["heading"][0] == "Inter" and _fonts(flat)["body"][0] == "Inter"
    sd = spec_from_tokens({"color": {"brand": {"primary": {"value": "#0077FF"}, "secondary": {"value": "rgb(39, 135, 245)"}},
                                     "chart": {"1": {"value": "{color.brand.primary.value}"}, "2": {"value": "#00C2FF"}}},
                           "size": {"margin": {"value": "36pt"}}})
    assert _palette(sd) == {"#0077FF": "primary", "#2787F5": "secondary", "#00C2FF": "chart"}
    assert sd.margins_px == 48  # 36 pt → 48 px


def test_w3c_color_objects_aliases_and_inherited_types():
    data = {
        "color": {"$type": "color",
                  "base": {"blue": {"$value": {"colorSpace": "srgb", "components": [0, 0.4667, 1], "hex": "#0077ff"}}},
                  "brand": {"primary": {"$value": "{color.base.blue}"}},
                  "bg": {"$value": "#ffffffff"}},
        "space": {"$type": "dimension", "page-margin": {"$value": {"value": 2, "unit": "rem"}}},
        "type": {"heading": {"$type": "typography", "$value": {"fontFamily": ["Golos Text", "Play"], "fontWeight": "bold"}}},
    }
    spec = spec_from_tokens(data)
    assert _palette(spec) == {"#0077FF": "primary", "#FFFFFF": "background"}
    assert spec.margins_px == 32
    assert _fonts(spec)["heading"] == ("Golos Text", "Play", 700)
    assert _fonts(spec)["body"][0] == "Golos Text"  # одно семейство — для обеих ролей


def test_primitive_scales_alone_get_guessed_roles_with_a_warning():
    spec = spec_from_tokens({"blue": {"$type": "color", "$value": "#0077FF"}, "pink": {"$type": "color", "$value": "#FF3985"},
                             "ink": {"$type": "color", "$value": "#0B1220"}, "paper": {"$type": "color", "$value": "#FFFFFF"}})
    assert _palette(spec) == {"#0077FF": "primary", "#FF3985": "accent", "#0B1220": "text", "#FFFFFF": "background"}
    assert any("угадал" in w for w in spec.warnings)


def test_semantic_tokens_hide_primitive_scales_and_states():
    spec = spec_from_tokens({"color": {"$type": "color",
                                       "blue": {"100": {"$value": "#E5F1FF"}, "500": {"$value": "#0077FF"}, "900": {"$value": "#002B5C"}},
                                       "primary": {"$value": "{color.blue.500}"}, "primary-hover": {"$value": "#0066DD"},
                                       "text": {"$value": "#0B1220"}}})
    assert _palette(spec) == {"#0077FF": "primary", "#0B1220": "text"}


def test_conflicting_roles_keep_one_colour_per_role():
    colors, _ = make_palette([ColorHit("#0077FF", "primary"), ColorHit("#2787F5", "primary"), ColorHit("#0077ff", "chart"),
                              ColorHit("#FFFFFF", "background"), ColorHit("#F5F5F5", "background")])
    assert [(c.hex, c.role) for c in colors] == [("#0077FF", "primary"), ("#2787F5", "chart"), ("#FFFFFF", "background"), ("#F5F5F5", "neutral")]


def test_figma_variables_export():
    data = {"meta": {
        "variableCollections": {"c1": {"defaultModeId": "m1", "modes": [{"modeId": "m1", "name": "Light"}]}},
        "variables": {
            "v1": {"name": "palette/blue", "resolvedType": "COLOR", "variableCollectionId": "c1", "valuesByMode": {"m1": {"r": 0, "g": 0.4667, "b": 1, "a": 1}}},
            "v2": {"name": "brand/primary", "resolvedType": "COLOR", "variableCollectionId": "c1", "valuesByMode": {"m1": {"type": "VARIABLE_ALIAS", "id": "v1"}}},
            "v3": {"name": "text/default", "resolvedType": "COLOR", "variableCollectionId": "c1", "valuesByMode": {"m1": {"r": 0.043, "g": 0.0706, "b": 0.1255, "a": 1}}},
            "v4": {"name": "font/heading", "resolvedType": "STRING", "variableCollectionId": "c1", "valuesByMode": {"m1": "VK Sans Display"}},
            "v5": {"name": "font/body", "resolvedType": "STRING", "variableCollectionId": "c1", "valuesByMode": {"m1": "VK Sans Text"}},
            "v6": {"name": "layout/margin", "resolvedType": "FLOAT", "variableCollectionId": "c1", "valuesByMode": {"m1": 48}},
        }}}
    spec = spec_from_tokens(data)  # тот же разбор, что и для JSON-файла
    assert spec.source == "tokens"
    assert _palette(spec)["#0077FF"] == "primary" and _palette(spec)["#0B1220"] == "text"
    assert _fonts(spec)["heading"][0] == "VK Sans Display" and _fonts(spec)["body"][0] == "VK Sans Text"
    assert spec.margins_px == 48
    assert spec_from_variables(data).source == "figma"


# ---- PDF ---------------------------------------------------------------------------------------------------------------------
def test_pdf_text_rules_for_colours_fonts_and_rules():
    text = (
        "Палитра\n"
        "VK Blue\nОсновной\n#0077FF\nRGB 0 119 255\n"
        "Pink\nАкцент\n#FF3985\n"
        "Текст · Night · #0B1220 · заголовки и основной текст\n"
        "Не используйте #FF0000 — красный не из бренда.\n"
        "Порядок цветов в диаграммах: #0077FF, #00C2FF\n"
        "CMYK 0 0 0 0 — фон слайдов\n"
        "Шрифты: заголовки набираются Golos Display Bold, а основной текст — Golos Text Regular.\n"
        "Если Golos нет на компьютере, используйте Play.\n"
        "Логотип ставим в левый верхний угол.\n"
        "Отступы от края слайда — 36 pt.\n"
        "Никогда не растягивайте логотип.\n"
    )
    hits = pdf_colors(text)
    roles = {h.hex: h.role for h in hits}
    assert roles["#0077FF"] == "primary" and roles["#FF3985"] == "accent" and roles["#0B1220"] == "text"
    assert "#FF0000" not in roles  # цвет только из запрета
    assert roles["#FFFFFF"] == "background"  # из CMYK
    assert {h.hex: h.name for h in hits}["#0077FF"] == "VK Blue"
    font_hits, fallback = pdf_fonts(text)
    fonts, _ = make_fonts(font_hits, fallback=fallback)
    assert {f.role: (f.family, f.fallback, f.weight) for f in fonts} == {"heading": ("Golos Display", "Play", 700), "body": ("Golos Text", "Play", 400)}
    rules, margin, _grid, place = pdf_rules(text)
    assert place == "top_left" and margin == 48
    assert [r.text for r in rules][:2] == ["Логотип — в левом верхнем углу", "Поля — 48 px"]
    assert any(r.text == "Никогда не растягивайте логотип" and r.kind == "logo" for r in rules)


def test_handmade_english_pdf(tmp_path):
    pdf = tmp_path / "Acme brand guidelines.pdf"
    pdf.write_bytes(_pdf_bytes([
        "Acme Brand Guidelines", "Primary colour  #1A73E8", "Accent  #FBBC04", "Text  RGB 32 33 36", "Background  #FFFFFF",
        "Headings: Inter Bold", "Body text: Inter Regular", "Logo: top right corner", "Margins: 40 px",
        "Never place the logo on busy photos.",
    ]))
    spec = read_brandbook(pdf)
    assert spec.name == "Acme" and spec.pages == 1
    assert _palette(spec) == {"#1A73E8": "primary", "#FBBC04": "accent", "#202124": "text", "#FFFFFF": "background"}
    assert _fonts(spec)["heading"] == ("Inter", None, 700) and _fonts(spec)["body"] == ("Inter", None, 400)
    assert spec.logo_place == "top_right" and spec.margins_px == 40
    assert any("busy photos" in r.text for r in spec.rules)


def test_pdf_with_a_model_refines_roles_but_never_adds_colours(tmp_path):
    reading = {
        "name": "VK Cloud",
        "colors": [{"hex": "#2787F5", "role": "chart", "name": "Cloud Blue"}, {"hex": "#123456", "role": "accent"}],
        "fonts": [{"role": "heading", "family": "VK Sans Display", "weight": 700}, {"role": "body", "family": "VK Sans Text", "weight": 400}],
        "rules": [{"text": "Фото — только в полный слайд", "kind": "other"}],
    }
    providers = ProviderRegistry.mock({"brand guideline": reading})
    spec = read_pdf(SAMPLE / "guideline.pdf", providers=providers, use_vlm=True)
    call = providers.get("vlm").calls[0]
    assert call["schema"] == "BrandbookReading" and 1 <= call["n_images"] <= 6
    pal = _palette(spec)
    assert pal["#2787F5"] == "chart" and "#123456" not in pal and len(pal) == 6
    assert _fonts(spec)["heading"] == ("VK Sans Display", "Play", 700)  # замена — из текста
    assert any(r.text == "Фото — только в полный слайд" for r in spec.rules)


def test_pdf_model_failure_keeps_the_text_reading():
    providers = ProviderRegistry.mock({"nothing matches": {}})
    spec = read_pdf(SAMPLE / "guideline.pdf", providers=providers, use_vlm=True)
    assert _palette(spec) == SCENARIO_COLORS
    assert any("Модель не смогла" in w for w in spec.warnings)
    assert BrandbookReading.model_json_schema()["properties"]["colors"]


def test_pdf_errors_are_human(tmp_path):
    scan = tmp_path / "скан.pdf"
    scan.write_bytes(_pdf_bytes([]))
    with pytest.raises(BrandReadError, match="нет текста"):
        read_brandbook(scan)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(BrandReadError, match="повреждён"):
        read_brandbook(broken)
    words_only = tmp_path / "words.pdf"
    words_only.write_bytes(_pdf_bytes(["Hello world, nothing about the brand here."]))
    with pytest.raises(BrandReadError, match="ни цветов, ни шрифтов"):
        read_brandbook(words_only)


# ---- Figma -----------------------------------------------------------------------------------------------------------------------
FIGMA_URL = "https://www.figma.com/design/AbCdEf1234567890/Brandbook-VK-Cloud?node-id=0-1"


def _figma_client(seen: list[httpx.Request], *, files_status: int = 200) -> httpx.Client:
    styles = {
        "1:1": {"name": "Brand/Primary", "styleType": "FILL"},
        "1:2": {"name": "Text/Default", "styleType": "FILL"},
        "1:3": {"name": "Background", "styleType": "FILL"},
        "1:4": {"name": "Accent", "styleType": "FILL", "description": "Акцент — только для главного числа"},
        "2:1": {"name": "Heading/H1", "styleType": "TEXT"},
        "2:2": {"name": "Body/Regular", "styleType": "TEXT"},
        "3:1": {"name": "Shadow/Card", "styleType": "EFFECT"},
    }
    fill = lambda r, g, b: {"fills": [{"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": 1}}]}  # noqa: E731
    nodes = {
        "1:1": {"document": fill(0, 119 / 255, 1)}, "1:2": {"document": fill(11 / 255, 18 / 255, 32 / 255)},
        "1:3": {"document": fill(1, 1, 1)}, "1:4": {"document": fill(1, 57 / 255, 133 / 255)},
        "2:1": {"document": {"style": {"fontFamily": "VK Sans Display", "fontWeight": 700, "fontSize": 40}}},
        "2:2": {"document": {"style": {"fontFamily": "VK Sans Text", "fontWeight": 400, "fontSize": 18}}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v1/files/AbCdEf1234567890":
            if files_status != 200:
                return httpx.Response(files_status, json={"status": files_status, "err": "nope"})
            return httpx.Response(200, json={"name": "Брендбук VK Cloud", "styles": styles})
        if path.endswith("/variables/local"):
            return httpx.Response(403, json={"status": 403, "error": True, "message": "Limited by Figma plan"})
        if path.endswith("/nodes"):
            ids = request.url.params["ids"].split(",")
            return httpx.Response(200, json={"nodes": {i: nodes[i] for i in ids if i in nodes}})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_figma_link_without_token_explains_what_to_do(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    with pytest.raises(BrandReadError, match="FIGMA_TOKEN") as e:
        read_brandbook(FIGMA_URL)
    assert "Tokens Studio" in str(e.value)


def test_figma_link_reads_styles_through_the_api(monkeypatch):
    monkeypatch.setenv("FIGMA_TOKEN", "test-token")
    seen: list[httpx.Request] = []
    spec = read_brandbook(FIGMA_URL, figma_client=_figma_client(seen))
    assert spec.source == "figma" and spec.name == "VK Cloud" and spec.file == FIGMA_URL
    assert _palette(spec) == {"#0077FF": "primary", "#0B1220": "text", "#FFFFFF": "background", "#FF3985": "accent"}
    assert _fonts(spec)["heading"][:1] == ("VK Sans Display",) and _fonts(spec)["heading"][2] == 700
    assert _fonts(spec)["body"][0] == "VK Sans Text"
    assert any("главного числа" in r.text for r in spec.rules)
    assert all(r.headers["X-Figma-Token"] == "test-token" for r in seen)
    assert all(r.url.host == "api.figma.com" for r in seen)


def test_figma_api_errors_are_human():
    for status, words in ((403, "доступ"), (404, "не найден"), (429, "через минуту")):
        with pytest.raises(BrandReadError, match=words):
            read_figma_url(FIGMA_URL, token="t", client=_figma_client([], files_status=status))
    with pytest.raises(BrandReadError, match="ссылку на файл Figma"):
        read_figma_url("https://www.figma.com/community", token="t", client=_figma_client([]))


def test_fig_file_and_other_links(tmp_path):
    fig = tmp_path / "Брендбук.fig"
    fig.write_bytes(b"fig-kiwi\x00binary")
    with pytest.raises(BrandReadError, match="Figma"):
        read_brandbook(fig)
    with pytest.raises(BrandReadError, match="только файлы Figma"):
        read_brandbook("https://example.com/brandbook.pdf")


# ---- папка, логотипы, ошибки -------------------------------------------------------------------------------------------------------
def _logo(path: Path, size: tuple[int, int], color: tuple[int, int, int], *, transparent: bool = True) -> Path:
    im = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([size[0] // 8, size[1] // 4, size[0] * 7 // 8, size[1] * 3 // 4], fill=color + (255,))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def test_logo_versions_by_name_and_by_picture(tmp_path):
    assert logo_variant_of(_logo(tmp_path / "logo-white.png", (400, 100), (0, 119, 255))) == ("white", "dark")
    assert logo_variant_of(_logo(tmp_path / "знак.png", (400, 100), (0, 119, 255))) == ("mark", "any")
    with Image.open(_logo(tmp_path / "a.png", (400, 100), (255, 255, 255))) as im:
        assert logo_variant(im) == ("white", "dark")
    with Image.open(_logo(tmp_path / "b.png", (400, 100), (11, 18, 32))) as im:
        assert logo_variant(im) == ("mono", "light")
    with Image.open(_logo(tmp_path / "c.png", (200, 200), (0, 119, 255))) as im:
        assert logo_variant(im) == ("mark", "any")
    with Image.open(_logo(tmp_path / "d.png", (400, 100), (0, 119, 255))) as im:
        assert logo_variant(im) == ("primary", "light")
    svg = tmp_path / "brand.svg"
    svg.write_text('<svg viewBox="0 0 400 100"><path fill="#FFFFFF" d="M0 0h10v10z"/></svg>', encoding="utf-8")
    assert logo_variant_of(svg) == ("white", "dark")


def test_folder_with_logos_slides_and_a_template(tmp_path):
    from pptx import Presentation

    root = tmp_path / "Acme"
    _logo(root / "logos" / "acme.png", (480, 120), (0, 119, 255))
    _logo(root / "logos" / "acme-white.png", (480, 120), (255, 255, 255))
    shutil.copy(SAMPLE / "slides" / "03-pokazateli.png", root / "пример.png")
    buf = io.BytesIO()
    Presentation().save(buf)
    src = zipfile.ZipFile(buf)
    with zipfile.ZipFile(root / "Шаблон Acme.pptx", "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "ppt/theme/theme1.xml":
                t = data.decode("utf-8").replace("4F81BD", "0077FF").replace("C0504D", "FF3985")
                t = re.sub(r'(<a:majorFont><a:latin typeface=")Calibri', r"\1Golos Display", t)
                t = re.sub(r'(<a:minorFont><a:latin typeface=")Calibri', r"\1Golos Text", t)
                data = t.encode("utf-8")
            dst.writestr(item, data)
    spec = read_brandbook(root)
    assert spec.name == "Acme"
    pal = _palette(spec)
    assert pal["#0077FF"] == "primary" and pal["#FF3985"] == "accent"  # тема важнее картинок
    assert _fonts(spec)["heading"][0] == "Golos Display" and _fonts(spec)["body"][0] == "Golos Text"
    assert sorted((lg.variant, lg.file) for lg in spec.logos) == [("primary", "logos/acme.png"), ("white", "logos/acme-white.png")]


def test_folder_tokens_win_over_the_pdf(tmp_path):
    root = tmp_path / "bb"
    root.mkdir()
    shutil.copy(SAMPLE / "guideline.pdf", root / "guideline.pdf")
    (root / "tokens.json").write_text(json.dumps({"color": {"$type": "color", "primary": {"$value": "#123456"}, "accent": {"$value": "#FF3985"}}}), encoding="utf-8")
    spec = read_brandbook(root)
    assert _palette(spec) == {"#123456": "primary", "#FF3985": "accent"}
    assert _fonts(spec)["heading"][0] == "VK Sans Display"  # шрифтов в токенах нет — из PDF


def test_only_slide_pictures_give_a_guessed_palette(tmp_path):
    root = tmp_path / "slides-only"
    root.mkdir()
    for p in (SAMPLE / "slides").glob("*.png"):
        shutil.copy(p, root / p.name)
    spec = read_brandbook(root)
    pal = _palette(spec)
    assert pal["#FFFFFF"] == "background" and pal["#0B1220"] == "text" and pal["#0077FF"] == "primary"
    assert any("картинок" in w for w in spec.warnings)
    assert [h for h, _ in image_colors(SAMPLE / "slides" / "01-oblozhka.png")][:2] == ["#FFFFFF", "#0077FF"]


def test_bad_and_empty_inputs_have_human_errors(tmp_path):
    empty = tmp_path / "tokens.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(BrandReadError, match="пустой"):
        read_brandbook(empty)
    bad = tmp_path / "bad.json"
    bad.write_text('{"color": {"primary": ', encoding="utf-8")
    with pytest.raises(BrandReadError, match="не JSON"):
        read_brandbook(bad)
    nothing = tmp_path / "nothing.json"
    nothing.write_text('{"version": 3, "author": "design team"}', encoding="utf-8")
    with pytest.raises(BrandReadError, match="ни цветов, ни шрифтов"):
        read_brandbook(nothing)
    with pytest.raises(BrandReadError, match="не нашёл|Не нашёл"):
        read_brandbook(tmp_path / "нет-такого.pdf")
    (tmp_path / "пусто").mkdir()
    with pytest.raises(BrandReadError, match="пустая"):
        read_brandbook(tmp_path / "пусто")
    doc = tmp_path / "brand.docx"
    doc.write_bytes(b"PK\x03\x04")
    with pytest.raises(BrandReadError, match="не подходит"):
        read_brandbook(doc)
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("просто заметки", encoding="utf-8")
    with pytest.raises(BrandReadError, match="не нашёл брендбука"):
        read_brandbook(junk)
    notzip = tmp_path / "brand.zip"
    notzip.write_bytes(b"not a zip at all")
    with pytest.raises(BrandReadError, match="повреждён"):
        read_brandbook(notzip)
    emptyzip = tmp_path / "empty.zip"
    with zipfile.ZipFile(emptyzip, "w"):
        pass
    with pytest.raises(BrandReadError, match="пустой"):
        read_brandbook(emptyzip)


def test_errors_are_russian_sentences(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2", encoding="utf-8")
    with pytest.raises(BrandReadError) as e:
        read_brandbook(bad)
    msg = str(e.value)
    assert re.search(r"[а-яё]", msg) and msg.endswith(".") and "Traceback" not in msg


# ---- мелочи ------------------------------------------------------------------------------------------------------------------------
def test_helpers():
    assert parse_color("#07f") == "#0077FF" and parse_color("rgba(0, 119, 255, .5)") == "#0077FF"
    assert parse_color({"r": 1, "g": 1, "b": 1}) == "#FFFFFF" and parse_color("blue") is None
    assert color_role("color.text.primary") == "text" and color_role("brandPrimary") == "primary"
    assert color_role("Основной текст") == "text" and color_role("Фон слайдов") == "background"
    assert color_role("Второй акцент") == "accent" and color_role("телефон") is None
    assert margins_px("Поля — 48 px") == 48 and margins_px("Охранное поле логотипа — 24 px") is None
    assert brand_name("Брендбук VK Cloud") == "VK Cloud" and brand_name("Acme Brand Guidelines 2026") == "Acme"
    rules: list = []
    add_rule(rules, "Только для главного числа на слайде")
    add_rule(rules, "Акцент — только для главного числа")
    add_rule(rules, "Акцент — только для главного числа на слайде")
    assert [r.text for r in rules] == ["Акцент — только для главного числа на слайде"]
    fonts, _ = make_fonts([FontHit("VK Sans Display Bold"), FontHit("VK Sans Text")], fallback="Play")
    assert [(f.role, f.family, f.weight, f.fallback) for f in fonts] == [("heading", "VK Sans Display", 700, "Play"), ("body", "VK Sans Text", 400, "Play")]
