"""POST /api/goals — «Цели из текста» (раунд 10): цели брифа над приложенными файлами с подписями для человека;
с моделью — понятые ею и проверенные кодом, без модели — разбор правил. Сеть закрыта (tests/conftest.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store
from verstka.data import intent
from verstka.providers.registry import ProviderRegistry

REGIONS = ("Регион;Заявлений, тыс.;Доля онлайн, %;Срок рассмотрения, дн.\n"
           "Северный;210;64;11,5\nЮжный;410;71;9\nВосточный;180;52;14\nЗападный;150;48;16,5\nГорный;38;31;21,5\n"
           ).encode("utf-8")
BRIEF = "Где дольше всего ждут решения по заявлению? Сколько платят сотрудникам?"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "store", Store(tmp_path))
    intent.clear_cache()
    yield TestClient(A.app)
    intent.clear_cache()


def _upload(c: TestClient) -> str:
    r = c.post("/api/datasets", files=[("files", ("Госуслуги регионы.csv", REGIONS, "text/csv"))])
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def test_goals_without_a_model_are_the_rules(api, monkeypatch):
    monkeypatch.setattr(A, "providers", lambda: None)
    did = _upload(api)
    r = api.post("/api/goals", json={"brief": BRIEF, "dataset_ids": [did]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "rules" and body["skipped"] == "без модели"
    g = body["goals"][0]
    assert g["dataset_id"] == did and g["task"] == "comparison" and g["task_title"] == "Сравнение категорий"
    assert g["label"].startswith("Сравнение категорий") and g["viz_title"] == "столбцы"


def test_goals_with_the_model_are_checked_and_cached(api, monkeypatch):
    calls = []

    def answer(messages):
        calls.append(1)
        return {"goals": [{"span": "Где дольше всего ждут решения по заявлению?", "dataset": "d1",
                           "task": "comparison", "metric": "Срок рассмотрения", "ask": "max", "direction": "lower",
                           "confidence": 0.9},
                          {"span": "Где дольше всего", "dataset": "d1", "task": "comparison", "metric": "Зарплата"}],
                "unanswerable": [{"span": "Сколько платят сотрудникам?", "reason": "в данных нет зарплат",
                                  "dataset": "d1"}]}

    prov = ProviderRegistry.mock({"*": answer})
    monkeypatch.setattr(A, "providers", lambda: prov)
    did = _upload(api)
    body = api.post("/api/goals", json={"brief": BRIEF, "dataset_ids": [did]}).json()
    assert body["source"] == "model" and not body["cached"]
    main = next(g for g in body["goals"] if g["metric"] == "Срок рассмотрения")
    assert main["ask"] == "max" and main["source"] == "model" and "«Срок рассмотрения»" in main["label"]
    other = next(g for g in body["goals"] if g["quote"] == "Где дольше всего")
    assert other["metric"] is None and any("Зарплата" in x for x in other["dropped"])
    assert body["notes"] == [{"quote": "Сколько платят сотрудникам?", "reason": "в данных нет зарплат",
                              "dataset_id": did, "file": "Госуслуги регионы.csv", "source": "model"}]
    again = api.post("/api/goals", json={"brief": BRIEF, "dataset_ids": [did]}).json()
    assert again["cached"] and len(calls) == 1
    # «Модель пишет тексты слайдов» off — the rules, no call
    off = api.post("/api/goals", json={"brief": BRIEF, "dataset_ids": [did], "use_models": False}).json()
    assert off["source"] == "rules" and len(calls) == 1


def test_goals_of_a_missing_dataset(api, monkeypatch):
    monkeypatch.setattr(A, "providers", lambda: None)
    r = api.post("/api/goals", json={"brief": BRIEF, "dataset_ids": ["nope0000"]})
    assert r.status_code == 404
