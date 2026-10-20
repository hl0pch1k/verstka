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


_REQUEST_LEAD_RE = re.compile(r"^(?:коротко|кратко|вкратце|в\s+двух\s+словах)?\s*(?:для\s+[^:.,]{2,40})?\s*:\s*", re.I)


def request_subject(request: str) -> str:
    """What a short request is about, without what it says to the planner: «Коротко для команды: что организаторы
    требуют на второй ступени хакатона. 6–8 слайдов.» → «что организаторы требуют на второй ступени хакатона»."""
    from verstka.planning.directives import strip_count_phrase

    t = " ".join((request or "").split())
    t = strip_count_phrase(t) or t
    t = _REQUEST_LEAD_RE.sub("", t)
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", t) if len(x.strip().split()) >= 2]
    return (sents[0] if sents else t).strip(" .")


def compose_text(kb: KbReference, topic: str, plan: Optional[list[str]] = None, slides: int = 8,
                 slides_out: Optional[list] = None) -> tuple[str, list[dict]]:
    """(the «Слайд N» text, the sources of its sentences) — empty text when the base knows nothing of the request.
    `slides_out` gets each slide as data ({"n", "title", "points", "table": {"header", "rows"} | None}) — the
    knowledge base's slides of a data deck are made of these (verstka/knowledge/with_data.py)."""
    used: set[str] = set()
    topic = request_subject(topic) or topic  # (the deck's size and «Коротко для команды:» are no title and no query)
    deck_title = topic.strip().rstrip(".")[:120]
    out = ["Слайд 1. Титульный", f"Название: «{deck_title[:1].upper() + deck_title[1:]}»."]
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
    if not plan and n - 2 < max(3, slides - 2):
        # a bare request the base answers with few sections: the base's best fragments, in the documents' order, as one
        # document digested by the rules (planning/digest.py) — a slide per part, its best sentence its title
        got = _digest_text(kb, topic, deck_title, slides)
        if got is not None and got[0].count("\nСлайд ") > n - 2:
            return got
    return "\n".join(out) + "\n", sources


def _digest_text(kb: KbReference, topic: str, title: str, slides: int) -> Optional[tuple[str, list[dict]]]:
    from verstka.planning import digest as DG

    hits = [f for f, _ in kb.search.top(topic, 40, min_score=MIN_SCORE) if not f.table]
    if not hits:
        return None
    hits.sort(key=lambda f: (f.doc, f.n))
    parts: list[str] = [f"# {title}"]
    last = None
    for f in hits:
        sec = f.section[-1] if f.section else kb.title_of(f.doc)
        if sec != last:
            parts += ["", f"## {sec}"]
            last = sec
        parts += ["", " ".join(_sentences(f.text))]
    d = DG.digest_by_rules("\n".join(parts), slides, title_hint=title[:1].upper() + title[1:])
    if d is None:
        return None
    text = d.text()
    sources: list[dict] = []
    for k, s in enumerate(d.slides, 2):
        for p in s.points:
            src = kb.source_of(p)
            if src is not None:
                sources.append({"slide": k, "id": f"s{k}", "text": p, "page": src.title, "url": src.url or "", "sentence": f"{src.place}: {src.text[:400]}",
                                "doc": src.doc, "place": src.place, "fragment": src.fragment})
    return text, sources


__all__ = ["compose_text", "request_subject"]
