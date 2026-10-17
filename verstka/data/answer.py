"""Ответ на вопрос брифа (qa4, NEW-S1…S5): история, которая отвечает первой.

Бриф-вопрос («Какой регион приносит больше всего и где мы растём быстрее? Что с NPS?», «Хватает ли нам прямых продаж
или пора развивать партнёров?») получает колоду, где ответ — на обложке, слайды отвечающих датасетов — первыми, а у
каждого вопроса есть карточка итога. Здесь — то, из чего `verstka/data/story.py` это собирает:

- `question_goals` — цели брифа, заданные вопросом (цели — от модели, `verstka/data/intent.py`, или от правил);
- `route` — датасет, который отвечает на вопрос: план, выбранный под эту цель, иначе тот, чьё имя, колонки или строки
  называет вопрос («Что с NPS?» → «NPS по кварталам»);
- `rows_answer` — ответ о строках, которые вопрос называет («прямых продаж», «партнёров» → «Прямые продажи — 46%
  (1 608 млн ₽), сделок: 214; партнёры — 28% (978 млн ₽), сделок: 391»), с фактами этих чисел;
- `weak_card` — узкое место, о котором спрашивает бриф, сказанное как узкое место, а не как успех;
- `card_label` — тема карточки, а не имя файла («Выручка и клиенты» вместо «Итоги квартала»);
- `summary_headline` — заголовок итога из двух сильнейших выводов, а не «Четыре главных вывода»; `topic_only` —
  тема без вывода («Ключевые итоги года»), которую итог и обложка не берут;
- `steps_basis` / `step_grounded` / `steps_head` — следующий шаг стоит только на тексте входа («Что дальше: …»), не на узком месте данных,
  а не придуман."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from verstka.data.aggregate import is_other_label
from verstka.data.goals import goal_match
from verstka.data.goals import stems_of as goal_stems
from verstka.data.headline import numbers_in
from verstka.data.words import file_title, fmt_value, join_and, lower_first, phrase, same_stem, stem_in, stems_of
from verstka.schemas.data import DatasetPlan, HeadlineFact, Table

__all__ = [
    "RowsAnswer", "question_goals", "route", "row_names", "rows_answer", "weak_card", "card_label", "summary_headline",
    "topic_only", "mid_case", "steps_basis", "steps_head", "step_grounded", "plan_vocab",
]

_QUESTION_RE = re.compile(r"[^.!?…\n]*\?")
MAX_ROWS_NAMED = 60  # a question names rows of a short table (channels, regions), not of a list of 240 clients


# ── the brief's questions ────────────────────────────────────────────────────────────────────────────────────────────
def question_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, the question as written) of every sentence of `text` that ends with a question mark."""
    out = []
    for m in _QUESTION_RE.finditer(text or ""):
        q = " ".join(m.group(0).split())
        if len(q) >= 5:
            out.append((m.start(), m.end(), q))
    return out


def question_goals(text: str, goals: Sequence[Any]) -> list[tuple[Any, str]]:
    """(goal, its question as written) for the goals the brief asks as questions, in the brief's order — a goal whose
    phrase is in a question, or (the model's own wording, `verstka/data/intent.py`) whose place is."""
    spans = question_spans(text)
    if not spans:
        return []
    out = []
    for g in sorted(goals or [], key=lambda g: int(getattr(g, "at", 0) or 0)):
        ph = " ".join(str(getattr(g, "phrase", "") or "").lower().split()).rstrip(" ?")
        q = next((q for _, _, q in spans if ph and ph in " ".join(q.lower().split())), None)
        if q is None:
            at = getattr(g, "at", None)
            q = next((q for a, b, q in spans if isinstance(at, int) and at > 0 and a <= at < b), None)
        if q is not None:
            out.append((g, q))
    return out


def label_column(t: Table) -> Optional[int]:
    """The column of the rows' names: the first whose cells are text."""
    for j in range(len(t.columns)):
        cells = [r[j] for r in t.rows[:200] if j < len(r) and r[j] not in (None, "")]
        if cells and sum(isinstance(c, str) for c in cells) >= 0.8 * len(cells):
            return j
    return None


def row_names(t: Optional[Table]) -> list[str]:
    if t is None:
        return []
    j = label_column(t)
    return [] if j is None else [str(r[j]).strip() for r in t.rows[:200] if j < len(r) and isinstance(r[j], str) and r[j].strip()]


def route(goal: Any, plans: Sequence[DatasetPlan], tables: Sequence[Table], taken: Sequence[int] = ()) -> Optional[int]:
    """The dataset that answers a question: the one whose plan was chosen for this goal, else the one whose name,
    columns or rows the question names best («Что с NPS?» → «NPS по кварталам»; the key figures say a little of
    everything and answer only when nothing else does). None — the data has nothing on it."""
    ph = getattr(goal, "phrase", None)
    cands = [k for k, p in enumerate(plans) if p.slides > 0]
    for k in cands:
        if ph and plans[k].task.goal == ph:
            return k
    best, score = None, 0.0
    for k in cands:
        try:
            s = goal_match(goal, plans[k].profile, row_names(tables[k]) if k < len(tables) else None)
        except Exception:  # noqa: BLE001 - a goal of another shape: no match
            s = 0.0
        if plans[k].task.task == "kpi":
            s -= 0.3
        if k in taken:
            s -= 0.2
        if s > score + 1e-9:
            best, score = k, s
    return best if score >= 0.6 else None


# ── the answer about the rows a question names ───────────────────────────────────────────────────────────────────────
@dataclass
class RowsAnswer:
    title: str  # «Прямые продажи и партнёры»
    text: str  # the card's text: every named row with its figures
    short: str  # the cover's line: «Прямые продажи — 46% выручки, партнёры — 28%»
    facts: list[HeadlineFact] = field(default_factory=list)  # the figures said, as facts of the dataset's slide


def mid_case(text: str, proper: Sequence[str] = ()) -> str:
    """A name or a sentence set inside a sentence: a common noun in lower case («Партнёры» → «партнёры», «Прямые
    продажи» → «прямые продажи», «Выручка растёт…» → «выручка растёт…»); a name stays («Москва», «NPS», «Scopus») —
    a one-word category of the data is taken for a name unless it is a plural («Партнёры»)."""
    t = (text or "").strip()
    if not t:
        return t
    first = re.split(r"[\s,:;—–-]", t, maxsplit=1)[0]
    if first in set(proper) and not re.search(r"[ыи]$", first.lower()):
        return t
    return lower_first(t)


def _is_num(c: Any) -> bool:
    return isinstance(c, (int, float)) and not isinstance(c, bool)


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е")) if w]


def _word_hit(w: str, q: Sequence[str]) -> bool:
    """Слово имени — целое слово вопроса или та же основа («партнёров» — «Партнёры»), а не кусок другого слова
    («город» — не «Академгородок», F4)."""
    from verstka.data.words import stem

    if w.isdigit():
        return w in q
    sw = stem(w)
    for x in q:
        if x.isdigit():
            continue
        sx = stem(x)
        if sw == sx or (min(len(sw), len(sx)) >= 4 and (sx.startswith(sw) or sw.startswith(sx))
                        and abs(len(sw) - len(sx)) <= 3):
            return True
    return False


_BENCH_RE = re.compile(r"(?i)^(?:средн|в\s+среднем|итог|всего|норматив|план\b|медиан|по\s+(?:сети|району|стране|компании))")


def named_rows(question: str, t: Table) -> list[int]:
    """Rows of a short table whose name the question says («прямых продаж» → «Прямые продажи», «партнёров» →
    «Партнёры»): every word of the name is a whole word of the question (or its stem) — «Академгородок» is not named by
    «город». Rows whose name repeats (one category over several rows) are no answer: their value is an aggregate."""
    j = label_column(t)
    if j is None or len(t.rows) > MAX_ROWS_NAMED:
        return []
    q = _tokens(question)
    labels = [str(r[j]).strip().lower() for i, r in enumerate(t.rows) if i not in set(t.totals) and j < len(r)
              and isinstance(r[j], str)]
    out = []
    for i, r in enumerate(t.rows):
        if i in set(t.totals) or j >= len(r) or not isinstance(r[j], str) or not r[j].strip():
            continue
        if labels.count(r[j].strip().lower()) > 1:
            continue
        if _BENCH_RE.match(r[j].strip()):
            continue  # «Среднее по району», «Итого», «Норматив» — ориентир, а не строка, о которой вопрос
        ws = [w for w in _tokens(r[j]) if len(w) >= 3 or w.isdigit()]
        if ws and all(_word_hit(w, q) for w in ws):
            out.append(i)
    return out


def _share_of(t: Table, share: int, col: int, rows: Sequence[int]) -> bool:
    """Колонка «%» — доля строки в сумме колонки `col` (значение / итог × 100 у каждой строки), а не другая
    величина в процентах (NPS, доля возвратов внутри категории)."""
    body = [i for i in range(len(t.rows)) if i not in set(t.totals)]
    vals = [t.rows[i][col] if col < len(t.rows[i]) else None for i in body]
    if not vals or any(not _is_num(v) for v in vals):
        return False
    tot = sum(float(v) for v in vals)
    if not tot:
        return False
    for i in body:
        a, b = t.rows[i][share] if share < len(t.rows[i]) else None, t.rows[i][col]
        if not _is_num(a) or abs(float(a) - float(b) / tot * 100) > 0.6:
            return False
    return True


def _col_label(t: Table, j: int) -> str:
    return lower_first(t.columns[j]) if not re.match(r"^[A-ZА-ЯЁ]{2,}", t.columns[j]) else t.columns[j]


def rows_answer(question: str, t: Optional[Table], main: Optional[str] = None) -> Optional[RowsAnswer]:
    """The figures of the rows a question names (up to three), said row by row, every figure with the column it came
    from (F4): the slide's measure `main` first («Ночная — оценка качества: 79 баллов, меньше — только у «Выходного
    дня» (74)»), a «%» column as a share only when it is the row's share of the sum column («Прямые продажи — 46%
    (1 608 млн ₽), сделок: 214»), any other «%» column by its own name. None — the question names no row."""
    if t is None:
        return None
    rows = named_rows(question, t)
    if not rows or len(rows) > 3:
        return None
    j0 = label_column(t)

    def unit(j: int) -> Optional[str]:
        return t.units[j] if j < len(t.units) else None

    nums = [j for j in range(len(t.columns)) if j != j0 and all(j < len(t.rows[i]) and _is_num(t.rows[i][j]) for i in rows)]
    if not nums:
        return None
    jm = next((j for j in nums if main and t.columns[j] == main), None)
    labels = [str(t.rows[i][j0]).strip() for i in rows]
    clauses, shorts, facts = [], [], []
    pct = [j for j in nums if unit(j) == "%"]
    sums = [j for j in nums if j not in pct and unit(j)]
    counts = [j for j in nums if j not in pct and not unit(j)]
    share = next((j for j in pct if sums and _share_of(t, j, sums[0], rows)), None)
    if jm is not None and share is not None and jm in (share, sums[0]) and len(rows) >= 2:
        jm = None  # каналы и их доли выручки: доля, сумма и сделки — по строке (qa4 NEW-S2)
    if jm is not None:
        body = [i for i in range(len(t.rows)) if i not in set(t.totals) and jm < len(t.rows[i]) and _is_num(t.rows[i][jm])
                and j0 < len(t.rows[i]) and isinstance(t.rows[i][j0], str)]
        u = unit(jm)
        name_m = _col_label(t, jm)
        for n, (i, lab) in enumerate(zip(rows, labels)):
            v = float(t.rows[i][jm])
            facts.append(HeadlineFact(id=f"ask_{i}_{jm}", text=f"{lab} — {t.columns[jm]}: {fmt_value(v, u)}", value=v,
                                      unit=u, kind="total"))
            line = f"{lab if n == 0 else mid_case(lab)} — {name_m}: {fmt_value(v, u)}"
            if len(rows) == 1 and len(body) >= 3:
                others = [(str(t.rows[k][j0]).strip(), float(t.rows[k][jm])) for k in body if k != i
                          and not is_other_label(str(t.rows[k][j0]))]
                hi = [x for x in others if x[1] > v]
                lo = [x for x in others if x[1] < v]
                for lab2, v2 in hi + lo:
                    if len(hi) <= 2 or len(lo) <= 2:
                        facts.append(HeadlineFact(id=f"ask_rank_{len(facts)}", text=f"{lab2} — {t.columns[jm]}: {fmt_value(v2, u)}",
                                                  value=v2, unit=u, kind="total"))
                said = lambda xs: join_and([f"«{a}» ({fmt_value(b, u)})" for a, b in xs])  # noqa: E731
                if not hi:
                    line += ", больше всех"
                elif not lo:
                    line += ", меньше всех"
                elif len(lo) <= 2:
                    line += f", меньше — только у {said(lo)}"
                elif len(hi) <= 2:
                    line += f", больше — только у {said(hi)}"
            clauses.append(line)
            shorts.append(line)
        if len(rows) == 2:
            (a, va), (b, vb) = [(lab, float(t.rows[i][jm])) for i, lab in zip(rows, labels)]
            if va != vb:
                short = (f"{a} — {name_m}: {fmt_value(va, u)}, {'больше' if va > vb else 'меньше'}, чем у "
                         f"«{b}» ({fmt_value(vb, u)})")
                shorts = [short]
        title = join_and([labels[0]] + [mid_case(x) for x in labels[1:]])
        return RowsAnswer(title=title, text="; ".join(clauses), short=", ".join(shorts), facts=facts)
    measure = None
    if share is not None:
        p = phrase(t.columns[sums[0]])
        measure = lower_first(p.gen) if p is not None and p.sure else None
    other_pct = [j for j in pct if j != share]
    for n, (i, lab) in enumerate(zip(rows, labels)):
        name = lab if n == 0 else mid_case(lab)
        r = t.rows[i]
        bits, short = [], ""
        if share is not None:
            s_ = fmt_value(float(r[share]), "%")
            facts.append(HeadlineFact(id=f"ask_{i}_{share}", text=f"{lab} — {s_}", value=float(r[share]), unit="%", kind="share"))
            short = s_ + (f" {measure}" if measure and n == 0 else "")
        if sums:
            v = fmt_value(float(r[sums[0]]), unit(sums[0]))
            facts.append(HeadlineFact(id=f"ask_{i}_{sums[0]}", text=f"{lab} — {v}", value=float(r[sums[0]]), unit=unit(sums[0]), kind="total"))
            bits.append(f"{fmt_value(float(r[share]), '%')} ({v})" if share is not None else f"{_col_label(t, sums[0])}: {v}")
            short = short or f"{_col_label(t, sums[0])}: {v}"
        for j in other_pct[:1]:
            v = fmt_value(float(r[j]), "%")
            facts.append(HeadlineFact(id=f"ask_{i}_{j}", text=f"{lab} — {t.columns[j]}: {v}", value=float(r[j]), unit="%", kind="total"))
            bits.append(f"{_col_label(t, j)}: {v}")
            short = short or f"{_col_label(t, j)}: {v}"
        for j in counts[:1]:
            v = fmt_value(float(r[j]), None)
            facts.append(HeadlineFact(id=f"ask_{i}_{j}", text=f"{lab} — {lower_first(t.columns[j])}: {v}", value=float(r[j]), unit=None, kind="count"))
            bits.append(f"{lower_first(t.columns[j])}: {v}")
        clauses.append(f"{name} — {', '.join(bits)}")
        shorts.append(f"{name} — {short}")
    title = join_and([labels[0]] + [mid_case(x) for x in labels[1:]])
    return RowsAnswer(title=title, text="; ".join(clauses), short=", ".join(shorts), facts=facts)


# ── a weak spot said as one ──────────────────────────────────────────────────────────────────────────────────────────
def weak_card(plan: DatasetPlan) -> Optional[tuple[str, str, list[HeadlineFact]]]:
    """(title, text, facts) of a distribution's weak spot — its tail past the threshold most values keep and its
    outliers («20% обращений — больше 120 мин, 3 — больше 10 часов») — for a brief that asks where it goes wrong
    (qa4 S3: «80% обращений получают ответ за 2 часа» read as a success). None — no tail to say."""
    if plan.task.task != "distribution":
        return None
    f = {x.id: x for x in plan.headline_facts}
    sw = f.get("share_within")
    if sw is None or sw.unit != "%" or not (0 < sw.value < 100):
        return None
    m = re.search(r"не\s+больше\s+(.+)$", sw.text or "")
    if not m:
        return None
    bound = m.group(1).strip().rstrip(".")
    tail = round(100 - float(sw.value))
    noun = ""
    cnt = f.get("count")
    if cnt is not None:
        mm = re.match(r"^\s*[\d\s  ]+\s+([а-яё]+)", cnt.text or "", re.I)
        noun = mm.group(1) if mm else ""
    text = f"{tail}% {noun} — больше {bound}".replace("  ", " ")
    facts = [HeadlineFact(id="story_tail_share", text=f"{tail}% — больше {bound}", value=float(tail), unit="%", kind="share")]
    for n in numbers_in(bound):
        facts.append(HeadlineFact(id="story_tail_bound", text=f"больше {bound}", value=float(n), unit=None, kind="percentile"))
    ob, oh = f.get("outlier_bound_high"), f.get("outliers_high") or f.get("outliers")
    if ob is not None and oh is not None and (ob.text or "").strip():
        text += f", {int(oh.value)} — {ob.text.strip()}"
        for n in numbers_in(ob.text):
            facts.append(HeadlineFact(id="story_outlier_bound", text=ob.text.strip(), value=float(n), unit=None, kind="outliers"))
    topic = plan.plain_headline or file_title(plan.profile.file)
    return f"Узкое место: {lower_first(topic)}", text, facts


# ── a card's topic ───────────────────────────────────────────────────────────────────────────────────────────────────
_REPORT_RE = re.compile(r"(?i)^(итог|отч[её]т|сводк|результат|данные|показател|ключев|kpi|обзор|резюме)")


def card_label(plan: DatasetPlan, head: Optional[str] = None) -> str:
    """The topic a summary card sets over its conclusion: the dataset's topic — and for a set of key figures, or a file
    named as a report («Итоги квартала», «Итоги года»), the names of the figures its conclusion says («Выручка и
    клиенты»), never the file's name (qa4 NEW-S4)."""
    topic = plan.plain_headline or file_title(plan.profile.file)
    if plan.task.task != "kpi" and not _REPORT_RE.match(topic or ""):
        return topic
    nums = numbers_in(head or plan.headline or "")
    names: list[str] = []
    for f in plan.headline_facts:
        if f.kind not in ("change", "total", "share") or not any(abs(abs(f.value) - n) < 0.051 for n in nums):
            continue
        name = re.split(r"\s*(?::|—|–)\s*", f.text or "", maxsplit=1)[0].strip()
        if name and len(name) <= 40 and name.lower() not in {x.lower() for x in names}:
            names.append(name)
    if not names:
        return topic
    return join_and([names[0]] + [lower_first(x) for x in names[1:2]])


# ── the summary's headline ───────────────────────────────────────────────────────────────────────────────────────────
def _first_clause(text: str) -> str:
    """A conclusion's main clause: up to its first comma or semicolon, or the claim before its colon («Выручка растёт
    быстрее числа клиентов: +23% против +18%» → «Выручка растёт быстрее числа клиентов») — never a part that says
    nothing on its own (the words before a dash: «Каждый час подготовки в неделю — около +1,9…» stays whole)."""
    t = " ".join((text or "").split()).rstrip(". ")
    for sep in (", ", "; ", ": "):
        k = t.find(sep, 12)
        if k > 0 and not topic_only(t[:k]):
            return t[:k].strip()
    return t


def summary_headline(conclusions: Sequence[str], proper: Sequence[str] = (), limit: int = 100) -> str:
    """The summary's headline from its two strongest conclusions (the cards in their order), each by its main clause,
    joined by «;» («Выручка растёт быстрее числа клиентов; Москва даёт 41% выручки»), the second left out when the line
    grows long. A synthesis of the cards, not a copy of one, and never a label like «Четыре главных вывода» (qa4
    NEW-S1)."""
    parts: list[str] = []
    for c in conclusions:
        c = _first_clause(c)
        if c and c not in parts:
            parts.append(c)
    if not parts:
        return ""
    if len(parts) < 2:
        return parts[0]
    cand = f"{parts[0]}; {mid_case(parts[1], proper)}"
    return cand if len(cand) <= limit else parts[0]


_LABEL_WORDS_RE = re.compile(r"(?i)\b(?:главн|ключев|основн|важн|итог|вывод|результат|резюме|обзор|сводк|анализ|данн|показател)\w*")
_VERB_RE = re.compile(
    r"(?i)(больше|меньше|быстрее|медленнее|выше|ниже|почти|половин|треть|четверт|вдвое|втрое|лидир|впереди|отста|"
    r"опережа|раст[её]т|растут|вырос|упал|пада|снизил|сниж|сократил|сокращ|увеличил|увелич|да[её]т|дают|принос|держ|"
    r"составля|достиг|получа|укладыва|закрыва|связан|влия|зависит|крупнейш|наибольш|наименьш|подним|опуска|тянут|"
    r"хватает|хватит|требу|нужн|стоит|остаётся|остается|занима|обгоня|уступа)"
)
_PAST_VERB_RE = re.compile(r"(?i)\b[а-яё]{3,}(?:ил|ила|ило|или|ала|али|ела|ели|ула|ули|ял|яла|яли|лся|лась|лось|лись)\b|"
                           r"\b[а-яё]*(?:шёл|шел|шла|шло|шли)\b")


def topic_only(text: str) -> bool:
    """A title that names a topic and says nothing about it: no figure (years and quarters date it, they are no figure)
    and no verb or comparison — «Ключевые итоги года», «КЛЮЧЕВЫЕ ИТОГИ ГОДА», «Четыре главных вывода», «Итоги III
    квартала 2026: рост выручки и NPS»."""
    t = " ".join((text or "").split())
    t = re.sub(r"(?<![\d,.])(?:19|20)\d\d(?![\d,])", " ", t)
    t = re.sub(r"(?i)\b[IV]{1,3}\s*(?:квартал\w*|полугоди\w*|кв\.?)", " ", t)
    t = _LABEL_WORDS_RE.sub(" ", t)
    if re.search(r"\d", t):
        return False
    return not (_VERB_RE.search(t) or _PAST_VERB_RE.search(t))


# ── next steps that stand on something ───────────────────────────────────────────────────────────────────────────────
_BASIS_RE = re.compile(r"(?i)(?:что\s+дальше|следующ\w*\s+шаг\w*|рекомендац\w*|предлага\w*|план\w*\s+на\s+\S+)\s*[:—–-]\s*([^.!?]{10,600})")
_STEP_STOP = frozenset(stems_of(
    "счёт счет цели целью пользу нам наш наши свой свои для при как так это эти все всех всего дольше больше меньше "
    "выше ниже двух трёх трех четырёх четырех один одна два три четыре пять раза раз также ещё еще уже часть"
))


def steps_basis(notes: Sequence[dict]) -> str:
    """What the files themselves propose («Что дальше: удержать темп роста в IV квартале за счёт партнёрского канала…»),
    or ""."""
    return " ".join(m.group(1).strip() for n in notes for m in _BASIS_RE.finditer(n.get("text") or ""))


def steps_head(basis: str) -> Optional[str]:
    """The closing slide's heading in the input's own words: the goal its proposal opens with («удержать темп роста в
    IV квартале за счёт партнёрского канала…» → «Удержать темп роста в IV квартале»), or None when it has none short
    enough — never the plan's line «Что делаем … и что просим» over a slide that asks nothing (qa6)."""
    first = re.split(r"\s+за\s+сч[её]т\s+|\s+благодаря\s+|[,;:.!?]\s|\s[—–]\s", (basis or "").strip(), maxsplit=1)[0].strip(" .,;:—–")
    n = len(first.split())
    return first[:1].upper() + first[1:] if 2 <= n <= 9 else None


def _content(step: str) -> list[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (step or "").lower())
    if words and re.search(r"(?:ть|ти|чь|ться)$", words[0]):
        words = words[1:]  # the step's verb («Сократить», «Развивать»)
    return [w for w in stems_of(" ".join(words)) if not w.isdigit() and w not in _STEP_STOP]


def plan_vocab(plan: Optional[DatasetPlan], extra: Sequence[str] = ()) -> set[str]:
    """The words a dataset speaks with: its topic and file, its columns, conclusion, caption, facts and the analysis'
    reasons («насколько длинный хвост»)."""
    if plan is None:
        return set(stems_of(" ".join(extra)))
    texts = [plan.plain_headline or "", file_title(plan.profile.file), plan.headline or "", plan.caption or ""]
    texts += [c.name for c in plan.profile.columns] + [f.text for f in plan.headline_facts]
    texts += [r for o in plan.options for r in (o.reasons or [])] + list(extra)
    return set(stems_of(" ".join(x for x in texts if x)))


def _hits(words: Sequence[str], vocab: set[str]) -> list[str]:
    return [w for w in words if any(same_stem(w, x) or stem_in(w, x) for x in vocab)]


_WEAK_WORDS = frozenset(stems_of("узкие места слабые места риски проблемы хвост задержки ожидание долгие"))


def step_grounded(step: str, basis: str, weak: set[str], data: set[str]) -> tuple[bool, str]:
    """A next step stands on the input's own proposal — the files' «Что дальше: …», «Предлагаем …» (its words, the
    data's words around them) — and on nothing else: not on the model's invention («Усилить работу с абитуриентами…»
    over files that propose to keep the budget places, qa4 NEW-S5), nor on a weak spot of the data the input proposes
    nothing about («Сократить хвост обращений дольше 120 минут» — the model's step, not the author's: qa6). `weak` is
    kept for the callers. (ok, why not)."""
    if not basis:
        return False, "во входе нет следующих шагов — финал их не придумывает"
    words = _content(step)
    b = set(stems_of(basis))
    hb = _hits(words, b)
    if len(words) < 2:
        return (True, "") if hb else (False, "такого шага нет в тексте входа")
    need = 0.6 * len(words)
    both = _hits(words, b | data)
    if len(hb) >= 2 and len(both) >= need:
        return True, ""
    return False, "такого шага нет в тексте входа"
