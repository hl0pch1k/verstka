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

__all__ = ["ratio_spec", "apply", "MARK"]

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
