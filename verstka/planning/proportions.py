"""Proportions told on a slide are checked as strictly as any figure (final polish M, round 3).

The grounding (planning/grounding.py) lets small whole numbers pass — «три этапа», «за пять месяцев» are counts read
off the brief. A proportion is not a count: «в 1 из 5 пиковых дней» told for the brief's «в 6 случаях из 30» changes
what is counted (nights, not peak days) though 6/30 = 1/5. The rules:

- «N из M» keeps the author's own pair: the brief says those two figures in one sentence, N before «из M»;
- «каждый N-й», «в N раз», «вдвое / втрое …», «половина / треть / четверть / две трети / три четверти», a percentage —
  said in the brief (the same words, or the same figure), or counted from two figures of one sentence of the brief
  (their ratio, or their share, at the precision the slide states);
- otherwise the line goes back to the author's words: the brief's clause with the most words of the line and a figure
  of its own (a heading, a conclusion line), or the line goes (a line among others).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from verstka.planning import heuristics as H

_NUM = r"\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_OF_RE = re.compile(rf"(?<![\d,.])(?P<n>{_NUM})\s+(?:[а-яё]+\s+){{0,3}}?из\s+(?P<m>{_NUM})(?![\d])", re.I)
_EACH_WORDS = {"второй": 2, "второе": 2, "вторая": 2, "третий": 3, "третье": 3, "третья": 3, "четвертый": 4, "четвёртый": 4,
               "четвертая": 4, "четвёртая": 4, "пятый": 5, "пятая": 5, "шестой": 6, "шестая": 6, "седьмой": 7, "восьмой": 8,
               "девятый": 9, "десятый": 10, "десятая": 10}
_EACH_RE = re.compile(r"\bкажд(?:ый|ая|ое|ого|ую|ой)\s+(?:(?P<n>\d+)\s*[-‑]?\s*(?:[йяоеу]|ый|ой|ая|ое|го|ю)\b|(?P<w>[а-яё]+))", re.I)
_TIMES_RE = re.compile(rf"\bв\s+(?P<n>{_NUM})\s+раза?\b", re.I)
_MULT = {"вдвое": 2.0, "втрое": 3.0, "вчетверо": 4.0, "впятеро": 5.0, "вдесятеро": 10.0}
_MULT_RE = re.compile(r"\b(?:" + "|".join(_MULT) + r")\b", re.I)
_FRAC = {"две трети": 2 / 3, "три четверти": 0.75, "половин": 0.5, "треть": 1 / 3, "четверть": 0.25}
_FRAC_RE = re.compile(r"\b(?:две\s+трети|три\s+четверти|половин\w*|трет[ьи]\b|четверт[ьи]\b)", re.I)
_PCT_RE = re.compile(rf"(?<![\d,.])(?P<n>{_NUM})\s?%")


def _num(t: str) -> float:
    return float(re.sub(r"[\s  ]", "", t).replace(",", "."))


def _decimals(t: str) -> int:
    m = re.search(r"[.,](\d+)$", t.strip())
    return len(m.group(1)) if m else 0


_STOP = {"из", "в", "во", "на", "по", "за", "и", "а", "но", "что", "это", "все", "всех"}


def _counted(of_text: str, after: str = "") -> set[str]:
    """The stems of what «N … из M …» counts: the words between N and «из», and up to two words right after M."""
    m = _OF_RE.match(of_text.strip()) or _OF_RE.search(of_text)
    words = []
    if m:
        mid = of_text[m.start():m.end()]
        words += [w for w in re.findall(r"[а-яёa-z]+", re.sub(r"(?i)\bиз\b.*$", "", mid))]
    words += re.findall(r"[а-яёa-z]+", (after or "").strip().split(".")[0], re.I)[:2]
    return {w.lower().replace("ё", "е")[:4] for w in words if w.lower() not in _STOP and len(w) >= 3}


@dataclass
class Claim:
    kind: str  # «of», «each», «times», «mult», «frac», «pct»
    text: str  # the words as the slide writes them
    value: float  # the proportion (a share for of/each/frac/pct, a ratio for times/mult)
    tol: float
    pair: Optional[tuple[float, float]] = None  # «N из M»
    after: str = ""  # the words after «N из M» on the slide (what it counts)


def claims(text: str) -> list[Claim]:
    """The proportions a line states."""
    out: list[Claim] = []
    t = " ".join((text or "").split())
    for m in _OF_RE.finditer(t):
        n, mm = _num(m.group("n")), _num(m.group("m"))
        if mm > 0 and n <= mm:
            out.append(Claim("of", m.group(0), n / mm, 0.0, (n, mm), t[m.end():]))
    for m in _EACH_RE.finditer(t):
        k = int(m.group("n")) if m.group("n") else _EACH_WORDS.get((m.group("w") or "").lower().replace("ё", "е"))
        if k and k >= 2:
            out.append(Claim("each", m.group(0), 1 / k, 0.5 / k / k + 0.01))
    for m in _TIMES_RE.finditer(t):
        v = _num(m.group("n"))
        if v > 1:
            out.append(Claim("times", m.group(0), v, 0.05 if _decimals(m.group("n")) else 0.5))
    for m in _MULT_RE.finditer(t):
        out.append(Claim("mult", m.group(0), _MULT[m.group(0).lower()], 0.25))
    for m in _FRAC_RE.finditer(t):
        w = m.group(0).lower()
        v = next(x for k, x in _FRAC.items() if w.startswith(k[:6]) or w.startswith(k))
        out.append(Claim("frac", m.group(0), v, 0.04))
    for m in _PCT_RE.finditer(t):
        v = _num(m.group("n"))
        out.append(Claim("pct", m.group(0), v / 100, (0.5 * 10 ** -_decimals(m.group("n"))) / 100 + 1e-9))
    return out


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("|"):
            out.append(line)
            continue
        out.extend(H.split_sentences(line) or [line])
    return out


def _numbers(sent: str) -> list[float]:
    vals = []
    for m in re.finditer(rf"(?<![\d,.:])({_NUM})(?![\d:])", sent):
        try:
            v = _num(m.group(1))
        except ValueError:
            continue
        if not (1900 <= v <= 2100 and float(v).is_integer()):
            vals.append(v)
    return vals


_CONSTRUCTION = {"кажд", "почт", "боле", "мене", "окол", "раза", "вдво", "втро", "полов", "трет", "четв"}


def _units(sent: str) -> dict[float, str]:
    """Each figure of a sentence → the first letters of the word right after it («%», «млн», «серв»)."""
    out: dict[float, str] = {}
    for m in re.finditer(rf"(?<![\d,.:])({_NUM})(?![\d:])\s*(%|[а-яёa-z]+)?", sent, re.I):
        try:
            v = _num(m.group(1))
        except ValueError:
            continue
        u = (m.group(2) or "").lower()
        out.setdefault(v, "%" if u == "%" else u[:3])
    return out


def supported(c: Claim, brief_text: str, line: str = "") -> bool:
    """The brief says the proportion, or two figures of one of its sentences (of the same measure, in a sentence about
    what the line says) or of one row of its table give it."""
    sents = _sentences(brief_text)
    low = (brief_text or "").lower().replace("ё", "е")
    if c.kind == "of":
        n, m = c.pair
        mine = _counted(c.text, c.after)
        for s in sents:
            for x in _OF_RE.finditer(s):
                if (n, m) != (_num(x.group("n")), _num(x.group("m"))):
                    continue
                theirs = _counted(x.group(0), s[x.end():])
                # what is counted stays: «6 из 30 пиковых дней» is not the brief's «6 случаях из 30»
                if not mine or not theirs or mine & theirs:
                    return True
        return False
    if c.kind in ("mult", "frac") and c.text.lower().replace("ё", "е")[:6] in low:
        return True
    if c.kind == "each" and c.text.lower().replace("ё", "е") in low:
        return True
    if c.kind == "times" and re.search(rf"\bв\s+{re.escape(c.text.split()[1])}\s+раз", brief_text or "", re.I):
        return True
    if c.kind == "pct" and any(abs(_num(x.group("n")) / 100 - c.value) <= 1e-9 for s in sents for x in _PCT_RE.finditer(s)):
        return True
    line_stems = _stems(re.sub(re.escape(c.text), " ", line or "", flags=re.I)) - _CONSTRUCTION
    for s in sents:
        table = s.startswith("|")
        # one fragment: a sentence that speaks of what the line speaks of (a word in common), or a row of a table
        if table:
            # a row of the table: its total, or the row the line names
            label = (s.strip("| ").split("|") or [""])[0]
            if not re.match(r"\s*(?:итого|всего|итог|total)\b", label, re.I) and not (line_stems & _stems(label)):
                continue
        elif not (line_stems & _stems(s)):
            continue
        units = _units(s)
        vals = [v for v in _numbers(s) if v > 0]
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                if not table and units.get(a, "") != units.get(b, ""):
                    continue  # 97% and 48 servers are no pair
                lo, hi = min(a, b), max(a, b)
                if c.kind in ("times", "mult"):
                    if abs(hi / lo - c.value) <= c.tol:
                        return True
                elif c.kind in ("frac", "each", "pct"):
                    if abs(lo / hi - c.value) <= c.tol or (c.kind == "pct" and min(abs((hi - lo) / lo - c.value), abs((hi - lo) / hi - c.value)) <= c.tol):
                        return True
    return False


_WORD_RE = re.compile(r"[а-яёa-z]{4,}", re.I)


def _stems(text: str) -> set[str]:
    return {w.lower().replace("ё", "е")[:5] for w in _WORD_RE.findall(text or "")}


def authors_words(line: str, brief_text: str) -> Optional[str]:
    """The brief's clause that says most of what the line says, with a figure of its own («ночные расчёты не успевают к
    утру в 6 случаях из 30»)."""
    want = _stems(line)
    best, score = None, 0
    for s in _sentences(brief_text):
        if s.startswith("|"):
            continue
        for cl in re.split(r",\s+(?:из-за\s+чего|поэтому|а|но|и)\s+|;\s+|:\s+", H.strip_end(s)):
            if not re.search(r"\d", cl) or len(cl.split()) > 16:
                continue
            sc = len(want & _stems(cl))
            if sc > score:
                best, score = cl, sc
    if best is None or score < 2:
        return None
    best = re.sub(r"^(?:из-за\s+чего|поэтому|а|но|и)\s+", "", best.strip(), flags=re.I)
    return H.cap_first(best)


def check_slide(s, brief_text: str) -> list[str]:
    """Each proportion on the slide the brief does not support goes back to the author's words (see the module)."""
    said: list[str] = []
    c = s.content

    def bad(text: Optional[str]) -> list[Claim]:
        return [x for x in claims(text or "") if not supported(x, brief_text, text or "")]

    for field in ("headline", "subtitle", "takeaway"):
        text = getattr(s, field)
        wrong = bad(text)
        if not wrong:
            continue
        new = authors_words(text, brief_text)
        if new and not bad(new):
            setattr(s, field, new)
            said.append(f"{field} «{text[:60]}»: «{wrong[0].text}» is not the brief's — the author's words «{new[:60]}»")
        elif field != "headline":
            setattr(s, field, None)
            said.append(f"{field} «{text[:60]}»: «{wrong[0].text}» is not the brief's — dropped")
        elif s.section:
            setattr(s, field, s.section)
            said.append(f"headline «{text[:60]}»: «{wrong[0].text}» is not the brief's — the slide's topic")
    for name in ("bullets", "paragraphs"):
        lines = getattr(c, name)
        keep = []
        for ln in lines:
            wrong = bad(ln)
            if not wrong:
                keep.append(ln)
                continue
            new = authors_words(ln, brief_text)
            if new and not bad(new):
                keep.append(new)
                said.append(f"line «{ln[:60]}»: «{wrong[0].text}» → the author's words «{new[:60]}»")
            else:
                said.append(f"line «{ln[:60]}»: «{wrong[0].text}» is not the brief's — dropped")
        if keep or not lines:
            setattr(c, name, keep)
    for it in [*c.items, *c.columns]:
        if bad(it.text):
            new = authors_words(it.text, brief_text)
            said.append(f"item «{it.title[:40]}»: «{bad(it.text)[0].text}» is not the brief's")
            it.text = new if new and not bad(new) else ""
    keep_n = []
    for n in c.numbers:
        if bad(n.value) or bad(n.label):
            said.append(f"figure «{n.value} — {n.label[:40]}»: a proportion the brief does not give — dropped")
            continue
        keep_n.append(n)
    if keep_n or not c.numbers:
        c.numbers = keep_n
    return said


def check_outline(o, brief_text: str) -> list[str]:
    out: list[str] = []
    if not (brief_text or "").strip():
        return out
    for s in o.slides:
        try:
            out.extend(f"slide {s.id}: {x}" for x in check_slide(s, brief_text))
        except Exception:  # noqa: BLE001 - the slide as planned
            continue
    return out
