"""Data files and the knowledge base in one deck: the data story (verstka/data/story.py — its charts, conclusions and
summary, untouched) plus the slides the knowledge base writes for what the data does not show.

The experts' typical input is «a rough plan + data», the knowledge base a plus. The plan's items the data story
already shows (their words are on its data slides: «Как выросла выручка — покажи на графике» over «Выручка выросла
на 37%») stay the data's; every other item («Что думают клиенты», «Что просим у правления») is written from the base
by the writer (planning/topic_writer.py, the same fact check: figures against the documents, the model's check by the
fragments) — or, without a model, of the documents' own sentences (compose.py). A bare request without a plan gets a
few slides of context from the base. Each knowledge slide keeps the sources of its statements in its notes («Источники:
«Отчёт Q3», раздел «Выручка», таблица; …»), the cover says the text comes from the base.

Where they go: the items before the first item the data shows — after the story's context, before its data slides;
the plan's last item, when the data does not show it, — after the summary (the request, the next steps close the
deck); the others — before the summary. The story's context lines that only said «this goal is not in the data» about an item the base now
answers are dropped."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from verstka.knowledge.reference import KbReference, KbSource, sources_line
from verstka.knowledge.text import tokens
from verstka.schemas.outline import Brief, DeckOutline, NumberCallout, OutlineSlide, PatternKind, SlideContent, SlideItem, TableData

log = logging.getLogger(__name__)

COVER_SHARE = 0.6  # the share of a plan item's words a data slide must say to be that item's slide
CONTEXT_SHARE = 0.6  # a context line of the data story that says as much of an item the base now answers goes
TOPIC_SLIDES = 3  # knowledge slides for a bare request (no plan) beside the data
WRITER_BUDGET_S = 210.0  # the writer's own budget (its deadline is the budget minus the agent reserve, at most 100 s)
_ASK_STEMS = {"покаж", "показа", "график", "диаграм", "сравн", "нужна", "нужен", "сдела", "добав", "картин", "таблиц", "слайд",
              "выведи", "вывед", "отраз", "нарисуй", "нарису", "кратк", "коротк", "подробн", "отдель"}


@dataclass
class KbPart:
    outline: DeckOutline
    writer: Any = None  # planning.writer.WriterResult of the knowledge part (None: nothing written)
    items: list[str] = field(default_factory=list)  # the plan's items the base wrote
    covered: list[str] = field(default_factory=list)  # the plan's items the data shows
    log: list[str] = field(default_factory=list)


def _stems(text: str) -> set[str]:
    return {t for t in tokens(text) if not t[0].isdigit() and len(t) >= 3 and t not in _ASK_STEMS}


def slide_words(s: OutlineSlide) -> set[str]:
    """What a data slide says on the slide: its headline, subtitle, takeaway and content (the chart's title, labels,
    numbers — the values, not the field names) — not its plan's reasons (they quote the whole brief)."""
    vals: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            vals.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(s.content.model_dump(mode="json"))
    return _stems(" ".join([s.headline or "", s.subtitle or "", s.takeaway or "", *vals]))


def item_covered(item: str, data_slides: list[OutlineSlide]) -> bool:
    """A plan item the data story shows: most of its own words (the author's asks aside) on one of its data slides."""
    want = _stems(item)
    if not want:
        return False
    need = max(1, math.ceil(COVER_SHARE * len(want)))
    return any(len(want & slide_words(s)) >= need for s in data_slides)


def _is_data(s: OutlineSlide) -> bool:
    return s.data is not None or s.id.startswith("data-") or s.id == "key-figures"


# ------------------------------------------------------------------ the writer's slides → outline slides


def _sentence(t: str) -> str:
    t = " ".join((t or "").split())
    return t if not t or t.endswith((".", "!", "?", "…", ":")) else t + "."


def outline_slide(d: dict, sid: str) -> Optional[OutlineSlide]:
    """A slide the writer (or compose.py) wrote, as an outline slide: key figures → a row of numbers, dated events →
    a timeline, steps → a process, a table → a table, a chart's rows → key figures, else the lead and points as a list.
    The figures are the slide's own (already checked against the base)."""
    title = " ".join(str(d.get("title") or "").split())
    if not title:
        return None
    lead = _sentence(d.get("lead") or "")
    points = [_sentence(p) for p in d.get("points") or [] if str(p).strip()]
    take = _sentence(d.get("takeaway") or "") or None
    nums = [NumberCallout(value=str(n.get("value") or "").strip(), label=str(n.get("label") or "").strip()) for n in d.get("numbers") or []
            if str(n.get("value") or "").strip() and str(n.get("label") or "").strip()]
    chart = d.get("chart") or None
    if not nums and chart and chart.get("rows"):
        unit = f" {chart.get('unit')}" if chart.get("unit") else ""
        nums = [NumberCallout(value=f"{r.get('value'):g}{unit}" if isinstance(r.get("value"), (int, float)) else str(r.get("value")), label=str(r.get("label") or ""))
                for r in chart["rows"][:4] if r.get("label")]
    table = d.get("table") or None
    timeline = [e for e in d.get("timeline") or [] if e.get("when") and e.get("what")]
    steps = [x for x in d.get("steps") or [] if str(x).strip()]
    base = {"id": sid, "headline": title, "takeaway": take, "rationale": "Факты — из базы знаний: документы и места — в заметках слайда."}
    if len(nums) >= 2:
        return OutlineSlide(kind=PatternKind.stat_row, subtitle=lead or None, content=SlideContent(numbers=nums[:4]), **base)
    if len(timeline) >= 3:
        return OutlineSlide(kind=PatternKind.timeline, subtitle=lead or None,
                            content=SlideContent(items=[SlideItem(title=str(e["when"]), text=_sentence(e["what"])) for e in timeline[:7]]), **base)
    if len(steps) >= 3:
        return OutlineSlide(kind=PatternKind.process, subtitle=lead or None,
                            content=SlideContent(items=[SlideItem(title=f"Шаг {i}", text=_sentence(x)) for i, x in enumerate(steps[:6], 1)]), **base)
    if table and table.get("rows") and table.get("header"):
        w = len(table["header"])
        rows = [[str(c) for c in (r + [""] * w)[:w]] for r in table["rows"][:8]]
        return OutlineSlide(kind=PatternKind.table, subtitle=lead or None, content=SlideContent(table=TableData(columns=[str(h) for h in table["header"]], rows=rows)), **base)
    lines = ([lead] if lead else []) + points
    if not lines:
        return None
    return OutlineSlide(kind=PatternKind.bullets, content=SlideContent(bullets=lines[:6]), **base)


# ------------------------------------------------------------------ the deck


def _item_of(d: dict, todo: list[str], items: list[str]) -> int:
    """The plan item a written slide is about (the most of its words in the slide's title and lead), -1 — none."""
    if not todo:
        return -1
    have = _stems(f"{d.get('title') or ''} {d.get('lead') or ''} {' '.join(d.get('points') or [])}")
    best = max(todo, key=lambda it: (len(_stems(it) & have) / max(1, len(_stems(it))), -todo.index(it)))
    return items.index(best) if _stems(best) & have else -1


def _notes_of(sources: list[dict], n: int) -> str:
    got = [KbSource(doc=x.get("doc") or "", title=x.get("page") or "", name="", url=x.get("url") or None, place=x.get("place") or "",
                    fragment=x.get("fragment") or "", text="") for x in sources if x.get("slide") == n]
    return sources_line(got)


def _write(brief: Brief, kb: KbReference, items: list[str], topic: str, n_slides: int, *, skills: Any, providers: Any,
           progress: Optional[Callable[[dict], None]], budget_end: Optional[float]) -> tuple[Any, list[dict]]:
    """The knowledge part's slides: (WriterResult, slides as data). With a model — the writer over the base, its plan
    the items; without — the documents' own sentences."""
    from verstka.planning.writer import WriterMode, WriterResult, load_config

    mode = WriterMode("topic", topic=topic, language=brief.language or "ru", reason="kb_data", plan=list(items))
    has_llm = providers is not None and skills is not None and getattr(providers, "has", lambda r: False)("llm")
    if has_llm:
        from verstka.planning.topic_writer import write_topic_deck

        part = Brief(text=topic, slide_count=(len(items) if items else n_slides) + 1, audience=brief.audience, language=brief.language, purpose=brief.purpose)
        res = write_topic_deck(part, mode, skills, providers, budget_end=budget_end or (time.monotonic() + WRITER_BUDGET_S), progress=progress,
                               config=load_config(), knowledge=kb, min_slides=1)
        if res.written:
            return res, list(res.slides_data)
        if res.status not in ("failed", "skipped"):
            return res, []
    from verstka.knowledge.compose import compose_text

    data: list[dict] = []
    text, sources = compose_text(kb, topic, plan=items or None, slides=n_slides + 1, slides_out=data)
    res = WriterResult(mode="topic", topic=topic, basis="kb", checked="knowledge", status="written" if text else "failed", text=text, sources=sources)
    res.slides = len(data)
    return res, data


def add_knowledge(outline: DeckOutline, brief: Optional[Brief], kb: KbReference, *, skills: Any = None, providers: Any = None,
                  progress: Optional[Callable[[dict], None]] = None, budget_end: Optional[float] = None) -> KbPart:
    """The data story's outline with the knowledge base's slides for what the data does not show (see the module)."""
    from verstka.planning.topic_writer import plan_items, topic_subject

    out = KbPart(outline=outline)
    if brief is None or not (brief.text or "").strip() or kb.empty:
        return out
    head, items = plan_items(brief.text)
    data_slides = [s for s in outline.slides if _is_data(s)]
    if len(items) >= 2:
        out.covered = [it for it in items if item_covered(it, data_slides)]
        todo = [it for it in items if it not in out.covered]
        if not todo:
            out.log.append("База знаний: все пункты плана показывают данные — слайдов по базе не нужно.")
            return out
        topic = head or outline.title or todo[0]
    else:
        todo = []
        topic = topic_subject(" ".join(brief.text.split())[:300]) or outline.title
        if kb.relevance(topic) < 1.0:
            out.log.append("База знаний: о теме в ней ничего нет — колода по данным.")
            return out
    res, slides = _write(brief, kb, todo, topic, TOPIC_SLIDES, skills=skills, providers=providers, progress=progress, budget_end=budget_end)
    res.part = "kb_with_data"
    if res.kb is None:
        res.kb = {"id": kb.kb.id, "name": kb.name, "docs": [{"id": k, "title": kb.title_of(k), "url": d.get("url")} for k, d in kb.docs.items()]}
        res.basis = "kb"
    if not res.pages_used:
        used = list(dict.fromkeys(x.get("doc") for x in res.sources or [] if x.get("doc")))
        res.pages_used = [{"title": kb.title_of(d), "url": (kb.docs.get(d) or {}).get("url") or ""} for d in used]
    out.writer = res
    if not slides:
        out.log.append("База знаний: текст по ней не написан — колода по данным.")
        return out
    made: list[tuple[int, OutlineSlide]] = []  # (the plan's item index or -1, slide)
    # the writer follows the plan: a slide per item, in order — then the slides take the items by place; otherwise by
    # their words
    by_place = len(slides) == len(todo)
    for k, d in enumerate(slides):
        s = outline_slide(d, f"kb-{k + 1}")
        if s is None:
            continue
        line = _notes_of(res.sources or [], int(d.get("n") or k + 2))
        s.notes = line
        made.append((items.index(todo[k]) if by_place else _item_of(d, todo, items), s))
    # a slide whose words name no item takes the first item no slide took, in order (the writer follows the plan)
    taken = {at for at, _ in made if at >= 0}
    free = [items.index(it) for it in todo if items.index(it) not in taken]
    made = [(at if at >= 0 else (free.pop(0) if free else -1), s) for at, s in made]
    if not made:
        return out
    out.items = todo
    slides_now = list(outline.slides)
    # the story's context lines that only said an item the base now answers was not in the data
    handled = [_stems(it) for it in todo]
    for s in slides_now:
        if s.id.startswith("context") and s.content.bullets:
            keep = [b for b in s.content.bullets if not any(h and len(h & _stems(b)) >= CONTEXT_SHARE * len(h) for h in handled)]
            s.content = s.content.model_copy(update={"bullets": keep})
    slides_now = [s for s in slides_now if not (s.id.startswith("context") and not s.content.bullets)]
    covered_at = [items.index(c) for c in out.covered]
    first_cov = min(covered_at) if covered_at else None
    last_cov = max(covered_at) if covered_at else None
    data_idx = [i for i, s in enumerate(slides_now) if _is_data(s)]
    summary_idx = next((i for i, s in enumerate(slides_now) if s.id == "summary"), None)
    before_data = data_idx[0] if data_idx else len(slides_now)
    before_summary = summary_idx if summary_idx is not None else (data_idx[-1] + 1 if data_idx else len(slides_now))
    end = len([s for s in slides_now if s.id != "appendix"])
    head_part, mid_part, tail_part = [], [], []
    for at, s in made:
        if at < 0 or first_cov is None:
            mid_part.append(s)
        elif at < first_cov:
            head_part.append(s)
        elif last_cov is not None and at > last_cov and at == len(items) - 1:
            tail_part.append(s)  # the plan's closing item (the request, the next steps) closes the deck
        else:
            mid_part.append(s)
    after_summary = (summary_idx + 1) if summary_idx is not None else end
    new = slides_now[:before_data] + head_part + slides_now[before_data:before_summary] + mid_part + slides_now[before_summary:after_summary] + tail_part + slides_now[after_summary:]
    o = outline.model_copy(deep=True)
    o.slides = new
    # the cover says where the text beside the data comes from
    docs = list(dict.fromkeys(x.get("page") for x in res.sources or [] if x.get("page")))
    line = (f"Слайды с графиками — по файлам с данными; остальные агент написал по базе знаний «{kb.name}»"
            + (f" (документы {', '.join('«' + d + '»' for d in docs[:5])}{' и другие' if len(docs) > 5 else ''})" if docs else "")
            + ". Источник каждого факта — в заметках слайда. Проверьте факты перед выступлением.")
    if o.slides:
        o.slides[0].notes = f"{o.slides[0].notes}\n\n{line}".strip()
    o.agent_log = list(o.agent_log) + [f"База знаний: {len(made)} слайд(а) по документам — " + "; ".join(f"«{s.headline}»" for _, s in made[:6])]
    out.outline = o
    out.log.append(o.agent_log[-1])
    if progress is not None:
        say_designs(o, progress)
    return out


def say_designs(outline: DeckOutline, progress: Callable[[dict], None]) -> None:
    """The designer's line for every slide of the joined deck (the build's storyboard draws the deck from them: the
    data story said its own slides under their old numbers — the base's slides moved them): «Заголовок» — its form,
    whose it is."""
    try:
        from verstka.planning.agent import form_ru
    except Exception:  # noqa: BLE001 - the lines are a nicety
        return
    for pos, s in enumerate(outline.slides, 1):
        if s.kind.value == "title":
            text = f"Обложка «{s.headline}»"
        else:
            how = ("по данным файла" if s.data is not None else "из выводов данных" if s.id in ("summary", "key-figures")
                   else "по базе знаний" if s.id.startswith("kb-") else "из текста")
            text = f"«{s.headline}» {how} — {form_ru(s)}"
        try:
            progress({"type": "agent", "step": "designer", "message": text, "slide": pos, "variant": None, "share": 0.36})
        except Exception:  # noqa: BLE001 - a listener never stops the deck
            log.debug("designer line not said", exc_info=True)


__all__ = ["KbPart", "add_knowledge", "item_covered", "outline_slide"]
