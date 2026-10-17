"""The deck's text from the knowledge base without a model: a short request (or a plan) and the person's documents →
«Слайд N. …» text built of the documents' own sentences, every slide with the fragments it comes from.

With a model the writer (planning/topic_writer.py) writes the deck from the base; without one (the switch «Модель пишет
тексты» off, no model configured) the base is still used: each plan item — or, with a bare request, each section of
the documents the request finds best — becomes a slide of the sentences of its best fragments, as written there (no
word changed, so every figure is the documents' own), a table fragment as its table. The result is a
planning.writer.WriterResult like the writer's: the pipeline lays the text out as a person's own «Слайд N» text, the
slides' notes name the sources (generate._kb_notes)."""

from __future__ import annotations

import re
from typing import Optional

from verstka.knowledge.index import Fragment
from verstka.knowledge.reference import KbReference
from verstka.knowledge.text import tokens

MAX_SENTENCES = 4
MIN_SCORE = 0.5


def _sentences(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("—-• ").strip()
        if not line:
            continue
        for s in re.split(r"(?<=[.!?…])\s+(?=[«A-ZА-ЯЁ0-9])", line):
            s = s.strip()
            if len(s) >= 12:
                out.append(s if s.endswith((".", "!", "?", "…", ":")) else s + ".")
    return out


def _table(f: Fragment) -> list[str]:
    lines = [ln for ln in f.text.splitlines()[1:] if "|" in ln]
    if len(lines) < 2:
        return []
    rows = [[c.strip() for c in ln.split("|")] for ln in lines]
    w = max(len(r) for r in rows)
    out = ["| " + " | ".join(rows[0] + [""] * (w - len(rows[0]))) + " |", "|" + "---|" * w]
    out += ["| " + " | ".join(r + [""] * (w - len(r))) + " |" for r in rows[1:]]
    caption = f.text.splitlines()[0].strip().rstrip(":")
    m = re.match(r"Таблица «(.+)»", caption)
    return ([f"{m.group(1)}:"] if m else []) + out


def _slide(title: str, frags: list[Fragment], used: set[str]) -> tuple[list[str], list[Fragment]]:
    """The slide's sentences (its fragments' own, at most MAX_SENTENCES, none twice in the deck), then one table — only
    the slide's best fragment may be a table (a table found third is about something else)."""
    body: list[str] = []
    took: list[Fragment] = []
    table: list[str] = []
    for k, f in enumerate(frags):
        if f.table:
            if k == 0 and not table and f.id not in used:
                table = _table(f)
                if table:
                    used.add(f.id)
                    took.append(f)
            continue
        for s in _sentences(f.text):
            key = " ".join(tokens(s))
            if key in used or len([x for x in body if not x.startswith("|")]) >= MAX_SENTENCES:
                continue
            used.add(key)
            body.append(s)
            if f not in took:
                took.append(f)
    return body + table, took


def _clean_item(item: str) -> str:
    """A plan item as a slide title: its own words, without the author's ask after a dash («— покажи на графике»)."""
    head = re.split(r"\s+[—–-]\s+", item, maxsplit=1)[0]
    return head.strip(" .:;").capitalize()[:120] if head else item[:120]


def compose_text(kb: KbReference, topic: str, plan: Optional[list[str]] = None, slides: int = 8,
                 slides_out: Optional[list] = None) -> tuple[str, list[dict]]:
    """(the «Слайд N» text, the sources of its sentences) — empty text when the base knows nothing of the request.
    `slides_out` gets each slide as data ({"n", "title", "points", "table": {"header", "rows"} | None}) — the
    knowledge base's slides of a data deck are made of these (verstka/knowledge/with_data.py)."""
    used: set[str] = set()
    out = ["Слайд 1. Титульный", f"Название: «{topic.strip().rstrip('.')[:120]}»."]
    sources: list[dict] = []
    n = 2
    if plan:
        topics = [(_clean_item(it), it) for it in plan]
    else:
        # the request's best fragments, one slide per section of a document (in the documents' order of relevance)
        hits = kb.search.top(topic, 60, min_score=MIN_SCORE)
        seen: list[tuple[str, str]] = []
        for f, _ in hits:
            key = (f.doc, f.section[-1] if f.section else kb.title_of(f.doc))
            if key[1] == kb.title_of(f.doc) and len(f.section) <= 1 and any(x.doc == f.doc and x.section != f.section for x, _ in hits):
                continue  # the document's own title over its opening lines: its sections say more
            if key not in seen:
                seen.append(key)
        topics = [(sec, f"{sec} {topic}") for _, sec in seen[: max(1, slides - 1)]]
    for title, query in topics:
        frags = [f for f, sc in kb.search.top(query, 3, min_score=MIN_SCORE)]
        if not plan:
            frags = [f for f in frags if (f.section[-1] if f.section else kb.title_of(f.doc)) == title] or frags
        body, took = _slide(title, frags, used)
        if not body:
            continue
        out += ["", f"Слайд {n}. {title}", *body]
        if slides_out is not None:
            rows = [[c.strip() for c in ln.strip("| ").split(" | ")] for ln in body if ln.startswith("|") and not ln.startswith("|---")]
            slides_out.append({"n": n, "title": title, "points": [x for x in body if not x.startswith("|") and not x.endswith(":")],
                               "table": {"header": rows[0], "rows": rows[1:]} if len(rows) >= 2 else None})
        for f in took:
            if f.table:
                d = kb.docs.get(f.doc) or {}
                sources.append({"slide": n, "id": f"s{n}t", "text": f.text, "page": kb.title_of(f.doc), "url": d.get("url") or "",
                                "sentence": f"{f.place()}: {f.text[:400]}", "doc": f.doc, "place": f.place(), "fragment": f.id})
        for s in body:
            if s.startswith("|") or s.endswith(":"):
                continue
            src = kb.source_of(s)
            if src is not None:
                sources.append({"slide": n, "id": f"s{n}", "text": s, "page": src.title, "url": src.url or "", "sentence": f"{src.place}: {src.text[:400]}",
                                "doc": src.doc, "place": src.place, "fragment": src.fragment})
        n += 1
    if n == 2:
        return "", []
    return "\n".join(out) + "\n", sources


__all__ = ["compose_text"]
