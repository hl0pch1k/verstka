"""Real mathematical formulas on slides.

A formula is set as PowerPoint sets one inserted with «Вставка → Уравнение»: one shape, `mc:AlternateContent`, whose
Choice is a text box holding a native Office Math equation (OMML, `a14:m`) — editable in PowerPoint, typeset by its
math engine — and whose Fallback is the same box filled with a picture of the formula, for the programs that do not
read Office Math (LibreOffice — the previews and the PDF —, Google Slides, Keynote). The picture is typeset here by
ziamath (TeX's rules of math layout, the STIX Two Math font: display fractions, large integrals with their limits,
«lim» with its condition under it) and drawn by Pillow; the equation comes from the same LaTeX through MathML
(latex2mathml) — one source, two renderings.

A formula comes as LaTeX — «$\\int_a^b f(x)\\,dx = F(b) - F(a)$», what the writer writes and what a person who knows
LaTeX types — or as a plain line of Unicode — «∫ f(x) dx = F(x) + C», «S = πr²», «x^(n+1)/(n+1)» —, which is read into
LaTeX first. A slide's formula field may hold several, each with its name: «Линейность: $…$; Аддитивность: $…$»."""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
MML_NS = "http://www.w3.org/1998/Math/MathML"

MATH_FONT = "Cambria Math"  # PowerPoint's own font of equations
EMU_PT = 12700

_LOCK = threading.Lock()  # ziamath keeps global state (its configuration, its font cache)


def _m(tag: str) -> str:
    return f"{{{M_NS}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{A_NS}}}{tag}"


# ------------------------------------------------------------------ what a formula field holds


@dataclass(frozen=True)
class Formula:
    """One formula of a slide: its name or role («Линейность», «Первообразная»; may be empty), its LaTeX, the same
    formula as a line of Unicode (alt text, speaker notes, the audit's reading of the slide) and what it says in words
    («показатель степени растёт на единицу, результат делится на новый показатель»; may be empty) — a formula
    alone does not explain a topic."""

    label: str
    latex: str
    text: str
    note: str = ""


_DOLLAR_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]{2,}|\\[,;:!]|[\^_]\{")
# what makes a line of Unicode a formula of mathematics or physics, not a business equation of figures and words
_MATH_RE = re.compile(r"[∫∑∏√∞∂∇πθλμσφΔΣΩ′²³⁴ⁿ⁺⁻ₐ₀₁₂]|\b[a-zA-Z]\s*\(\s*[a-zA-Z]\s*\)|\bd[xytr]\b|\b(?:sin|cos|tg|tan|ctg|ln|log|lim|arctg|arcsin|exp)\b|\b[a-zA-Z]\s*=\s*[a-zA-Z]|\b[a-zA-Z]\^")


def _math_inside(m: re.Match) -> bool:
    """A «$…$» that holds math, not two sums of dollars («$5 млн и $3 млн»): a command or a sign of math inside, no
    words of prose, no space at its edges (TeX's own rule for inline math)."""
    inner = next(g for g in m.groups() if g is not None)
    if m.group(0).startswith(("\\(", "\\[", "$$")):
        return bool(inner.strip())
    if not inner.strip() or inner != inner.strip():
        return False
    if len(re.findall(r"[А-Яа-яЁё]{3,}", re.sub(r"\\text\{[^}]*\}", "", inner))) >= 2:
        return False
    return bool(_LATEX_CMD_RE.search(inner) or re.search(r"[\^_=<>+\-*/]|\b[a-zA-Z]\b", inner))


def math_spans(text: str) -> list[re.Match]:
    return [m for m in _DOLLAR_RE.finditer(text or "") if _math_inside(m)]


def has_latex(text: str) -> bool:
    return bool(math_spans(text)) or bool(_LATEX_CMD_RE.search(text or ""))


def is_math(text: str) -> bool:
    """A formula of symbols (mathematics, physics) — LaTeX, or Unicode with integrals, roots, exponents, functions of
    x, Greek letters, «E = mc²» — rather than a business equation of figures with their words («100 покупок × 300 ₽»)."""
    t = text or ""
    return has_latex(t) or bool(_MATH_RE.search(t))


def is_sentence(text: str) -> bool:
    """A sentence of words that may mention a symbol («Неопределённый интеграл — множество первообразных функции
    f(x)»), not a formula with a word or two in it («S = πr², где r — радиус»)."""
    return len(re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", re.sub(r"\$[^$]*\$|\\[A-Za-z]+", " ", text or ""))) >= 4


def formulas_of(text: Optional[str]) -> list[Formula]:
    """The formulas a formula field holds, each typeset-ready: «$…$» (one or several, each after its name:
    «Линейность: $…$; Аддитивность: $…$»), or one line of Unicode read into LaTeX. Empty when the field holds no
    formula of mathematics (a business equation of figures is the composer's own figure blocks) or the formula
    cannot be typeset."""
    t = (text or "").strip()
    if not t:
        return []
    out: list[Formula] = []
    if math_spans(t):
        found = math_spans(t)
        bounds = [0] + [m.end() for m in found]
        for i, m in enumerate(found):
            # between two formulas: the note of the one before (up to the last «; »), then the name of this one
            between = t[bounds[i] : m.start()]
            if i and "; " in between:
                between = between.rsplit("; ", 1)[1]
            elif i:
                between = between if not _note(between) else ""
            label = _label(between)
            tail = t[m.end() : found[i + 1].start()] if i + 1 < len(found) else t[m.end() :]
            if i + 1 < len(found):
                tail = tail.rsplit("; ", 1)[0] if "; " in tail else ""
            latex = next(g for g in m.groups() if g is not None).strip()
            if latex and typesettable(latex):
                out.append(Formula(label, latex, latex_text(latex), _note(tail)))
        return out
    if not is_math(t):
        return []
    lines = [x for x in re.split(r"\s*;\s+(?=[А-ЯЁA-Z][^:]{0,60}:)|\n+", t) if x.strip()]
    for line in lines:
        label, body = "", line.strip()
        lm = re.match(r"^([А-ЯЁа-яё][А-ЯЁа-яё\s\-—–,()«»]{1,60}?):\s+(.+)$", body)
        if lm and is_math(lm.group(2)):
            label, body = lm.group(1).strip(), lm.group(2).strip()
        note = ""
        nm = re.match(r"^(.+?)\s+[—–]\s+(.+)$", body)
        if nm and _note(nm.group(2)) and is_sentence(nm.group(2)):
            body, note = nm.group(1).strip(), _note(nm.group(2))
        latex = to_latex(body)
        if latex and typesettable(latex):
            out.append(Formula(label, latex, latex_text(latex), note))
    return out


def _note(tail: str) -> str:
    """What follows a formula in words («$…$ — показатель растёт на единицу»): its explanation, or ""."""
    s = re.sub(r"^[\s,;:.—–-]+|[\s;]+$", "", tail or "")
    s = plain_math(s)
    return s[:1].upper() + s[1:] if len(re.findall(r"[А-Яа-яЁёA-Za-z]{2,}", s)) >= 2 else ""


def _label(between: str) -> str:
    """The name before a formula: «; Линейность:» → «Линейность»."""
    s = re.sub(r"^[\s;,.—–-]+|[\s:—–-]+$", "", between or "")
    s = re.sub(r"^\d+[.)]\s*", "", s)
    return s.strip()[:80]


def to_latex(text: str) -> Optional[str]:
    """LaTeX of one formula: the inside of «$…$» as written; LaTeX without dollars as written; a line of Unicode
    read into LaTeX («∫ₐᵇ f(x) dx» → «\\int_{a}^{b} f(x)\\,dx», «x^(n+1)/(n+1)» → «\\frac{x^{n+1}}{n+1}»)."""
    t = (text or "").strip()
    if not t:
        return None
    m = _DOLLAR_RE.search(t)
    if m:
        return next(g for g in m.groups() if g is not None).strip() or None
    if _LATEX_CMD_RE.search(t):
        return t
    if not is_math(t):
        return None
    return unicode_latex(t)


# ------------------------------------------------------------------ a line of Unicode → LaTeX

_SUP = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻ", "0123456789+-=()niabcdefghjklmoprstuvwxyz"))
_SUB = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼ", "0123456789+-=()aeoxhklmnpstij"))
_SYM = {
    "−": "-", "–": "-", "×": r"\times ", "·": r"\cdot ", "⋅": r"\cdot ", "÷": r"\div ", "±": r"\pm ", "∓": r"\mp ",
    "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ", "≈": r"\approx ", "≡": r"\equiv ", "∼": r"\sim ", "→": r"\to ",
    "⇒": r"\Rightarrow ", "⇔": r"\Leftrightarrow ", "∞": r"\infty ", "∂": r"\partial ", "∇": r"\nabla ", "∈": r"\in ",
    "∉": r"\notin ", "⊂": r"\subset ", "∪": r"\cup ", "∩": r"\cap ", "∅": r"\emptyset ", "∀": r"\forall ",
    "∃": r"\exists ", "′": "'", "″": "''", "∫": r"\int ", "∬": r"\iint ", "∭": r"\iiint ", "∮": r"\oint ",
    "∑": r"\sum ", "∏": r"\prod ", "°": r"^{\circ}", "…": r"\ldots ", "∠": r"\angle ", "⊥": r"\perp ", "∥": r"\parallel ",
}
_FUNCS = ("arcsin", "arccos", "arctg", "arcctg", "arctan", "sin", "cos", "tg", "ctg", "tan", "cot", "ln", "lg", "log", "exp", "lim", "max", "min", "sh", "ch", "th")
_STD_FUNCS = {"arcsin", "arccos", "arctan", "sin", "cos", "tan", "cot", "ln", "lg", "log", "exp", "lim", "max", "min", "sh", "ch", "th"}


def unicode_latex(text: str) -> Optional[str]:
    """A formula typed in Unicode, as LaTeX: superscripts and subscripts, «^(…)», roots, fractions of whole terms
    («x^(n+1)/(n+1)»), integrals with their limits («∫[a,b]», «∫ₐᵇ»), function names, words as text."""
    s = " ".join((text or "").replace("\u00a0", " ").split()).rstrip(".")
    if not s:
        return None
    # integral limits written after the sign: «∫[a,b]», «∫_a^b»
    s = re.sub(r"([∫∬∮∑∏])\s*\[\s*([^\],;]+?)\s*[,;]\s*([^\]]+?)\s*\]", lambda m: f"{m.group(1)}_{{{m.group(2)}}}^{{{m.group(3)}}}", s)
    # super- and subscript runs
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻ]+", lambda m: "^{" + "".join(_SUP[c] for c in m.group(0)) + "}", s)
    s = re.sub(r"[₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼ]+", lambda m: "_{" + "".join(_SUB[c] for c in m.group(0)) + "}", s)
    # «^(n+1)» and «^10»: a group as one exponent
    s = _caret_groups(s)
    # words in Cyrillic: text inside the formula («где», «при»)
    s = re.sub(r"[А-Яа-яЁё]+(?:[\s,]+[А-Яа-яЁё]+)*", lambda m: r"\text{" + m.group(0) + "}", s)
    # roots: «√(…)» and «√x»
    s = _roots(s)
    for ch, cmd in _SYM.items():
        s = s.replace(ch, cmd)
    # function names
    s = re.sub(r"(?<![\\A-Za-z])(" + "|".join(_FUNCS) + r")(?![A-Za-z])", lambda m: ("\\" + m.group(1) + " ") if m.group(1) in _STD_FUNCS else (r"\operatorname{" + m.group(1) + "} "), s)
    s = _fractions(s)
    # a decimal comma stays in the number: «2,67»
    s = re.sub(r"(\d),(\d)", r"\1{,}\2", s)
    # the differential gets its thin space: «f(x) dx», «f(x)dx»
    s = re.sub(r"(?<=[)\w}])\s*(d[xytrsuvφθ])\b", r"\\,\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _caret_groups(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "^" and i + 1 < len(s) and s[i + 1] == "(":
            depth, j = 0, i + 1
            while j < len(s):
                depth += {"(": 1, ")": -1}.get(s[j], 0)
                if depth == 0:
                    break
                j += 1
            out.append("^{" + s[i + 2 : j] + "}")
            i = j + 1
            continue
        if s[i] == "^" and i + 1 < len(s) and s[i + 1] != "{":
            m = re.match(r"-?[0-9A-Za-z]+(?:\.\d+)?", s[i + 1 :])
            if m:
                out.append("^{" + m.group(0) + "}")
                i += 1 + len(m.group(0))
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _match_close(s: str, i: int, open_: str = "(", close: str = ")") -> int:
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_:
            depth += 1
        elif s[j] == close:
            depth -= 1
            if depth == 0:
                return j
    return -1


def _roots(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "√":
            j = i + 1
            while j < len(s) and s[j] == " ":
                j += 1
            if j < len(s) and s[j] == "(":
                k = _match_close(s, j)
                if k > 0:
                    out.append(r"\sqrt{" + s[j + 1 : k] + "}")
                    i = k + 1
                    continue
            m = re.match(r"[0-9A-Za-zα-ωπ]+(?:\^\{[^}]*\})?", s[j:])
            if m:
                out.append(r"\sqrt{" + m.group(0) + "}")
                i = j + len(m.group(0))
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


_ATOM_TAIL = r"(?:\^\{[^{}]*\}|_\{[^{}]*\})*"


def _fractions(s: str) -> str:
    """«a/b» of whole terms as \\frac{a}{b}: a number, a letter or a function call with its exponents, a group in
    parentheses (its parentheses dropped), a root; a slash between other things stays a slash."""
    for _ in range(8):
        m = re.search(r"/", s)
        if not m:
            break
        i = m.start()
        left = _atom_before(s, i)
        right = _atom_after(s, i + 1)
        if left is None or right is None:
            s = s[:i] + "\x00" + s[i + 1 :]
            continue
        (l0, ltxt), (r1, rtxt) = left, right
        s = s[:l0] + r"\frac{" + ltxt + "}{" + rtxt + "}" + s[r1:]
    return s.replace("\x00", "/")


def _strip_parens(t: str) -> str:
    t = t.strip()
    if t.startswith("(") and _match_close(t, 0) == len(t) - 1:
        return t[1:-1].strip()
    return t


def _atom_before(s: str, i: int) -> Optional[tuple[int, str]]:
    j = i
    while j > 0 and s[j - 1] == " ":
        j -= 1
    end = j
    # exponents and subscripts of the atom
    while j > 0 and s[j - 1] == "}":
        depth, k = 0, j - 1
        while k >= 0:
            depth += {"}": 1, "{": -1}.get(s[k], 0)
            if depth == 0:
                break
            k -= 1
        if k > 0 and s[k - 1] in "^_":
            j = k - 1
        elif k > 5 and s[:k].endswith(r"\sqrt"):
            j = k - 5
            break
        else:
            break
    if j > 0 and s[j - 1] == ")":
        depth, k = 0, j - 1
        while k >= 0:
            depth += {")": 1, "(": -1}.get(s[k], 0)
            if depth == 0:
                break
            k -= 1
        if k < 0:
            return None
        j = k
        # a function call: «f(x)», «\sin(x)»
        m = re.search(r"(?:\\[A-Za-z]+|[A-Za-z])$", s[:j])
        if m:
            j = m.start()
    elif j > 0 and re.match(r"[0-9A-Za-zα-ωπ.]", s[j - 1]):
        m = re.search(r"[0-9.]+$|[A-Za-zα-ωπ]$", s[:j])
        if not m:
            return None
        j = m.start()
    elif j == end:
        return None
    txt = s[j:end]
    return (j, _strip_parens(txt)) if txt.strip() else None


def _atom_after(s: str, i: int) -> Optional[tuple[int, str]]:
    j = i
    while j < len(s) and s[j] == " ":
        j += 1
    start = j
    if j < len(s) and s[j] == "(":
        k = _match_close(s, j)
        if k < 0:
            return None
        j = k + 1
    elif s.startswith(r"\sqrt{", j):
        k = _match_close(s, j + 5, "{", "}")
        if k < 0:
            return None
        j = k + 1
    else:
        m = re.match(r"[0-9]+(?:\.[0-9]+)?|\\[A-Za-z]+\s?[A-Za-z]?|[A-Za-zα-ωπ]", s[j:])
        if not m:
            return None
        j += len(m.group(0))
        if j < len(s) and s[j] == "(" and re.match(r"[A-Za-z]$|\\[A-Za-z]+\s?$", m.group(0)):
            k = _match_close(s, j)
            if k > 0:
                j = k + 1
    m = re.match(_ATOM_TAIL, s[j:])
    if m:
        j += len(m.group(0))
    txt = s[start:j]
    return (j, _strip_parens(txt)) if txt.strip() else None


# ------------------------------------------------------------------ LaTeX the typesetters read


def tidy(latex: str) -> str:
    """LaTeX as both typesetters read it: display commands of the same meaning, a unary minus as a sign («n ≠ −1»,
    not «n ≠ − 1»), a decimal comma inside its number."""
    s = (latex or "").strip().strip("$").strip()
    s = re.sub(r"\\(?:dfrac|tfrac|cfrac)\b", r"\\frac", s)
    s = re.sub(r"\\(?:displaystyle|textstyle|scriptstyle|limits|nolimits)\b\s*", "", s)
    s = re.sub(r"\\(?:big|Big|bigg|Bigg)[lrm]?\b\s*", "", s)
    s = s.replace(r"\dots", r"\ldots").replace(r"\tg", r"\operatorname{tg}").replace(r"\ctg", r"\operatorname{ctg}").replace(r"\arctg", r"\operatorname{arctg}")
    s = re.sub(r"(\d),(\d)", r"\1{,}\2", s)
    s = re.sub(r"\\(max|min|sup|inf)(?![A-Za-z_])\s*(?=[\\A-Za-z])", r"\\\1\\, ", s)  # never inside «\\infty»
    s = re.sub(r"(^|[=<>(\[{,]|\\(?:ne|neq|le|leq|ge|geq|approx|in|to|pm|times|cdot)\b)\s*-\s*(?=[\w\\])", lambda m: m.group(1) + " {-}", s)
    return s


@lru_cache(maxsize=512)
def typesettable(latex: str) -> bool:
    """The LaTeX reads as math for both typesetters (a broken or unsupported command is never set half-way)."""
    t = latex or ""
    depth = 0
    for ch in re.sub(r"\\[{}]", "", t):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if depth < 0:
            return False
    if depth or not t.strip():
        return False
    try:
        mml = _mathml(t)
        if any("\\" in (x or "") for x in mml.itertext()):
            return False  # a command neither typesetter knows («\\badcmd») would be printed as it is
        _layout(t, 20.0)
        return True
    except Exception:  # noqa: BLE001 - not a formula we can set: the composer sets the line as text
        return False


@lru_cache(maxsize=512)
def _mathml(latex: str) -> etree._Element:
    import latex2mathml.converter as l2m

    xml = l2m.convert(tidy(latex), display="block")
    return etree.fromstring(xml.encode("utf-8"))


# ------------------------------------------------------------------ the picture (ziamath + Pillow)


def _ziamath():
    import ziamath as zm

    zm.config.svg2 = False  # plain paths and rectangles, no <symbol>/<use>
    return zm


@lru_cache(maxsize=512)
def _layout(latex: str, size_pt: float) -> tuple[float, float, float, float, tuple]:
    """The formula typeset at a size: its box (x, y, w, h in points of the SVG) and its glyph outlines and rules."""
    with _LOCK:
        zm = _ziamath()
        svg = zm.Latex(tidy(latex), size=size_pt, margin=0).svg()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    paths = tuple(re.findall(r'<path d="([^"]+)"', svg))
    rects = []
    for r in re.findall(r"<rect ([^>]+?)/?>", svg):
        a = dict(re.findall(r'([\w-]+)="([^"]+)"', r))
        if a.get("fill", "").lower() in ("none", "transparent"):
            continue
        try:
            rects.append((float(a["x"]), float(a["y"]), float(a["width"]), float(a["height"])))
        except (KeyError, ValueError):
            continue
    return vb[0], vb[1], vb[2], vb[3], (paths, tuple(rects))


PAD = 0.06  # air around the formula, a share of its size (the picture's edge never touches a glyph)


def measure(latex: str, size_pt: float) -> tuple[float, float]:
    """The formula's box at a size, in points, with its air: what the slide reserves for it."""
    _x, _y, w, h, _ = _layout(latex, round(float(size_pt), 2))
    pad = size_pt * PAD
    return w + 2 * pad, h + 2 * pad


_NUM = r"-?\d*\.?\d+(?:e-?\d+)?"


def _subpaths(d: str) -> list[list[tuple[float, float]]]:
    toks = re.findall(r"[MLQCZHV]|" + _NUM, d, re.I)
    out: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    pos = start = (0.0, 0.0)
    i = 0
    while i < len(toks):
        c = toks[i]
        i += 1
        if c in "Mm":
            if cur:
                out.append(cur)
            pos = (float(toks[i]), float(toks[i + 1]))
            i += 2
            cur, start = [pos], pos
        elif c in "Ll":
            pos = (float(toks[i]), float(toks[i + 1]))
            i += 2
            cur.append(pos)
        elif c in "Hh":
            pos = (float(toks[i]), pos[1])
            i += 1
            cur.append(pos)
        elif c in "Vv":
            pos = (pos[0], float(toks[i]))
            i += 1
            cur.append(pos)
        elif c in "Qq":
            cx, cy, x, y = (float(v) for v in toks[i : i + 4])
            i += 4
            x0, y0 = pos
            for k in range(1, 9):
                t = k / 8
                cur.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y))
            pos = (x, y)
        elif c in "Cc":
            c1x, c1y, c2x, c2y, x, y = (float(v) for v in toks[i : i + 6])
            i += 6
            x0, y0 = pos
            for k in range(1, 11):
                t = k / 10
                u = 1 - t
                cur.append((u**3 * x0 + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t**3 * x, u**3 * y0 + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t**3 * y))
            pos = (x, y)
        elif c in "Zz":
            if cur:
                out.append(cur)
            cur, pos = [], start
        else:  # a number where a command was due: skip it
            continue
    if cur:
        out.append(cur)
    return out


@lru_cache(maxsize=256)
def picture(latex: str, size_pt: float, color: str, dpi: int = 300) -> tuple[bytes, float, float]:
    """The formula as a PNG with a transparent ground, in `color`, at `size_pt` (its box with its air, in points)."""
    from PIL import Image, ImageChops, ImageDraw

    size_pt = round(float(size_pt), 2)
    x0, y0, w, h, (paths, rects) = _layout(latex, size_pt)
    pad = size_pt * PAD
    ss = 3  # drawn three times larger, then reduced: smooth edges
    k = dpi / 72 * ss
    W, H = max(int((w + 2 * pad) * k), 1), max(int((h + 2 * pad) * k), 1)
    mask = Image.new("L", (W, H), 0)

    def px(x: float, y: float) -> tuple[float, float]:
        return (x - x0 + pad) * k, (y - y0 + pad) * k

    for d in paths:
        polys = [[px(x, y) for x, y in sp] for sp in _subpaths(d)]
        polys = [p for p in polys if len(p) >= 3]
        if not polys:
            continue
        xs = [x for p in polys for x, _ in p]
        ys = [y for p in polys for _, y in p]
        gx, gy = int(min(xs)) - 1, int(min(ys)) - 1
        gw, gh = int(max(xs)) - gx + 2, int(max(ys)) - gy + 2
        glyph = Image.new("1", (gw, gh), 0)
        for p in polys:  # even-odd: a counter («о», «д») is a hole
            one = Image.new("1", (gw, gh), 0)
            ImageDraw.Draw(one).polygon([(x - gx, y - gy) for x, y in p], fill=1)
            glyph = ImageChops.logical_xor(glyph, one)
        mask.paste(255, (gx, gy), glyph)
    draw = ImageDraw.Draw(mask)
    for rx, ry, rw, rh in rects:
        a, b = px(rx, ry)
        c, d = px(rx + rw, ry + rh)
        draw.rectangle([a, b, max(c - 1, a), max(d - 1, b)], fill=255)
    mask = mask.resize((max(W // ss, 1), max(H // ss, 1)), Image.LANCZOS)
    rgb = tuple(int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"#?[0-9A-Fa-f]{6}", color or "") else (0, 0, 0)
    img = Image.new("RGBA", mask.size, rgb + (0,))
    img.putalpha(mask)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), w + 2 * pad, h + 2 * pad


# ------------------------------------------------------------------ MathML → Office Math (OMML)

_NARY = {"∫": "subSup", "∬": "subSup", "∭": "subSup", "∮": "subSup", "∯": "subSup", "∰": "subSup", "∑": "undOvr", "∏": "undOvr", "∐": "undOvr", "⋃": "undOvr", "⋂": "undOvr", "⋁": "undOvr", "⋀": "undOvr", "⨁": "undOvr", "⨂": "undOvr"}
_INTEGRALS = {"∫": 1, "∬": 2, "∭": 3, "∮": 1, "∯": 2, "∰": 3}
_LIMS = {"lim", "max", "min", "sup", "inf", "lim sup", "lim inf", "limsup", "liminf"}
_FN_NAMES = {"sin", "cos", "tg", "ctg", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctg", "arcctg", "arctan", "ln", "lg", "log", "exp", "sh", "ch", "th", "sinh", "cosh", "tanh", "det", "deg", "dim", "ker", "arg", "gcd", "Pr", "sgn", "sign"}
_STOPS = {"=", "≈", "≠", "<", ">", "≤", "≥", "≡", "∼", "≅", "∝", "+", "−", "-", "±", "∓", ",", ";", "⇒", "⇔", "→", "∈"}
_ACCENTS = {"→": "⃗", "⃗": "⃗", "^": "̂", "ˆ": "̂", "~": "̃", "˜": "̃", "˙": "̇", "¨": "̈", "ˇ": "̌", "´": "́", "`": "̀", "˘": "̆"}
_BARS = {"¯", "‾", "―", "_", "̅", "─"}


class _Omml:
    """MathML (latex2mathml's) as Office Math. Every run carries the slide's size and colour in its DrawingML run
    properties (`a:rPr`), as PowerPoint writes them; the structures carry the same in their control properties."""

    def __init__(self, size_pt: float, color: str, lang: str = "ru-RU") -> None:
        self.sz = str(int(round(size_pt * 100)))
        self.color = (color or "000000").lstrip("#").upper()
        self.lang = lang

    # ---- the pieces
    def _rpr(self, italic: Optional[bool] = None, bold: bool = False) -> etree._Element:
        r = etree.Element(_a("rPr"))
        r.set("lang", self.lang)
        r.set("sz", self.sz)
        if italic is not None:
            r.set("i", "1" if italic else "0")
        r.set("b", "1" if bold else "0")
        fill = etree.SubElement(r, _a("solidFill"))
        etree.SubElement(fill, _a("srgbClr")).set("val", self.color)
        etree.SubElement(r, _a("latin")).set("typeface", MATH_FONT)
        etree.SubElement(r, _a("cs")).set("typeface", MATH_FONT)
        return r

    def run(self, text: str, style: str = "i") -> etree._Element:
        """`style`: «i» a variable (math italic), «p» upright (a number, an operator, a function's name), «b» bold
        upright, «nor» ordinary text («где»)."""
        r = etree.Element(_m("r"))
        if style in ("p", "b", "nor"):
            rp = etree.SubElement(r, _m("rPr"))
            if style == "nor":
                etree.SubElement(rp, _m("nor"))
            etree.SubElement(rp, _m("sty")).set(_m("val"), "b" if style == "b" else "p")
        r.append(self._rpr(italic=style == "i", bold=style == "b"))
        t = etree.SubElement(r, _m("t"))
        t.text = text
        if text != text.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return r

    def ctrl(self, parent: etree._Element) -> None:
        c = etree.SubElement(parent, _m("ctrlPr"))
        c.append(self._rpr(italic=True))

    def box(self, tag: str, items: list[etree._Element]) -> etree._Element:
        el = etree.Element(_m(tag))
        el.extend(items)
        return el

    # ---- the tree
    def convert(self, math: etree._Element) -> etree._Element:
        o = etree.Element(_m("oMath"))
        o.extend(self.seq(list(_children(math))))
        return o

    def of(self, node: etree._Element) -> list[etree._Element]:
        """The content of an argument (a base, an exponent, a numerator): an mrow is its sequence."""
        if _tag(node) in ("mrow", "mstyle", "mpadded", "semantics"):
            fence = _fence(node)
            if fence is not None:  # «\left( … \right)^2»: the brackets grow with what they hold
                return [self.delim(*fence)]
            return self.seq(list(_children(node)))
        return self.node(node)

    def seq(self, kids: list[etree._Element]) -> list[etree._Element]:
        out: list[etree._Element] = []
        i = 0
        while i < len(kids):
            ch = kids[i]
            nary = _nary_parts(ch)
            if nary is not None:
                op, sub, sup, loc = nary
                j, operand = i + 1, []
                need = _INTEGRALS.get(op, 0)
                while j < len(kids):
                    nxt = kids[j]
                    if not need and _is_stop(nxt):
                        break
                    inner = _nary_parts(nxt)
                    if inner is not None and inner[0] in _INTEGRALS:
                        need += _INTEGRALS[inner[0]]
                    if need and _is_stop(nxt) and _tag(nxt) == "mo" and _text(nxt) in ("=", "≈", "≠", "<", ">", "≤", "≥"):
                        break
                    operand.append(nxt)
                    j += 1
                    if need and _is_d(nxt) and j < len(kids) and _tag(kids[j]) == "mi":
                        operand.append(kids[j])
                        j += 1
                        need -= 1
                        if need <= 0:
                            break
                out.append(self.nary(op, sub, sup, loc, operand))
                i = j
                continue
            lim = _lim_parts(ch)
            if lim is not None:
                name, under = lim
                j, operand = i + 1, []
                while j < len(kids) and not _is_stop(kids[j]):
                    operand.append(kids[j])
                    j += 1
                    if _tag(operand[-1]) in ("mfrac", "mrow", "msup", "msub", "msubsup") or len(operand) >= 3:
                        break
                out.append(self.lim(name, under, operand))
                i = j
                continue
            if _tag(ch) in ("mi", "mo") and _text(ch) in _FN_NAMES:
                arg, j = _fn_argument(kids, i + 1)
                if arg:
                    out.append(self.func(_text(ch), arg))
                    i = j
                    continue
            # a decimal comma: «2», «,», «67» → «2,67»
            if _tag(ch) == "mn" and i + 2 < len(kids) and _is_comma_group(kids[i + 1]) and _tag(kids[i + 2]) == "mn":
                out.append(self.run(_text(ch) + "," + _text(kids[i + 2]), "p"))
                i += 3
                continue
            out.extend(self.node(ch))
            i += 1
        return out

    def node(self, n: etree._Element) -> list[etree._Element]:
        tag = _tag(n)
        kids = list(_children(n))
        if tag in ("mrow", "mstyle", "mpadded", "semantics", "math"):
            fence = _fence(n)
            if fence is not None:
                beg, end, inner = fence
                return [self.delim(beg, end, inner)]
            return self.seq(kids)
        if tag == "mi":
            t = _text(n)
            if not t:
                return []
            variant = n.get("mathvariant", "")
            if variant == "bold":
                return [self.run(t, "b")]
            if len(t) > 1 or variant in ("normal", "double-struck") or not t.isalpha() or t in "ℝℕℤℚℂ":
                return [self.run(t, "p")]
            return [self.run(t, "i")]
        if tag == "mn":
            return [self.run(_text(n), "p")] if _text(n) else []
        if tag == "mo":
            t = _text(n)
            if not t or t == "\u2062":  # an invisible times
                return []
            if t in _NARY:
                return [self.nary(t, None, None, _NARY[t], [])]
            return [self.run(t, "p")]
        if tag == "mtext":
            t = (n.text or "").replace("\u00a0", " ")
            return [self.run(t, "nor")] if t else []
        if tag == "mspace":
            w = n.get("width", "")
            m = re.match(r"([\d.]+)em", w)
            em = float(m.group(1)) if m else 0.2
            return [self.run("\u2003" if em >= 0.9 else ("\u2005" if em >= 0.25 else "\u2009"), "p")]
        if tag == "msup" and len(kids) == 2:
            if _nary_parts(n) is not None:
                op, sub, sup, loc = _nary_parts(n)
                return [self.nary(op, sub, sup, loc, [])]
            return [self.box("sSup", self._pr("sSupPr") + [self._arg("e", kids[0]), self._arg("sup", kids[1])])]
        if tag == "msub" and len(kids) == 2:
            if _nary_parts(n) is not None:
                op, sub, sup, loc = _nary_parts(n)
                return [self.nary(op, sub, sup, loc, [])]
            return [self.box("sSub", self._pr("sSubPr") + [self._arg("e", kids[0]), self._arg("sub", kids[1])])]
        if tag == "msubsup" and len(kids) == 3:
            if _nary_parts(n) is not None:
                op, sub, sup, loc = _nary_parts(n)
                return [self.nary(op, sub, sup, loc, [])]
            return [self.box("sSubSup", self._pr("sSubSupPr") + [self._arg("e", kids[0]), self._arg("sub", kids[1]), self._arg("sup", kids[2])])]
        if tag == "mfrac" and len(kids) == 2:
            pr = etree.Element(_m("fPr"))
            if n.get("linethickness") in ("0", "0pt", "0em"):
                etree.SubElement(pr, _m("type")).set(_m("val"), "noBar")
            self.ctrl(pr)
            return [self.box("f", [pr, self._arg("num", kids[0]), self._arg("den", kids[1])])]
        if tag == "msqrt":
            pr = etree.Element(_m("radPr"))
            etree.SubElement(pr, _m("degHide")).set(_m("val"), "1")
            self.ctrl(pr)
            e = etree.Element(_m("e"))
            e.extend(self.seq(kids) or [self.run("", "p")])
            return [self.box("rad", [pr, etree.Element(_m("deg")), e])]
        if tag == "mroot" and len(kids) == 2:
            pr = etree.Element(_m("radPr"))
            self.ctrl(pr)
            return [self.box("rad", [pr, self._arg("deg", kids[1]), self._arg("e", kids[0])])]
        if tag in ("mover", "munder", "munderover"):
            return self.over_under(n, tag, kids)
        if tag == "mtable":
            return [self.matrix(n)]
        if tag in ("mphantom", "annotation", "annotation-xml"):
            return []
        if tag == "menclose":
            return self.seq(kids)
        return self.seq(kids) if kids else ([self.run(_text(n), "p")] if _text(n) else [])

    def _pr(self, tag: str) -> list[etree._Element]:
        pr = etree.Element(_m(tag))
        self.ctrl(pr)
        return [pr]

    def _arg(self, tag: str, node: etree._Element) -> etree._Element:
        el = etree.Element(_m(tag))
        el.extend(self.of(node))
        return el

    def _args(self, tag: str, nodes: list[etree._Element]) -> etree._Element:
        el = etree.Element(_m(tag))
        el.extend(self.seq(nodes))
        return el

    def nary(self, op: str, sub: Optional[etree._Element], sup: Optional[etree._Element], loc: str, operand: list[etree._Element]) -> etree._Element:
        pr = etree.Element(_m("naryPr"))
        if op != "∫":
            etree.SubElement(pr, _m("chr")).set(_m("val"), op)
        etree.SubElement(pr, _m("limLoc")).set(_m("val"), loc)
        if sub is None:
            etree.SubElement(pr, _m("subHide")).set(_m("val"), "1")
        if sup is None:
            etree.SubElement(pr, _m("supHide")).set(_m("val"), "1")
        self.ctrl(pr)
        s = etree.Element(_m("sub"))
        if sub is not None:
            s.extend(self.of(sub))
        p = etree.Element(_m("sup"))
        if sup is not None:
            p.extend(self.of(sup))
        e = etree.Element(_m("e"))
        e.extend(self.seq(operand))
        return self.box("nary", [pr, s, p, e])

    def lim(self, name: str, under: etree._Element, operand: list[etree._Element]) -> etree._Element:
        low = self.box("limLow", self._pr("limLowPr") + [self.box("e", [self.run(name, "p")]), self._arg("lim", under)])
        if not operand:
            return low
        return self.box("func", self._pr("funcPr") + [self.box("fName", [low]), self._args("e", operand)])

    def func(self, name: str, arg: list[etree._Element]) -> etree._Element:
        return self.box("func", self._pr("funcPr") + [self.box("fName", [self.run(name, "p")]), self._args("e", arg)])

    def delim(self, beg: str, end: str, inner: list[etree._Element]) -> etree._Element:
        pr = etree.Element(_m("dPr"))
        etree.SubElement(pr, _m("begChr")).set(_m("val"), beg)
        etree.SubElement(pr, _m("endChr")).set(_m("val"), end)
        self.ctrl(pr)
        e = etree.Element(_m("e"))
        if len(inner) == 1 and _tag(inner[0]) == "mtable":
            eq = etree.SubElement(e, _m("eqArr"))
            for row in inner[0]:
                if _tag(row) != "mtr":
                    continue
                re_ = etree.SubElement(eq, _m("e"))
                cells = [c for c in row if _tag(c) == "mtd"]
                for ci, cell in enumerate(cells):
                    if ci:
                        re_.append(self.run("\u2003", "p"))
                    re_.extend(self.seq(list(_children(cell))))
        else:
            e.extend(self.seq(inner))
        return self.box("d", [pr, e])

    def over_under(self, n: etree._Element, tag: str, kids: list[etree._Element]) -> list[etree._Element]:
        base = kids[0] if kids else None
        if base is None:
            return []
        if tag == "mover" and len(kids) == 2:
            acc = _text(kids[1])
            if acc in _BARS or (len(acc) == 1 and acc in "¯‾―"):
                pr = etree.Element(_m("barPr"))
                etree.SubElement(pr, _m("pos")).set(_m("val"), "top")
                self.ctrl(pr)
                return [self.box("bar", [pr, self._arg("e", base)])]
            if acc in _ACCENTS:
                pr = etree.Element(_m("accPr"))
                etree.SubElement(pr, _m("chr")).set(_m("val"), _ACCENTS[acc])
                self.ctrl(pr)
                return [self.box("acc", [pr, self._arg("e", base)])]
            return [self.box("limUpp", self._pr("limUppPr") + [self._arg("e", base), self._arg("lim", kids[1])])]
        if tag == "munder" and len(kids) == 2:
            mark = _text(kids[1])
            if mark in ("⏟", "︸"):
                pr = etree.Element(_m("groupChrPr"))
                etree.SubElement(pr, _m("chr")).set(_m("val"), "⏟")
                self.ctrl(pr)
                return [self.box("groupChr", [pr, self._arg("e", base)])]
            if mark in _BARS:
                pr = etree.Element(_m("barPr"))
                etree.SubElement(pr, _m("pos")).set(_m("val"), "bot")
                self.ctrl(pr)
                return [self.box("bar", [pr, self._arg("e", base)])]
            return [self.box("limLow", self._pr("limLowPr") + [self._arg("e", base), self._arg("lim", kids[1])])]
        if tag == "munderover" and len(kids) == 3:
            low = self.box("limLow", self._pr("limLowPr") + [self._arg("e", base), self._arg("lim", kids[1])])
            return [self.box("limUpp", self._pr("limUppPr") + [self.box("e", [low]), self._arg("lim", kids[2])])]
        return self.seq(kids)

    def matrix(self, n: etree._Element) -> etree._Element:
        rows = [r for r in n if _tag(r) == "mtr"]
        cols = max((len([c for c in r if _tag(c) == "mtd"]) for r in rows), default=1)
        pr = etree.Element(_m("mPr"))
        mcs = etree.SubElement(pr, _m("mcs"))
        mc = etree.SubElement(mcs, _m("mc"))
        mcp = etree.SubElement(mc, _m("mcPr"))
        etree.SubElement(mcp, _m("count")).set(_m("val"), str(cols))
        etree.SubElement(mcp, _m("mcJc")).set(_m("val"), "center")
        self.ctrl(pr)
        m = self.box("m", [pr])
        for r in rows:
            mr = etree.SubElement(m, _m("mr"))
            cells = [c for c in r if _tag(c) == "mtd"]
            for c in cells + [None] * (cols - len(cells)):
                e = etree.SubElement(mr, _m("e"))
                if c is not None:
                    e.extend(self.seq(list(_children(c))))
        return m


def _tag(n: etree._Element) -> str:
    return etree.QName(n).localname if isinstance(n.tag, str) else ""


def _children(n: etree._Element):
    return (c for c in n if isinstance(c.tag, str))


def _text(n: etree._Element) -> str:
    return "".join(n.itertext()).strip() if n is not None else ""


def _is_stop(n: etree._Element) -> bool:
    return _tag(n) == "mo" and _text(n) in _STOPS


def _is_d(n: etree._Element) -> bool:
    return _tag(n) == "mi" and _text(n) == "d"


def _is_comma_group(n: etree._Element) -> bool:
    return (_tag(n) == "mo" and _text(n) == ",") or (_tag(n) == "mrow" and len(list(_children(n))) == 1 and _text(n) == ",")


def _nary_parts(n: etree._Element) -> Optional[tuple[str, Optional[etree._Element], Optional[etree._Element], str]]:
    """(operator, lower limit, upper limit, where the limits go) of a big operator, bare or with its limits."""
    tag = _tag(n)
    kids = list(_children(n))
    if tag == "mo" and _text(n) in _NARY:
        return _text(n), None, None, _NARY[_text(n)]
    if tag in ("msub", "msup", "msubsup", "munder", "mover", "munderover") and kids and _tag(kids[0]) == "mo" and _text(kids[0]) in _NARY:
        op = _text(kids[0])
        under = tag in ("munder", "mover", "munderover")
        loc = "undOvr" if under else _NARY[op]
        sub = kids[1] if tag in ("msub", "msubsup", "munder", "munderover") and len(kids) > 1 else None
        sup = (kids[2] if tag in ("msubsup", "munderover") and len(kids) > 2 else (kids[1] if tag in ("msup", "mover") and len(kids) > 1 else None))
        return op, sub, sup, loc
    return None


def _lim_parts(n: etree._Element) -> Optional[tuple[str, etree._Element]]:
    tag = _tag(n)
    kids = list(_children(n))
    if tag in ("msub", "munder") and len(kids) == 2 and _tag(kids[0]) in ("mo", "mi") and _text(kids[0]) in _LIMS:
        return _text(kids[0]), kids[1]
    return None


def _fn_argument(kids: list[etree._Element], i: int) -> tuple[list[etree._Element], int]:
    """A function's argument: the group in parentheses after its name, or the next term («sin x», «ln|x|»)."""
    if i >= len(kids):
        return [], i
    n = kids[i]
    if _tag(n) == "mo" and _text(n) in ("(", "|", "["):
        close = {"(": ")", "|": "|", "[": "]"}[_text(n)]
        for j in range(i + 1, len(kids)):
            if _tag(kids[j]) == "mo" and _text(kids[j]) == close:
                return kids[i : j + 1], j + 1
        return [], i
    if _is_stop(n):
        return [], i
    return [n], i + 1


def _fence(n: etree._Element) -> Optional[tuple[str, str, list[etree._Element]]]:
    """«\\left( … \\right)»: an mrow opened and closed by stretchy fences."""
    kids = list(_children(n))
    if len(kids) < 2:
        return None
    a, b = kids[0], kids[-1]
    if _tag(a) == "mo" and _tag(b) == "mo" and a.get("fence") == "true" and b.get("fence") == "true":
        return _text(a), _text(b), kids[1:-1]
    if _tag(a) == "mo" and a.get("fence") == "true" and a.get("form") == "prefix" and len(kids) >= 2:
        return _text(a), "", kids[1:]
    return None


@lru_cache(maxsize=256)
def _omml_xml(latex: str, size_pt: float, color: str, align: str) -> bytes:
    conv = _Omml(size_pt, color)
    para = etree.Element(f"{{{A14_NS}}}m", nsmap={"a14": A14_NS, "m": M_NS, "a": A_NS})
    mp = etree.SubElement(para, _m("oMathPara"))
    ppr = etree.SubElement(mp, _m("oMathParaPr"))
    etree.SubElement(ppr, _m("jc")).set(_m("val"), {"l": "left", "r": "right"}.get(align, "center"))
    mp.append(conv.convert(_mathml(latex)))
    return etree.tostring(para)


def omml(latex: str, size_pt: float, color: str, align: str = "ctr") -> etree._Element:
    """The formula as Office Math: an `a14:m` element (a paragraph of math) for a DrawingML paragraph."""
    return etree.fromstring(_omml_xml(latex, round(float(size_pt), 2), (color or "000000").lstrip("#").upper(), align))


# ------------------------------------------------------------------ the formula as one line of Unicode

_SUP_OUT = dict(zip("0123456789+-=()abcdefghijklmnoprstuvwxyz−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ⁻"))
_SUB_OUT = dict(zip("0123456789+-=()aehijklmnoprstuvx−", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ₋"))


@lru_cache(maxsize=512)
def latex_text(latex: str) -> str:
    """The formula as a readable line of Unicode («∫ₐᵇ f(x) dx = F(b) − F(a)», «xⁿ⁺¹/(n + 1)»): alt text, speaker
    notes, the audit's reading of the slide, and a slide's text that mentions a formula inline."""
    try:
        s = _plain(_mathml(latex))
    except Exception:  # noqa: BLE001 - LaTeX we cannot read: its commands taken out
        s = re.sub(r"\\[A-Za-z]+\s*", " ", tidy(latex)).replace("{", "").replace("}", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"(^|[=≈≠<>≤≥(,±]\s*)([−+])\s+(?=\S)", r"\1\2", s)  # a sign, not an operation: «n ≠ −1», «(−b ± …)»
    return s


def _script(t: str, table: dict, mark: str) -> str:
    t = t.strip()
    if t and set(t) <= {"′", "″", "‴", "*"}:  # a prime is written after its letter: «F′(x)»
        return t
    if t and all(c in table for c in t.replace(" ", "")):
        return "".join(table[c] for c in t.replace(" ", ""))
    return f"{mark}({t})" if len(t) > 1 else f"{mark}{t}"


def _wrap(t: str) -> str:
    t = t.strip()
    return t if re.fullmatch(r"[\w.,′²³⁴ⁿ⁺⁻¹⁰⁵⁶⁷⁸⁹ᵃˣ]+", t) else f"({t})"


def _plain(n: etree._Element) -> str:
    tag = _tag(n)
    kids = list(_children(n))
    if tag in ("math", "mrow", "mstyle", "mpadded", "semantics", "menclose", "mtd"):
        return "".join(_plain(k) for k in kids)
    if tag in ("mi", "mn") and not (tag == "mi" and _text(n) in ("±", "∓", "×", "·", "÷")):  # («\\pm» comes as an identifier)
        return _text(n)
    if tag in ("mo", "mi"):
        t = _text(n).replace("\u2062", "")
        if t in ("=", "≈", "≠", "<", ">", "≤", "≥", "≡", "+", "−", "±", "→", "⇒", "⇔", "∈", "×", "·", "÷"):
            return f" {t} "
        if t == ",":
            return ", "
        return t
    if tag == "mtext":
        return (n.text or "").replace("\u00a0", " ")
    if tag == "mspace":
        return " "
    if tag == "msup" and len(kids) == 2:
        return _plain(kids[0]) + _script(_plain(kids[1]), _SUP_OUT, "^")
    if tag == "msub" and len(kids) == 2:
        return _plain(kids[0]) + _script(_plain(kids[1]), _SUB_OUT, "_")
    if tag == "msubsup" and len(kids) == 3:
        return _plain(kids[0]) + _script(_plain(kids[1]), _SUB_OUT, "_") + _script(_plain(kids[2]), _SUP_OUT, "^")
    if tag in ("munder", "munderover", "mover") and kids:
        base = _plain(kids[0])
        if tag == "mover" and len(kids) == 2:
            return base + ("\u0305" if _text(kids[1]) in _BARS else "\u20d7" if _text(kids[1]) in ("→", "⃗") else "")
        lo = _plain(kids[1]) if len(kids) > 1 else ""
        hi = _plain(kids[2]) if tag == "munderover" and len(kids) > 2 else ""
        if base.strip() in _LIMS:
            return f"{base} ({lo}) " if lo else base
        return base + (_script(lo, _SUB_OUT, "_") if lo else "") + (_script(hi, _SUP_OUT, "^") if hi else "")
    if tag == "mfrac" and len(kids) == 2:
        return f"{_wrap(_plain(kids[0]))}/{_wrap(_plain(kids[1]))}"
    if tag == "msqrt":
        inner = "".join(_plain(k) for k in kids)
        return "√" + _wrap(inner)
    if tag == "mroot" and len(kids) == 2:
        return _script(_plain(kids[1]), _SUP_OUT, "^") + "√" + _wrap(_plain(kids[0]))
    if tag == "mtable":
        return "; ".join("".join(_plain(c) + " " for c in r if _tag(c) == "mtd").strip() for r in kids if _tag(r) == "mtr")
    return "".join(_plain(k) for k in kids) or _text(n)


def plain_math(text: str) -> str:
    """A line of text with its inline formulas («$F'(x) = f(x)$») as readable Unicode: what a text box shows. Sums of
    dollars («$5 млн и $3 млн») stay as written."""
    if not text or "$" not in text and "\\(" not in text:
        return text
    return _DOLLAR_RE.sub(lambda m: latex_text(next(g for g in m.groups() if g is not None)) if _math_inside(m) else m.group(0), text)


# ------------------------------------------------------------------ the shape


def equation_element(shape_id: int, name: str, box: tuple[int, int, int, int], formula: Formula, size_pt: float, color: str, rid: str, align: str = "ctr", lang: str = "ru-RU") -> etree._Element:
    """The slide element of a formula: `mc:AlternateContent` with the native equation (Choice, a14) and the same box
    filled with its picture (Fallback, relationship `rid`) — PowerPoint's own form of an inserted equation."""
    x, y, w, h = (int(v) for v in box)
    nsmap = {"mc": MC_NS, "p": P_NS, "a": A_NS, "r": R_NS}
    ac = etree.Element(f"{{{MC_NS}}}AlternateContent", nsmap=nsmap)
    choice = etree.SubElement(ac, f"{{{MC_NS}}}Choice", nsmap={"a14": A14_NS})
    choice.set("Requires", "a14")
    fallback = etree.SubElement(ac, f"{{{MC_NS}}}Fallback")
    descr = (f"{formula.label}: " if formula.label else "") + formula.text

    def sp(parent: etree._Element, locked: bool) -> etree._Element:
        s = etree.SubElement(parent, f"{{{P_NS}}}sp")
        nv = etree.SubElement(s, f"{{{P_NS}}}nvSpPr")
        c = etree.SubElement(nv, f"{{{P_NS}}}cNvPr")
        c.set("id", str(shape_id))
        c.set("name", name)
        c.set("descr", descr[:900])
        cs = etree.SubElement(nv, f"{{{P_NS}}}cNvSpPr")
        if locked:
            etree.SubElement(cs, _a("spLocks")).attrib.update({"noRot": "1", "noChangeAspect": "1", "noTextEdit": "1"})
        else:
            cs.set("txBox", "1")
        etree.SubElement(nv, f"{{{P_NS}}}nvPr")
        pr = etree.SubElement(s, f"{{{P_NS}}}spPr")
        xf = etree.SubElement(pr, _a("xfrm"))
        etree.SubElement(xf, _a("off")).attrib.update({"x": str(x), "y": str(y)})
        etree.SubElement(xf, _a("ext")).attrib.update({"cx": str(w), "cy": str(h)})
        g = etree.SubElement(pr, _a("prstGeom"))
        g.set("prst", "rect")
        etree.SubElement(g, _a("avLst"))
        return s

    # Choice: the native equation in a text box
    s1 = sp(choice, False)
    s1.find(f"{{{P_NS}}}spPr").append(etree.Element(_a("noFill")))
    tx = etree.SubElement(s1, f"{{{P_NS}}}txBody")
    bp = etree.SubElement(tx, _a("bodyPr"))
    bp.attrib.update({"wrap": "none", "lIns": "0", "tIns": "0", "rIns": "0", "bIns": "0", "anchor": "ctr", "rtlCol": "0"})
    etree.SubElement(bp, _a("noAutofit"))
    etree.SubElement(tx, _a("lstStyle"))
    p = etree.SubElement(tx, _a("p"))
    etree.SubElement(p, _a("pPr")).set("algn", {"l": "l", "r": "r"}.get(align, "ctr"))
    p.append(omml(formula.latex, size_pt, color, align))
    end = etree.SubElement(p, _a("endParaRPr"))
    end.attrib.update({"lang": lang, "sz": str(int(round(size_pt * 100))), "dirty": "0"})
    # Fallback: the same box filled with the formula's picture
    s2 = sp(fallback, True)
    pr2 = s2.find(f"{{{P_NS}}}spPr")
    bf = etree.SubElement(pr2, _a("blipFill"))
    etree.SubElement(bf, _a("blip")).set(f"{{{R_NS}}}embed", rid)
    st = etree.SubElement(bf, _a("stretch"))
    etree.SubElement(st, _a("fillRect"))
    tx2 = etree.SubElement(s2, f"{{{P_NS}}}txBody")
    etree.SubElement(tx2, _a("bodyPr"))
    etree.SubElement(tx2, _a("lstStyle"))
    p2 = etree.SubElement(tx2, _a("p"))
    r2 = etree.SubElement(p2, _a("r"))
    rp2 = etree.SubElement(r2, _a("rPr"))
    rp2.set("lang", lang)
    etree.SubElement(rp2, _a("noFill"))
    etree.SubElement(r2, _a("t")).text = " "
    return ac


def is_equation(el: etree._Element) -> bool:
    """A slide element that is a formula of ours or PowerPoint's: AlternateContent whose Choice holds Office Math."""
    if not isinstance(el.tag, str) or etree.QName(el).localname != "AlternateContent":
        return False
    return next(el.iter(f"{{{A14_NS}}}m"), None) is not None or next(el.iter(_m("oMath")), None) is not None


def equation_text(el: etree._Element) -> str:
    """What an equation element says, as a line of Unicode (its alt text; else its Office Math's characters)."""
    c = next(el.iter(f"{{{P_NS}}}cNvPr"), None)
    if c is not None and c.get("descr"):
        return c.get("descr")
    return " ".join("".join(t.text or "" for t in el.iter(_m("t"))).split())


def shape_of(el: etree._Element) -> Optional[etree._Element]:
    """The shape an equation element shows where Office Math is not read (its Fallback) — what LibreOffice draws."""
    fb = el.find(f"{{{MC_NS}}}Fallback")
    src = fb if fb is not None else el.find(f"{{{MC_NS}}}Choice")
    if src is None:
        return None
    return next((c for c in src if isinstance(c.tag, str)), None)
