"""Брендбук, PDF: устойчивое чтение (разбор замечаний ревью задачи 5) — образцы цвета столбиком, роли шрифтов в обычной русской
речи, названия шрифтов вне списка, форматы цвета, имена и заголовок документа, фотографии вместо логотипов, выбор страниц
для модели и скан с моделью. Входы ревьюера — `tests/fixtures/brand/pdf/`. Модель подменена, сеть не нужна."""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from verstka.brand.common import ColorHit, make_palette
from verstka.brand.pdf import (
    _FILE_TITLE,
    _guess_name,
    _is_photo,
    _page_images,
    _vlm_pages,
    _page_texts,
    _open,
    pdf_colors,
    pdf_fonts,
    read_pdf,
)
from verstka.brand.read import read_brandbook
from verstka.providers.registry import ProviderRegistry

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "brand" / "pdf"
SAMPLE = ROOT / "examples" / "brandbook-vk-cloud" / "guideline.pdf"


def _roles(spec) -> dict[str, str]:
    return {c.hex: c.role for c in spec.colors}


def _fonts(spec) -> dict[str, tuple]:
    return {f.role: (f.family, f.fallback, f.weight) for f in spec.fonts}


def _fonts_of(text: str) -> dict[str, tuple]:
    from verstka.brand.common import make_fonts

    hits, fb = pdf_fonts(text)
    fonts, _ = make_fonts(hits, fallback=fb)
    return {f.role: (f.family, f.weight) for f in fonts}


# ---- 1. образцы цвета столбиком -----------------------------------------------------------------------------------------------
def test_swatches_with_hex_rgb_and_cmyk_on_separate_lines_are_four_colours_not_eight():
    spec = read_brandbook(FIX / "swatches.pdf")
    assert [c.hex for c in spec.colors] == ["#0A2540", "#1E90FF", "#3DDC97", "#F5F7FA"]
    assert {c.hex: c.name for c in spec.colors} == {"#0A2540": "Deep Navy", "#1E90FF": "Bright Blue", "#3DDC97": "Mint", "#F5F7FA": "Snow"}
    roles = _roles(spec)
    assert roles["#0A2540"] == "primary" and roles["#F5F7FA"] == "background"  # Snow — настоящий фон, а не «графики»
    assert not any("приблизительно" in w for w in spec.warnings)  # CMYK образцов — не отдельные цвета


def test_swatch_row_in_one_line_still_reads():
    spec = read_brandbook(FIX / "swatch_row.pdf")
    assert [c.hex for c in spec.colors] == ["#0A2540", "#1E90FF"]


def test_rgb_and_cmyk_lines_after_a_hex_belong_to_its_swatch():
    text = "Deep Navy\nHEX #0A2540\nRGB 10 37 64\nCMYK 100 80 40 50\nPantone 289 C\nMint\nHEX #3DDC97\nRGB 61 220 151\nCMYK 62 0 59 0\n"
    assert [h.hex for h in pdf_colors(text)] == ["#0A2540", "#3DDC97"]
    # порядок «RGB, затем HEX» тоже не рождает лишних цветов: RGB, равный названному HEX, — дубль
    assert [h.hex for h in pdf_colors("RGB 10 37 64\nHEX #0A2540\n")] == ["#0A2540"]


def test_a_swatch_without_hex_is_read_from_rgb_and_its_cmyk_line_is_skipped():
    text = "Синий Нева\nRGB 0 82 204\nCMYK 100 60 0 0\nНебо\nRGB 76 156 255\nCMYK 70 40 0 0\n"
    hits = pdf_colors(text)
    assert [h.hex for h in hits] == ["#0052CC", "#4C9CFF"]
    assert not any(h.approx for h in hits)


def test_cmyk_only_swatches_are_read_and_flagged_as_approximate():
    hits = pdf_colors("Aurora Green — CMYK 90 20 100 20\nSun — CMYK 0 35 100 0\n")
    assert [h.hex for h in hits] == ["#14A300", "#FFA600"] and all(h.approx for h in hits)
    colors, warnings = make_palette(hits)
    assert len(colors) == 2 and any("приблизительно" in w and "#14A300" in w for w in warnings)
    # точный HEX того же цвета снимает пометку
    _, warnings = make_palette([ColorHit("#14A300", None, None, approx=True), ColorHit("#14A300", "primary")])
    assert not any("приблизительно" in w for w in warnings)


def test_a_line_with_words_next_to_cmyk_or_a_new_name_between_is_a_separate_colour():
    text = "Основной #0052CC\nАкцент\nRGB 255 160 0\n"  # название нового образца между строками разрывает описание
    assert [h.hex for h in pdf_colors(text)] == ["#0052CC", "#FFA000"]
    text = "Основной #0052CC\nCMYK 0 0 0 0 — фон слайдов\n"
    assert {h.hex: h.role for h in pdf_colors(text)} == {"#0052CC": "primary", "#FFFFFF": "background"}


def test_cmyk_pdf_from_the_reviewer_keeps_names_and_warns_about_cmyk():
    spec = read_brandbook(FIX / "cmyk_pantone.pdf")
    assert [c.name for c in spec.colors] == ["Aurora Green", "Deep Teal", "Sun", "Charcoal"]  # без «Colour» и «PANTONE Black»
    assert spec.name == "Aurora Energy"  # а не «cmyk_pantone.html» из заголовка документа
    assert any("приблизительно" in w for w in spec.warnings)
    assert spec.logo_place == "bottom_right"


def test_pantone_only_guideline_explains_why_there_are_no_colours():
    spec = read_brandbook(FIX / "pantone_only.pdf")
    assert spec.colors == []
    assert any("Pantone" in w and "HEX" in w for w in spec.warnings)
    assert spec.fonts  # шрифты прочитаны


def test_other_ways_to_print_a_colour():
    assert [h.hex for h in pdf_colors("Основной R 0 G 82 B 204")] == ["#0052CC"]
    assert [h.hex for h in pdf_colors("Текст R:33 G:37 B:41")] == ["#212529"]
    assert [(h.hex, h.approx) for h in pdf_colors("Акцент C100 M80 Y40 K50")] == [("#00194C", True)]
    assert [h.hex for h in pdf_colors("Акцент C 0 / M 78 / Y 48 / K 0")] == ["#FF3885"]
    assert {h.hex: h.role for h in pdf_colors("Основной HEX 0052CC")} == {"#0052CC": "primary"}
    assert [h.hex for h in pdf_colors("Primary HEX #0052CC")] == ["#0052CC"]  # метка и решётка вместе — один цвет
    assert [h.hex for h in pdf_colors("Слово HEX обозначает цвет, а номер 123456 — нет")] == []


def test_role_comes_from_the_same_sentence():
    hits = pdf_colors("Цвет текста — Night. Фон #FFFFFF. Основной #0077FF.\n")
    assert {h.hex: h.role for h in hits} == {"#FFFFFF": "background", "#0077FF": "primary"}


# ---- 2–3. шрифты ----------------------------------------------------------------------------------------------------------------
def test_font_roles_survive_ordinary_russian_prose():
    spec = read_brandbook(FIX / "rgb_only.pdf")  # «Для заголовков используется шрифт Montserrat Bold. Для основного текста — Roboto Regular.»
    assert _fonts(spec) == {"heading": ("Montserrat", None, 700), "body": ("Roboto", None, 400)}
    spec = read_brandbook(FIX / "table_ru.pdf")  # «Основной шрифт — Golos Text. Шрифт для заголовков — Golos Display.»
    assert _fonts(spec) == {"heading": ("Golos Display", None, 700), "body": ("Golos Text", None, 400)}


@pytest.mark.parametrize("text, expected", [
    ("Для заголовков используется шрифт Montserrat Bold. Для основного текста — Roboto.", {"heading": ("Montserrat", 700), "body": ("Roboto", 400)}),
    ("Основной шрифт — Golos Text. Шрифт для заголовков — Golos Display.", {"heading": ("Golos Display", 700), "body": ("Golos Text", 400)}),
    ("Заголовки набираем в Montserrat Bold, основной текст — в Roboto.", {"heading": ("Montserrat", 700), "body": ("Roboto", 400)}),
    ("Montserrat Bold для заголовков, Roboto для текста.", {"heading": ("Montserrat", 700), "body": ("Roboto", 400)}),
    ("Для заголовков — Montserrat Bold, для текста — Roboto.", {"heading": ("Montserrat", 700), "body": ("Roboto", 400)}),
    ("Для текста — Roboto. Для заголовков — Montserrat.", {"heading": ("Montserrat", 700), "body": ("Roboto", 400)}),
])
def test_font_role_phrasings(text, expected):
    assert _fonts_of(text) == expected


def test_single_word_fonts_outside_the_known_list_are_kept():
    assert _fonts_of("Шрифт заголовков: Poppins Bold / Шрифт текста: Inter") == {"heading": ("Poppins", 700), "body": ("Inter", 400)}
    assert _fonts_of("Primary typeface: Zephyr. Secondary typeface: Quasar.") == {"heading": ("Zephyr", 700), "body": ("Quasar", 400)}
    assert _fonts_of("Headings: Zephyr Bold\nBody: Quasar") == {"heading": ("Zephyr", 700), "body": ("Quasar", 400)}
    spec = read_brandbook(FIX / "swatches.pdf")  # «Primary typeface: Poppins. Secondary typeface: Source Sans Pro.»
    assert _fonts(spec) == {"heading": ("Poppins", None, 700), "body": ("Source Sans Pro", None, 400)}


def test_ordinary_capitalised_words_are_not_fonts():
    assert pdf_fonts("Headings: Use sparingly. Never stretch the logo.\nFont: Always readable.")[0] == []
    assert pdf_fonts("Typography. Colour. Logo. Primary. Secondary.")[0] == []


# ---- имена и заголовок документа -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("title", ["rgb_only.html", "Microsoft Word - Документ1", "Untitled", "Без названия", "брендбук.docx", "Presentation1.pptx"])
def test_a_title_the_program_set_itself_is_not_a_brand_name(title):
    assert _FILE_TITLE.search(title)
    name, trusted = _guess_name(title, ["Acme Brand Guidelines\nЦвета"], "whatever")
    assert name == "Acme" and trusted


def test_title_equal_to_the_file_name_is_only_a_guess_and_the_model_may_replace_it(tmp_path):
    assert _guess_name("Aster Brand Guidelines", [""], "Aster-Brand-Guidelines") == ("Aster", False)
    assert _guess_name("VK Cloud — брендбук", [""], "x") == ("VK Cloud", True)
    assert _guess_name(None, ["Руководство по фирменному стилю\n«Нева Банк»\nЦвета"], "rgb_only") == ("Нева Банк", True)
    assert _guess_name(None, ["Hello"], "navybank") == ("navybank", False)


def test_the_title_of_a_russian_guideline_wraps_onto_two_lines():
    spec = read_brandbook(FIX / "rgb_only.pdf")
    assert spec.name == "Нева Банк"
    assert _roles(spec) == {"#0052CC": "primary", "#4C9CFF": "secondary", "#FFA000": "accent", "#212529": "text", "#FFFFFF": "background"}
    assert spec.margins_px == 40 and spec.logo_place == "top_left"


# ---- 10. фотографии вместо логотипов ------------------------------------------------------------------------------------------------------
def test_a_photo_on_a_page_that_mentions_the_logo_is_not_saved_as_a_logo(tmp_path):
    spec = read_brandbook(FIX / "logo_photo.pdf", assets_dir=tmp_path)
    assert spec.logos == [] and not list((tmp_path / "logos").glob("*"))
    assert _roles(spec)["#1E90FF"] == "primary"
    # настоящие логотипы примера не отброшены
    spec = read_brandbook(SAMPLE, assets_dir=tmp_path / "real")
    assert sorted(lg.variant for lg in spec.logos) == ["mark", "mono", "primary", "white"]


def test_photo_detector_separates_flat_logos_from_pictures():
    import random

    random.seed(3)
    photo = Image.new("RGB", (300, 200))
    photo.putdata([(int(110 + x / 3 + random.gauss(0, 7)), int(100 + y / 3 + random.gauss(0, 7)), int(90 + random.gauss(0, 7))) for y in range(200) for x in range(300)])
    assert _is_photo(photo)
    flat = Image.new("RGB", (300, 100), (255, 255, 255))
    flat.paste((0, 68, 204), (20, 30, 160, 70))
    assert not _is_photo(flat)
    cut = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
    cut.paste((255, 255, 255, 255), (20, 30, 160, 70))
    assert not _is_photo(cut)
    buf = io.BytesIO()
    flat.save(buf, format="JPEG", quality=60)  # шум сжатия — ещё не фотография
    assert not _is_photo(Image.open(io.BytesIO(buf.getvalue())))


# ---- 11. страницы для модели ---------------------------------------------------------------------------------------------------------------
def test_pages_for_the_model_skip_the_cover_and_the_contents_and_keep_logo_grid_and_rules():
    texts = _page_texts(_open(SAMPLE))
    picked = [i + 1 for i in _vlm_pages(texts)]
    assert len(picked) == 6 and picked == sorted(picked)
    assert 1 not in picked and 12 not in picked  # обложка и «Файлы брендбука»
    assert {3, 5, 8, 10} <= set(picked)  # палитра, шрифты, сетка и поля, правила
    assert 9 in picked  # диаграммы: HEX порядка цветов и правила


def test_pages_with_only_colour_font_and_logo_words_are_not_chosen():
    def page(extra: str = "") -> str:
        return f"Acme · цвета, шрифты, логотип\n{extra}\n3 / 12"

    texts = [page("Цвета, шрифты, логотип и правила бренда")]  # обложка
    texts.append(page("Содержание\n3 Цвет\n4 Шрифты\n5 Логотип\n6 Правила"))  # оглавление
    texts += [page("О компании") for _ in range(6)]
    texts.append(page("Основной #0052CC\nАкцент #FFA000"))  # настоящая страница палитры — только она на 9-м месте
    texts.append(page("Шрифт заголовков — Poppins Bold, основной текст — Inter"))
    texts.append(page("Логотип — в правом нижнем углу. Не растягивайте логотип. Нельзя менять цвета логотипа."))
    texts += [page("О компании") for _ in range(4)]
    picked = [i + 1 for i in _vlm_pages(texts)]
    assert picked == [9, 10, 11] and 1 not in picked and 2 not in picked
    assert _vlm_pages(["scan"] * 3) == [0, 1, 2]


def test_a_scanned_guideline_sends_six_pages_spread_over_the_document():
    picked = _vlm_pages([""] * 24)
    assert len(picked) == 6 and 0 not in picked and picked[-1] >= 20


def test_pages_for_the_model_are_rendered_wide_enough_to_read_hex():
    img = Image.open(io.BytesIO(_page_images(SAMPLE, [2])[0]))
    assert img.size[0] >= 1600
    providers = ProviderRegistry.mock({"brand guideline": {"name": "VK Cloud"}})
    read_pdf(SAMPLE, providers=providers, use_vlm=True)
    sent = [im for m in providers.get("vlm").calls[0]["messages"] for im in m.images]
    assert 1 <= len(sent) <= 6 and all(Image.open(io.BytesIO(b)).size[0] >= 1600 for b in sent)


# ---- модель: скан и имя -----------------------------------------------------------------------------------------------------------------------
def _scan_of(src: Path, dst: Path) -> Path:
    doc = pdfium.PdfDocument(str(src))
    try:
        doc[0].render(scale=1.5).to_pil().convert("RGB").save(dst, format="PDF")
    finally:
        doc.close()
    return dst


READING = {
    "name": "Нева Банк",
    "colors": [{"hex": "#0052cc", "role": "primary", "name": "Синий Нева"}, {"hex": "#FFA000", "role": "accent"},
               {"hex": "#212529", "role": "text"}, {"hex": "#FFFFFF", "role": "background"}],
    "fonts": [{"role": "heading", "family": "Montserrat", "weight": 700}, {"role": "body", "family": "Roboto", "weight": 400}],
    "logo_place": "top_left",
    "margins_px": 40,
    "rules": [{"text": "Нельзя менять пропорции логотипа", "kind": "logo"}],
}


def test_scanned_pdf_is_read_by_the_model_and_merged(tmp_path):
    scan = _scan_of(FIX / "rgb_only.pdf", tmp_path / "скан гайдлайна.pdf")
    providers = ProviderRegistry.mock({"brand guideline": READING})
    spec = read_brandbook(scan, providers=providers, use_vlm=True)
    assert _roles(spec) == {"#0052CC": "primary", "#FFA000": "accent", "#212529": "text", "#FFFFFF": "background"}
    assert _fonts(spec) == {"heading": ("Montserrat", None, 700), "body": ("Roboto", None, 400)}
    assert spec.name == "Нева Банк"  # а не «скан гайдлайна» из имени файла
    assert spec.logo_place == "top_left" and spec.margins_px == 40
    assert any("по картинкам страниц" in w for w in spec.warnings)
    assert any(r.text == "Нельзя менять пропорции логотипа" for r in spec.rules)
    call = providers.get("vlm").calls[0]
    assert call["schema"] == "BrandbookReading" and call["n_images"] == 1
    # без модели скан не читается — человеческая ошибка
    from verstka.brand.common import BrandReadError

    with pytest.raises(BrandReadError, match="нет текста"):
        read_brandbook(scan)
    # модель недоступна или ответила мусором — понятная ошибка, а не трассировка
    with pytest.raises(BrandReadError, match="не смогла прочитать"):
        read_brandbook(scan, providers=ProviderRegistry.mock({"nothing matches": {}}), use_vlm=True)


def test_the_models_name_outranks_a_name_guessed_from_the_file_name(tmp_path):
    from test_brand_read import _pdf_bytes

    pdf = tmp_path / "navybank.pdf"
    pdf.write_bytes(_pdf_bytes(["Primary colour  #1A73E8", "Text  #202124", "Headings: Inter Bold"]))
    assert read_pdf(pdf).name == "navybank"  # без модели — догадка по имени файла
    providers = ProviderRegistry.mock({"brand guideline": {"name": "Navy Bank"}})
    assert read_pdf(pdf, providers=providers, use_vlm=True).name == "Navy Bank"
    # имя из заголовка страницы надёжно: модель его не заменяет
    pdf2 = tmp_path / "x.pdf"
    pdf2.write_bytes(_pdf_bytes(["Acme Brand Guidelines", "Primary colour  #1A73E8", "Text  #202124", "Headings: Inter Bold"]))
    providers = ProviderRegistry.mock({"brand guideline": {"name": "Другое имя"}})
    assert read_pdf(pdf2, providers=providers, use_vlm=True).name == "Acme"
