"""Ход чтения брендбука: шаги `on_step` приходят по мере чтения (PDF — до запроса к модели, который идёт до двух минут), с
прочитанной частью, и «страница N из M» по ходу; обработчик с двумя аргументами работает как раньше. Модель подменена."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verstka.brand.common import STEP_KEYS, StepReporter, step_partials
from verstka.brand.pdf import read_pdf
from verstka.brand.read import brand_partials, brand_steps, read_brandbook
from verstka.providers.registry import ProviderRegistry

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "brandbook-vk-cloud"
WHAT = {"open": "открыт файл", "palette": "палитра", "fonts": "шрифты", "logos": "логотипы", "rules": "правила"}


def _keys(events: list[tuple]) -> list[str]:
    """Ключи шагов событий (ход чтения — «страница», «модель» — по своим словам)."""
    by_what = {v: k for k, v in WHAT.items()}
    return [by_what.get(e[0], e[0]) for e in events]


def test_pdf_steps_arrive_while_reading_before_the_model_answers_and_carry_their_part(tmp_path):
    events: list[tuple] = []
    at_model: list[tuple] = []
    reading = {"name": "VK Cloud", "colors": [{"hex": "#2787F5", "role": "chart"}], "rules": [{"text": "Фото — только в полный слайд", "kind": "other"}]}

    def answer(messages):  # модель отвечает: к этому моменту интерфейс уже должен был получить разбор по тексту
        at_model.extend(events)
        return reading

    providers = ProviderRegistry.mock({"brand guideline": answer})
    spec = read_brandbook(SAMPLE / "guideline.pdf", providers=providers, use_vlm=True, assets_dir=tmp_path,
                          on_step=lambda what, result, part: events.append((what, result, part)))
    assert [e[0] for e in at_model[:5]] == ["открыт файл", "палитра", "шрифты", "логотипы", "правила"]  # все пять — до ответа модели
    assert at_model[0][1:] == ("12 страниц", {"name": "VK Cloud", "source": "pdf", "file": "guideline.pdf", "pages": 12})
    assert at_model[1][1] == "6 цветов" and {c["hex"] for c in at_model[1][2]["colors"]} >= {"#0077FF", "#FF3985"}
    assert at_model[2][1] == "VK Sans Display, VK Sans Text" and [f["role"] for f in at_model[2][2]["fonts"]] == ["heading", "body"]
    assert at_model[3][1] == "4" and len(at_model[3][2]["logos"]) == 4
    assert at_model[4][2]["margins_px"] == 48 and at_model[4][2]["logo_place"] == "bottom_right" and at_model[4][2]["rules"]
    pages = [e for e in at_model if e[0] == "страница"]  # «страница N из M» по ходу, а не одним куском
    assert [e[1] for e in pages] == [f"{k} из 6" for k in range(1, 7)] and all(e[2] is None for e in pages)
    assert at_model[-1][0] == "модель" and at_model[-1][1] == "читает 6 страниц"
    # шаги, которые модель изменила (роль #2787F5 → графики, новое правило), повторяются с новым итогом
    later = events[len(at_model):]
    assert _keys(later) == ["palette", "rules"]
    assert next(c for c in later[0][2]["colors"] if c["hex"] == "#2787F5")["role"] == "chart"
    assert any(r["text"] == "Фото — только в полный слайд" for r in later[1][2]["rules"])
    # последнее слово каждого шага совпадает с итогом, и всё сказано до возврата
    last = {_keys([e])[0]: e for e in events if _keys([e])[0] in STEP_KEYS}
    parts = step_partials(spec)
    assert {k: last[k][2] for k in STEP_KEYS} == {k: parts[k] for k in STEP_KEYS} | {"rules": last["rules"][2]}
    assert last["rules"][2]["rules"] == parts["rules"]["rules"] and last["palette"][1] == "6 цветов"
    assert [(w, r) for k, (w, r, _) in ((k, last[k]) for k in STEP_KEYS)] == brand_steps(spec)


def test_a_two_argument_handler_keeps_working_and_the_text_steps_equal_brand_steps():
    steps: list[tuple] = []
    spec = read_brandbook(SAMPLE / "guideline.pdf", on_step=lambda what, result: steps.append((what, result)))
    assert steps == brand_steps(spec)  # без модели — ровно пять шагов по порядку, без повторов
    assert [s[0] for s in steps] == ["открыт файл", "палитра", "шрифты", "логотипы", "правила"]
    named: list[tuple] = []

    def three(what, result, partial):
        named.append((what, result, partial))

    read_brandbook(SAMPLE / "guideline.pdf", on_step=three)
    assert [e[0] for e in named] == [s[0] for s in steps] and all(e[2] for e in named)
    star: list[tuple] = []
    read_brandbook(SAMPLE / "tokens.json", on_step=lambda *args: star.append(args))  # *args получает и часть
    assert len(star) == 5 and all(len(a) == 3 and a[2] for a in star)


@pytest.mark.parametrize("source, first", [("tokens.json", "прочитаны токены"), ("tokens-studio.json", "прочитаны токены"), (".", "открыта папка")])
def test_fast_readers_say_all_five_steps_once_in_order(source, first):
    events: list[tuple] = []
    spec = read_brandbook(SAMPLE / source, on_step=lambda what, result, part: events.append((what, result, part)))
    assert [e[0] for e in events] == [first, "палитра", "шрифты", "логотипы", "правила"]
    assert [(e[0], e[1]) for e in events] == brand_steps(spec)
    assert [e[2] for e in events] == brand_partials(spec)


def test_the_page_progress_of_a_pdf_inside_a_folder_comes_before_the_folders_own_steps(tmp_path):
    root = tmp_path / "bb"
    root.mkdir()
    shutil.copy(SAMPLE / "guideline.pdf", root / "guideline.pdf")
    events: list[tuple] = []
    providers = ProviderRegistry.mock({"brand guideline": {"name": "VK Cloud"}})
    spec = read_brandbook(root, providers=providers, use_vlm=True, on_step=lambda what, result, part: events.append((what, result, part)))
    assert [e[0] for e in events[:7]] == ["страница"] * 6 + ["модель"]  # палитра папки ещё неизвестна: идёт ход модели
    assert [e[0] for e in events[7:]] == ["открыта папка", "палитра", "шрифты", "логотипы", "правила"]
    assert [(e[0], e[1]) for e in events[7:]] == brand_steps(spec)


def test_the_model_failing_leaves_the_text_steps_and_says_nothing_extra(tmp_path):
    events: list[tuple] = []
    providers = ProviderRegistry.mock({"nothing matches": {}})
    spec = read_pdf(SAMPLE / "guideline.pdf", providers=providers, use_vlm=True, on_step=lambda what, result, part: events.append((what, result, part)))
    assert any("Модель не смогла" in w for w in spec.warnings)
    assert _keys(events)[:5] == list(STEP_KEYS) and "модель" in _keys(events)
    assert _keys(events)[-1] == "rules"  # предупреждение модели попало в итог шага «правила»
    assert events[-1][2]["warnings"] == spec.warnings


def test_the_reporter_without_a_handler_is_silent_and_partials_are_plain_json():
    rep = StepReporter(None)
    rep.step("palette", "палитра", "нет", {})
    rep.progress("страница", "1 из 6")
    spec = read_brandbook(SAMPLE / "tokens.json")
    import json

    json.dumps(brand_partials(spec))  # то, что уходит в событие задачи, сериализуется как есть
    assert [set(p) for p in brand_partials(spec)][:2] == [{"name", "source", "file", "pages"}, {"colors"}]
