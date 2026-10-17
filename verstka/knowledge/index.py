"""Fragments of the knowledge base and the local search over them (BM25 over Russian stems — nothing leaves the
machine, no embeddings).

A fragment is a piece of one document a fact can be pointed at: its document, its section (the headings above it),
its page (PDF) and its paragraph number — «Отчёт Q3.docx», раздел «Выручка», стр. 2, абз. 5."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from verstka.ingest.documents import DocumentText
from verstka.knowledge.text import figures, tokens

FRAGMENT_CHARS = 700  # a fragment grows paragraph by paragraph up to about this many characters
FRAGMENT_MAX = 1400  # a longer paragraph is cut at its sentences
TABLE_ROWS = 12  # rows of a table per fragment (the header repeated)


@dataclass
class Fragment:
    id: str  # «<doc id>:<n>»
    doc: str
    n: int
    text: str
    section: list[str] = field(default_factory=list)
    page: Optional[int] = None
    para: Optional[int] = None  # the first paragraph's number in the document (1-based)
    table: bool = False
    tokens: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Fragment":
        return cls(**{k: d.get(k) for k in ("id", "doc", "n", "text", "section", "page", "para", "table", "tokens") if k in d})

    def place(self) -> str:
        """Where in its document: «раздел «Выручка», стр. 2, абз. 5»."""
        parts: list[str] = []
        if self.section:
            parts.append(f"раздел «{self.section[-1]}»")
        if self.page:
            parts.append(f"стр. {self.page}")
        if self.table:
            parts.append("таблица")
        elif self.para:
            parts.append(f"абз. {self.para}")
        return ", ".join(parts)


def _sentences(text: str, limit: int) -> list[str]:
    parts = re.split(r"(?<=[.!?…»])\s+(?=[«A-ZА-ЯЁ0-9])", text)
    out: list[str] = []
    cur = ""
    for p in parts:
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def fragments_of(doc: DocumentText, doc_id: str) -> list[Fragment]:
    """The document cut into fragments: a heading starts a new one, paragraphs and list items gather up to
    FRAGMENT_CHARS, a table is a fragment of its own (its rows in groups of TABLE_ROWS)."""
    out: list[Fragment] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_page: Optional[int] = None
    buf_para: Optional[int] = None
    para_no = 0

    def section() -> list[str]:
        return [t for _, t in stack]

    def add(text: str, page: Optional[int], para: Optional[int], table: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        n = len(out) + 1
        head = " ".join(section()[-2:])
        out.append(Fragment(f"{doc_id}:{n}", doc_id, n, text, section(), page, para, table, tokens(f"{doc.title} {head} {head} {text}")))

    def flush() -> None:
        nonlocal buf, buf_page, buf_para
        if buf:
            add("\n".join(buf), buf_page, buf_para)
        buf, buf_page, buf_para = [], None, None

    blocks = doc.blocks
    for i, b in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if b.kind == "para" and nxt is not None and nxt.kind == "table" and nxt.table is not None and nxt.table.caption \
                and b.text.rstrip(":").strip() == nxt.table.caption.strip():
            continue  # the table's caption: it goes with the table
        if b.kind == "heading":
            flush()
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, b.text))
            continue
        if b.kind == "table" and b.table is not None:
            flush()
            rows = b.table.rows
            if not rows:
                continue
            head, body = rows[0], rows[1:] or []
            cap = f"Таблица «{b.table.caption}»" if b.table.caption else "Таблица"
            for k in range(0, max(1, len(body)), TABLE_ROWS):
                chunk = [head] + body[k:k + TABLE_ROWS]
                lines = [" | ".join(c for c in r) for r in chunk]
                add(f"{cap}:\n" + "\n".join(lines), b.page, None, table=True)
            continue
        para_no += 1
        text = ("— " if b.kind == "item" else "") + b.text
        pieces = _sentences(text, FRAGMENT_MAX) if len(text) > FRAGMENT_MAX else [text]
        for piece in pieces:
            if buf and (sum(len(x) for x in buf) + len(piece) > FRAGMENT_CHARS or (buf_page is not None and b.page is not None and b.page != buf_page)):
                flush()
            if not buf:
                buf_page, buf_para = b.page, para_no
            buf.append(piece)
    flush()
    return out


class Bm25:
    """Okapi BM25 over the fragments' tokens."""

    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.72) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: Iterable[str]) -> list[float]:
        q = Counter(query)
        out = [0.0] * len(self.tf)
        for i, tf in enumerate(self.tf):
            s = 0.0
            denom_len = self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1.0))
            for t, qn in q.items():
                f = tf.get(t)
                if not f:
                    continue
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + denom_len) * (1 + 0.2 * (qn - 1))
            out[i] = s
        return out


class Search:
    """The search over a set of fragments: `top(query, k)` — the best fragments with their scores (only those that
    share a word with the query)."""

    def __init__(self, frags: list[Fragment]) -> None:
        self.frags = frags
        self.bm = Bm25([f.tokens or tokens(f.text) for f in frags])

    def top(self, query: str, k: int = 8, min_score: float = 0.0) -> list[tuple[Fragment, float]]:
        q = tokens(query)
        if not q or not self.frags:
            return []
        sc = self.bm.scores(q)
        figs = figures(query)
        if figs:
            for i, f in enumerate(self.frags):
                shared = figs & figures(f.text)
                if shared:
                    sc[i] += 1.5 * len(shared)
        order = sorted(range(len(sc)), key=lambda i: -sc[i])
        return [(self.frags[i], sc[i]) for i in order[:k] if sc[i] > min_score]


__all__ = ["Bm25", "FRAGMENT_CHARS", "Fragment", "Search", "fragments_of"]
