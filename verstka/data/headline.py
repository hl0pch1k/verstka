"""Заголовок-вывод (описание решения §2.6): шаблоны по задаче и проверка чисел.

Заголовок — вывод с настоящим числом из данных («Выручка выросла на 23% к сентябрю», «Москва даёт 41% выручки,
Казань растёт быстрее всех», «80% обращений получают ответ за 2 часа», «Топ-10 клиентов дают 38% выручки»), а не тема
(«Выручка по месяцам»). Числа берутся только из фактов (`verstka/data/facts.py`), слова — из `verstka/data/words.py`.
`headline_ok` проверяет, что каждое число заголовка есть среди фактов; числа внутри известных подписей («Филиал 1»,
«25–34») можно исключить параметром `labels`. Модель (навык `data_storyteller`) может переформулировать заголовок, но
проверка её текста строгая: если в нём число не из фактов, остаётся детерминированный."""

from __future__ import annotations

import re
from typing import Optional, Sequence

from verstka.data.facts import FactSet
from verstka.data.words import (
    PERIOD_WORDS, WORD_NUMS, Gender, Phrase, count_words, fmt_num, fmt_pct, fmt_signed, fmt_value, fraction_words,
    is_plural_value, lower_first, number_word, plural, times_word, upper_first, verb,
)
from verstka.schemas.data import HeadlineFact, TaskKind

__all__ = ["numbers_in", "headline_ok", "compose"]


# ── проверка чисел заголовка ──────────────────────────────────────────────────────────────────────────────────────────
_NUM_IN_TEXT = re.compile(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])"
                          r"|(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])")
_WORD_RE = re.compile(r"[а-яё]+", re.I)


def _without(text: str, labels: Sequence[str]) -> str:
    """Текст без известных подписей («Филиал 1», «25–34»): цифры внутри названий — не числа заголовка."""
    for lab in sorted({x for x in labels if x}, key=len, reverse=True):
        text = re.sub(r"(?<![\w])" + re.escape(lab) + r"(?![\w])", " ", text)
    return text


def numbers_in(text: str, labels: Sequence[str] = ()) -> list[float]:
    """Числа в тексте: «1 433», «4,2», «+23%», «топ-10» (10), «два квартала» (2). Римские («III кв.») — не числа.
    `labels` — подписи категорий из данных: их цифры («Филиал 1», «18–24») не считаются."""
    out: list[float] = []
    text = _without(text or "", labels)
    for m in _NUM_IN_TEXT.finditer(text):
        tok = m.group(0)
        tok = re.sub(r"[   ]", "", tok).replace(",", ".").lstrip("+−–-")
        try:
            out.append(abs(float(tok)))
        except ValueError:
            continue
    for w in _WORD_RE.findall(text):
        n = WORD_NUMS.get(w.lower())
        if n is not None:
            out.append(float(n))
    return out


def _matches(n: float, v: float) -> bool:
    v = abs(v)
    if abs(n - v) < 1e-9:
        return True
    for d in (0, 1, 2):
        if abs(round(v, d) - n) < 1e-9:
            return True
    return False


def headline_ok(text: str, facts: Sequence[HeadlineFact], labels: Sequence[str] = ()) -> bool:
    """Каждое число заголовка есть среди фактов (значение, как его пишет заголовок: целое или с одним-двумя знаками).
    По умолчанию проверка строгая — так проверяется перефразировка модели. `labels` — подписи категорий, которые
    шаблон сам поставил в заголовок («Филиал 1 даёт 50% выручки»): их цифры — часть названия, а не вывод."""
    values = [f.value for f in facts]
    return all(any(_matches(n, v) for v in values) for n in numbers_in(text, labels))


def _labels(fs: FactSet) -> list[str]:
    c = fs.ctx
    out = list(c.get("labels") or [])
    for k in ("leader", "last_label", "growth_leader", "a_name", "b_name"):
        if c.get(k):
            out.append(c[k])
    return out


# ── шаблоны заголовка ─────────────────────────────────────────────────────────────────────────────────────────────────
def compose(task: TaskKind, fs: FactSet) -> tuple[str, Optional[str]]:
    """Заголовок-вывод и подпись-пояснение из фактов задачи. Факты задают и слова (ctx: лидер, период, сущность) —
    шаблон только расставляет их по-русски."""
    fn = {
        "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
        "reference": _reference, "kpi": _kpi, "relationship": _relationship,
    }[task]
    head, caption = fn(fs)
    head = head.strip().rstrip(".")
    head = upper_first(head)
    if not headline_ok(head, fs.facts, _labels(fs)):  # страховка: число не из фактов — заголовок-описание
        head = fs.ctx.get("plain") or head
    return head, caption


def _f(fs: FactSet, fid: str) -> Optional[HeadlineFact]:
    return next((f for f in fs.facts if f.id == fid), None)


def _dynamics(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    m: Phrase = c["metric"]
    subj = c["subject"]  # «Выручка», «NPS», «Число клиентов»
    g: Gender = c["gender"]
    gap = _f(fs, "gaps")
    gap_txt = ""
    if gap is not None:
        k = int(gap.value)
        pw = PERIOD_WORDS.get(c["freq"], PERIOD_WORDS["irregular"])
        if k == 1 and c.get("gap_label"):
            gap_txt = f", за {c['gap_label']} данных нет"
        elif k <= 4:
            gap_txt = f", за {number_word(k, pw[3])} {plural(k, pw[0], pw[1], pw[2])} данных нет"
        else:
            gap_txt = f", за {count_words(k, pw[0], pw[1], pw[2])} данных нет"
    last = _f(fs, "last")
    change = _f(fs, "change")
    ratio = _f(fs, "ratio")
    if c.get("level") and last is not None:
        delta = c.get("delta", 0.0)
        if abs(delta) < 1e-9 or change is None:
            head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, c.get('unit_short'))}"
        else:
            v = verb("grow" if delta > 0 else "fall", g)
            head = f"{subj} {v} до {fmt_value(last.value, c.get('unit_short'))}"
        return head + gap_txt, c.get("caption")
    if change is None and last is not None:
        return f"{subj} — {fmt_value(last.value, c.get('unit_short'))}" + gap_txt, c.get("caption")
    if change is None:
        return c.get("plain", subj), c.get("caption")
    when = c.get("when", "")
    if ratio is not None:
        r = ratio.value
        head = f"{subj} {verb('grow', g)} в {fmt_num(r, 1)} {times_word(r)} {when}"
    elif c.get("abs_change") and last is not None:
        if abs(c["delta"]) < 1e-9:
            head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, c.get('unit_short'))}"
        else:
            v = verb("grow" if c["delta"] > 0 else "fall", g)
            head = (f"{subj} {v} на {fmt_value(change.value, c.get('unit_short'))} {when}, до "
                    f"{fmt_value(last.value, c.get('unit_short'))}")
    elif abs(change.value) < 1 and last is not None:
        head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, c.get('unit_short'))}"
    else:
        v = verb("grow" if c["delta"] > 0 else "fall", g)
        head = f"{subj} {v} на {fmt_pct(change.value)}% {when}"
    return " ".join(head.split()) + gap_txt, c.get("caption")


def _comparison(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    leader = c["leader"]
    pl = "pl" if is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    grow_leader = c.get("growth_leader")
    m: Optional[Phrase] = c.get("metric")
    if share is not None and m is not None:
        head = f"{leader} {verb('give', pl, past=False)} {fmt_pct(share.value)}% {m.low.gen}"
    elif _f(fs, "leader_value") is not None:
        lv = _f(fs, "leader_value")
        head = f"{leader} впереди: {fmt_value(lv.value, c.get('unit_short'))}"
        last = _f(fs, "last_value")
        if last is not None and c.get("last_label"):
            head += f", {c['last_label']} — {fmt_value(last.value, c.get('unit_short'))}"
    else:
        head = c.get("plain", leader)
    if grow_leader:
        gpl = "pl" if is_plural_value(grow_leader) else "m"
        if grow_leader == leader:
            head += f" и {verb('grow', pl, past=False)} быстрее всех"
        else:
            head += f", {grow_leader} {verb('grow', gpl, past=False)} быстрее всех"
    neg = _f(fs, "negatives")
    if neg is not None and not grow_leader:
        forms = c.get("neg_forms") or ("категория", "категории", "категорий")
        head += f", {count_words(int(neg.value), *forms)} в минусе"
    return head, c.get("caption")


def _shares(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    leader = c["leader"]
    pl = "pl" if is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    whole: Optional[Phrase] = c.get("whole")
    if share is None:
        return c.get("plain", leader), c.get("caption")
    p = share.value
    words = fraction_words(p)
    v = verb("bring" if c.get("money") else "give", pl, past=False)
    if whole is not None:
        if words:
            head = f"{leader} {v} {words} {whole.low.gen} — {fmt_pct(p)}%"
        else:
            head = f"{leader} {v} {fmt_pct(p)}% {whole.low.gen}"
    else:
        head = f"{leader} — крупнейшая доля: {fmt_pct(p)}%"
    return head, c.get("caption")


def _distribution(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    ent = c.get("entities_gen")  # «обращений»
    if c.get("constant"):
        nom = c.get("entities_nom_pl")
        who = f"{'Все' if c['constant'] == 'all' else 'Почти все'} {lower_first(nom) if nom else 'значения'}"
        return f"{who} — {c['median_text']}", c.get("caption")
    share = _f(fs, "share_within")
    if share is None:
        return (f"Медиана — {c['median_text']}" if c.get("median_text") else c.get("plain", "")), c.get("caption")
    p = share.value
    who = f"{fmt_pct(p)}% {ent or 'значений'}"
    if c.get("duration") and ent and c.get("predicate"):
        head = f"{who} {c['predicate']} {c['threshold_text']}"
    elif c.get("duration"):
        head = f"{who} — не дольше {c['threshold_text']}"
    else:
        head = f"{who} — не больше {c['threshold_text']}"
    return head, c.get("caption")


def _reference(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    top = _f(fs, "top_share")
    n_top = _f(fs, "top_n")
    m: Optional[Phrase] = c.get("metric")
    if top is not None and n_top is not None and m is not None:
        ent = c.get("entities_gen")
        who = f"Топ-{int(n_top.value)} {ent}" if ent else f"{int(n_top.value)} крупнейших"
        return f"{who} {verb('give', 'pl', past=False)} {fmt_pct(top.value)}% {m.low.gen}", c.get("caption")
    lv = _f(fs, "leader_value")
    if lv is not None and not c.get("leader") and m is not None:
        return f"{m.nom}: наибольшее значение — {fmt_value(lv.value, c.get('unit_short'))}", c.get("caption")
    if lv is not None and c.get("leader"):
        by = f"по {m.low.dat}" if m is not None else "по значению"
        head = f"{c['leader']} — первое место {by}: {fmt_value(lv.value, c.get('unit_short'))}"
        neg = _f(fs, "negatives")
        if neg is not None:
            forms = c.get("entity_forms") or ("строка", "строки", "строк")
            head += f", {count_words(int(neg.value), *forms)} в минусе"
        return head, c.get("caption")
    count = _f(fs, "count")
    if count is not None:
        forms = c.get("entity_forms") or ("строка", "строки", "строк")
        head = count_words(int(count.value), *forms)
        groups = _f(fs, "groups")
        if groups is not None and c.get("group_forms"):
            gn = int(groups.value)
            gf = c["group_forms"]
            head += f" из {fmt_num(gn)} {gf[0] if plural(gn, 1, 2, 3) == 1 else gf[1]}"
        return head, c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _kpi(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    a, b = _f(fs, "kpi_a"), _f(fs, "kpi_b")
    a_name: str = c.get("a_name", "")
    if a is not None and b is not None:
        ga: Gender = c.get("a_gender", "m")
        b_gen = c.get("b_gen")
        sa = fmt_signed(c["a_signed"], c.get("a_unit") or "")
        sb = fmt_signed(c["b_signed"], c.get("b_unit") or "")
        if c["a_signed"] > 0 and c["b_signed"] > 0 and b_gen:
            cmp_word = "быстрее" if c["a_signed"] > c["b_signed"] else "медленнее" if c["a_signed"] < c["b_signed"] else None
            if cmp_word:
                return f"{a_name} {verb('grow', ga, past=False)} {cmp_word} {b_gen}: {sa} против {sb}", c.get("caption")
        if c["a_signed"] > 0 > c["b_signed"]:
            gb: Gender = c.get("b_gender", "m")
            return (f"{a_name} {verb('grow', ga, past=False)}, а {lower_first(c.get('b_name', ''))} "
                    f"{verb('fall', gb, past=False)}: {sa} и {sb}"), c.get("caption")
        return f"{a_name}: {sa}, {lower_first(c.get('b_name', ''))}: {sb}", c.get("caption")
    if a is not None:
        ga = c.get("a_gender", "m")
        v = verb("grow" if c["a_signed"] > 0 else "fall", ga)
        return f"{a_name} {v} на {fmt_pct(abs(c['a_signed']))}%" if c.get("a_unit") == "%" else \
            f"{a_name}: {fmt_signed(c['a_signed'], c.get('a_unit') or '')}", c.get("caption")
    val = _f(fs, "kpi_value")
    if val is not None:
        return f"{a_name} — {c.get('a_value_text')}", c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _relationship(fs: FactSet) -> tuple[str, Optional[str]]:
    c = fs.ctx
    r = _f(fs, "r")
    if r is None:
        return c.get("plain", ""), c.get("caption")
    x, y = c["x"], c["y"]
    rv = c["r_signed"]
    rt = fmt_num(rv, 2)
    if abs(rv) < 0.3:
        return f"{upper_first(x)} и {lower_first(y)} почти не связаны: r = {rt}", c.get("caption")
    more = "выше"
    other = "выше" if rv > 0 else "ниже"
    strength = "" if abs(rv) >= 0.7 else ", но связь умеренная"
    return f"Чем {more} {lower_first(x)}, тем {other} {lower_first(y)}{strength}: r = {rt}", c.get("caption")
