"""A plan + data files (final polish M, round 2): the experts' typical input — «примерная структура + данные». The data
story (verstka/data/story.py) draws every file's chart with its checked conclusion; this module puts its slides in the
order of the author's plan:

- the plan's items (planning/plan_form.py: a numbered list, bullets, the lines of a letter) are the deck's order;
- a data slide stands on the item that speaks of it — the most words in common with its file name, its headline, its
  measures and the goal the analyst read («Как выросла выручка — покажи на графике по месяцам» ↔ «Выручка по
  месяцам.csv»); the key-figures slide of the files stays first (it says why to listen);
- an item no file shows, with words of its own («Что просим: утвердить найм 12 менеджеров …»), is a slide of the
  author's text laid out as written (planning/agent.py without a model: its table, its asks taken as its form); a bare
  item («Что думают клиенты») gets no slide of words it does not have — the knowledge base writes it when there is one;
- the story's summary closes the data part; the plan's closing item that asks for a decision comes last;
- the context lines that only repeated the plan's items go; the cover is the plan's title.

The plan's text slides are «data-plan-N»: verstka/knowledge/with_data.py takes slides whose id starts with «data-» as
the ones that already show an item, so the base writes only for the items nobody shows (no slide twice). Nothing of the
data slides (charts, conclusions, their checks — verstka/data/verify.py) is changed: only their place.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from verstka.planning import heuristics as H
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline, OutlineSlide

log = logging.getLogger(__name__)

# the words of an item that ask the designer, not name what it is about
_ASK_WORDS = {"покаж", "график", "диагр", "сравн", "нужна", "нужен", "сдела", "добав", "табли", "слайд", "отраз", "нарис",
              "какие", "какой", "какая", "откуд", "сколь", "почем", "главн", "основ", "котор", "через", "после", "перед"}
_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.I)


def _stems(text: str) -> set[str]:
    out = set()
    for w in _WORD_RE.findall((text or "").lower().replace("ё", "е")):
        if w.isdigit():
            continue
        if len(w) >= 4 or (len(w) >= 3 and re.fullmatch(r"[a-z]+", w)):
            st = w[:5]
            if st not in _ASK_WORDS:
                out.add(st)
    return out


def _score(s: OutlineSlide, item: set[str]) -> int:
    """How much a data slide speaks of a plan item: its file's name and the goal the analyst read count twice, its
    headline and topic once, its columns once (a table of clients has a «регион» column, it is no slide of regions)."""
    d = s.data
    strong = [re.sub(r"\.[a-z]+$", "", d.file or "", flags=re.I)] if d is not None else []
    if d is not None and d.task is not None and d.task.goal:
        strong.append(d.task.goal)
    mid = [s.headline or "", d.plain_headline if d is not None else ""]
    ch = s.content.chart
    if ch is not None:
        mid.append(ch.title or "")
    weak = (list(d.metrics) + list(d.dimensions)) if d is not None else []
    if s.content.table is not None:
        weak += s.content.table.columns
    st, md, wk = _stems(" ".join(strong)), _stems(" ".join(mid)), _stems(" ".join(weak))
    return 2 * len(st & item) + len((md - st) & item) + (1 if (wk - st - md) & item and not (st | md) & item else 0)


def _group_of(s: OutlineSlide) -> Optional[str]:
    """The dataset a data slide belongs to (its continuation parts share it)."""
    if s.data is None:
        return None
    return s.data.dataset_id or s.data.file


def _item_text(it) -> str:
    return " ".join([it.title, *[ln for ln in it.lines if not ln.strip().startswith("|")]])


_ASK_ITEM_RE = re.compile(r"\b(?:просим|прошу|предлагаем|предлагаю|утвердить|согласовать|одобрить|выделить|запрашиваем|"
                          r"что\s+просим|следующие\s+шаги|что\s+дальше|план\s+на\s+(?:iv|4|следующ)|решение)\b", re.I)


def _own_words(it) -> bool:
    """An item says something of its own (a figure, or a sentence beyond its title) — not only a topic to show."""
    from verstka.planning.directives import split_directive

    text = " ".join(ln for ln in it.lines if not ln.strip().startswith("|"))
    rest = " ".join(r for r in (split_directive(x)[1] for x in (H.split_sentences(text) or [text])) if r)
    if any(ln.strip().startswith("|") for ln in it.lines):
        return True
    if re.search(r"\d", rest):
        return True
    extra = _stems(rest) - _stems(it.title)
    return len(extra) >= 4


def _text_slides(plan, brief_language: str = "ru") -> dict[int, list[OutlineSlide]]:
    """The plan's items laid out as written by the rules (planning/agent.py with no model): item index → its slides."""
    from verstka.planning.agent import run_agent
    from verstka.planning.strategies import load_strategies
    from verstka.schemas.outline import Brief

    st = load_strategies()["structured"]
    res = run_agent(Brief(text=plan.text, language=brief_language or "ru"), None, [st])
    out: dict[int, list[OutlineSlide]] = {}
    if res is None or "structured" not in res.outlines:
        return out
    for s in res.outlines["structured"].slides:
        k = (s.spec_ref or 0) - 2  # «Слайд 1» is the cover, item k is «Слайд k + 2»
        if 0 <= k < len(plan.items) and s.kind != PatternKind.title:
            out.setdefault(k, []).append(s)
    return out


def follow_plan(outline: DeckOutline, brief_text: str, *, slide_count: Optional[int] = None) -> list[str]:
    """Puts the data story's slides in the order of the author's plan (see the module); what it did, in Russian (the
    build's log). Leaves the outline as it is when the text is no plan or the plan does not speak of the data."""
    from verstka.planning.plan_form import as_slides

    plan = as_slides(brief_text or "")
    if plan is None or len(plan.items) < 2:
        return []
    slides = list(outline.slides)
    groups: dict[str, list[OutlineSlide]] = {}
    for s in slides:
        g = _group_of(s)
        if g is not None:
            groups.setdefault(g, []).append(s)
    if not groups:
        return []
    item_words = [_stems(_item_text(it)) for it in plan.items]
    # opening: the files' key figures (a «kpi» dataset the story put first) stay first — the deck says why to listen
    opening = [g for g, ss in groups.items() if ss[0].data.task is not None and ss[0].data.task.task == "kpi" and slides.index(ss[0]) == min(slides.index(x[0]) for x in groups.values())]
    scored = []
    for g, ss in groups.items():
        if g in opening:
            continue
        sc = [_score(ss[0], iw) for iw in item_words]
        scored.append((max(sc), g, sc))
    at: dict[str, int] = {}
    taken: dict[int, int] = {}
    for best, g, sc in sorted(scored, key=lambda x: -x[0]):
        if best < 1:
            continue
        cands = [k for k, v in enumerate(sc) if v == best]
        k = next((c for c in cands if c not in taken), cands[0])
        at[g] = k
        taken[k] = taken.get(k, 0) + 1
    if len(set(at.values())) < min(2, len(plan.items)):
        return []  # the plan does not speak of the data: the story's own order stays
    said: list[str] = []
    closing = len(plan.items) - 1 if _ASK_ITEM_RE.search(_item_text(plan.items[-1])) and (len(plan.items) - 1) not in taken else None
    texts_for = [k for k in range(len(plan.items)) if k not in taken and _own_words(plan.items[k])]
    text_slides = _text_slides(plan) if texts_for else {}
    title = next((s for s in slides if s.kind == PatternKind.title), None)
    context = [s for s in slides if s.id.startswith("context")]
    summary = [s for s in slides if s.id in ("summary", "next-steps")]
    appendix_ids = {s.id for s in slides if s.data is not None and s.data.task is not None and s.data.task.task == "reference" and s.data.part[1] > 1 and s.data.part[0] > 1}
    key_figures = [s for s in slides if s.id == "key-figures"]
    used: set[str] = set()
    body: list[OutlineSlide] = []
    for g in opening:
        body.extend(groups[g])
        used.update(s.id for s in groups[g])
    body.extend(key_figures)
    used.update(s.id for s in key_figures)
    tail: list[OutlineSlide] = []
    for k, it in enumerate(plan.items):
        mine = [g for g in groups if at.get(g) == k]
        mine.sort(key=lambda g: slides.index(groups[g][0]))
        part: list[OutlineSlide] = []
        for g in mine:
            part.extend(groups[g])
        if not mine and k in text_slides and k in texts_for:
            for j, s in enumerate(text_slides[k]):
                s.id = f"data-plan-{k + 1}" + (f"-{j + 1}" if j else "")
                s.continues = None
                part.append(s)
            said.append(f"пункт плана «{it.title}» — слайд из текста автора: данных о нём в файлах нет")
        elif mine:
            said.append(f"пункт плана «{it.title}» — " + ", ".join(f"«{groups[g][0].data.file}»" for g in mine))
        elif not mine:
            said.append(f"пункт плана «{it.title}» — ни файла, ни своего текста: слайда нет")
        used.update(s.id for s in part)
        (tail if k == closing else body).extend(part)
    # the files no item speaks of: after the plan's items, before the summary (never lost)
    rest = [s for s in slides if s.data is not None and s.id not in used and s.id not in appendix_ids]
    if rest:
        said.append("файлы, о которых план не говорит, — после его пунктов: " + ", ".join(dict.fromkeys(f"«{s.data.file}»" for s in rest)))
    used.update(s.id for s in rest)
    # the context lines that only repeated the plan's items (or its title) go
    plan_words = [_stems(_item_text(it)) for it in plan.items] + [_stems(plan.title or "")]
    for s in context:
        # a line that repeats an item, or says an item is «not in the data» (the item has its slide now): most of the
        # item's words, or most of the line's, are the other's
        keep = [b for b in s.content.bullets
                if not any(w and (len(w & _stems(b)) >= max(1, 0.6 * len(w)) or len(w & _stems(b)) >= max(1, 0.6 * len(_stems(b) or {1})))
                           for w in plan_words)]
        s.content = s.content.model_copy(update={"bullets": keep})
    framed = {s.id for s in context} | {s.id for s in summary} | {s.id for s in key_figures} | appendix_ids | ({title.id} if title is not None else set())
    context = [s for s in context if s.content.bullets]
    others = [s for s in slides if s.id not in used and s.id not in framed]
    appendix = [s for s in slides if s.id in appendix_ids]
    new = ([title] if title is not None else []) + context + body + rest + others + summary + tail + appendix
    if slide_count:
        # the person's slide count: the context, then the key figures go first; the plan's own slides stay
        for drop in (context, key_figures):
            for s in list(drop):
                if len(new) <= slide_count:
                    break
                new.remove(s)
    if title is not None and plan.title:
        title.headline = plan.title
        if plan.subtitle:
            title.subtitle = plan.subtitle
    outline.slides = new
    if plan.title:
        outline.title = plan.title
    head = (f"План автора — {len(plan.items)} пунктов: слайды данных стоят на пунктах, о которых говорят, в его порядке"
            + ("; просьба — последней" if closing is not None and tail else "") + ".")
    return [head, *said]
