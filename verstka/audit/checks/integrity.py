"""Integrity checks: file opens, empty deck, placeholders, empty/picture slides, lost slides and content, chart labels, duplicates."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from verstka.analysis.shapes import looks_like_placeholder
from verstka.audit.checks.common import content_elements, fix, text_elements, title_element
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import IRSlide
from verstka.schemas.outline import OutlineSlide

FILE_OPENS = CheckSpec(id="file_opens", title="Файл не открывается", severity="error", category="integrity", description="PPTX не открывается python-pptx или не рендерится LibreOffice.")
EMPTY_DECK = CheckSpec(id="empty_deck", title="В колоде нет ни одного слайда", severity="error", category="integrity", description="Файл открывается, но не содержит слайдов.")
PLACEHOLDER_TEXT = CheckSpec(id="placeholder_text", title="Остался текст-заглушка", severity="error", category="integrity", description="На слайде остался lorem ipsum, XXX, TODO, «вставьте текст», «Заголовок», «Имя Фамилия» и подобные заглушки шаблона.")
EMPTY_SLIDE = CheckSpec(id="empty_slide", title="Пустой слайд или слайд с одним заголовком", severity="error", category="integrity", description="На слайде нет контента кроме заголовка (кроме титульного, разделителей и финального).")
SLIDE_IS_PICTURE = CheckSpec(id="slide_is_picture", title="Слайд оказался картинкой, а не редактируемыми объектами", severity="error", category="integrity", description="Одна картинка занимает ≥ 90% слайда и на слайде нет текста.")
CHART_MISSING_LABELS = CheckSpec(id="chart_missing_labels", title="У диаграммы нет подписей осей, единиц или легенды", severity="warn", category="integrity", description="Нативная диаграмма без подписей данных и без оси значений, либо многосерийная без легенды, либо без единиц измерения.")
DUPLICATE_SLIDES = CheckSpec(id="duplicate_slides", title="Два слайда дублируют друг друга", severity="warn", category="integrity", description="Текст двух слайдов совпадает более чем на 90%.")
CONTENT_MISSING = CheckSpec(id="content_missing", title="Часть запланированного контента пропала со слайда", severity="error", category="integrity", description="Заголовок, пункты списков, названия карточек, числа с подписями и заголовки колонок из плана ищутся в тексте слайда (включая ячейки таблиц) без учёта пробелов и регистра по первым 18 символам; ошибка, если нет трети и более строк, иначе предупреждение.")

SLIDE_MISSING = CheckSpec(id="slide_missing", title="Слайда из плана нет в колоде", severity="error", category="integrity", description="Слайд плана не нашёлся в готовой колоде ни по метке в заметках докладчика, ни по числу слайдов: рендер не смог собрать его ни одним способом, и колода стала короче плана.")

CONTENT_KEY_CHARS = 18
_WS_RE = re.compile(r"[\s\u00a0\u202f\u2009\u2007\u2060]+")


@check(FILE_OPENS)
def file_opens(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    if not ctx.opens_ok:
        out.append(ctx.new_issue(FILE_OPENS, 0, "файл не открывается python-pptx"))
    if ctx.render_ok is False:
        out.append(ctx.new_issue(FILE_OPENS, 0, "LibreOffice не смог отрендерить файл", severity="warn"))
    return out


@check(EMPTY_DECK)
def empty_deck(ctx: AuditContext) -> list[Issue]:
    if ctx.opens_ok and not ctx.ir.slides:
        return [ctx.new_issue(EMPTY_DECK, 0, "в колоде нет ни одного слайда")]
    return []


@check(PLACEHOLDER_TEXT)
def placeholder_text(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:  # table cells included: sample tables keep their placeholder text too
            if not e.has_text:
                continue
            t = e.text.strip()
            if looks_like_placeholder(t):
                out.append(ctx.new_issue(PLACEHOLDER_TEXT, s.index, f"заглушка «{t[:40]}»", bboxes=[e.bbox_frac], element_ids=[e.id], autofix=fix("drop_element", "удалить заглушку", element_id=e.id)))
    return out


def _outline_slide(ctx: AuditContext, s: IRSlide) -> Optional[OutlineSlide]:
    if ctx.outline is None or not s.outline_id:
        return None
    return next((o for o in ctx.outline.slides if o.id == s.outline_id), None)


@check(EMPTY_SLIDE)
def empty_slide(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    n = len(ctx.ir.slides)
    for s in ctx.ir.slides:
        if s.index in (1, n):
            continue
        els = content_elements(s, ctx.ir, ctx.manifest)
        title = title_element(s)
        others = [e for e in els if e is not title]
        text_others = [e for e in others if e.has_text or e.type in ("chart", "table") or e.formula]
        osl = _outline_slide(ctx, s)
        # a picture is content only when the plan asked for one; otherwise it is template decoration next to a lone title
        picture_planned = osl is None or bool(osl.content.image_hint) or osl.kind.value == "image_text"
        has_picture = picture_planned and any(e.type == "picture" and e.bbox_frac.area > 0.1 for e in others)
        if not els or (title is not None and not text_others and not has_picture):
            kind = osl.kind.value if osl is not None else "unknown"
            if kind in ("section", "thanks", "title", "quote"):
                continue
            out.append(ctx.new_issue(EMPTY_SLIDE, s.index, "на слайде только заголовок", autofix=fix("rematch", "перевыбрать макет", outline_id=s.outline_id)))
    return out


_DASHES = str.maketrans({c: "-" for c in "\u2212\u2010\u2011\u2012\u2013\u2014"})
_RUB_RE = re.compile(r"\s*(?:рубл(?:ей|я|ь)|руб\.?)(?![а-яё])", re.I)


def _norm_text(t: str) -> str:
    # (a sum is the same written «300 рублей» in the plan and «300 ₽» on the slide: the typesetting's own choice)
    return _WS_RE.sub("", _RUB_RE.sub("₽", t or "")).lower().replace("ё", "е").translate(_DASHES)


def wanted_strings(osl: OutlineSlide, outline=None) -> list[str]:
    """Texts the plan puts on the slide that must survive rendering (order preserved, duplicates dropped). A line that
    only repeats a figure of the slide's chart is the chart's own (the composer drops it)."""
    from verstka.rendering.compose import bare_chart_figure, chart_values

    c = osl.content
    raw: list[str] = [osl.headline]
    values = chart_values(c, outline) if c.bullets else set()
    raw.extend(b for b in c.bullets if not bare_chart_figure(b, values))
    raw.extend(it.title for it in c.items)
    for n in c.numbers:
        raw.extend((n.value, n.label))
    raw.extend(col.title for col in c.columns)
    if c.table:
        raw.extend(c.table.columns)
    out: list[str] = []
    for t in raw:
        t = (t or "").strip()
        if t and _norm_text(t) and t not in out:
            out.append(t)
    return out


def _present(wanted: str, have: str) -> bool:
    """The planned line is on the slide: verbatim (by its first characters); as a cover's title and subtitle («Итоги
    пилота: план на 2027 год» set as «Итоги пилота» over «План на 2027 год»); or as a callout — a line that carries
    one figure («Средний чек — 300 рублей») set as its figure large and its words under it («300 ₽» over «Средний
    чек»), as the visual variant presents a chart's side lines."""
    if _norm_text(wanted)[:CONTENT_KEY_CHARS] in have:
        return True
    from verstka.matching.scorer import split_display_title
    from verstka.rendering.compose import kpi_callout

    head, tail = split_display_title(wanted)
    if tail and _norm_text(head)[:CONTENT_KEY_CHARS] in have and _norm_text(tail)[:CONTENT_KEY_CHARS] in have:
        return True  # a cover heading of two phrases set as a title and its subtitle

    got = kpi_callout(wanted)
    if got is None:
        return False
    value, label = got
    return _norm_text(label)[:CONTENT_KEY_CHARS] in have and _norm_text(value) in have


def slide_text_norm(s: IRSlide) -> str:
    parts = [e.text for e in s.elements if e.type == "text" and e.has_text]
    for e in s.elements:
        if e.type == "table" and e.table:
            parts.extend(cell for row in e.table.rows for cell in row)
    return "|".join(_norm_text(p) for p in parts)


@check(CONTENT_MISSING)
def content_missing(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        wanted = wanted_strings(osl, ctx.outline)
        if not wanted:
            continue
        have = slide_text_norm(s)
        missing = [w for w in wanted if not _present(w, have)]
        if not missing:
            continue
        # a line said aloud (the slide had no room: the composer put it into the speaker notes) is not lost — a
        # warning, as a conclusion in the notes is (content_in_notes); lost is what is neither on the slide nor there
        notes = _alnum(s.notes)
        aloud = [w for w in missing if (key := _alnum(w)[:NOTE_KEY_CHARS]) and key in notes]
        lost = [w for w in missing if w not in aloud]
        severity = "error" if lost and len(lost) * 3 >= len(wanted) else "warn"
        word = "текста" if len(wanted) % 10 == 1 and len(wanted) % 100 != 11 else "текстов"
        if lost:
            shown = ", ".join(f"«{m[:40]}»" for m in lost[:3]) + ("…" if len(lost) > 3 else "")
            msg = f"{len(lost)} из {len(wanted)} {word} плана нет на слайде: {shown}" + (f" (ещё {len(aloud)} — в заметках докладчика)" if aloud else "")
        else:
            shown = ", ".join(f"«{m[:40]}»" for m in aloud[:3]) + ("…" if len(aloud) > 3 else "")
            msg = f"{len(aloud)} из {len(wanted)} {word} плана — только в заметках докладчика, на слайде не нашлось места: {shown}"
        out.append(ctx.new_issue(CONTENT_MISSING, s.index, msg, severity=severity, details={"missing": missing, "wanted": len(wanted), "in_notes": aloud}, autofix=fix("rematch", "перевыбрать макет, чтобы весь контент поместился", outline_id=s.outline_id)))
    return out


AUTHOR_ITEM_MISSING = CheckSpec(id="author_item_missing", title="Пункт списка автора не попал на слайды", severity="warn", category="integrity", description="Для слайдов, собранных из текста автора как написан: пункты списков из раздела «Слайд N» брифа ищутся на слайдах этого раздела (и его продолжениях) — по началу строки или по её числу и большей части слов (цифра крупно и подпись под ней тоже считается). Пункт, которого нет ни на одном из них, — потеря текста автора.")

_ITEM_MARK_RE = re.compile(r"^\s*(?:[—–\-•*·]|\d{1,2}[.)])\s+(?P<t>\S.*)$")


def _author_items(brief: str, ref: int) -> list[str]:
    """The list items of the brief's section «Слайд N» (one per marked line, its marker and trailing «;» off)."""
    m = re.search(rf"(?:^|\n)\s*(?:слайд|slide)\s*{ref}\b[^\n]*\n(.*?)(?=\n\s*(?:слайд|slide)\s*\d+\b|\Z)", brief, re.I | re.S)
    if not m:
        return []
    out = []
    for ln in m.group(1).splitlines():
        g = _ITEM_MARK_RE.match(ln)
        if g:
            t = g.group("t").strip().rstrip(";.,").strip()
            if 2 <= len(t) <= 160 and len(t.split()) <= 20:
                out.append(t)
    return out


def _item_present(item: str, have: str) -> bool:
    """An author's list item is on the slide: by its first characters, or by its figures and most of its words (a
    figure set large over its label, a term of a formula)."""
    if _norm_text(item)[:CONTENT_KEY_CHARS] in have:
        return True
    digits = re.findall(r"\d+", re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}\b)", "", item))
    flat = have.replace("|", "")
    if any(d not in flat for d in digits):
        return False
    words = [w for w in re.findall(r"[а-яёa-z]{3,}", _RUB_RE.sub("₽", item).lower().replace("ё", "е"))]
    return bool(words or digits) and sum(1 for w in words if w[:6] in flat) >= 0.6 * len(words)


@check(AUTHOR_ITEM_MISSING)
def author_item_missing(ctx: AuditContext) -> list[Issue]:
    """B4 of the swarm review: content_missing compares a slide with its plan — a list item the plan itself lost (eight
    steps planned as six) is caught here, against the brief."""
    out: list[Issue] = []
    if not ctx.brief_text or ctx.outline is None:
        return out
    groups: dict[int, list] = {}
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is not None and osl.verbatim and getattr(osl, "spec_ref", None):
            groups.setdefault(osl.spec_ref, []).append((s, osl))
    for ref, members in groups.items():
        items = _author_items(ctx.brief_text, ref)
        if not items:
            continue
        # (with the data of the slides' charts: a list of sums drawn as a pie is on the slide as its slices; a gap of a
        # line — a point without a value — says no figure)
        charts = []
        for s, _ in members:
            for e in s.elements:
                if e.type == "chart" and e.chart:
                    charts += list(e.chart.categories) + [f"{v:,.2f}".replace(",", "").rstrip("0").rstrip(".") for sr in e.chart.series for v in sr.values if v is not None]
        have = "|".join([slide_text_norm(s) for s, _ in members] + [_norm_text(t) for t in charts])
        missing = [t for t in items if not _item_present(t, have)]
        if not missing:
            continue
        s0, osl0 = members[0]
        shown = ", ".join(f"«{m[:40]}»" for m in missing[:3]) + ("…" if len(missing) > 3 else "")
        out.append(ctx.new_issue(AUTHOR_ITEM_MISSING, s0.index, f"{len(missing)} из {len(items)} пунктов списка автора нет на слайде: {shown}", details={"missing": missing, "items": len(items), "spec_ref": ref}, autofix=fix("rematch", "перевыбрать макет, чтобы весь список поместился", outline_id=s0.outline_id)))
    return out


@check(SLIDE_MISSING)
def slide_missing(ctx: AuditContext) -> list[Issue]:
    """A planned slide the deck lost: its marker is on no slide and the deck is shorter than the plan (a slide whose
    marker was not written is still there — the count tells)."""
    if ctx.outline is None or not ctx.ir.slides:
        return []
    marked = {s.outline_id for s in ctx.ir.slides if s.outline_id}
    lost = [(i, o) for i, o in enumerate(ctx.outline.slides, 1) if o.id not in marked]
    short = len(ctx.outline.slides) - len(ctx.ir.slides)
    out: list[Issue] = []
    for i, o in lost[: max(short, 0)]:
        issue = ctx.new_issue(SLIDE_MISSING, 0, f"слайда {i} плана «{(o.headline or '').strip()[:60]}» нет в колоде: его не удалось собрать", details={"plan_slide": i, "outline_id": o.id})
        issue.outline_id = o.id
        out.append(issue)
    return out


@check(SLIDE_IS_PICTURE)
def slide_is_picture(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        pics = [e for e in s.elements if e.type == "picture" and e.bbox_frac.area >= 0.9]
        if pics and not text_elements(s):
            out.append(ctx.new_issue(SLIDE_IS_PICTURE, s.index, "слайд состоит из одной картинки", bboxes=[pics[0].bbox_frac], element_ids=[pics[0].id]))
    return out


@check(CHART_MISSING_LABELS)
def chart_missing_labels(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type != "chart" or not e.chart:
                continue
            c = e.chart
            problems = []
            if not c.has_data_labels and not c.has_value_axis:
                problems.append("нет ни подписей данных, ни оси значений")
            if len(c.series) > 1 and not (c.has_legend or c.series_labels):  # series named on their labels need no legend
                problems.append("несколько серий без легенды")
            fmt = c.number_format or ""
            has_unit = any(ch in fmt for ch in "%₽$") or '"' in fmt
            if not has_unit and c.has_data_labels:
                problems.append("единицы измерения не указаны в подписях")
            if problems:
                out.append(ctx.new_issue(CHART_MISSING_LABELS, s.index, "; ".join(problems), bboxes=[e.bbox_frac], element_ids=[e.id], severity="info" if problems == ["единицы измерения не указаны в подписях"] else "warn"))
    return out


@check(DUPLICATE_SLIDES)
def duplicate_slides(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    texts = [(s.index, " ".join(e.text for e in s.elements if e.has_text).strip().lower()) for s in ctx.ir.slides]
    for i, (ia, ta) in enumerate(texts):
        if len(ta) < 40:
            continue
        for ib, tb in texts[i + 1 :]:
            if len(tb) < 40:
                continue
            if SequenceMatcher(None, ta, tb).ratio() > 0.9:
                out.append(ctx.new_issue(DUPLICATE_SLIDES, ib, f"слайд {ib} повторяет слайд {ia}", details={"other": ia}))
    return out


CONTENT_IN_NOTES = CheckSpec(
    id="content_in_notes",
    title="Строка плана ушла со слайда в заметки докладчика",
    severity="warn",
    category="integrity",
    description=(
        "Вывод слайда («Вывод: …»), его сноска (оговорка «мелким текстом», например «Все данные условные» на первом "
        "слайде) или цель под заголовком обложки есть в плане, но на слайде их нет: рендер не нашёл им места и они "
        "только в заметках докладчика (или пропали совсем). Строка ищется в тексте слайда без учёта пробелов, регистра "
        "и знаков препинания по первым 24 символам, а также как крупное число с подписью."
    ),
)

PROMISED_COUNT = CheckSpec(
    id="promised_count_mismatch",
    title="Заголовок обещает больше или меньше пунктов, чем на слайде",
    severity="error",
    category="integrity",
    description=(
        "Заголовок или подзаголовок называет число пунктов («Программа из 4 модулей», «Три шага к запуску», «5 причин»), "
        "а в списке слайда — пунктах, шагах, карточках, строках таблицы — их другое число: пункт потерян или лишний."
    ),
)

TIMELINE_ORDER = CheckSpec(
    id="timeline_order",
    title="Даты на таймлайне идут не по порядку",
    severity="warn",
    category="integrity",
    description=(
        "Пункты слайда (этапы, карточки или строки списка), которые начинаются с даты — «22 июня 1941», «Июль 1937», "
        "«Апрель — июнь 1940», «1931–1937», «1998 год», «Q3 2025», — стоят в плане слайда не в хронологическом порядке: "
        "ни по возрастанию, ни по убыванию. Проверяются слайды, где дат не меньше трёх и с даты начинается не меньше 80% "
        "пунктов; диапазон сравнивается по началу, дата без месяца или дня — только по тому, что в ней есть."
    ),
)

NOTE_KEY_CHARS = 24
_ALNUM_RE = re.compile(r"[\W_]+")


def _alnum(t: str) -> str:
    return _ALNUM_RE.sub("", (t or "").lower().replace("ё", "е"))


def planned_lines(osl: OutlineSlide) -> list[tuple[str, str]]:
    """(kind, text) of the plan's lines that stand apart from the slide's body and may be pushed off it by a
    renderer with no room: the conclusion (not on covers, dividers and the closing slide), the footnote, the cover's
    goal line under its subtitle."""
    from verstka.matching.scorer import cover_goal

    out: list[tuple[str, str]] = []
    kind = osl.kind.value if hasattr(osl.kind, "value") else str(osl.kind)
    take = " ".join((osl.takeaway or "").split())
    if take and kind not in ("title", "section", "thanks"):
        out.append(("takeaway", take))
    note = " ".join((osl.footnote or "").split())
    if note:
        out.append(("footnote", note))
    goal = cover_goal(osl)
    if goal:
        out.append(("goal", goal))
    return out


def _line_on_slide(text: str, have: str, have_alnum: str) -> bool:
    """The line is on the slide: verbatim (its first letters and digits), as a cover heading's two phrases, or as a
    callout — its figure large and at least half of the words of its label beside it («Прогноз: 254 795 ₽ в месяц» set
    as «254 795 ₽» over «Прогноз» under a chart of the monthly profit)."""
    key = _alnum(text)[:NOTE_KEY_CHARS]
    if (bool(key) and key in have_alnum) or _present(text, have):
        return True
    from verstka.rendering.compose import _aside_figure, kpi_callout, label_without_figure

    forms = []
    got = kpi_callout(text)
    if got is not None:
        forms.append(got)
    try:
        # the visual variant's own split of a conclusion beside its chart: the key figure large, the rest of the
        # sentence under it («900 000 ₽» over «За 30 дней выручка» — a line of two figures kpi_callout declines)
        fig = _aside_figure(text)
        if fig:
            forms.append((fig, label_without_figure(text, fig)))
    except Exception:  # noqa: BLE001 - the renderer's helpers are advice here
        pass
    for value, label in forms:
        if not _alnum(value) or _alnum(value) not in have_alnum:
            continue
        words = [w for w in re.findall(r"\w{3,}", (label or "").lower().replace("ё", "е"))]
        if words and sum(1 for w in words if w in have_alnum) >= 0.5 * len(words):
            return True
    return False


def _said_shorter(text: str, have: str, have_alnum: str, notes_alnum: str) -> bool:
    """A conclusion of two sentences or more the renderer said shorter: its first sentence on the slide, the rest in
    the speaker notes (`compose._reserve_notes` — a chart of a data file keeps the height its plot needs). Nothing of
    it is lost: no issue. The rest missing from the notes is."""
    try:
        from verstka.rendering.compose import _first_sentence
    except Exception:  # noqa: BLE001
        return False
    first = _first_sentence(text)
    if not first or not _line_on_slide(first, have, have_alnum):
        return False
    rest = " ".join(text.split())[len(" ".join(first.split())):].strip(" .")
    key = _alnum(rest)[:NOTE_KEY_CHARS]
    return not key or key in notes_alnum


_KIND_RU = {"takeaway": "Вывод", "footnote": "Сноска", "goal": "Цель обложки"}


@check(CONTENT_IN_NOTES)
def content_in_notes(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        lines = planned_lines(osl)
        if not lines:
            continue
        have = slide_text_norm(s)
        have_alnum = _alnum(have)
        notes = _alnum(s.notes)
        for kind, text in lines:
            if _line_on_slide(text, have, have_alnum):
                continue
            if kind == "takeaway" and _said_shorter(text, have, have_alnum, notes):
                continue
            key = _alnum(text)[:NOTE_KEY_CHARS]
            said = bool(key) and key in notes
            where = "есть только в заметках докладчика: на слайде не нашлось места" if said else "нет ни на слайде, ни в заметках"
            # another sample of the template (or the slide composed) may hold it: the autofix ladder tries them, the
            # change kept only when the slide gets better (Классика's cover lost its goal and its footnote to the notes;
            # its other cover holds both)
            # a data slide's conclusion under its chart («Остальные 230 клиентов — 62%») is what the chart says: off the
            # slide, it is an error, not a warning
            sev = {"severity": "error"} if (osl.data is not None and kind == "takeaway") else {}
            out.append(ctx.new_issue(CONTENT_IN_NOTES, s.index, f"{_KIND_RU[kind]} «{text[:50]}{'…' if len(text) > 50 else ''}» {where}", details={"line": kind, "text": text, "in_notes": said}, autofix=fix("rematch", "перевыбрать макет, чтобы строка встала на слайд", outline_id=s.outline_id), **sev))
    return out


_COUNT_WORDS = {
    "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3, "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5,
    "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
}
# what a slide lists (never time: «за 4 месяца», «3 года»)
_ITEM_NOUNS = (r"модул|шаг|этап|причин|принцип|блок|ступен|пункт|урок|задач|вопрос|фактор|преимуществ|риск|правил|"
               r"компонент|раздел|функци|возможност|сценари|инструмент|метрик|критери|вывод|иде[йияю]|совет|тренд|"
               r"направлени|продукт|решени|кейс|трек|роль|ролей|отличи|ошибк|ошибок|групп")
_PROMISE_RE = re.compile(
    r"(?<![\w,.])(\d{1,2}|" + "|".join(_COUNT_WORDS) + r")\s+(?:[а-яё-]+(?:ых|их|ые|ие|ми)\s+)?(?:" + _ITEM_NOUNS + r")[а-яё]*",
    re.I,
)


def promised_count(text: str) -> Optional[int]:
    """The number of items a headline promises («Программа из 4 модулей» — 4), or None."""
    m = _PROMISE_RE.search(text or "")
    if not m:
        return None
    w = m.group(1).lower()
    n = int(w) if w.isdigit() else _COUNT_WORDS.get(w)
    return n if n is not None and 2 <= n <= 12 else None


@check(PROMISED_COUNT)
def promised_count_mismatch(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None or re.search(r"\(продолжение\)", osl.headline or ""):
            continue
        kind = osl.kind.value if hasattr(osl.kind, "value") else str(osl.kind)
        if kind in ("title", "section", "thanks", "agenda"):
            continue
        n = promised_count(osl.headline) or promised_count(osl.subtitle or "")
        if n is None:
            continue
        c = osl.content
        counts = [len(x) for x in (c.items, c.bullets, c.numbers, c.columns, c.table.rows if c.table is not None else []) if x]
        if not counts or n in counts:
            continue
        have = max(counts)
        out.append(ctx.new_issue(
            PROMISED_COUNT, s.index, f"Заголовок обещает {n}, а на слайде {have}: «{(osl.headline or '')[:60]}»",
            suggestion="Верните потерянный пункт на слайд или поправьте число в заголовке.", details={"promised": n, "shown": have},
        ))
    return out


_MONTHS = (
    ("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("ма", 5), ("июн", 6), ("июл", 7), ("август", 8),
    ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12),
    ("jan", 1), ("feb", 2), ("mar", 3), ("apr", 4), ("may", 5), ("jun", 6), ("jul", 7), ("aug", 8), ("sep", 9),
    ("oct", 10), ("nov", 11), ("dec", 12),
)
_MONTH_WORD = r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)\.?"
_DASH = r"\s*[—–\-]\s*"
_YEAR = r"(1\d{3}|20\d{2}|21\d{2})"
_DATE_FORMS = (
    # 22 июня 1941 / 1–17 сентября 1939
    ("dmy", re.compile(rf"^(\d{{1,2}})(?:{_DASH}\d{{1,2}})?\s+({_MONTH_WORD})(?:{_DASH}(?:\d{{1,2}}\s+)?{_MONTH_WORD})?\s+{_YEAR}(?!\d)")),
    # Июль 1937 / Апрель — июнь 1940
    ("my", re.compile(rf"^({_MONTH_WORD})(?:{_DASH}(?:\d{{1,2}}\s+)?{_MONTH_WORD})?\s+{_YEAR}(?!\d)")),
    # Q3 2025 / 3 квартал 2025 / III кв. 2025
    ("qy", re.compile(rf"^(?:q([1-4])|([1-4]|iv|i{{1,3}})\s*(?:-?й\s*)?кв\w*\.?)\s+{_YEAR}(?!\d)")),
    # 1998 / 1998 год / 1931–1937 / 1990-е
    ("y", re.compile(rf"^{_YEAR}(?:{_DASH}\d{{2,4}})?(?!\d)(?!\s*(?:%|₽|\$|€|руб|тыс|млн|млрд|чел|шт|км|кг|м²|раз))")),
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


def _month_of(word: str) -> Optional[int]:
    w = word.lower().rstrip(".")
    if re.fullmatch(r"ма[йяе]", w):
        return 5
    for stem, m in _MONTHS:
        if stem != "ма" and w.startswith(stem):
            return m
    return None


def date_key(text: str) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    """(year, month, day) of the date a line starts with («22 июня 1941 — …», «Апрель — июнь 1940», «1931–1937»,
    «Q3 2025»; a range by its start), None when it does not start with a date."""
    t = re.sub(r"[\s    ]+", " ", (text or "")).replace("⁠", "").strip().lower()
    for form, rx in _DATE_FORMS:
        m = rx.match(t)
        if not m:
            continue
        if form == "dmy":
            return int(m.group(3)), _month_of(m.group(2)), int(m.group(1))
        if form == "my":
            return int(m.group(2)), _month_of(m.group(1)), None
        if form == "qy":
            q = int(m.group(1)) if m.group(1) else (int(m.group(2)) if m.group(2).isdigit() else _ROMAN[m.group(2)])
            return int(m.group(3)), 3 * (q - 1) + 1, None
        return int(m.group(1)), None, None
    return None


def _cmp_dates(a: tuple, b: tuple) -> int:
    """-1 / 0 / 1 at the precision both dates have (a year alone is equal to any date of that year)."""
    for x, y in zip(a, b):
        if x is None or y is None:
            return 0
        if x != y:
            return -1 if x < y else 1
    return 0


def _dated_rows(osl: OutlineSlide) -> list[list[tuple[str, tuple]]]:
    """The slide's item lists whose entries start with dates: (text, date) per entry, for each list of at least three
    entries where at least 80 % start with a date."""
    c = osl.content
    groups = [[it.title for it in c.items], [col.title for col in c.columns], list(c.bullets)]
    out = []
    for g in groups:
        g = [t for t in g if (t or "").strip()]
        if len(g) < 3:
            continue
        keys = [(t, date_key(t)) for t in g]
        dated = [(t, k) for t, k in keys if k is not None]
        if len(dated) >= 3 and len(dated) >= 0.8 * len(g):
            out.append(dated)
    return out


@check(TIMELINE_ORDER)
def timeline_order(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        for rows in _dated_rows(osl):
            steps = [_cmp_dates(rows[i][1], rows[i + 1][1]) for i in range(len(rows) - 1)]
            if all(x <= 0 for x in steps) or all(x >= 0 for x in steps):
                continue
            # the list's own direction is where most of its steps go; the first step against it is the one shown
            way = 1 if sum(steps) > 0 else (-1 if sum(steps) < 0 else next(x for x in steps if x))
            i = next(i for i, x in enumerate(steps) if x == -way)
            a, b = rows[i][0], rows[i + 1][0]
            shown = " → ".join(t[:22] for t, _ in rows[:6]) + (" → …" if len(rows) > 6 else "")
            out.append(ctx.new_issue(TIMELINE_ORDER, s.index, f"даты идут не по порядку: {shown} («{b[:30]}» после «{a[:30]}»)", details={"order": [t for t, _ in rows]}))
            break
    return out


PHOTO_PLACE_EMPTY = CheckSpec(
    id="photo_place_empty",
    title="Серая заглушка картинки в готовой колоде",
    severity="warn",
    category="integrity",
    description="На слайде осталось свободное место под картинку («Место для фото»). Место, которое автор просил оставить под "
    "своё фото, — не ошибка, если оно оформлено как место для фото (оттенок цвета шаблона, пунктирная рамка, подпись): "
    "это сведение. Серая заглушка без оформления — предупреждение, как и место под картинку, которую должна была "
    "нарисовать модель, а её нет (генерация выключена, не успела, не ответила): такому слайду нужен макет без места "
    "под картинку или уместный рисунок шаблона.",
)


def _grey(hex_: Optional[str]) -> bool:
    if not hex_ or len(hex_) != 6:
        return False
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    return mx == 0 or (mx - mn) / mx < 0.12


@check(PHOTO_PLACE_EMPTY)
def photo_place_empty(ctx: AuditContext) -> list[Issue]:
    from verstka.images.places import is_own
    from verstka.schemas.outline import PHOTO_PLACE_NAME

    out: list[Issue] = []
    for s in ctx.ir.slides:
        places = [e for e in s.elements if e.name == PHOTO_PLACE_NAME and e.type in ("shape", "text")]
        if not places:
            continue
        osl = _outline_slide(ctx, s)
        c = osl.content if osl is not None else None
        own = is_own((c.photo_slot or "") if c is not None else "", bool(getattr(c, "photo_own", False))) if c is not None else False
        for e in places:
            designed = bool(e.line_hex) and not _grey(e.fill_hex) or (bool(e.line_hex) and _grey(e.fill_hex) and any(x.name.startswith("Photo caption icon") for x in s.elements))
            if own and designed:
                out.append(ctx.new_issue(PHOTO_PLACE_EMPTY, s.index, "место под фото автора оставлено свободным, как он просил", severity="info", bboxes=[e.bbox_frac], element_ids=[e.id]))
            elif own:
                out.append(ctx.new_issue(PHOTO_PLACE_EMPTY, s.index, "место под фото автора — серая заглушка без оформления", bboxes=[e.bbox_frac], element_ids=[e.id],
                                         suggestion="Оформить место как место для фото: оттенок цвета шаблона, рамка, подпись."))
            else:
                out.append(ctx.new_issue(PHOTO_PLACE_EMPTY, s.index, "место под картинку осталось пустым: картинки нет", bboxes=[e.bbox_frac], element_ids=[e.id],
                                         suggestion="Макет без места под картинку или рисунок шаблона, который подходит к слайду."))
    return out
