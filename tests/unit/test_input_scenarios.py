"""Вход, как его дают эксперты (прогон «все сценарии ввода», 20.10): неудобные реальные случаи чтения данных, плана,
документов, страниц базы знаний и брендбука — каждый с тем, что было не так.

- CSV через запятую с дробной запятой без кавычек («Прибыль, млн ₽» / «-12,5») — одно число и единица, а не «-12» и «5»;
- таблица в тексте «Этап|Пользователи» без рамки — читается; проза с «|» — нет;
- «Покажи, что выручка растёт, сравни регионы» — цель динамики рядом с другими целями того же предложения;
- служебные имена файлов («d06_multisheet.xlsx») не идут в название колоды и подписи; название до двоеточия брифа —
  название колоды; в склеенном заголовке имя из данных («Москва») — с большой буквы;
- величина «меньше — лучше» (текучесть) — не «впереди»;
- журнал операций с номером строки и плотными датами — ось времени (агрегация по месяцам), а не перечень заказов;
- план в .txt построчно («Слайд 1: …», «Слайд 2: …») — строка на абзац, а не одна склеенная строка;
- формулы Википедии — знаками («ẋ»), без «{\\displaystyle …}»;
- скан PDF-гайдлайна без модели — палитра с картинок страниц и честное предупреждение."""

from __future__ import annotations

import csv
import datetime
import io
import random

import pytest
from PIL import Image, ImageDraw

from verstka.data.goals import goals_of
from verstka.data.plan import plan_dataset
from verstka.data.profile import profile_table
from verstka.data.readers import DataReadError, read_bytes
from verstka.data.words import file_title, technical_name
from verstka.ingest.documents import read_document, read_html, tex_plain


def _plan(name: str, text: str):
    t = read_bytes(name, text.encode("utf-8"))[0]
    return t, plan_dataset(profile_table(t), t)


# ---- чтение данных -------------------------------------------------------------------------------------------------------------
def test_comma_csv_with_unquoted_decimal_comma_and_unit():
    t = read_bytes("q.csv", "Квартал,Прибыль, млн ₽\nI кв. 2025,-12,5\nII кв. 2025,-4,1\nIII кв. 2025,3,8\nIV кв. 2025,9,2\n".encode())[0]
    assert t.columns == ["Квартал", "Прибыль"] and t.units[1] == "млн ₽"
    assert [r[1] for r in t.rows] == [-12.5, -4.1, 3.8, 9.2]
    _, p = _plan("q.csv", "Квартал,Прибыль, млн ₽\nI кв. 2025,-12,5\nII кв. 2025,-4,1\nIII кв. 2025,3,8\nIV кв. 2025,9,2\n")
    assert "21,7 млн ₽" in p.headline
    # обычный CSV с единицей в кавычках и целыми — как был
    t2 = read_bytes("r.csv", 'Регион,"Выручка, млн ₽"\nМосква,120\nКазань,80\nПермь,40\n'.encode())[0]
    assert t2.columns == ["Регион", "Выручка"] and [r[1] for r in t2.rows] == [120, 80, 40]


def test_single_pipe_two_column_text_table():
    t = read_bytes("воронка.txt", "Этап|Пользователи\nЗашли|10000\nЗарегистрировались|3200\nОплатили|640\nПродлили|410\n".encode())[0]
    assert t.columns == ["Этап", "Пользователи"] and t.rows[0] == ["Зашли", 10000]
    with pytest.raises(DataReadError):
        read_bytes("проза.txt", "Это текст | не таблица\nа здесь просто | слова\nи ещё | раз\n".encode())


def test_transaction_log_gets_a_time_axis():
    rnd = random.Random(3)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID заказа", "Дата", "Категория", "Сумма, ₽"])
    for i in range(3000):
        d = datetime.date(2025, 1, 1) + datetime.timedelta(days=rnd.randrange(365))
        w.writerow([100000 + i, d.isoformat(), f"Категория {rnd.randrange(60):02d}", round(rnd.uniform(500, 5000), 2)])
    t, p = _plan("orders.csv", buf.getvalue())
    prof = profile_table(t)
    assert {c.name: c.role for c in prof.columns}["Дата"] == "time"
    assert p.task.task == "dynamics" and p.options[p.chosen].kind in ("line", "column", "area")


def test_client_list_date_stays_an_attribute():
    rows = "\n".join(f"Клиент {i},2024-{1 + i % 12:02d}-{1 + (i * 7) % 28:02d},{100 + i * 3}" for i in range(40))
    t = read_bytes("clients.csv", ("Клиент,Дата договора,Выручка, млн ₽\n" + rows + "\n").encode())[0]
    roles = {c.name: c.role for c in profile_table(t).columns}
    assert roles["Дата договора"] != "time"


# ---- цели, названия, формулировки --------------------------------------------------------------------------------------------
def test_show_that_goal_beside_other_goals():
    gs = goals_of("Итоги 2025 года для правления. Покажи, что выручка растёт, сравни регионы.")
    assert [(g.task, g.subject) for g in gs[:2]] == [("dynamics", ["выручк"]), ("comparison", ["регион"])]
    assert goals_of("Покажите, что отток снизился за год.")[0].subject == ["оттк"]
    # «вырос сильнее всего» — вопрос «кто быстрее», а не просто динамика
    assert goals_of("Покажи, что найм в разработку вырос сильнее всего.")[0].ask == "fastest"


def test_technical_file_names_are_not_titles():
    assert technical_name("d06_multisheet.xlsx") and technical_name("export_2025.csv") and not technical_name("Выручка по месяцам.csv")
    assert file_title("d06_multisheet.xlsx", "Регионы") == "Регионы"
    assert file_title("Продажи.xlsx", "Регионы") == "Продажи · Регионы"
    _, p = _plan("d03_cp1251.csv", "Канал;Доля, %\nПрямые продажи;42\nПартнёры;27\nМаркетплейс;18\nСайт;13\n")
    assert "d03" not in (p.plain_headline or "").lower()


def test_lower_is_better_metric_is_not_ahead():
    _, p = _plan("Отделы.tsv", "Отдел\tСотрудников\tТекучесть, %\nПродажи\t48\t12,5\nПоддержка\t35\t18,2\nРазработка\t120\t6,1\n"
                               "Маркетинг\t17\t9,4\nHR\t8\t4,0\n")
    assert "впереди" not in p.headline and "Поддержка" in p.headline


def test_data_deck_title_and_joined_heading():
    from verstka.data.story import build_data_outline
    from verstka.planning.brief import parse_brief_text

    tables = read_bytes("d07_records.json", '[{"Продукт":"Облако","Выручка, млн ₽":320},{"Продукт":"Хранилище","Выручка, млн ₽":145},'
                                            '{"Продукт":"CDN","Выручка, млн ₽":23}]'.encode())
    tables += read_bytes("d02_regions.csv", "Регион;Выручка, млн ₽\nМосква;412\nКазань;64\nПермь;51\n".encode())
    o = build_data_outline(parse_brief_text("Квартальный отчёт: продукты и регионы."), tables, use_llm=False)
    assert o.slides[0].headline == "Квартальный отчёт"
    o2 = build_data_outline(parse_brief_text("Отчёт для финансового директора: продукты и регионы."), tables, use_llm=False)
    assert o2.slides[0].headline == "Отчёт для финансового директора"
    for s in o.slides:
        assert "d07" not in (s.headline or "").lower() and "d02" not in (s.headline or "").lower()
        for it in s.content.items:
            assert "d07" not in (it.title or "").lower() and "d02" not in (it.title or "").lower()


# ---- документы и страницы ------------------------------------------------------------------------------------------------------
def test_txt_plan_keeps_its_lines():
    d = read_document("план.txt", "Слайд 1: Обложка — Итоги хакатона 2025\nСлайд 2: 412 участников из 37 городов\nСлайд 3: Лучшие команды\n".encode())
    md = d.markdown()
    assert "Слайд 2: 412 участников из 37 городов\n\nСлайд 3: Лучшие команды" in md and not md.startswith("#")
    # перенос строки внутри фразы — та же фраза
    d2 = read_document("t.txt", "Команда и найм\nВ этом году мы наняли 40 человек, из них половина\nв разработку.\n".encode())
    assert "половина в разработку." in d2.markdown()


def test_wikipedia_formulas_in_signs():
    assert tex_plain(r"{\displaystyle {\dot {x}}}") == "ẋ"
    assert tex_plain(r"{\displaystyle f'(x_{0})=\lim _{\Delta x\to 0}{\frac {\Delta y}{\Delta x}}}") == "f'(x₀) = lim_(Δx → 0)(Δy)/(Δx)"
    html = ('<html><body><main><p>Например: <span class="mwe-math-element"><span style="display:none"><math><semantics><mi>x</mi>'
            '<annotation encoding="application/x-tex">{\\displaystyle {\\dot {x}}}</annotation></semantics></math></span>'
            '<img alt="{\\displaystyle {\\dot {x}}}"></span> — производная.</p></main></body></html>')
    md = read_html("w.html", html).markdown()
    assert "Например: ẋ — производная." in md and "displaystyle" not in md


# ---- брендбук ------------------------------------------------------------------------------------------------------------------
def test_scanned_brand_pdf_without_model_gives_page_colours(tmp_path):
    from verstka.brand.read import read_brandbook

    page = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(page)
    d.rectangle((100, 300, 500, 500), fill="#1B5E20")
    d.rectangle((600, 300, 1000, 500), fill="#FF6F00")
    p = tmp_path / "скан.pdf"
    page.save(p, "PDF", resolution=150)
    spec = read_brandbook(p)
    roles = {c.hex: c.role for c in spec.colors}
    assert roles.get("#FFFFFF") == "background" and any(r == "primary" for r in roles.values())
    assert any("нет текста (скан)" in w for w in spec.warnings) and not spec.fonts


def test_brand_margins_move_text_placeholders(tmp_path, monkeypatch):
    """Поля из токенов («slide-margin: 120px») применяются: заголовки и текст макетов, стоявшие ближе к краю, отодвинуты
    внутрь; в расхождениях — строка «Поля»; без полей в брендбуке ничего не двигается."""
    import re as _re
    import zipfile

    import verstka.brand.apply as ap
    from test_brand_apply import W, _analyze, _brand, build_template
    from verstka.brand.apply import apply_brand, template_inset_px
    from verstka.brand.conflicts import brand_conflicts
    from verstka.brand.package import Package

    monkeypatch.setattr(ap, "font_available", lambda f: True)
    src = build_template(tmp_path, logo=False)
    m = _analyze(src, tmp_path / "ws")
    before = template_inset_px(Package(src))
    assert before is not None and before < 120
    out = tmp_path / "branded.pptx"
    res = apply_brand(src, out, _brand(margins_px=120), manifest=m)
    assert res.margins_moved > 0 and any("Поля брендбука 120 px" in w for w in res.warnings)
    with zipfile.ZipFile(out) as z:
        for n in z.namelist():
            if _re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n):
                xml = z.read(n).decode()
                for x, cx in _re.findall(r'<p:sp>.*?<p:ph type="title".*?<a:off x="(\d+)" y="\d+"/><a:ext cx="(\d+)"', xml, _re.S):
                    assert int(x) >= 120 / 1920 * W - W * 0.004 and int(x) + int(cx) <= W - 120 / 1920 * W + W * 0.004
    rows = {c.what: c for c in brand_conflicts(m, _brand(margins_px=120), source=src, workspace_root=tmp_path / "ws")}
    assert rows["Поля"].brand == "120 px" and "отодвинут" in rows["Поля"].result
    res0 = apply_brand(src, tmp_path / "plain.pptx", _brand(margins_px=None), manifest=m)
    assert res0.margins_moved == 0


def test_brand_folder_reads_its_readme(tmp_path):
    """Папка брендбука: логотипы, примеры слайдов и README.txt с цветами и шрифтами словами — шрифты и роли цветов из
    README, фон и текст — с примеров слайдов; README без цветов и шрифтов ничего не меняет."""
    from verstka.brand.read import read_brandbook

    d = tmp_path / "Лес"
    (d / "logos").mkdir(parents=True)
    (d / "slides").mkdir()
    im = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((0, 0, 100, 100), fill="#1B5E20")
    im.save(d / "logos" / "logo.png")
    s = Image.new("RGB", (1600, 900), "#F5F1E8")
    ImageDraw.Draw(s).rectangle((100, 200, 900, 300), fill="#212121")
    s.save(d / "slides" / "slide1.png")
    (d / "README.txt").write_text("Основной цвет #1B5E20, акцент #FF6F00. Заголовки — PT Serif, основной текст — PT Sans.\n", encoding="utf-8")
    spec = read_brandbook(d, assets_dir=tmp_path / "a")
    roles = {c.role: c.hex for c in spec.colors}
    assert roles["primary"] == "#1B5E20" and roles["accent"] == "#FF6F00" and roles["background"] == "#F5F1E8"
    assert {f.role: f.family for f in spec.fonts} == {"heading": "PT Serif", "body": "PT Sans"}
    (d / "README.txt").write_text("Файлы брендбука: логотипы и примеры слайдов.\n", encoding="utf-8")
    plain = read_brandbook(d, assets_dir=tmp_path / "b")
    assert not plain.fonts and any("примеров слайдов" in w for w in plain.warnings)


def test_figma_links_without_token_point_to_fig_file(monkeypatch):
    from verstka.brand.common import BrandReadError
    from verstka.brand.read import read_brandbook

    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    with pytest.raises(BrandReadError, match=r"файл \.fig"):
        read_brandbook("https://www.figma.com/design/kVm3XqRsU1pTz0aBcDeFgH/Brand?node-id=0-1")
    with pytest.raises(BrandReadError, match="Сообществе Figma"):
        read_brandbook("https://www.figma.com/community/file/1380235722331273046/simple-design-system")


def test_figma_plugin_export_string_font_variable(tmp_path):
    import json

    from verstka.brand.read import read_brandbook

    p = tmp_path / "variables.json"
    p.write_text(json.dumps({"collections": [{"name": "Brand", "modes": [{"name": "Light", "variables": [
        {"name": "primary", "type": "color", "value": "#1B5E20"}, {"name": "background", "type": "color", "value": "#F5F1E8"},
        {"name": "font-heading", "type": "string", "value": "PT Serif"}, {"name": "font-body", "type": "string", "value": "PT Sans"}]}]}]}),
        encoding="utf-8")
    spec = read_brandbook(p)
    assert {f.role: f.family for f in spec.fonts} == {"heading": "PT Serif", "body": "PT Sans"}


def _pdf_with(items: list[tuple[float, float, str, bool]]) -> bytes:
    """Одна страница A4: текст в точках (x, y), Helvetica (жирный — Helvetica-Bold)."""
    ops = "".join(f"BT /{'F2' if b else 'F1'} 12 Tf {x} {y} Td ({t}) Tj ET\n" for x, y, t, b in items).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % k + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def test_pdf_narrow_table_columns_by_alignment():
    """Таблица PDF с колонками в одно слово друг от друга («Moscow 18400»): раньше строки шли абзацами, а жирная шапка —
    заголовком; теперь колонки находятся по выравниванию начал слов — таблица с шапкой, число — данные. Проза из
    нескольких кусков с разными отступами таблицей не становится."""
    items = [(56, 780, "Delivery report", True), (56, 750, "The service runs in three cities since 2025.", False),
             (63, 600, "City", True), (105, 600, "Orders per month", True)]
    for k, (c, n) in enumerate([("Moscow", "18400"), ("Kazan", "6200"), ("Perm", "3100")]):
        items += [(58, 569 - 31 * k, c, False), (103, 569 - 31 * k, n, False)]
    items += [(56, 400, "Plain text goes on here with a", False), (240, 400, "bold", True), (270, 400, "word inside.", False),
              (56, 386, "Another line of plain text,", False), (60, 372, "and one more line", False), (200, 372, "of text.", False)]
    d = read_document("narrow.pdf", _pdf_with(items))
    md = d.markdown()
    assert "| City | Orders per month |" in md and "| Moscow | 18400 |" in md and "### City" not in md
    assert d.summary()["data_tables"] == 1
    assert "Plain text goes on here" in md and "| Plain" not in md


def test_monochrome_brand_replaces_template_accents(tmp_path, monkeypatch):
    """Брендбук задаёт только основной #2C2C2C и нейтральные (Simple Design System): приоритет у брендбука — акценты
    шаблона (#1F6FEB, #E8590C) становятся тонами основного, строка «Акценты шаблона заменены цветами бренда»; в разборе
    копии акцент — тон основного, а не красный «ошибки» бренда."""
    import verstka.brand.apply as ap
    from test_brand_apply import _analyze, build_template
    from verstka.brand.apply import apply_brand, brand_plan
    from verstka.brand.conflicts import brand_conflicts
    from verstka.brand.palette import retune_manifest, tone
    from verstka.schemas.brand import BrandColor, BrandSpec
    from verstka.schemas.template import ColorToken

    monkeypatch.setattr(ap, "font_available", lambda f: True)
    src = build_template(tmp_path, logo=False)
    m = _analyze(src, tmp_path / "ws")
    brand = BrandSpec(name="Simple", source="figma", colors=[BrandColor(hex="#2C2C2C", role="primary"), BrandColor(hex="#FFFFFF", role="background"),
                                                              BrandColor(hex="#1E1E1E", role="text"), BrandColor(hex="#EC221F", role="danger")])
    plan = brand_plan(src, m, brand, "brand").colors
    assert plan.mono == "2C2C2C"
    for a in ("1F6FEB", "E8590C"):
        assert tone(plan.map(a)) != "chromatic", (a, plan.map(a))
    res = apply_brand(src, tmp_path / "out.pptx", brand, manifest=m)
    assert "#1F6FEB" in res.colors and tone(res.colors["#1F6FEB"].lstrip("#")) != "chromatic"
    rows = {c.what: c for c in brand_conflicts(m, brand, source=src, workspace_root=tmp_path / "ws")}
    assert rows["Акценты"].result.startswith("Акценты шаблона заменены цветами бренда")
    copy = m.model_copy(deep=True)
    copy.tokens.colors = [ColorToken(hex="EC221F", role="accent.1", roles=["accent.1"], weight=5.0),
                          ColorToken(hex="FFFFFF", role="background.light", roles=["background.light"], weight=50.0)]
    copy.components.number_callout.color_hex = "EC221F"
    assert retune_manifest(copy, m, plan, {})
    assert copy.tokens.color_for("accent.1") != "EC221F" and tone(copy.tokens.color_for("accent.1")) != "chromatic"
    assert copy.components.number_callout.color_hex != "EC221F"


def test_monochrome_brand_on_a_saturated_picture_ground(tmp_path, monkeypatch):
    """Фон шаблона — насыщенная синяя картинка (Metropolis), её не перекрасить: в разборе копии фон остаётся синим,
    выделение — светлый тон основного с контрастом ≥ 4,5 : 1, серые плашки средней светлоты — не заливкой (контур)."""
    import verstka.brand.apply as ap
    from test_brand_apply import _analyze, build_template
    from verstka.brand.apply import brand_plan
    from verstka.brand.palette import lightness, retune_manifest
    from verstka.schemas.brand import BrandColor, BrandSpec
    from verstka.schemas.common import contrast_ratio
    from verstka.schemas.template import BackgroundFamily, ColorToken

    monkeypatch.setattr(ap, "font_available", lambda f: True)
    src = build_template(tmp_path, logo=False)
    m = _analyze(src, tmp_path / "ws")
    brand = BrandSpec(name="Simple", source="figma", colors=[BrandColor(hex="#2C2C2C", role="primary"), BrandColor(hex="#FFFFFF", role="background"),
                                                              BrandColor(hex="#1E1E1E", role="text")])
    orig = m.model_copy(deep=True)
    orig.tokens.colors = [ColorToken(hex="20549A", role="background.dark", roles=["background.dark", "accent.1"], weight=1.0)]
    orig.tokens.backgrounds = [BackgroundFamily(family="dark", fill_kind="image", hex="20549A", slides=[1, 2, 3])]
    plan = brand_plan(src, m, brand, "brand").colors
    plan.main = ["20549A"] + [x for x in plan.main if x != "20549A"]
    plan.table.setdefault("20549A", "555555")
    copy = orig.model_copy(deep=True)
    copy.tokens.colors = [ColorToken(hex="555555", role="background.dark", roles=["background.dark", "accent.1"], weight=1.0),
                          ColorToken(hex="656565", role="surface", roles=["surface"], weight=0.5)]
    copy.tokens.backgrounds = [BackgroundFamily(family="dark", fill_kind="image", hex="555555", slides=[1, 2, 3])]
    from verstka.schemas.template import CardSpec

    copy.components.card = CardSpec(fill_hex="656565")
    retune_manifest(copy, orig, plan, {})
    assert copy.tokens.backgrounds[0].hex == "20549A"
    acc = copy.tokens.color_for("accent.1")
    assert lightness(acc) > 80 and contrast_ratio(acc, "20549A") >= 4.5
    assert not any("surface" in t.roles for t in copy.tokens.colors if t.hex == "656565")
    assert copy.components.card.fill_hex is None
