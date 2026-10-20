"""Величина на единицу из двух колонок (F2): «выручка на одного посетителя», «зрителей за сеанс», «доля ДМС в выплатах
региона», «не сдали относительно числа сдававших», «заявлений на место».

Бриф спрашивает отношение, а в таблице — только числитель и знаменатель. Колонка-отношение добавляется к таблице
(`apply`): у каждой строки — числитель / знаменатель (с множителями единиц: «тыс. ₽» на «чел.» — рубли на человека),
доля в процентах — когда числитель — часть знаменателя (не сдавшие из сдававших); а у категории из нескольких строк —
среднее с весом по знаменателю, то есть Σчислитель / Σзнаменатель (`weight`). Колонка — данные таблицы: проверка
(`verify`) пересчитывает вывод по ней же, «Пересобрать слайд» добавляет её снова по `spec` плана."""

from __future__ import annotations

import math
import re
from typing import Any, Optional

from verstka.data.parse import quantity
from verstka.data.words import stem, stems_of
from verstka.schemas.data import Table

__all__ = ["ratio_spec", "apply", "MARK", "funnel_columns", "metric_question", "metric_goals"]

MARK = "ratio"
_SCALE = {"тыс": 1e3, "тыс.": 1e3, "млн": 1e6, "млн.": 1e6, "млрд": 1e9, "млрд.": 1e9, "трлн": 1e12}
_MONEY = ("₽", "руб", "руб.", "$", "€")
# «на одного посетителя», «за сеанс», «в расчёте на одного читателя», «на место», «на одного активного члена»
_PER = re.compile(r"(?i)(?:в\s+расч[её]те\s+)?(?:на|за)\s+(?:одн(?:ого|у|о)\s+|1\s+)?(?:[а-яё]+\s+)?[а-яё]{3,}")


def _num(cell: Any) -> Optional[float]:
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    q = quantity(" ".join(str(cell).split()))
    return None if q is None else q.full


def _split(unit: Optional[str]) -> tuple[float, str]:
    """(множитель, основа единицы): «тыс. ₽» → (1000, «₽»), «млн ₽» → (1e6, «₽»), «тыс.» → (1000, «»)."""
    u = " ".join((unit or "").split())
    if not u:
        return 1.0, ""
    head, _, rest = u.partition(" ")
    if head.lower() in _SCALE:
        return _SCALE[head.lower()], rest.strip()
    return 1.0, u


def _col(t: Table, name: str) -> Optional[int]:
    for j, c in enumerate(t.columns):
        if c == name:
            return j
    for j, c in enumerate(t.columns):
        u = t.units[j] if j < len(t.units) else None
        if u and name in (f"{c}, {u}", f"{c} {u}", f"{c} ({u})"):
            return j
    return None


def _per_phrase(quote: str, den: str) -> Optional[str]:
    """Слова брифа о знаменателе («на одного посетителя», «за сеанс», «на одного активного члена»): слово после «на» /
    «за» (через «одного» и одно определение) — главное слово колонки-знаменателя (последнее: «Мест» у «Бюджет Мест»)."""
    ds = [stem(w) for w in stems_of(den)]
    if not ds:
        return None
    head = ds[-1]
    words = re.findall(r"[а-яё0-9]+", (quote or "").lower())
    for k, w in enumerate(words):
        if w not in ("на", "за"):
            continue
        lead = ["в", "расчете"] if k >= 2 and words[k - 2:k] in (["в", "расчете"], ["в", "расчёте"]) else []
        for e in range(k + 1, min(k + 4, len(words))):
            x = stem(words[e])
            if len(x) >= 4 and len(head) >= 4 and (x.startswith(head[:5]) or head.startswith(x[:5])):
                return " ".join(lead + words[k:e + 1])
            if not (words[e] in ("одного", "одну", "одно", "один", "1") or words[e].endswith(("ого", "его", "ых", "их"))):
                break
    return None


def ratio_spec(t: Table, num: str, den: str, quote: str = "") -> Optional[dict]:
    """Описание колонки-отношения `num` / `den` таблицы `t` (None — колонок нет, или знаменатель пуст / не
    положителен): имя, единица, множитель и доля ли это."""
    jn, jd = _col(t, num), _col(t, den)
    if jn is None or jd is None or jn == jd:
        return None
    un = t.units[jn] if jn < len(t.units) else None
    ud = t.units[jd] if jd < len(t.units) else None
    sn, bn = _split(un)
    sd, bd = _split(ud)
    pairs = [(_num(r[jn]) if jn < len(r) else None, _num(r[jd]) if jd < len(r) else None) for r in t.rows]
    body = [(a, b) for i, (a, b) in enumerate(pairs) if i not in set(t.totals) and a is not None and b is not None]
    if not body or any(b <= 0 for _, b in body):
        return None
    if bd == "%" or bn == "%":
        return None  # доля на долю — не «на единицу» (вероятность, процент — это произведение, а не отношение)
    money = bn in _MONEY or bn.startswith(("₽", "$", "€"))
    same = bn == bd or (not money and (not bn or not bd))
    # часть целого: числитель — из знаменателя (не сдавшие из сдававших, ДМС из всех выплат региона) — в процентах
    part = same and all(a * sn <= b * sd * (1 + 1e-9) for a, b in body)
    nb = re.sub(r"\s*,.*$", "", num).strip()
    db = re.sub(r"\s*,.*$", "", den).strip()
    if part:
        scale, unit = sn / sd * 100.0, "%"
        name = f"Доля «{nb}» от «{db}»"
    else:
        scale = sn / sd
        unit = bn if money and bd not in _MONEY else (None if not bn or bn == bd else f"{bn}")
        per = _per_phrase(quote, den)
        name = f"{nb} {per}" if per else f"{nb} на единицу «{db}»"
    if name in t.columns:
        name = f"{name} (расчёт)"
    return {"kind": MARK, "num": t.columns[jn], "den": t.columns[jd], "name": name[:120], "unit": unit,
            "scale": scale, "part": part}


def apply(t: Table, spec: Optional[dict]) -> Table:
    """Таблица с колонкой-отношением (та же таблица — если её уже добавили или `spec` не о ней)."""
    if not spec or spec.get("kind") != MARK or spec.get("name") in t.columns:
        return t
    jn, jd = _col(t, spec["num"]), _col(t, spec["den"])
    if jn is None or jd is None:
        return t
    scale = float(spec.get("scale") or 1.0)
    rows = []
    for r in t.rows:
        a = _num(r[jn]) if jn < len(r) else None
        b = _num(r[jd]) if jd < len(r) else None
        v = None if a is None or b is None or b <= 0 else a / b * scale
        if v is not None and spec.get("zero_none") and a == 0:
            v = None  # бесплатный канал: «0 ₽ на клиента» — не самый дешёвый, а без затрат (сказано отдельно)
        rows.append(list(r) + [None if v is None else round(v, 6)])
    units = list(t.units) + [None] * (len(t.columns) - len(t.units))
    raw = list(t.raw_header) + [""] * (len(t.columns) - len(t.raw_header))
    unit = spec.get("unit")
    groups = list(t.column_groups) + ([None] if t.column_groups else [])
    return t.model_copy(update={
        "columns": list(t.columns) + [spec["name"]], "units": units + [unit], "rows": rows,
        "raw_header": raw + [f"{spec['name']}, {unit}" if unit else spec["name"]], "column_groups": groups,
    })


# ── опечатки в подписях (F7) ─────────────────────────────────────────────────────────────────────────────────────────
def _dist(a: str, b: str) -> int:
    """Расстояние правки (вставка, удаление, замена) — для коротких подписей."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def merge_label_typos(t: Table) -> tuple[Table, list[str]]:
    """«Новосибрск» рядом с «Новосибирск»: редкая подпись в одну-две буквы от частой той же колонки — опечатка; её
    строки — строки частой (иначе опечатка становится отдельной категорией и лидирует). (таблица, пометки о слияниях)
    — пометка видна в контексте колоды. Цифры подписи должны совпадать («Школа № 12» и «Школа № 21» — разные)."""
    if len(t.rows) > 2000:
        return t, []
    notes: list[str] = []
    rows = [list(r) for r in t.rows]
    changed = False
    for j in range(len(t.columns)):
        vals = [r[j] for i, r in enumerate(rows) if j < len(r) and isinstance(r[j], str) and r[j].strip() and i not in set(t.totals)]
        if len(vals) < 4 or len(vals) < 0.8 * len(rows):
            continue
        counts: dict[str, int] = {}
        for v in vals:
            counts[v.strip()] = counts.get(v.strip(), 0) + 1
        if len(counts) > 60:
            continue
        fix: dict[str, str] = {}
        for a, na in counts.items():
            for b, nb in counts.items():
                if a == b or nb < 2 or na * 2 > nb or len(a) < 5 or len(b) < 5:
                    continue
                if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
                    continue
                d = _dist(a.lower(), b.lower())
                if 1 <= d <= (1 if len(b) < 8 else 2) and (a not in fix or _dist(a.lower(), fix[a].lower()) > d):
                    fix[a] = b
        if not fix:
            continue
        for r in rows:
            if j < len(r) and isinstance(r[j], str) and r[j].strip() in fix:
                r[j] = fix[r[j].strip()]
                changed = True
        for a, b in fix.items():
            notes.append(f"В «{t.file}» подпись «{a}» — опечатка «{b}»: её строки посчитаны вместе с «{b}»")
    if not changed:
        return t, []
    return t.model_copy(update={"rows": rows}), notes



# ── вопрос плана → производная мера (жюри 5): конверсия этапов воронки и стоимость единицы результата ────────────────
# «Где теряем?» над колонками «Лиды · Пилоты · Контракты» — конверсия каждого этапа и худший этап сегмента, а не «у кого
# больше пилотов»; «какой канал самый дешёвый» над «Новых клиентов · Затраты» — затраты на одного клиента (ноль затрат —
# не «самый дешёвый», а отдельная строка), а не «у кого меньше затрат». Колонка-отношение добавляется к таблице (`apply`),
# проверка (`verify`) пересчитывает вывод по ней; вопрос отвечает её крайним значением.
_LOSS_Q = re.compile(r"теря\w*|потер[ия]\w*|узк\w*\s+мест|застрева\w*|отвалива\w*|отсева\w*|"
                     r"доход(?:ит|ят)\s+до|где\s+(?:провал|просед|буксу)\w*", re.I)
_COST_Q = re.compile(r"дешев\w*|дешёв\w*|дорог\w*|обходит\w*|окупа\w*|эффективн\w*|стоимост\w*\s+(?:привлечен|клиент|лид)|"
                     r"(?:^|[^a-z])cac(?:[^a-z]|$)|цен\w*\s+(?:клиента|лида|заявки)|отказаться|в\s+расч[её]те\s+на|"
                     r"(?:на|за)\s+одного\s+(?:клиента|лида|покупател|пользовател|ученика|участника)", re.I)
_COST_COL = re.compile(r"затрат|расход|бюджет|стоимост|издерж|потрачен|вложен|инвестиц|маркетинг", re.I)
_COUNT_COL = re.compile(r"клиент|лид|заяв|покупател|пользовател|подписчик|контракт|сделк|заказ|установ|регистрац|"
                        r"абонент|ученик|студент|участник|пациент|продаж|конверси|подключен", re.I)
_PER_NAME = {"клиент": "клиента", "лид": "лид", "заяв": "заявку", "покупател": "покупателя", "пользовател": "пользователя",
             "подписчик": "подписчика", "контракт": "контракт", "сделк": "сделку", "заказ": "заказ",
             "установ": "установку", "регистрац": "регистрацию", "абонент": "абонента", "ученик": "ученика",
             "студент": "студента", "участник": "участника", "пациент": "пациента", "продаж": "продажу",
             "подключен": "подключение"}


def _numeric_cols(t: Table) -> list[int]:
    body = [r for i, r in enumerate(t.rows) if i not in set(t.totals)]
    out = []
    for j in range(len(t.columns)):
        vals = [_num(r[j]) if j < len(r) else None for r in body]
        if body and sum(v is not None for v in vals) >= max(2, int(0.8 * len(body))):
            out.append(j)
    return out


def funnel_columns(t: Table) -> list[int]:
    """Колонки-этапы воронки по порядку: от двух колонок-счётчиков (без единицы или «шт.», целые, ≥ 0), где в каждой
    строке каждый следующий этап не больше предыдущего, а хоть где-то меньше («Лиды ≥ Пилоты ≥ Контракты»). Самая
    длинная такая цепочка соседних колонок; [] — воронки нет."""
    body = [r for i, r in enumerate(t.rows) if i not in set(t.totals)]
    if len(body) < 2:
        return []
    cand = []
    for j in _numeric_cols(t):
        u = (t.units[j] if j < len(t.units) else None) or ""
        if u and u.strip(". ") not in ("шт", "чел", "ед"):
            continue
        vals = [_num(r[j]) if j < len(r) else None for r in body]
        if all(v is None or (v >= 0 and float(v).is_integer()) for v in vals):
            cand.append(j)
    best: list[int] = []
    k = 0
    while k < len(cand):
        run = [cand[k]]
        for j in cand[k + 1:]:
            prev = run[-1]
            ok, strict = True, False
            for r in body:
                a = _num(r[prev]) if prev < len(r) else None
                b = _num(r[j]) if j < len(r) else None
                if a is None or b is None:
                    continue
                if b > a:
                    ok = False
                    break
                strict = strict or b < a
            if not ok or not strict or j != prev + 1:
                break
            run.append(j)
        if len(run) > len(best):
            best = run
        k += 1
    return best if len(best) >= 2 else []


def _stage(name: str) -> str:
    return re.sub(r"\s*,.*$", "", name).strip()


def _conversion_spec(t: Table, a: int, b: int) -> Optional[dict]:
    spec = ratio_spec(t, t.columns[b], t.columns[a])
    if spec is None:
        return None
    name = f"Конверсия «{_stage(t.columns[a])}» → «{_stage(t.columns[b])}»"
    return {**spec, "name": name, "unit": "%", "scale": 100.0, "part": True, "funnel": True}


def _funnel_pick(t: Table, cols: list[int], words: str = "") -> Optional[tuple[int, int]]:
    """Этап, где теряют: у какого сегмента конверсия этапа дальше всего ниже конверсии этапа по всем строкам (20% у
    госсектора при 39% в целом); этап, который называет вопрос («застревает на пилоте»), — первым."""
    body = [r for i, r in enumerate(t.rows) if i not in set(t.totals)]
    best = None
    named = [k for k in range(len(cols) - 1) if any(
        w and len(w) >= 4 and (w in stem(_stage(t.columns[cols[k]])) or stem(_stage(t.columns[cols[k]])).startswith(w[:5]))
        for w in stems_of(words))]
    for k in range(len(cols) - 1):
        a, b = cols[k], cols[k + 1]
        pairs = [(_num(r[a]), _num(r[b])) for r in body]
        pairs = [(x, y) for x, y in pairs if x and y is not None and x > 0]
        if len(pairs) < 2:
            continue
        overall = sum(y for _, y in pairs) / sum(x for x, _ in pairs)
        worst = min(y / x for x, y in pairs)
        gap = worst / overall if overall > 0 else 1.0
        key = (0 if k in named else 1, gap)
        if best is None or key < best[0]:
            best = (key, (a, b))
    return best[1] if best is not None else None


def _cost_pair(t: Table) -> Optional[tuple[int, int]]:
    """(затраты, счёт результата): денежная колонка расходов и колонка-счётчик в одной строке («Затраты, тыс. ₽» и «Новых
    клиентов»)."""
    nums = _numeric_cols(t)
    cost = [j for j in nums if _COST_COL.search(t.columns[j]) and (
        (t.units[j] if j < len(t.units) else "") or "").strip().endswith(("₽", "$", "€", "руб", "руб."))]
    cnt = [j for j in nums if j not in cost and _COUNT_COL.search(t.columns[j]) and not (
        (t.units[j] if j < len(t.units) else "") or "").strip().endswith(("₽", "$", "€", "%"))]
    if len(cost) != 1 or not cnt:
        return None
    return cost[0], cnt[0]


def _cost_spec(t: Table, num: int, den: int) -> Optional[dict]:
    body = [r for i, r in enumerate(t.rows) if i not in set(t.totals)]
    if any((_num(r[den]) or 0) <= 0 for r in body if den < len(r)):
        return None
    spec = ratio_spec(t, t.columns[num], t.columns[den], "")
    if spec is None or spec.get("part"):
        return None
    un = (t.units[num] if num < len(t.units) else None) or ""
    ud = (t.units[den] if den < len(t.units) else None) or ""
    if un and (not ud or ud.strip(". ") in ("шт", "чел", "ед")):
        # затраты в «тыс. ₽» на одного клиента — тоже в «тыс. ₽» (40 тыс. ₽, а не 40 000 ₽): единица числителя
        spec = {**spec, "scale": 1.0, "unit": un}
    dn = t.columns[den].lower()
    per = next((v for k_, v in _PER_NAME.items() if k_ in dn), None)
    nb = _stage(t.columns[num])
    name = f"{nb} на одного {per}" if per and per.endswith(("а", "я")) and not per.endswith(("ку", "ю")) else (
        f"{nb} на {per}" if per else spec["name"])
    zero = any(_num(r[num]) == 0 for r in body if num < len(r))
    return {**spec, "name": name[:120], "zero_none": zero}


def _per_unit(text: str, t: Table) -> Optional[dict]:
    """«Выручка на одно место падает?»: величина «на одного X» — колонка-отношение числителя (слово до «на») к колонке
    X (слово после «на одного»), если обе есть в таблице и такой колонки-отношения ещё нет."""
    m = re.search(r"([а-яё]{4,})\s+(?:в\s+расч[её]те\s+)?(?:на|за)\s+(?:одн(?:ого|у|о)\s+|1\s+)([а-яё]{3,})", text)
    if not m:
        return None
    a, b = stem(m.group(1)), stem(m.group(2))
    nums = _numeric_cols(t)

    def hit(w: str) -> list[int]:
        return [j for j in nums if any(x.startswith(w[:5]) or w.startswith(x[:5]) for x in stems_of(t.columns[j])
                                       if len(x) >= 3)]
    na, nb = hit(a), hit(b)
    if len(na) != 1 or not nb or na[0] in nb:
        return None
    spec = ratio_spec(t, t.columns[na[0]], t.columns[nb[0]], text)
    if spec is None:
        return None
    return {"spec": spec, "ask": None, "kind": "per_unit"}


def metric_question(phrase: Optional[str], t: Table) -> Optional[dict]:
    """Производная мера, которой отвечают на вопрос `phrase` (None — вопроса нет: мера по профилю таблицы): {"spec":
    колонка-отношение, "ask": "min" | "max", "kind": "funnel" | "cost", "note": что сказано про нули}. None — этот
    вопрос (или таблица) производной меры не требует."""
    text = " ".join((phrase or "").lower().split())
    if not text:
        return None  # мера — только по вопросу: без вопроса таблица отвечает своим обычным выводом
    cols = funnel_columns(t)
    if cols and _LOSS_Q.search(text):
        pick = _funnel_pick(t, cols, text)
        spec = _conversion_spec(t, *pick) if pick else None
        if spec is not None:
            return {"spec": spec, "ask": "min", "kind": "funnel"}
    per = _per_unit(text, t) if text else None
    if per is not None:
        return per
    pair = _cost_pair(t)
    if pair is not None and _COST_Q.search(text):
        spec = _cost_spec(t, *pair)
        if spec is not None:
            # «от какого отказаться», «какой дороже всех» — самый дорогой; иначе — самый дешёвый
            dear = bool(re.search(r"дорож\w*|дороже|отказа\w*|убыточ\w*|неэффективн\w*", text)) and not re.search(
                r"дешев|дешёв", text)
            return {"spec": spec, "ask": "max" if dear else "min", "kind": "cost"}
    return None


def metric_goals(table: Table, goals: list, *, default: bool = False) -> tuple[Table, list, Optional[dict]]:
    """Цели датасета глазами производной меры: цель-вопрос «где теряем», «какой канал дешевле» (или, без целей, сама
    таблица-воронка и таблица «затраты и результат») — цель, понятая точно: колонка-отношение, вопрос «min»/«max».
    (таблица с колонкой-отношением, цели, мера) — или исходные, если мера не нужна. Цели модели с колонкой не трогаются."""
    from verstka.data.goals import Goal

    out = list(goals)
    for k, g in enumerate(goals):
        if getattr(g, "given", False) and (g.column or g.derive):
            continue
        mq = metric_question(g.phrase, table)
        if mq is None:
            continue
        spec = mq["spec"]
        task = g.task if mq["kind"] == "per_unit" else "comparison"
        mg = Goal(phrase=g.phrase, task=task, viz="line" if task == "dynamics" else "bar",
                  to="линейный график" if task == "dynamics" else "столбцы", subject=list(g.subject), at=g.at,
                  given=True, column=spec["name"], ask=mq["ask"], derive=spec)
        # вопрос, которому отвечает мера, — главный у этого датасета: первым (задачу решает первая осуществимая цель)
        return apply(table, spec), [mg] + [x for i, x in enumerate(out) if i != k], mq
    if default and not [g for g in goals if not g.unmet]:
        mq = metric_question(None, table)
        if mq is not None:
            spec = mq["spec"]
            g = Goal(phrase="", task="comparison", viz="bar", to="столбцы", given=True, column=spec["name"],
                     ask=mq["ask"], derive=spec)
            return apply(table, spec), [*out, g], mq
    return table, out, None
