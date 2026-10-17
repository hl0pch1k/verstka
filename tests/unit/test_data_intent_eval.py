"""Точность понимания целей брифа (раунд 10): ручная разметка (`tests/fixtures/intent/labels.json`) — все брифы
проверок conv4 (90) и conv3 (76) и брифы двух наборов-примеров (SCENARIO.md), по каждой цели: датасет, задача,
колонка-величина, что спрошено, агрегация, период.

Без модели точность считается здесь же, правилами (`goals_of` → `assign_goals` → колонка плана). С моделью — по
записанным ответам Qwen3.8-27B на VK (`tests/fixtures/intent/answers.json`, живой прогон — по одному вызову,
`scratchpad/intent/eval.py`): код проверяет каждый ответ так же, как в генерации, — тест модели не зовёт.

`load_cases()` и `score()` использует и живой прогон."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from verstka.data.intent import GoalReading, GoalsRead, read_goals, rules_goals
from verstka.data.readers import read_bytes, read_file
from verstka.schemas.data import Table

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "tests" / "fixtures" / "intent" / "labels.json"
ANSWERS = ROOT / "tests" / "fixtures" / "intent" / "answers.json"


# ── the corpus ───────────────────────────────────────────────────────────────────────────────────────────────────────
HOLDOUT = ROOT / "tests" / "fixtures" / "intent" / "holdout.json"
_EXAMPLES = {"sales": "examples/data-sales-2026", "science": "examples/data-science-2026"}


def load_cases(path: Path = LABELS) -> list[tuple[dict, list[Table]]]:
    """(разметка брифа, таблицы его датасетов) — таблицы conv3/conv4 строит генератор проверок
    (`test_data_factcheck`), наборы-примеры читаются из `examples/`. Источник — по id («c4-01A») или полю `src`
    («c4:01», «c3:05», «sales»)."""
    from tests.unit.test_data_factcheck import corpus_conv3, corpus_conv4

    labels = json.loads(path.read_text(encoding="utf-8"))["briefs"]
    c4 = {k: files for k, files, _ in corpus_conv4()}
    c3 = {k: files for k, files, _a, _b in corpus_conv3()}
    cache: dict[str, list[Table]] = {}
    out = []
    for lab in labels:
        src = lab.get("src") or (f"c4:{lab['id'][3:5]}" if lab["id"].startswith("c4-") else
                                 f"c3:{lab['id'][3:5]}" if lab["id"].startswith("c3-") else lab["id"])
        if src not in cache:
            if src.startswith("c4:"):
                tables = [t for name, b in c4[src[3:]] for t in read_bytes(name, b)]
            elif src.startswith("c3:"):
                tables = [t for name, b in c3[src[3:]] for t in read_bytes(name, b)]
            elif lab.get("files"):
                tables = [t for f in lab["files"] for t in read_file(ROOT / f)]
            else:
                d = ROOT / _EXAMPLES[src]
                tables = [t for f in sorted(d.iterdir()) if f.is_file() and f.suffix in (".csv", ".xlsx", ".json", ".txt")
                          for t in read_file(f)]
            cache[src] = tables
        out.append((lab, cache[src]))
    return out


# ── the score ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _n(s: Any) -> Optional[str]:
    return None if s is None else " ".join(str(s).lower().replace("ё", "е").split())


def _ask(a: Optional[str]) -> Optional[str]:
    if a in (None, "", "max", "none", "null"):
        return None
    if a.startswith(("above:", "below:")):
        side, v = a.split(":", 1)
        try:
            return f"{side}:{float(v.replace(',', '.')):g}"
        except ValueError:
            return a
    return a


def _in(pred: Any, allowed: Any, norm=_n) -> bool:
    if allowed == "ANY":
        return True
    allowed = allowed if isinstance(allowed, list) else [allowed]
    return norm(pred) in {norm(x) for x in allowed}


def _file_of(u) -> str:
    return f"{u.file}#{u.sheet}" if u.sheet and u.file.endswith((".txt", ".md")) else u.file


def _fields(e: dict, u) -> dict[str, bool]:
    """Каждое поле понятой цели `u` против ожидаемой `e` (с допустимыми прочтениями `alts`)."""
    best: dict[str, bool] = {}
    for spec in [e] + [{**e, **alt} for alt in e.get("alts", [])]:
        task = _in(u.task, spec["t"], str)
        metric = _in(u.metric, spec.get("m", "ANY"))
        ask = _in(_ask(u.ask), spec.get("a"), _ask)
        agg = "g" not in spec or _in(u.aggregation, spec["g"], lambda x: x)
        period = _in((u.period.kind if u.period is not None else "all"), spec.get("p", "all"), lambda x: x or "all")
        r = {"task": task, "metric": task and metric, "ask": ask, "agg": agg, "period": period,
             "full": task and metric and ask and agg and period}
        if sum(r.values()) > sum(best.values()) if best else True:
            best = r
    return best


def score(lab: dict, res: GoalsRead) -> list[dict[str, bool]]:
    """По каждой ожидаемой цели брифа: верны ли датасет и задача, колонка, вопрос, агрегация, период, всё вместе.
    Честная пометка «данные не отвечают» засчитывается там, где разметка её допускает (`ok_miss`)."""
    out = []
    for e in lab["goals"]:
        cands = [u for u in res.understood if _file_of(u) == e["f"] or u.file == e["f"]]
        best = {"task": False, "metric": False, "ask": False, "agg": False, "period": False, "full": False}
        for u in cands:
            r = _fields(e, u)
            if (r["full"], r["metric"], r["task"], sum(r.values())) > (best["full"], best["metric"], best["task"],
                                                                       sum(best.values())):
                best = r
        if not best["full"] and e.get("ok_miss") and any(n.file in (None, e["f"].split("#")[0]) for n in res.notes):
            best = {k: True for k in best}
        out.append(best)
    return out


def totals(rows: list[list[dict[str, bool]]]) -> dict[str, float]:
    flat = [g for r in rows for g in r]
    n = len(flat) or 1
    out = {k: round(sum(1 for g in flat if g[k]) / n, 3) for k in ("task", "metric", "ask", "agg", "period", "full")}
    out["goals"] = len(flat)
    out["briefs_full"] = round(sum(1 for r in rows if all(g["full"] for g in r)) / (len(rows) or 1), 3)
    return out


def _clear_given() -> None:
    """Цели, понятые снаружи, план помнит по фразе (`plan._GIVEN`): правила считаются без памяти о прошлых прогонах."""
    import verstka.data.plan as plan

    getattr(plan, "_GIVEN", {}).clear()


# ── the tests ────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_labels_cover_the_corpus(cases):
    ids = [lab["id"] for lab, _ in cases]
    assert len(ids) == len(set(ids)) == 168
    assert sum(1 for i in ids if i.startswith("c4-")) == 90 and sum(1 for i in ids if i.startswith("c3-")) == 76
    for lab, tables in cases:
        files = {t.file for t in tables} | {f"{t.file}#{t.sheet}" for t in tables if t.sheet}
        for e in lab["goals"]:
            assert e["f"] in files, (lab["id"], e["f"], files)


def test_rules_accuracy_is_measured(cases):
    """Без модели: правила. Число — для отчёта (раунд 10: см. .superpowers/sdd/s2/intent-report.md); тест держит
    только нижнюю границу, чтобы правка правил не обрушила их молча."""
    _clear_given()
    rows = [score(lab, rules_goals(lab["brief"], tables)) for lab, tables in cases]
    t = totals(rows)
    print("rules", t)
    assert t["goals"] == 182
    assert t["task"] >= 0.6 and t["full"] >= 0.3, t


def _model_rows(cases) -> tuple[list, list]:
    """Записанные ответы — для этих подсказок навыка и этих таблиц: подсказки изменились или больше пятой части таблиц
    читается иначе — тест падает и просит перезаписать ответы (живой прогон, `scratchpad/intent/eval.py live`)."""
    from verstka.data.intent import SKILL, _table_sha
    from verstka.skills_registry import SkillsRegistry

    rec = json.loads(ANSWERS.read_text(encoding="utf-8"))
    sha = SkillsRegistry.load().get(SKILL).sha256
    if rec.get("skill_sha256") != sha:
        pytest.fail(f"подсказки навыка {SKILL} изменились после записи ответов ({str(rec.get('skill_sha256'))[:8]} → "
                    f"{sha[:8]}): перезапишите tests/fixtures/intent/answers.json живым прогоном")
    answers = rec["answers"]
    rows, stale = [], []
    for lab, tables in cases:
        a = answers.get(lab["id"])
        if a is not None and a.get("tables_sha") and a["tables_sha"] != [_table_sha(t) for t in tables]:
            stale.append(lab["id"])  # the reader reads these files otherwise now: the answer was for other columns
            continue
        _clear_given()
        if a is None or a.get("reading") is None:
            res = rules_goals(lab["brief"], tables)  # the call failed: the rules, as in the generation
        else:
            res = read_goals(lab["brief"], tables, reading=GoalReading.model_validate(a["reading"]))
        rows.append(score(lab, res))
    if len(stale) > len(cases) // 5:
        pytest.fail(f"таблицы читаются иначе, чем при записи ответов ({len(stale)} из {len(cases)}: {', '.join(stale[:12])}"
                    f"): перезапишите эти ответы в tests/fixtures/intent/answers.json живым прогоном")
    return rows, stale


@pytest.mark.skipif(not ANSWERS.exists(), reason="ответы модели ещё не записаны")
def test_model_accuracy_on_recorded_answers(cases):
    """С моделью: записанные ответы Qwen3.8-27B (VK) проходят ту же проверку кодом, что и в генерации; цель — ≥ 90%
    целей верны целиком (датасет, задача, колонка, вопрос, агрегация, период)."""
    rows, stale = _model_rows(cases)
    t = totals(rows)
    print("model", t, "stale", stale)
    assert t["full"] >= 0.9, t


@pytest.mark.skipif(not ANSWERS.exists(), reason="ответы модели ещё не записаны")
def test_model_accuracy_on_the_holdout():
    """Отложенные 30 брифов (размечены до прогона, подсказка на них не настраивалась): модель — ≥ 90% (правила при записи
    — 53%, печатаются для сравнения)."""
    cases = load_cases(HOLDOUT)
    rows, _ = _model_rows(cases)
    _clear_given()
    rules = totals([score(lab, rules_goals(lab["brief"], tables)) for lab, tables in cases])
    t = totals(rows)
    print("holdout model", t, "rules", rules)
    assert t["full"] >= 0.9, (t, rules)
