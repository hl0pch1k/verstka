"""One slide redesigned by the person's request in the chat («на слайде 3 покажи расходы таблицей», «сделай заголовок
короче», «добавь вывод про риски») — the agent's own loop for one slide.

The slide designer (skills/slide_designer, its revision mode) gets the request as the note to fix, the slide as it is
now and the same source text, data and template kinds it had when it designed the deck; its answer passes the same
guards (design_from_answer, tidy_design) and the same grounding as every slide of the agent, so a request never brings a
figure the brief does not have. The request wins over the form the brief asked for this slide: the person has just
asked for another one. Without a model (or when it fails) a change of form the request names («таблицей»,
«круговой диаграммой», «карточками») is made by the rules (reshape); anything else is declined in plain words."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from verstka.schemas.outline import Brief, DeckOutline, OutlineSlide
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

EDIT_BUDGET_S = 120.0  # one designer call (with its retries) and the checks; the chat waits for it
FRAME_KINDS = ("title", "section", "thanks")

# the form a request names, for the rules when there is no model: (pattern, kind, chart type)
_FORMS: list[tuple[re.Pattern, str, Optional[str]]] = [
    (re.compile(r"таблиц", re.I), "table", None),
    (re.compile(r"кругов|пирог", re.I), "chart", "pie"),
    (re.compile(r"кольцев|бублик", re.I), "chart", "doughnut"),
    (re.compile(r"столбч|гистограм|столбик", re.I), "chart", "column"),
    (re.compile(r"горизонтальн\w*\s+(?:диаграм|столб)", re.I), "chart", "bar"),
    (re.compile(r"линейн|график\w*\s+по\s+месяц|динамик", re.I), "chart", "line"),
    (re.compile(r"диаграмм|график", re.I), "chart", None),
    (re.compile(r"карточк", re.I), "cards", None),
    (re.compile(r"крупн\w*\s+(?:цифр|числ)|(?:цифр|числ)\w*\s+крупн", re.I), "stat_row", None),
    (re.compile(r"этап|шаг|шкал|таймлайн|по\s+месяцам", re.I), "timeline", None),
    (re.compile(r"две\s+колонк|два\s+столбц", re.I), "two_column", None),
    (re.compile(r"списк|пункт", re.I), "bullets", None),
]


def requested_form(request: str) -> Optional[tuple[str, Optional[str]]]:
    for rx, kind, chart_type in _FORMS:
        if rx.search(request):
            return kind, chart_type
    return None


def _slide_text(s: OutlineSlide) -> str:
    c = s.content
    lines = [s.headline, s.subtitle or "", *c.bullets, *c.paragraphs]
    lines += [f"{it.title} — {it.text}" if it.text else it.title for it in c.items]
    lines += [f"{n.label} — {n.value}" for n in c.numbers]
    lines += [s.takeaway or "", s.notes or ""]
    return "\n".join(x for x in lines if x and x.strip())


def _inline(outline: DeckOutline, s: OutlineSlide) -> OutlineSlide:
    """The slide with its charts' data written inline (a compiled chart refers to the deck's series registry by id)."""
    from verstka.schemas.outline import InlineSeries

    s = s.model_copy(deep=True)
    reg = {x.id: x for x in outline.series}
    for key in ("chart", "chart2"):
        ch = getattr(s.content, key)
        if ch is None or ch.series or not ch.series_ids:
            continue
        found = [reg[i] for i in ch.series_ids if i in reg]
        if found:
            ch.categories = ch.categories or list(found[0].categories)
            ch.series = [InlineSeries(name=x.name or "", values=[float(v or 0) for v in x.values]) for x in found]
            ch.unit = ch.unit or found[0].unit
    return s


def rules_form(outline: DeckOutline, s: OutlineSlide, kind: str, chart_type: Optional[str]) -> Optional[OutlineSlide]:
    """The form a request names, made by the rules: the slide's lines stay under the new form (a chart shown as a table
    keeps the lines beside it); None when the content does not fit it."""
    from verstka.planning import agent as A
    from verstka.schemas.common import PatternKind

    s = _inline(outline, s)
    c = s.content
    if kind == "table" and c.chart is not None and c.table is None:
        t = A._table_from_chart(c.chart)
        if t is None:
            return None
        content = c.model_copy(update={"table": t, "chart": c.chart2, "chart2": None}, deep=True)
        return s.model_copy(update={"kind": PatternKind.chart if c.chart2 is not None else PatternKind.table, "content": content}, deep=True)
    lines = list(c.bullets)
    bare = s.model_copy(update={"content": c.model_copy(update={"bullets": []})}, deep=True)
    new = A.reshape(bare, kind, chart_type)
    if new is None:
        return None
    if lines and not new.content.bullets:
        new.content.bullets = lines
    return new


_KEEP_VERB = r"(?:оставь|оставить|сохрани|сохранить|не\s+трогай|не\s+убирай)"
_KEEP_RX = re.compile(rf"\b{_KEEP_VERB}\b[^.;]{{0,40}}?(график|диаграмм|таблиц)|(график|диаграмм|таблиц)\w*[^.;]{{0,30}}?\b{_KEEP_VERB}\b", re.I)


def keep_what_was_asked(old: OutlineSlide, new: OutlineSlide, request: str, outline: DeckOutline) -> OutlineSlide:
    """«…карточками, а выручку оставь графиком»: the chart (or table) the person asked to keep stays on the slide when
    the redesign dropped it — the chart with the new lines beside it (a card's title and text as one line)."""
    m = _KEEP_RX.search(request)
    if not m:
        return new
    what = (m.group(1) or m.group(2)).lower()
    c, oc = new.content, _inline(outline, old).content
    if what.startswith("таблиц"):
        if c.table is None and oc.table is not None:
            c.table = oc.table.model_copy(deep=True)
        return new
    if c.chart is not None:
        return new
    olds = [ch for ch in (oc.chart, oc.chart2) if ch is not None]
    if not olds:
        return new
    keep = next((ch for ch in olds if ch.type in ("line", "area")), olds[0]) if what.startswith("график") else olds[0]
    from verstka.schemas.common import PatternKind

    lines = list(c.bullets) + [f"{it.title} — {it.text}" if it.text else it.title for it in c.items] + [f"{n.label} — {n.value}" for n in c.numbers]
    content = c.model_copy(update={"chart": keep.model_copy(deep=True), "chart2": None, "items": [], "numbers": [], "columns": [], "bullets": lines[:6]}, deep=True)
    return new.model_copy(update={"kind": PatternKind.chart, "content": content}, deep=True)


def _ground(o: DeckOutline, brief: Brief, structure) -> DeckOutline:
    """The compiler's checks without its deck-level steps (the order and count the brief asked for, the brief's
    requests for each slide, the variety pass, the cover): the person may have moved or removed slides, and their
    newest request wins over the brief's earlier one for this slide."""
    o = o.model_copy(deep=True)
    # the slides made from data files (OutlineSlide.data) are the data layer's: their figures come from the files
    # (checked by audit/checks/data.py), never from the brief — and their charts keep their gaps (None)
    held = [(k, s) for k, s in enumerate(o.slides) if s.data is not None]
    if held:
        o.slides = [s for s in o.slides if s.data is None]
    o = _ground_rest(o, brief, structure)
    for k, s in held:
        o.slides.insert(min(k, len(o.slides)), s)
    return o


def _ground_rest(o: DeckOutline, brief: Brief, structure) -> DeckOutline:
    from verstka.planning import compile as C
    from verstka.planning.grounding import BriefIndex, ground_outline

    run = C._Run(o, None)
    C._registry(o, structure)
    idx = BriefIndex.of(brief)
    idx.use_structure(structure)
    C._compile_charts(o, run)
    C._tense_guard(o, structure, idx, run)
    log_kept = list(o.agent_log)
    o, _ = ground_outline(o, brief, idx, structure=structure)
    o.agent_log = log_kept
    C._sync_charts(o)
    return o


# what a text edit is about: the words of the slide it names (none named — all of them)
_TARGETS: list[tuple[re.Pattern, set[str]]] = [
    (re.compile(r"подзаголов", re.I), {"subtitle"}),
    (re.compile(r"(?<!под)заголов|название\s+слайда", re.I), {"headline"}),
    (re.compile(r"подпис|вывод|пояснени|takeaway|caption", re.I), {"takeaway"}),
    (re.compile(r"пункт|строк|списк|тезис", re.I), {"bullets"}),
    (re.compile(r"замет|для\s+докладчика", re.I), {"notes"}),
]


def edit_targets(request: str) -> set[str]:
    """The words a request asks to change («сделай заголовок короче» — the headline; «добавь в подпись, почему…» — the
    caption), all of them when it names none («перепиши понятнее»)."""
    out: set[str] = set()
    for rx, fields in _TARGETS:
        if rx.search(request or ""):
            out |= fields
    return out or {"headline", "subtitle", "takeaway", "bullets", "notes"}


_ADD_RE = re.compile(r"(?<![\wё])(?:добав\w*|дополн\w*|допиш\w*|допиши|поясни\w*|объясни\w*)", re.I)


def _sentence_key(x: str) -> str:
    return re.sub(r"\s+", " ", (x or "").replace("\u00a0", " ")).strip(" .;").lower()


def _added(old_text: Optional[str], new_text: Optional[str]) -> Optional[str]:
    """An addition to a text («добавь в подпись, почему…»): the new text when it keeps every figure and most words of
    the old one (rewritten with the addition); else the old sentences all kept and the new ones after them; None when
    the new text adds no sentence of its own (the old text stays)."""
    from verstka.planning import heuristics as H

    def split(x: Optional[str]) -> list[str]:
        # a sentence ends before a capital: «кв. 2025», «п. за 7 кварталов» stay inside theirs
        return [t.strip() for t in re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«])", (x or "").replace("\u00a0", " ")) if t.strip()]

    olds, news = split(old_text), split(new_text)
    nums = lambda x: re.findall(r"\d+(?:[.,]\d+)?", (x or "").replace("\u00a0", ""))  # noqa: E731
    words = lambda x: set(re.findall(r"[а-яёa-z]{4,}", (x or "").lower()))  # noqa: E731
    ow, nw = words(old_text), words(new_text)
    if set(nums(old_text)) <= set(nums(new_text)) and len(ow & nw) * 10 >= len(ow) * 7 and len(nw) > len(ow):
        return H.strip_end(new_text or "")  # the caption rewritten with the addition: every figure and most words kept
    have = {_sentence_key(x) for x in olds}
    extra = [x for x in news if _sentence_key(x) not in have and not any(_sentence_key(x) in k for k in have)]
    if not extra:
        return None
    base = (old_text or "").strip()  # as it was written (its non-breaking spaces too)
    if base and not base.endswith((".", "!", "?", "…")):
        base += "."
    return (base + " " + " ".join(extra)).strip().rstrip(".")


def data_words(old: OutlineSlide, answer: Any, fields: Optional[set[str]] = None, adding: bool = False) -> OutlineSlide:
    """A slide made from a data file with the designer's words only (E1: «сделай заголовок короче», «добавь в подпись,
    почему…» on a chart from a file): the words the request is about (`fields`: headline, subtitle, the caption under the
    chart — `takeaway`, lines, notes; all by default) from the answer, everything else — the chart, the table, the
    figures, the cards — as it was. The answer's content blocks are the brief's business, never a data slide's: the
    chart stays the file's. The number rule of the data layer runs next (`keep_data`)."""
    from verstka.planning import heuristics as H

    fields = fields or {"headline", "subtitle", "takeaway", "bullets", "notes"}
    new = old.model_copy(deep=True)
    head = H.strip_end(getattr(answer, "headline", "") or "")
    if head and "headline" in fields:
        new.headline = head
    sub = H.strip_end(getattr(answer, "subtitle", None) or "")
    if sub and "subtitle" in fields:
        new.subtitle = sub
    tk = H.strip_end(getattr(answer, "takeaway", None) or "")
    if tk and "takeaway" in fields:
        # an addition keeps what the caption said («добавь в подпись, почему…» never drops its figures)
        new.takeaway = (_added(old.takeaway, tk) or old.takeaway) if adding and old.takeaway else tk
    notes = (getattr(answer, "notes", "") or "").strip()
    if notes and "notes" in fields:
        new.notes = notes
    c = new.content
    for key in ("bullets", "paragraphs") if "bullets" in fields else ():
        lines = [H.strip_end(x) for x in (getattr(answer, key, None) or []) if (x or "").strip()]
        # (the lines that say the headline or the caption again add nothing)
        lines = [x for x in lines if x.lower() not in {(new.headline or "").lower(), (new.takeaway or "").lower()}]
        if lines or getattr(c, key):
            setattr(c, key, lines[:6])
    if getattr(answer, "rationale", ""):
        new.rationale = answer.rationale
    return new


def _refused(old: OutlineSlide, proposed: OutlineSlide, got: OutlineSlide) -> list[str]:
    """The words the data's number rule did not take from the designer's answer, in plain Russian."""
    out = []
    if proposed.headline != old.headline and got.headline == old.headline:
        out.append(f"заголовок «{proposed.headline}» — в нём число, которого нет в данных слайда")
    if (proposed.takeaway or "") != (old.takeaway or "") and (got.takeaway or "") == (old.takeaway or ""):
        out.append(f"подпись «{proposed.takeaway}» — в ней число, которого нет в данных слайда")
    return out


def _data_facts(old: OutlineSlide) -> str:
    d = old.data
    facts = [f.text for f in (d.headline_facts if d is not None else []) if f.text][:8]
    return "; ".join(f"«{x}»" for x in facts)


def _words_of(s: OutlineSlide) -> tuple:
    c = s.content
    return (s.headline, s.subtitle, s.takeaway, tuple(c.bullets), tuple(c.paragraphs), tuple((it.title, it.text) for it in c.items))


def data_context(s: OutlineSlide) -> str:
    """The prose notes of the slide's data file (`SlideData.context`: «Опрос NPS во II квартале 2025 и 2026 года не
    проводился…» of «Итоги квартала.txt»), empty when the file has none or the deck predates the field."""
    d = s.data
    return " ".join(str(getattr(d, "context", None) or "").split()) if d is not None else ""


def keep_data(old: OutlineSlide, new: OutlineSlide) -> OutlineSlide:
    """A redesigned slide made from a data file stays the data layer's: its chart, table or figures, their source and
    `data` (for «Почему так» and the data checks) are kept. The designer's words stay only where every number in them
    is the data's (`verstka/data/story.data_text_ok` — the same rule the audit applies): the headline — one of the
    slide's facts; the subtitle, lines, cards and the caption — a fact or a value the slide shows. A line that fails is
    dropped; a headline or a caption that fails (or a caption the designer left out) keeps the old one. A number of the
    file's own notes (`data_context`: «во II квартале 2025 и 2026 года») counts as the data's in the words beside the
    figures; the headline stays one of the slide's facts."""
    from verstka.data.headline import numbers_in
    from verstka.data.story import data_text_ok, slide_values

    out = new.model_copy(deep=True)
    out.kind = old.kind
    out.data = old.data.model_copy(deep=True)
    out.footnote = old.footnote
    c = old.content
    out.content.chart = c.chart.model_copy(deep=True) if c.chart is not None else None
    out.content.chart2 = c.chart2.model_copy(deep=True) if c.chart2 is not None else None
    out.content.table = c.table.model_copy(deep=True) if c.table is not None else None
    out.content.numbers = [n.model_copy() for n in c.numbers]
    values = slide_values(old) + numbers_in(data_context(old))

    def ok(text: Optional[str]) -> bool:
        return not (text or "").strip() or data_text_ok(text or "", old, values=values)

    if not (out.headline or "").strip() or not data_text_ok(out.headline, old):
        out.headline = old.headline
    if not (out.takeaway or "").strip() or not ok(out.takeaway):
        out.takeaway = old.takeaway
    if not ok(out.subtitle):
        out.subtitle = old.subtitle if ok(old.subtitle) else None
    oc = out.content
    oc.bullets = [b for b in oc.bullets if ok(b)]
    oc.paragraphs = [b for b in oc.paragraphs if ok(b)]
    oc.items = [it for it in oc.items if ok(it.title) and ok(it.text) and ok(it.number) and all(ok(b) for b in it.bullets)]
    oc.columns = [it for it in oc.columns if ok(it.title) and ok(it.text) and ok(it.number) and all(ok(b) for b in it.bullets)]
    if oc.quote and not ok(oc.quote):
        oc.quote = None
    return out


def describe_change(old: OutlineSlide, new: OutlineSlide) -> str:
    """What a redesign changed, in plain words: «было — список (5 пунктов), стало — этапы (5); заголовок «…»»."""
    from verstka.planning import agent as A

    before, after = A.form_ru(old), A.form_ru(new)
    changed = []
    if before != after:
        changed.append(f"было — {before}, стало — {after}")
    if new.headline != old.headline:
        changed.append(f"заголовок «{new.headline}»")
    if (new.takeaway or "") != (old.takeaway or ""):
        word = "подпись" if old.data is not None else "вывод"
        changed.append(f"{word} «{new.takeaway}»" if new.takeaway else f"без отдельного вывода")
    for key in ("chart", "chart2"):
        a, b = getattr(old.content, key), getattr(new.content, key)
        if a is not None and b is not None and a.highlight_index != b.highlight_index and b.highlight_index is not None and 0 <= b.highlight_index < len(b.categories):
            changed.append(f"выделено «{b.categories[b.highlight_index]}» на диаграмме")
    if new.content.photo_slot and not old.content.photo_slot:
        changed.append("оставлено свободное место под фото — вставьте его в рамку на слайде")
    elif old.content.photo_slot and not new.content.photo_slot:
        changed.append("место под фото убрано")
    return "; ".join(changed) if changed else "переписан текст"


def story_brief(outline: DeckOutline, brief: Optional[Brief]) -> Optional[Brief]:
    """The text a data deck's slide is checked against (N-E3): its one-line brief says nothing of the figures, the data
    story does — every data slide's facts, headline, caption and figures and the story's own slides (the summary, «Что
    дальше»), which the story writer built from those facts. None for a deck without data slides (the brief as it is)."""
    data = [s for s in outline.slides if s.data is not None]
    if not data:
        return None
    lines: list[str] = []
    for s in outline.slides:
        if s.kind.value in FRAME_KINDS:
            continue
        lines.append(_slide_text(s))
        if s.data is not None:
            lines += [f.text for f in s.data.headline_facts if f.text]
            lines += [f.explain for f in s.data.headline_facts if f.explain]
            if data_context(s):
                lines.append(data_context(s))
    base = brief or Brief(text="")
    story = "\n".join(x for x in lines if x and x.strip())
    return base.model_copy(update={"text": f"{base.text or ''}\n\n{story}".strip()})


# «выдели Казань цветом», «подсвети Москву», «сделай акцент на Казани»: a category of the slide's chart, made to stand out
_EMPHASIS_RE = re.compile(r"(?<![\wё])(?:выдели\w*|выделить|подсвет\w*|акцент\w*|сделай\s+ярче|отметь\s+цветом|покрась)", re.I)


def emphasis_request(request: str) -> bool:
    return bool(_EMPHASIS_RE.search(request or "")) and not re.search(r"(?<![\wё])(?:жирн|курсив|заголов)", request or "", re.I)


def emphasis_index(request: str, s: OutlineSlide) -> tuple[Optional[str], Optional[int], list[str]]:
    """(which chart: "chart" | "chart2", the category the request names, the chart's categories) — the category matched
    by the stems of its words («Казань» in «выдели Казань цветом», «Казани»)."""
    words = [w.lower() for w in re.findall(r"[А-Яа-яЁёA-Za-z0-9]{3,}", request or "")]
    for key in ("chart", "chart2"):
        ch = getattr(s.content, key)
        if ch is None or not ch.categories:
            continue
        cats = [str(c) for c in ch.categories]
        for k, cat in enumerate(cats):
            stems = [w.lower()[: max(4, len(w) - 2)] for w in re.findall(r"[А-Яа-яЁёA-Za-z0-9]{3,}", cat)]
            if stems and all(any(w.startswith(st) for w in words) for st in stems):
                return key, k, cats
        return key, None, cats
    return None, None, []


def _visible(s: OutlineSlide) -> dict:
    """What the person sees of a slide (its form, words, figures, charts and their highlight), for «did it change»."""
    return s.model_dump(include={"kind", "headline", "subtitle", "takeaway", "footnote", "content"})


_TAIL_RE = re.compile(r"(?:^|\s)(?P<prep>при|на|в|во|к|ко|для|из|по|о|об|от|с|со|за|до|после|без|через|перед)\s+(?P<w>[а-яё-]{4,})$", re.I)


def whole_headline(headline: str, source: str) -> str:
    """A headline cut mid-phrase to fit a word count («…опросы не проводились при переходе») taken to the end of its
    phrase in the source («…при переходе на новую систему опросов»), when the source continues that word; as it is
    otherwise (N-E6)."""
    h = (headline or "").strip()
    m = _TAIL_RE.search(h)
    if not m or not source:
        return h
    stem = m.group("w").lower()[:6]
    for mm in re.finditer(rf"(?<![\wё]){re.escape(stem)}[а-яё]*\s+(?P<rest>[^.;:!?()«»—–]+)", source, re.I):
        rest = mm.group("rest").strip(" ,")
        if not rest or len(rest.split()) > 6 or rest.split()[0].lower() in ("и", "а", "но", "что", "где", "когда"):
            continue
        out = f"{h} {rest}"
        if len(out.split()) <= 16:
            return out
    return h


@dataclass
class SlideRedesign:
    """One slide redesigned: the grounded outline (the caller takes slide `index` and the registry), the agent's reply,
    who designed it ("model" | "rules") and what changed («было — пункты, стало — этапы (6 шагов)»)."""

    outline: DeckOutline
    reply: str
    how: str
    what: str
    # what the edit's model calls cost (pipeline/generate.call_totals): carried into the variant's run_manifest.usage
    usage: dict = field(default_factory=dict)


# the usage of the edits whose outlines the caller has not rendered yet, by the outline's hash (revise.rerender_variant
# takes it when it renders that outline: the chat's edit returns only the outline)
_EDIT_USAGE: dict[str, dict] = {}


def outline_key(o: DeckOutline) -> str:
    import hashlib

    return hashlib.sha256(o.model_dump_json().encode("utf-8")).hexdigest()[:24]


def take_edit_usage(o: DeckOutline) -> dict:
    """The usage of the edit that made `o` (once), {} when none is known."""
    return _EDIT_USAGE.pop(outline_key(o), {})


def redesign_slide(
    outline: DeckOutline,
    index: int,
    brief: Optional[Brief],
    manifest: Optional[TemplateManifest],
    *,
    request: str = "",
    note: Optional[str] = None,
    start_line: Optional[str] = None,
    rationale: Optional[str] = None,
    log_line: Optional[str] = None,
    skills: Any = None,
    providers: Any = None,
    progress: Optional[Callable[..., None]] = None,
) -> SlideRedesign:
    """Slide `index` (1-based) redesigned by the slide designer's revision mode.

    `request` is what the person asks («покажи этапами»; may be empty for a fix of remarks), `note` the designer's
    `issues` block (default: the person's request), `start_line` what the designer says it does («переделываю по
    замечаниям»; default: the request in quotes), `rationale` the start of the slide's «почему так» (default: «По вашей
    просьбе «…»»), `log_line` the agent log's line with a `{what}` placeholder. Without a model (or when it fails) the
    form the request names is made by the rules; with a `note` and no form named it raises ValueError("model_unavailable")
    (the slide fix then fixes the slide in place). Raises ValueError with a plain Russian message otherwise."""
    from verstka.planning import agent as A
    from verstka.planning.strategies import load_strategies

    if not 1 <= index <= len(outline.slides):
        raise ValueError(f"в этом варианте {len(outline.slides)} слайдов — слайда {index} нет")
    old = outline.slides[index - 1]
    if old.kind.value in FRAME_KINDS:
        raise ValueError("обложку и разделители агент собирает из названия и разделов текста — поменяйте их в тексте и соберите презентацию заново")
    request = request or ""
    fixing = note is not None
    # a data deck's slides are checked against its data story, never against its one-line brief alone (N-E3)
    brief = story_brief(outline, brief) or brief or Brief(text=_slide_text(old))
    tracker = A._Tracker(progress)
    stats: list = []
    if providers is not None:
        try:
            from verstka.pipeline.generate import _recording

            providers, _ = _recording(providers, stats)  # what the edit's model calls cost (run_manifest.usage)
        except Exception:  # noqa: BLE001 - recording is a nicety
            pass
    structure, _ = A.analyse_brief(brief)  # the rules' reading: no model call, the data the deck was built from
    facts = A._resolve_facts(None, brief, [], structure)
    ctx = A._build_ctx(brief, structure, facts, manifest)
    try:
        from verstka.planning.writer import is_written_text

        ctx.written = is_written_text(brief.text or "")  # a written deck's slide: the same checks as at the build
    except Exception:  # noqa: BLE001 - the writer's check or none
        pass
    units = A._units_from_specs(ctx) if structure.specs else []
    unit = next((u for u in units if u.spec is not None and u.spec.number == old.spec_ref), None) if old.spec_ref else None
    if unit is None:
        text = _slide_text(old)
        chart_ids = [sid for ch in (old.content.chart, old.content.chart2) if ch is not None for sid in ch.series_ids if sid in ctx.series]
        if data_context(old):
            text += f"\nИз файла «{old.data.file}»: {data_context(old)}"  # the file's prose notes: the slide's source too
        unit = A._Unit(key=f"edit{index}", title=old.headline, text=text, series_ids=chart_ids, fact_ids=A._facts_in(ctx, text))
    # the deck's own order for the designer's context (the neighbours' titles), whatever the brief's order was
    neighbours = [unit if i == index else A._Unit(key=f"s{i}", title=s.headline) for i, s in enumerate(outline.slides, 1)]

    strategies = load_strategies()
    strategy = strategies.get(outline.strategy or "structured") or next(iter(strategies.values()))
    clock = A._Clock(providers if skills is not None else None, time.monotonic() + EDIT_BUDGET_S)
    agent = A._Agent(brief, manifest, [strategy], skills, providers, tracker, clock, raw=[])
    form = requested_form(request) if request.strip() else None
    # «оставь место под фото»: the slide keeps a free place for the person's own photo (the renderer makes it — the
    # template's own photo place or a quiet frame); «убери место под фото» takes it back
    from verstka.planning.brief_structure import photo_dropped, photo_request

    photo = photo_request(request) if request.strip() else None
    drop_photo = bool(request.strip()) and photo_dropped(request)
    emphasis: Optional[tuple[str, int]] = None
    if not fixing and emphasis_request(request):
        # «выдели Казань цветом»: the chart's own highlight on that category — a safe edit the rules make, no model; a
        # colour the slide cannot show this way is said so, never reported as done (N-E4)
        key, k, cats = emphasis_index(request, old)
        if key is None:
            raise ValueError(f"цветом выделяется столбец, точка или сектор диаграммы, а на слайде {index} диаграммы нет — выделить так не получится")
        if k is None:
            raise ValueError(f"на диаграмме слайда {index} нет такой категории — можно выделить: " + ", ".join(f"«{c}»" for c in cats[:12]))
        if getattr(old.content, key).highlight_index == k:
            raise ValueError(f"«{cats[k]}» на слайде {index} уже выделена цветом")
        emphasis = (key, k)
    if old.data is not None and emphasis is None:
        # a slide made from a data file changes its form only among the analysis's options («Пересобрать слайд так»);
        # its words — with the model only (the rules have nothing to say about the data)
        from verstka.data.rebuild import _form_phrase, option_for_request

        titles = ", ".join(f"«{o.title.lower()}»" for o in old.data.options)
        if request.strip() and _form_phrase(request) and option_for_request(request, old.data) is None:
            raise ValueError(f"слайд {index} собран из файла «{old.data.file}»: его вид меняет «Пересобрать слайд так» — можно {titles}")
        form = None
        if not agent.models and not (photo or drop_photo):
            if fixing:
                raise ValueError("model_unavailable")
            raise ValueError(f"без модели слайд из файла «{old.data.file}» меняет только «Пересобрать слайд так» — можно {titles}")
    new: Optional[OutlineSlide] = None
    how = ""
    answered = False  # the model answered (its answer may still not fit the slide): never «the model is unavailable»
    proposed: Optional[OutlineSlide] = None  # a data slide's words as the model proposed them (before the number rule)
    refused_first: list[str] = []
    if emphasis is not None:
        new = old.model_copy(deep=True)
        getattr(new.content, emphasis[0]).highlight_index = emphasis[1]
        how = "rules"
    elif agent.models:
        tracker.emit("designer", f"Дизайнер: слайд {index} — {start_line if start_line is not None else '«' + request[:140] + '»'}.", slide=index)
        if note is None:
            note = (
                f"- The person who reads this deck asks to change this slide: «{request}». Do exactly what they ask and keep the "
                "rest of your design. Their request overrides the form the brief asked for this slide. Every figure still comes "
                "from the source text or the data list."
            )
            if photo:
                note += f"\n- The slide keeps {A.photo_requirement(photo)}."
        if old.data is not None:
            note += (
                f"\n- This slide is made from the data file «{old.data.file}»: its chart, table and figures stay exactly as they are "
                "(do not return them). Change only the words the request is about: the headline, the caption under the chart "
                "(\"takeaway\"), the subtitle or the lines. Every number you write is one of this slide's own figures, as in "
                "your previous design. A headline is a whole statement: never cut a phrase to fit a word count (say less instead)."
            )
            notes = data_context(old)
            if notes:
                # the file's own words explain what the figures do not (why a quarter has no value): a «почему…» is
                # answered from them, never made up
                note += (
                    f"\n- The data file's own notes (the source's words, the only explanation you may give): «{notes}». "
                    "When the person asks why or asks to explain, take the reason from these notes; numbers from them count as the data's."
                )
        fields = edit_targets(request) if old.data is not None else None

        def data_attempt(issues: str) -> tuple[OutlineSlide, Optional[OutlineSlide], list[str]]:
            """One designer call for a data slide's words: (the slide after the number rule, the words as proposed, what
            the rule did not take); a design without its answer (a stub's) is taken as it is: (it, None, [])."""
            try:
                d = agent.model_design(unit, index, neighbours, ctx, clock.deadline, issues=issues, previous=A._previous_json(old))
                ans = d.answer
            except A.UnusableAnswer as e:
                if e.answer is None:
                    raise
                ans = e.answer  # a headline or a caption without a content block: a text edit of a data slide (E1)
            if ans is None:
                return d.slide, None, []
            prop = data_words(old, ans, fields, adding=bool(_ADD_RE.search(request or "")))  # the words only: the brief's checks are not the data's
            if prop.headline != old.headline:
                prop.headline = whole_headline(prop.headline, f"{unit.text}\n{data_context(old)}")
            got = keep_data(old, prop.model_copy(deep=True))
            log.info("data slide edit %s: proposed %s", index, json.dumps({"headline": prop.headline, "takeaway": prop.takeaway, "fields": sorted(fields or [])}, ensure_ascii=False))
            return got, prop, _refused(old, prop, got)

        try:
            if old.data is not None:
                first = data_attempt(note)
                answered = True
                if first[2] and clock.left() > 20:
                    # once more, with the figures the slide has: «за 9 месяцев» is no figure of a September-to-September chart
                    again = data_attempt(note + f"\n- Your answer was not taken: {'; '.join(first[2])}. This slide's own figures: {_data_facts(old)}. Write it again with these figures only, or without a number.")
                    if len(again[2]) < len(first[2]) and _words_of(again[0]) != _words_of(old):
                        first = again
                new, proposed, refused_first = first
            else:
                d = agent.model_design(unit, index, neighbours, ctx, clock.deadline, issues=note, previous=A._previous_json(old))
                answered = True
                A.tidy_design(d, ctx)
                new = d.slide
            how = "model"
        except A.UnusableAnswer:
            answered = True
            log.warning("slide edit: the designer's answer has no content for slide %s", index)
            how = "model answered without content"
        except Exception as e:  # noqa: BLE001 - the rules try the form the request names
            log.warning("slide edit: the designer failed", exc_info=True)
            if not fixing or form is not None:
                tracker.emit("designer", "Дизайнер: модель не ответила — пробую сделать по правилам.", slide=index)
            how = f"model failed: {str(e)[:120]}"
    if new is None and (photo or drop_photo) and form is None:
        new, how = old.model_copy(deep=True), "rules"  # the slide as it is, with its photo place made or taken back
    if new is None:
        if form is not None:
            new = rules_form(outline, old, form[0], form[1])
            if new is not None:
                how = "rules"
        if new is None:
            if form is None:
                if answered:
                    raise ValueError("модель ответила, но в её ответе нет содержимого для этого слайда — попробуйте сказать иначе, что поменять: заголовок, подпись или пункты")
                if fixing:
                    raise ValueError("model_unavailable")
                if agent.models:
                    raise ValueError("модель не ответила, а без неё могу только сменить форму слайда («таблицей», «круговой диаграммой», «карточками») — попробуйте ещё раз через минуту")
                raise ValueError("без модели могу только сменить форму слайда («таблицей», «круговой диаграммой», «карточками»), а модель сейчас недоступна")
            raise ValueError(f"содержимое слайда {index} не ложится в такую форму: для неё нет подходящих данных в тексте")
    new = keep_what_was_asked(old, new.model_copy(deep=True), request, outline)
    refused: list[str] = []
    if old.data is not None:
        new = keep_data(old, new)
        if emphasis is not None:
            getattr(new.content, emphasis[0]).highlight_index = emphasis[1]  # (the data's chart, with the asked highlight)
        if proposed is not None:
            refused = refused_first
            if _words_of(new) == _words_of(old) and not (photo or drop_photo):
                if refused:
                    why = "; ".join(refused)
                elif _ADD_RE.search(request or ""):
                    why = "в её ответе нет ничего нового к тексту слайда — в данных слайда этого нет"
                else:
                    why = "модель вернула прежний текст"
                raise ValueError(f"модель ответила, но правку не применил: {why}")
    new.id = old.id
    new.spec_ref = old.spec_ref
    new.content.photo_slot = photo or (None if drop_photo else old.content.photo_slot)
    # «оставь место под фото» asks for the person's own photo; a kept place keeps what it was for
    new.content.photo_own = bool(photo) or (False if drop_photo else old.content.photo_own)
    if new.content.photo_slot is None:
        new.content.photo_hint = None if drop_photo else new.content.photo_hint
    why = (new.rationale or "").strip()
    lead = rationale if rationale is not None else f"По вашей просьбе «{request.strip()}»"
    lead = lead.strip()
    if lead and lead[-1] not in ".!?…":
        lead += "."
    new.rationale = lead + (f" {why}" if why else "")
    edited = outline.model_copy(deep=True)
    edited.slides[index - 1] = new
    checked = _ground(edited, brief, structure)
    # the slide by its id: the checks may drop slides whose figures the text does not have (a deck built from a plan
    # has only this slide's text to check against), and every other slide stays exactly as it was
    result = next((s for s in checked.slides if s.id == new.id), None)
    if result is None:
        raise ValueError("после проверки цифр на слайде ничего не осталось — попросите иначе")
    grounded = outline.model_copy(deep=True)
    grounded.slides[index - 1] = result
    have = {x.id for x in grounded.series}
    grounded.series.extend(x for x in checked.series if x.id not in have)
    have = {x.id for x in grounded.facts}
    grounded.facts.extend(x for x in checked.facts if x.id not in have)
    for t in checked.tables:
        if not any(t.columns == u.columns and t.rows == u.rows for u in grounded.tables):
            grounded.tables.append(t)
    if _visible(result) == _visible(old) and not (photo or drop_photo):
        # never «переделан» for a slide that did not change (N-E4): the reply says what happened instead
        if answered:
            raise ValueError("модель ответила, но слайд после проверки не изменился — попробуйте сказать иначе, что поменять")
        raise ValueError(f"слайд {index} не изменился: такую правку по правилам сделать не получилось")
    after = A.form_ru(result)
    what = describe_change(old, result)
    reply = f"Слайд {index} переделан: {what}."
    if emphasis is not None:
        reply = f"Слайд {index}: выделил «{getattr(result.content, emphasis[0]).categories[emphasis[1]]}» цветом на диаграмме."
    elif how == "rules":
        reply += " Модель не ответила, форму сменил по правилам." if not answered else " Ответ модели не подошёл к слайду, форму сменил по правилам."
    if refused:
        reply += " Не взял из ответа модели: " + "; ".join(refused) + "."
    tracker.emit("designer", f"Дизайнер: слайд {index} — {after}.", slide=index)
    line = log_line if log_line is not None else f"Правка: слайд {index} по просьбе «{request.strip()[:160]}» — {{what}}."
    grounded.agent_log = [*outline.agent_log, line.replace("{what}", what)]
    log.info("slide edit %s: %s", how, json.dumps({"slide": index, "request": request[:200], "fix": fixing}, ensure_ascii=False))
    usage: dict = {}
    if stats:
        try:
            from verstka.pipeline.generate import call_totals

            usage = call_totals(list(stats))
            if len(_EDIT_USAGE) > 64:
                _EDIT_USAGE.clear()
            _EDIT_USAGE[outline_key(grounded)] = usage
        except Exception:  # noqa: BLE001
            usage = {}
    return SlideRedesign(outline=grounded, reply=reply, how=how, what=what, usage=usage)


def revise_slide(
    outline: DeckOutline,
    index: int,
    request: str,
    brief: Optional[Brief],
    manifest: Optional[TemplateManifest],
    *,
    skills: Any = None,
    providers: Any = None,
    progress: Optional[Callable[..., None]] = None,
) -> tuple[DeckOutline, str]:
    """The outline with slide `index` (1-based) redesigned by `request`, and what the agent says about it. Raises
    ValueError with a plain Russian message when it cannot do it (the job reports it in the chat)."""
    r = redesign_slide(outline, index, brief, manifest, request=request, skills=skills, providers=providers, progress=progress)
    return r.outline, r.reply
