"""The composer after the swarm review of 2026-10-05: no option dropped from a row of columns, the figures of a grid at
one size, no computed figure that contradicts the author, a formula's figures not repeated under it."""

from __future__ import annotations

from test_compose import _render, env  # noqa: F401  (shared fixture)

from verstka.schemas.common import PatternKind
from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem


def _texts(slide) -> str:
    return "\n".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def test_four_options_on_a_two_column_slide_are_all_shown(env):  # noqa: F811
    items = [SlideItem(title=t, text=f"Тариф «{t}» для кофейни") for t in ("Старт", "Бизнес", "Сеть", "Премиум")]
    o = OutlineSlide(id="c", kind=PatternKind.two_column, headline="Тарифы", content=SlideContent(items=items))
    for comp in ("two_column", "cards"):
        slide, warnings = _render(env, o, comp)
        text = _texts(slide)
        assert all(t in text for t in ("Старт", "Бизнес", "Сеть", "Премиум")), (comp, text)


def test_no_growth_is_computed_across_a_loss_nor_without_a_unit():
    """Profit from −2,1 to 10,5 млн ₽: «+12,6 прирост» across the sign read as a growth the brief never stated, and
    without its unit. A computed change needs a positive start and a unit."""
    from verstka.rendering.compose import _series_takeaway
    from verstka.schemas.outline import ChartSpec, DeckOutline, Series

    months = ["Январь", "Март", "Июнь", "Декабрь"]
    loss = DeckOutline(title="t", series=[Series(id="p", name="Прибыль", categories=months, values=[-2.1, 1.0, 4.0, 10.5], unit="млн ₽")])
    assert _series_takeaway(ChartSpec(type="line", series_ids=["p"]), loss, "Прибыль") is None
    flat = DeckOutline(title="t", series=[Series(id="v", name="Гости", categories=months, values=[400, 410, 430, 450])])
    assert _series_takeaway(ChartSpec(type="line", series_ids=["v"]), flat, "Гости") is None
    with_unit = DeckOutline(title="t", series=[Series(id="v", name="Гости", categories=months, values=[400, 410, 430, 450], unit="чел.")])
    assert _series_takeaway(ChartSpec(type="line", series_ids=["v"]), with_unit, "Гости") == ("+50 чел.", "прирост за период январь → декабрь")


def test_the_lines_beside_a_chart_count_as_its_stated_change(env):  # noqa: F811
    """«Выручка выросла к декабрю на 55% относительно января» beside the chart: no «×1,6 рост» next to it."""
    from verstka.schemas.outline import ChartSpec, DeckOutline, Series

    o = OutlineSlide(id="r", kind=PatternKind.chart, headline="Выручка по месяцам", content=SlideContent(chart=ChartSpec(type="line", series_ids=["rev"]), bullets=["Выручка выросла к декабрю на 55% относительно января"]))
    deck, manifest, ws = env
    from verstka.rendering.deck import DeckBuilder
    from verstka.rendering.synth import render_synth
    from verstka.schemas.layout import LayoutSlide

    outline = DeckOutline(title="T", strategy="visual", slides=[o], series=[Series(id="rev", name="Выручка", categories=["Январь", "Июнь", "Декабрь"], values=[41.2, 50.0, 63.9], unit="млн ₽")])
    slide, _ = render_synth(DeckBuilder(deck), LayoutSlide(outline_id="r", mode="synth", composition="chart_text"), o, manifest, ws, outline)
    text = _texts(slide)
    assert "×1,6" not in text and "×1,5" not in text, text
    # the author's own slide (verbatim) never gets a computed figure
    o2 = o.model_copy(update={"verbatim": True, "content": o.content.model_copy(update={"bullets": ["Выручка по месяцам за год"]})})
    outline2 = outline.model_copy(update={"slides": [o2]})
    slide, _ = render_synth(DeckBuilder(deck), LayoutSlide(outline_id="r", mode="synth", composition="chart_text"), o2, manifest, ws, outline2)
    assert "×1,6" not in _texts(slide)
    # (and a slide written for the deck does: the guard above is the author's words, not a missing callout)
    o3 = o2.model_copy(update={"verbatim": False})
    slide, _ = render_synth(DeckBuilder(deck), LayoutSlide(outline_id="r", mode="synth", composition="chart_text"), o3, manifest, ws, outline.model_copy(update={"slides": [o3]}))
    assert "×1,6" in _texts(slide)


def test_a_formula_never_repeats_its_own_figures_under_it(env):  # noqa: F811
    """Coffee, visual slide 2: «100 покупок в день × 300 ₽ × 30 рабочих дней = 900 000 ₽» — 100 and 30 kept their own
    words in the equation, were left «unused» and came back as cards under it (on Office the cards ran off the foot)."""
    from verstka.schemas.outline import NumberCallout

    nums = [NumberCallout(value="100", label="Покупок в день"), NumberCallout(value="300 ₽", label="Средний чек"), NumberCallout(value="30", label="Рабочих дней в расчетном месяце"), NumberCallout(value="900 000 ₽", label="Выручка за месяц")]
    o = OutlineSlide(id="f", kind=PatternKind.big_number, headline="Расчет выручки", content=SlideContent(formula="100 покупок в день × 300 × 30 рабочих дней = 900 000 ₽", numbers=nums))
    slide, warnings = _render(env, o, "formula", strategy="visual")
    text = _texts(slide)
    assert "100 — " not in text and "30 — " not in text, text
    caps = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.name.startswith("Term label")]
    assert len(caps) >= 3 and all(t[:1].isupper() for t in caps if t.strip()), caps
    # the author's fuller words under a figure the equation names shortly («30 рабочих дней»)
    assert any("в расчетном месяце" in t.replace("\u00a0", " ") for t in caps), caps


def test_the_figures_of_a_card_grid_share_one_size(env):  # noqa: F811
    items = [SlideItem(title=t, number=n) for n, t in (("100", "Покупок в день"), ("300 ₽", "Средний чек"), ("30", "Рабочих дней"), ("900 000 ₽", "Выручка в месяц"))]
    o = OutlineSlide(id="c", kind=PatternKind.cards, headline="Расчет", content=SlideContent(items=items))
    slide, _ = _render(env, o, "cards")
    figs = [sh for sh in slide.shapes if sh.name.startswith("Figure")]
    assert len(figs) == 4
    sizes = {max(r.font.size.pt for p in f.text_frame.paragraphs for r in p.runs if r.font.size) for f in figs}
    assert len(sizes) == 1, sizes


def test_the_photo_caption_stays_inside_its_shortened_frame(env):  # noqa: F811
    """Coffee chart brief, slide 3: the frame for the user's photo was cut to the content's foot after its caption
    had been centred at its full height — the description hung 120 pt below the frame."""
    from verstka.schemas.outline import PHOTO_PLACE_NAME

    hint = "Интерьер кофейни с витриной десертов. Бариста готовит кофе у стойки. Гости за столиками у окна. Вечерний свет."
    o = OutlineSlide(id="p", kind=PatternKind.bullets, headline="Наша кофейня", content=SlideContent(bullets=["Уютный зал на 30 мест", "Своя обжарка"], photo_slot="Место под фото кофейни", photo_hint=hint))
    slide, _ = _render(env, o, "bullets")
    frame = next(sh for sh in slide.shapes if sh.name == PHOTO_PLACE_NAME)
    caps = [sh for sh in slide.shapes if sh.name.startswith("Photo caption")]
    assert caps
    for c in caps:
        assert c.top >= frame.top and c.top + c.height <= frame.top + frame.height + 12700, (c.top, c.height, frame.top, frame.height)


def test_a_heading_is_measured_at_its_own_line_spacing():
    """VK Education: headings at 90 %, the deck's text at 110 % — a three-line 36 pt heading measured at the text's
    1.32 em got a 150 pt box for 117 pt of lines, and the content started 66 pt under it."""
    from lxml import etree
    from pptx import Presentation

    from verstka.analysis.xmlns import q
    from verstka.rendering.synth import _title_line_height

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    master = prs.slide_masters[0]._element
    lvl = master.find(q("p:txStyles") + "/" + q("p:titleStyle") + "/" + q("a:lvl1pPr"))
    for old in lvl.findall(q("a:lnSpc")):
        lvl.remove(old)
    ln = etree.Element(q("a:lnSpc"))
    etree.SubElement(ln, q("a:spcPct")).set("val", "90000")
    lvl.insert(0, ln)
    assert _title_line_height(s.shapes.title, 1.32) == 1.08


def test_a_pie_legend_never_breaks_a_name_inside_a_word(env):  # noqa: F811
    """Marketing Report: «Рекомендации» measured 226 pt in a 202 pt name column — the legend showed «Рекомендац / ии
    друзей». The stacked form's amount line is not padded for a right-aligned column it is not set in."""
    from verstka.rendering.deck import DeckBuilder
    from verstka.rendering.synth import render_synth
    from verstka.schemas.layout import LayoutSlide
    from verstka.schemas.outline import ChartSpec, DeckOutline, Series

    deck, manifest, ws = env
    cats = ["Рекомендации друзей", "Партнёрские программы", "Социальные сети", "Наружная реклама", "Продукты, упаковка и списания"]
    s = Series(id="src", name="Источники", categories=cats, values=[250000, 180000, 120000, 25000, 90000], unit="₽")
    o = OutlineSlide(id="p", kind=PatternKind.chart, headline="Откуда приходят гости", content=SlideContent(chart=ChartSpec(type="pie", series_ids=["src"]), bullets=["Половина гостей приходит по рекомендации"]))
    outline = DeckOutline(title="T", strategy="visual", slides=[o], series=[s])
    slide, _ = render_synth(DeckBuilder(deck), LayoutSlide(outline_id="p", mode="synth", composition="chart_text"), o, manifest, ws, outline)
    names = [sh for sh in slide.shapes if sh.name.startswith("Legend") and sh.has_text_frame]
    assert names
    for sh in names:
        lines = [p.text for p in sh.text_frame.paragraphs if p.text.strip()]
        joined = " ".join(lines).replace(" ", " ").split()
        name = next((c for c in cats if c.split()[0] in lines[0].replace(" ", " ")), None)
        if name is None:
            continue
        assert joined == name.split(), (lines, name)


def test_a_legend_name_is_set_in_the_lines_its_row_was_measured_for(env):  # noqa: F811
    """MyBrand: «Продукты, упаковка и списания» at 0.998 of its column — its row was measured for two lines (1.5 % of
    the line kept free) and the name set on one, a blank line under it. The widest unbreakable piece of a name counts
    the words a no-break space binds."""
    from verstka.rendering.compose import Composer, Kit, para_lines, widest_word_pt
    from verstka.rendering.deck import DeckBuilder
    from verstka.rendering.fonts import text_width_pt
    from verstka.schemas.common import EMU_PER_PT
    from verstka.schemas.outline import DeckOutline

    deck, manifest, ws = env
    b = DeckBuilder(deck)
    slide = b.add_blank_slide()
    kit = Kit(manifest, b.slide_w, b.slide_h, "FFFFFF")
    o = OutlineSlide(id="x", kind=PatternKind.chart, headline="x")
    comp = Composer(slide, kit, o, DeckOutline(title="T", slides=[o]), "structured", manifest)
    name = "Продукты, упаковка и списания"
    para = comp.P(name, 20.0, "000000")
    w_pt = text_width_pt(para.text, kit.font, 20.0, False) / 0.995
    width = int(w_pt * EMU_PER_PT)
    assert len(comp._set_lines(name, 20.0, "000000", width)) == para_lines(para, w_pt)
    assert widest_word_pt("до автоматизации", None, 20, False) > widest_word_pt("до автоматизации", None, 20, False)


def _chart_xml(slide):
    from lxml import etree

    gf = next(sh for sh in slide.shapes if sh.has_chart)
    return etree.fromstring(gf.chart.part.blob)


def test_value_ticks_print_the_decimals_of_their_step_and_labels_keep_the_floor(env):  # noqa: F811
    """A line of 41,2…63,9 млн ₽ with steps of 10 printed «30,0 · 40,0 … 70,0»; column labels of long words were set at
    7.5 pt under 12 pt values — below the chart's own floor (2 % of the slide's height)."""
    from verstka.schemas.common import EMU_PER_PT
    from verstka.schemas.outline import ChartSpec, DeckOutline, Series

    deck, manifest, ws = env
    from verstka.rendering.deck import DeckBuilder
    from verstka.rendering.synth import render_synth
    from verstka.schemas.layout import LayoutSlide

    C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь"]
    o = OutlineSlide(id="l", kind=PatternKind.chart, headline="Выручка", content=SlideContent(chart=ChartSpec(type="line", series_ids=["r"])))
    outline = DeckOutline(title="T", slides=[o], series=[Series(id="r", name="Выручка", categories=months, values=[41.2, 45.5, 50.1, 55.0, 58.7, 63.9], unit="млн ₽")])
    slide, _ = render_synth(DeckBuilder(deck), LayoutSlide(outline_id="l", mode="synth", composition="chart"), o, manifest, ws, outline)
    assert _chart_xml(slide).find(".//" + C + "valAx") is not None
    from verstka.rendering.charts import tick_decimals

    assert tick_decimals(10.0, 1) == 0 and tick_decimals(2.5, 0) == 1 and tick_decimals(0.25, 1) == 2 and tick_decimals(None, 1) == 1
    long = ["Автоматизированный", "Полуавтоматический", "Ручной контроль", "Дистанционный", "Комбинированный", "Экспериментальный", "Традиционный"]
    o2 = OutlineSlide(id="c", kind=PatternKind.chart, headline="Способы", content=SlideContent(chart=ChartSpec(type="column", series_ids=["s"])))
    outline2 = DeckOutline(title="T", slides=[o2], series=[Series(id="s", name="Часы", categories=long, values=[2, 3, 6, 4, 3, 5, 7], unit="ч")])
    b = DeckBuilder(deck)
    slide2, _ = render_synth(b, LayoutSlide(outline_id="c", mode="synth", composition="chart"), o2, manifest, ws, outline2)
    floor = max(8.0, 0.02 * b.slide_h / EMU_PER_PT)
    ca = _chart_xml(slide2).find(".//" + C + "catAx")
    szs = [int(r.get("sz")) / 100 for r in ca.iter(A + "defRPr") if r.get("sz")]
    assert szs and min(szs) >= floor - 0.3, (szs, floor)


def test_small_numerals_take_the_accents_text_tone():
    from verstka.rendering.compose import Colors, Composer

    c = Colors(ground="EBF3F9", text="111111", muted="666666", accent="0077FF", accent_text="005BC4", divider="DDDDDD", heading="111111", figure="0077FF")
    pick = Composer.accent_for
    assert pick(None, c, 16.0, False) == "005BC4" and pick(None, c, 13.0, True) == "005BC4"
    assert pick(None, c, 18.0, False) == "0077FF" and pick(None, c, 14.0, True) == "0077FF"


def test_the_authors_lines_are_set_denser_before_any_goes_to_the_notes(env):  # noqa: F811
    """Marketing, visual slide 8: a six-month timeline and five budget lines — three lines went to the speaker notes,
    where two columns at the template's small size held them all."""
    items = [SlideItem(title=f"{k}-й месяц", text=t) for k, t in enumerate(["Учет показателей и обновление меню", "Запуск комбо и обучение сотрудников", "Запуск программы лояльности и партнерств с офисами", "Продвижение дневных предложений и настройка закупок", "Корректировка предложений по результатам продаж", "Оценка результатов и закрепление удачных решений"], 1)]
    lines = ["Витрина для десертов — 70 000 рублей", "Настройка программы лояльности и учета — 35 000 рублей", "Обновление меню, фотографии и оформление — 25 000 рублей", "Обучение сотрудников — 20 000 рублей", "Резерв — 30 000 рублей"]
    o = OutlineSlide(id="p", kind=PatternKind.timeline, headline="План внедрения и разовые вложения", verbatim=True, content=SlideContent(items=items, bullets=lines))
    slide, warnings = _render(env, o, "process", strategy="visual")
    text = _texts(slide).replace(" ", " ")
    shown = [ln for ln in lines if ln.split(" — ")[0] in text]
    dropped = [w for w in warnings if "left to the speaker notes" in w]
    assert len(shown) == len(lines) or dropped == [], (shown, warnings)


def test_a_formulas_own_lines_caption_its_terms(env):  # noqa: F811
    """Coffee, structured slide 2: the equation 100 × 300 ₽ × 30 = 900 000 ₽ was followed by the author's five lines
    repeating its figures. The lines that state a term's figure are its captions; the one the equation does not show
    («3 000 покупок в месяц») and the shop's paragraph stay under it."""
    lines = ["100 покупок в день", "Средний чек — 300 рублей", "30 рабочих дней в расчетном месяце", "3 000 покупок в месяц", "Месячная выручка — 900 000 рублей"]
    lead = "Кофейня площадью 45 м² рядом с офисами и жилыми домами. Внутри 18 посадочных мест."
    o = OutlineSlide(id="f", kind=PatternKind.bullets, headline="Как работает кофейня сейчас", verbatim=True, content=SlideContent(formula="100 покупок в день × 300 × 30 рабочих дней = 900 000 ₽", bullets=lines, paragraphs=[lead]))
    slide, _ = _render(env, o, "formula")
    caps = [sh.text_frame.text.replace(" ", " ") for sh in slide.shapes if sh.has_text_frame and sh.name.startswith("Term label")]
    assert any("Средний чек" in t for t in caps) and any("Месячная выручка" in t for t in caps) and any("в расчетном месяце" in t for t in caps), caps
    text = _texts(slide).replace(" ", " ")
    assert "Средний чек — 300" not in text and "Месячная выручка — 900" not in text  # not repeated as lines
    assert "3 000 покупок в месяц" in text and "Кофейня площадью 45 м²" in text
