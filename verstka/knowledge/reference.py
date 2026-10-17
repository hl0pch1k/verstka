"""The knowledge base as the writer's reference — the way the topic's Wikipedia article is one
(verstka/planning/reference.py), and when the base has the topic, its main source of facts.

- `cut(query)`: what the planner reads — the fragments the request finds first, then every document's opening, each
  under its document's and section's name;
- `relevant(query)`: the fragments for one slide (the slide writer) or one batch of statements (the fact check), each
  with its label «[«Отчёт Q3», раздел «Выручка», стр. 2]»;
- `unsupported(statement)`: the figures of a statement no document of the base states (the statement then goes:
  figures are never invented);
- `source_of(statement)`: the fragment a statement comes from — its document, place and link — for the slide's notes
  and «Почему так»."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from verstka.knowledge.index import Fragment, Search
from verstka.knowledge.store import KnowledgeBase
from verstka.knowledge.text import figures, tokens

MIN_SHARED = 2  # content words a statement shares with its source fragment (or one figure and one word)
SMALL_INT = 10
DERIVED_FRAGMENTS = 1  # the statement's top fragments whose figures may give its share, change or ratio  # «три филиала» in a document is «3 филиала» on a slide: integers up to this are not checked


@dataclass
class KbSource:
    doc: str
    title: str
    name: str
    url: Optional[str]
    place: str
    fragment: str
    text: str

    def label(self) -> str:
        return f"«{self.title}»" + (f", {self.place}" if self.place else "")

    def to_json(self) -> dict:
        return {"doc": self.doc, "title": self.title, "name": self.name, "url": self.url, "place": self.place, "fragment": self.fragment}


class KbReference:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.docs = {str(d.get("id")): d for d in kb.docs}
        self.frags: list[Fragment] = kb.fragments()
        self.search = Search(self.frags)
        self._figs: Optional[set[str]] = None

    @property
    def empty(self) -> bool:
        return not self.frags

    @property
    def name(self) -> str:
        return str(self.kb.meta().get("name") or "База знаний")

    def title_of(self, doc_id: str) -> str:
        d = self.docs.get(doc_id) or {}
        return str(d.get("title") or d.get("name") or "документ")

    def label(self, f: Fragment) -> str:
        place = f.place()
        return f"«{self.title_of(f.doc)}»" + (f", {place}" if place else "")

    def doc_titles(self) -> list[str]:
        return [self.title_of(k) for k in self.docs]

    # ---------------------------------------------------------------- what the writer reads

    def relevance(self, query: str) -> float:
        """How well the base knows the request: the best fragment's score (0 — nothing about it)."""
        hits = self.search.top(query, 1)
        return hits[0][1] if hits else 0.0

    def cut(self, query: str, limit: int = 10000) -> str:
        """The planner's excerpt: the fragments the request finds (best first), then every document's opening and its
        other fragments in order, until `limit` characters — grouped by document in the documents' order."""
        picked: list[Fragment] = []
        seen: set[str] = set()
        size = 0

        def take(f: Fragment) -> bool:
            nonlocal size
            if f.id in seen:
                return True
            if size + len(f.text) + 80 > limit:
                return False
            seen.add(f.id)
            picked.append(f)
            size += len(f.text) + 80
            return True

        for f, _ in self.search.top(query, 40):
            take(f)
        by_doc: dict[str, list[Fragment]] = {}
        for f in self.frags:
            by_doc.setdefault(f.doc, []).append(f)
        # every document opens the excerpt with its first fragments: a request in other words still sees the base
        depth = 0
        while size < limit and any(depth < len(v) for v in by_doc.values()):
            for fl in by_doc.values():
                if depth < len(fl):
                    take(fl[depth])
            depth += 1
        return self._render(picked)

    def relevant(self, query: str, limit: int, k: int = 12) -> str:
        """The fragments for one slide or one check: the best `k` under `limit` characters, each with its label."""
        out: list[Fragment] = []
        size = 0
        for f, _ in self.search.top(query, k):
            if size + len(f.text) > limit and out:
                continue
            out.append(f)
            size += len(f.text) + 60
        return self._render(out, labels=True)

    def _render(self, frags: list[Fragment], labels: bool = False) -> str:
        order = {k: i for i, k in enumerate(self.docs)}
        frags = sorted(frags, key=lambda f: (order.get(f.doc, 99), f.n))
        out: list[str] = []
        doc = None
        sec: list[str] = []
        for f in frags:
            if labels:
                out.append(f"[{self.label(f)}]\n{f.text}")
                continue
            if f.doc != doc:
                doc, sec = f.doc, []
                out.append(f"# {self.title_of(f.doc)}")
            if f.section and f.section != sec:
                sec = f.section
                out.append(f"## {f.section[-1]}" + (f" (стр. {f.page})" if f.page else ""))
            out.append(f.text)
        return "\n\n".join(out).strip()

    def full_texts(self) -> list[str]:
        return [f.text for f in self.frags]

    # ---------------------------------------------------------------- checks and sources

    def all_figures(self) -> set[str]:
        if self._figs is None:
            figs: set[str] = set()
            for f in self.frags:
                figs |= figures(f.text)
            self._figs = figs
        return self._figs

    def _derived(self, statement: str) -> set[str]:
        """What the figures of the fragments the statement is about give by plain arithmetic, rounded as a slide writes
        it: a share (a / b · 100 — «610 из 1 240 — 49,2 %»), a change (a / b − 1 — «с 301 до 412 — +37 %»), a ratio
        («в 1,4 раза»). Only the statement's own top fragments are paired — a figure is never «derivable» from the
        whole base."""
        vals: set[float] = set()
        for f, _ in self.search.top(statement, DERIVED_FRAGMENTS):
            for n in figures(f.text):
                try:
                    v = float(n)
                except ValueError:
                    continue
                if v > 0 and not (1900 <= v <= 2100 and v == int(v)):
                    vals.add(v)
        out: set[str] = set()
        xs = sorted(vals)
        for a in xs:
            for b in xs:
                if a == b:
                    continue
                for x in (a / b * 100, (a - b) / b * 100, a / b):
                    out.add(str(round(abs(x))))
                    out.add(f"{round(abs(x), 1):g}")
        return out

    def unsupported(self, statement: str, given: str = "") -> set[str]:
        """The figures of `statement` that no document of the base states (nor the person's own request `given`), nor
        the arithmetic of its own fragments gives (a share, a change, a ratio)."""
        known = self.all_figures() | figures(given)
        out = set()
        for n in figures(statement):
            if n in known:
                continue
            if re.fullmatch(r"\d+", n) and int(n) <= SMALL_INT:
                continue
            out.add(n)
        if out and re.search(r"%|процент|раз(?:а)?(?![а-яё])", statement):
            out -= self._derived(statement)
        return out

    def source_of(self, statement: str) -> Optional[KbSource]:
        hits = self.search.top(statement, 3)
        if not hits:
            return None
        st = set(tokens(statement))
        sf = figures(statement)
        best = None
        for f, sc in hits:
            shared = st & set(tokens(f.text))
            words = {t for t in shared if not t[0].isdigit()}
            figs = sf & figures(f.text)
            ok = len(words) >= MIN_SHARED or (figs and len(words) >= 1)
            if ok and (best is None or sc > best[1]):
                best = (f, sc)
        if best is None:
            return None
        f = best[0]
        d = self.docs.get(f.doc) or {}
        return KbSource(doc=f.doc, title=self.title_of(f.doc), name=str(d.get("name") or ""), url=d.get("url"), place=f.place(), fragment=f.id, text=f.text)


def sources_line(sources: list[KbSource], limit: int = 4) -> str:
    """«Источники: «Отчёт Q3», раздел «Выручка», стр. 2; «Стратегия 2027», раздел «Рынки».» — every document and
    place once, in the order the slide states them."""
    seen: list[str] = []
    for s in sources:
        lab = s.label() + (f" ({s.url})" if s.url else "")
        if lab not in seen:
            seen.append(lab)
    if not seen:
        return ""
    more = len(seen) - limit
    shown = "; ".join(seen[:limit]) + (f" и ещё {more}" if more > 0 else "")
    return ("Источник: " if len(seen) == 1 else "Источники: ") + shown + "."


__all__ = ["KbReference", "KbSource", "sources_line"]
