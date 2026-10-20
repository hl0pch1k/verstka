"""The live lecture on the derivative (VK Education, 20.10): Verstka chose «касательная», «геометрический смысл» and
«определение» for its pictures, spent two attempts on each (Z-Image draws no mathematics), started its second chance on
the 4th minute and left the vision model no time — 7 pictures drawn for a limit of 4, a turbine nobody had checked. Here:
the first choice is the most concrete slides (an abstract slide never while a concrete one is free), a scene is the
slide's most concrete sentence, the pictures start right after the plan with their own time for the vision model, and
the image model's calls for Verstka's own pictures are limited to the owner's minimum × 2. No live model is called."""

from __future__ import annotations

import json
import time
from concurrent.futures import Future
from pathlib import Path

import pytest
from PIL import Image

from verstka.images import providers as IP
from verstka.images.prompt import ImageAsk
from verstka.images.text_check import PictureNotFitting, TextCheck
from verstka.planning.pictures import AUTO_LABEL, SCENE, concreteness, ensure_pictures, is_abstract, scene_words, writer_places_as_own
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent

TPL = Path(__file__).resolve().parents[1] / "fixtures" / "tpl_audit" / "templates" / "lo_focus.pptx"


def _sl(i, head, bullets, kind=K.bullets, **content):
    return OutlineSlide(id=f"s{i}", kind=kind, headline=head, content=SlideContent(bullets=bullets, **content))


def _lecture() -> DeckOutline:
    """The lecture's slides as the writer laid them out (short enough for a picture each)."""
    return DeckOutline(title="Производная функции", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Производная функции"),
        _sl(1, "Определение производной", ["Производная — предел отношения приращения функции к приращению аргумента."]),
        _sl(2, "Производная — мгновенная скорость", ["Средняя скорость считается на отрезке времени.", "Спидометр автомобиля показывает скорость в данный момент."]),
        _sl(3, "Производная равна угловому коэффициенту касательной", ["Касательная — предельное положение секущей."]),
        _sl(4, "Геометрический смысл производной", ["Наклон касательной к графику в точке."]),
        _sl(5, "Правила дифференцирования", ["Производная суммы равна сумме производных."]),
        _sl(6, "Производная описывает изменения в экономике и технике", ["Производная применяется для анализа процессов.", "Курьер на велосипеде разгоняется на прямой улице."]),
        _sl(7, "Итоги", ["Производная — предел отношения приращений."]),
    ])


def test_the_first_choice_never_takes_an_abstract_slide_while_a_concrete_one_is_free():
    o = _lecture()
    assert all(is_abstract(o.slides[k]) for k in (1, 3, 4, 5))
    assert not is_abstract(o.slides[2]) and not is_abstract(o.slides[6])
    assert concreteness(o.slides[2]) > concreteness(o.slides[7]) > concreteness(o.slides[1])
    ensure_pictures([o], "")
    chosen = [k for k, s in enumerate(o.slides) if s.content.photo_slot]
    assert chosen == [2, 6], chosen  # the speedometer and the courier, never «касательная», «смысл», «определение»
    # the scene is the slide's own concrete situation, not its first (general) words
    assert "Спидометр автомобиля" in o.slides[2].content.photo_hint
    assert "Курьер на велосипеде" in o.slides[6].content.photo_hint
    assert all(o.slides[k].content.photo_hint.startswith(SCENE) for k in chosen)


def test_verstkas_own_place_on_an_abstract_slide_moves_to_a_concrete_one():
    """The writer chose «касательная» (made Verstka's own): the place goes there where one can see something."""
    o = _lecture()
    o.slides[3].content.photo_slot, o.slides[3].content.photo_hint = AUTO_LABEL, "Касательная прямая к параболе"
    out = ensure_pictures([o], "")
    assert not o.slides[3].content.photo_slot
    assert any("moved off slide 4" in w for w in out)
    assert [k for k, s in enumerate(o.slides) if s.content.photo_slot] == [2, 6]


def test_an_abstract_slide_is_chosen_only_when_nothing_else_is_free():
    o = DeckOutline(title="Производная", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Производная"),
        _sl(1, "Определение производной", ["Предел отношения приращений."]),
        _sl(2, "Таблица", [], kind=K.table, table={"columns": ["f", "f'"], "rows": [["x²", "2x"]]}),
    ])
    ensure_pictures([o], "")
    assert o.slides[1].content.photo_slot == AUTO_LABEL  # the owner's minimum still holds


def test_a_concrete_slide_too_long_for_half_comes_before_a_definition():
    """The lecture's «Мгновенная скорость» laid out as steps was no candidate of the first choice: the pictures went to
    «касательная». A concrete slide the renderer can narrow for a strip comes first now."""
    from verstka.schemas.outline import SlideItem

    o = DeckOutline(title="Производная", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Производная"),
        _sl(1, "Определение производной", ["Предел отношения приращений."]),
        OutlineSlide(id="v", kind=K.process, headline="Мгновенная скорость автомобиля",
                     content=SlideContent(items=[SlideItem(title=f"Шаг {i}", text="Средняя скорость на малом отрезке времени") for i in range(4)])),
        _sl(3, "Производная равна угловому коэффициенту касательной", ["Касательная — предельное положение секущей."]),
    ])
    ensure_pictures([o], "")
    assert [k for k, s in enumerate(o.slides) if s.content.photo_slot] == [2]


def test_the_writers_places_are_verstkas_own_the_persons_stay_theirs():
    o = _lecture()
    o.slides[3].content.photo_slot, o.slides[3].content.photo_hint = "Фото", "Касательная прямая, касающаяся параболической кривой"
    o.slides[2].content.photo_slot, o.slides[2].content.photo_hint = "Изображение", "спидометр автомобиля на трассе"
    n = writer_places_as_own([o], "Сделай лекцию про производную. [Место под изображение: спидометр автомобиля на трассе]")
    assert n == 1
    assert o.slides[3].content.photo_slot == AUTO_LABEL and o.slides[2].content.photo_slot == "Изображение"


def test_scene_words_take_the_most_concrete_sentence():
    s = _sl(1, "Производная описывает скорость изменения", ["Производная описывает мгновенную скорость изменения величины.",
                                                             "Например, водитель смотрит на спидометр автомобиля на трассе."])
    assert scene_words(s, s.headline).startswith("Например, водитель смотрит на спидометр")
    plain = _sl(2, "Итоги", ["Первый пункт.", "Второй пункт."])
    assert scene_words(plain, plain.headline) == "Первый пункт"  # nothing more concrete: the first words, as before


# ------------------------------------------------------------------ the build's limit of attempts


def _maker(tmp_path, provider, *, attempts=None, deadline=None, checks_end=None):
    from verstka.images.service import ImageMaker

    return ImageMaker(provider, None, tmp_path / "images", skills=None, providers=None, attempts=attempts, deadline=deadline, checks_end=checks_end)


@pytest.fixture
def misfit(monkeypatch):
    """Every picture is clean and misses its slide (2/10); Verstka's places get an English description."""
    from verstka.images import service

    monkeypatch.setattr(service, "check_text", lambda *a, **k: TextCheck(text="none", fits=2, flaws="another subject"))
    monkeypatch.setattr(service.ImageMaker, "_subject", lambda self, ask: "A car on a highway, the speedometer's needle in the middle")


def test_the_limit_counts_the_image_models_calls_not_the_pictures(tmp_path, misfit):
    prov = IP.MockImages()
    mk = _maker(tmp_path, prov, attempts=2)
    a = ImageAsk(hint="Сцена по смыслу слайда — Мгновенная скорость", headline="Мгновенная скорость", label=AUTO_LABEL)
    b = ImageAsk(hint="Сцена по смыслу слайда — Курьер", headline="Курьер", label=AUTO_LABEL)
    fa, fb = mk.submit(a, "1:1"), mk.submit(b, "1:1")
    errs = []
    for f in (fa, fb):
        with pytest.raises(Exception) as e:
            f.result(timeout=30)
        errs.append(e.value)
    assert len(prov.calls) == 2  # two pictures asked, at most two drawn in all
    assert mk.auto_used == 2 and mk.budget_hit
    assert any(isinstance(e, PictureNotFitting) for e in errs)
    # the person's own ask comes on top of the limit
    user = ImageAsk(hint="экран приложения с балансом", headline="Экран", label="Изображение")
    with pytest.raises(PictureNotFitting):
        mk.submit(user, "1:1").result(timeout=30)
    assert len(prov.calls) > 2
    mk.close()


def test_a_place_refused_by_the_limit_says_so(tmp_path, misfit):
    from verstka.images.service import WHY_LIMIT

    prov = IP.MockImages()
    mk = _maker(tmp_path, prov, attempts=0)
    with pytest.raises(Exception) as e:
        mk.submit(ImageAsk(hint="Сцена по смыслу слайда — Склад", headline="Склад", label=AUTO_LABEL), "1:1").result(timeout=30)
    assert getattr(e.value, "why", "") == WHY_LIMIT and "проверку соответствия" in WHY_LIMIT
    assert prov.calls == []
    mk.close()


def test_a_picture_asked_after_the_plan_serves_its_place_in_any_frame_but_a_background(tmp_path):
    prov = IP.MockImages(delay_s=0.2)
    mk = _maker(tmp_path, prov)
    ask = ImageAsk(hint="Склад — Сборка заказов", headline="Сборка", label=AUTO_LABEL, frame="tall")
    early = mk.prefetch(ask, "1:1")
    later = ImageAsk(hint="Склад — Сборка заказов", headline="Сборка", label=AUTO_LABEL, frame="square", slide_text="Пункт")
    assert mk.submit(later, "3:4") is early
    bg = ImageAsk(hint="Склад — Сборка заказов", headline="Сборка", label=AUTO_LABEL, frame="background")
    assert mk.submit(bg, "16:9") is not early
    mk.close()


def test_the_maker_draws_no_attempt_it_cannot_check_in_time(tmp_path, misfit):
    prov = IP.MockImages()
    now = time.monotonic()
    mk = _maker(tmp_path, prov, deadline=now + 3, checks_end=now + 18)
    with pytest.raises(Exception):
        mk.submit(ImageAsk(hint="экран приложения", headline="Экран", label="Изображение"), "1:1").result(timeout=30)
    assert prov.calls == []
    mk.close()


def test_the_maker_of_a_build_keeps_the_limit_and_the_vision_models_window():
    from verstka.pipeline.generate import CONTENT_CHECKS_END_S, PICTURE_CHECK_S, _picture_maker

    t0 = time.monotonic()
    for n, want in ((6, 2), (12, 4)):
        o = DeckOutline(title="Т", slides=[_sl(i, f"Слайд {i}", ["Пункт."]) for i in range(n)])
        mk, _ = _picture_maker(True, IP.ImageChain([IP.MockImages()]), None, Path("/nonexistent/images"), t0, None, None, None, o, {})
        assert mk.attempts == want
        assert mk.checks_end == pytest.approx(t0 + CONTENT_CHECKS_END_S)
        assert mk.deadline <= t0 + CONTENT_CHECKS_END_S - PICTURE_CHECK_S
        mk.close()


# ------------------------------------------------------------------ the second chance right away


class _FakeMaker:
    deck_title = "Производная"

    def __init__(self, left):
        self.left = left
        self.asked: list[ImageAsk] = []
        self.futures: list[Future] = []
        self.budget_hit = False

    def prefetch(self, ask, aspect):
        f: Future = Future()
        self.asked.append(ask)
        self.futures.append(f)
        return f

    def budget_left(self):
        return self.left


def test_a_rejected_picture_hands_its_place_on_at_once():
    from verstka.images.early import EarlyPictures

    o = _lecture()
    ensure_pictures([o], "")
    mk = _FakeMaker(left=2)
    ep = EarlyPictures(mk, o, need=2, second_max=2)
    assert [it.index for it in ep.start()] == [2, 6]
    mk.futures[1].set_exception(PictureNotFitting("2/10"))  # the courier missed: the next slide is asked now
    assert len(mk.asked) == 3 and mk.asked[2].label == AUTO_LABEL
    assert ep.picks and ep.picks[0][1] not in (2, 6) and ep.state_of(mk.asked[1].hint) == "failed"
    mk.futures[0].set_result(object())
    mk.futures[2].set_exception(PictureNotFitting("3/10"))
    assert len(mk.asked) == 4  # the second of the SECOND_CHANCES


def test_no_second_chance_past_the_limit_and_it_is_said():
    from verstka.images.early import EarlyPictures

    o = _lecture()
    ensure_pictures([o], "")
    mk = _FakeMaker(left=0)
    ep = EarlyPictures(mk, o, need=2, second_max=2)
    ep.start()
    mk.futures[0].set_exception(PictureNotFitting("2/10"))
    assert len(mk.asked) == 2 and mk.budget_hit and "limit" in ep.declined


# ------------------------------------------------------------------ in a build

PLAIN = """Тема презентации: «Склад в сентябре». Презентация на 6 слайдов.

Слайд 1. Склад в Подольске за сентябрь

Итоги месяца для директора по логистике.

Слайд 2. Отгрузили больше

48 200 заказов — на 12% больше, чем в августе.

Слайд 3. Сборка стала быстрее

Среднее время сборки заказа — 2,4 часа против 3,1 часа в августе.

Слайд 4. Ошибок меньше цели

Доля ошибок комплектации — 0,4% при цели 0,5%.

Слайд 5. Ночная смена

Ночью собирают треть заказов, а ошибок там больше половины.

Слайд 6. Что предлагаю

Перевести ночную смену на сканеры с проверкой.
"""


def _build(tmp_path, ip, progress=None):
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import load_brief

    p = tmp_path / "brief.md"
    p.write_text(PLAIN, encoding="utf-8")
    return generate_variants(TPL, brief=load_brief(p), strategies=["structured"], out_dir=tmp_path / "run", workspace_root=tmp_path / "ws",
                             use_llm=False, use_vlm=False, audit=True, exports=[], image_provider=ip, progress=progress)


def test_the_pictures_are_asked_right_after_the_plan_before_the_layout(tmp_path, monkeypatch):
    from verstka.images.service import ImageMaker, Made
    from verstka.pipeline import generate as G

    order: list[str] = []
    real_prefetch, real_render = ImageMaker.prefetch, G.render_deck

    def prefetch(self, ask, aspect, **kw):
        order.append("picture")
        return real_prefetch(self, ask, aspect, **kw)

    def render(*a, **kw):
        order.append("render")
        return real_render(*a, **kw)

    def fake(self, ask, aspect, seed):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{ask.key()}-{aspect.replace(':', 'x')}.jpg"
        Image.new("RGB", (300, 300), (90, 140, 200)).save(path)
        return Made(key=ask.key(), aspect=aspect, path=str(path), prompt="p", style="photo", subject_by="model", model="mock", model_label="Mock",
                    seed=1, palette_match=1.0, seconds=0.0, fits=9)

    monkeypatch.setattr(ImageMaker, "prefetch", prefetch)
    monkeypatch.setattr(ImageMaker, "_make", fake)
    monkeypatch.setattr(G, "render_deck", render)
    events: list[str] = []
    g = _build(tmp_path, IP.ImageChain([IP.MockImages()]), progress=lambda m, f, **kw: events.append(m))
    assert "picture" in order and order.index("picture") < order.index("render")
    assert any("рисую сразу после плана" in e for e in events)
    v = g.variants[0]
    rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["pictures"]["generated"] >= 1 and "timeline" in rm["pictures"]
    assert rm["pictures"]["timeline"]["attempts_limit"] == 2


def test_a_build_past_the_limit_says_the_pictures_did_not_pass(tmp_path, misfit):
    prov = IP.MockImages()
    events: list[str] = []
    g = _build(tmp_path, IP.ImageChain([prov]), progress=lambda m, f, **kw: events.append(m))
    v = g.variants[0]
    assert len(prov.calls) <= 2  # 6 slides: the minimum is 1, the limit 2 attempts
    assert any("картинки не прошли проверку соответствия" in e and "лимит попыток" in e for e in events)
    assert any("картинки не прошли проверку соответствия" in w for w in v.warnings)
    assert not [i for i in v.audit.issues if i.check_id == "photo_place_empty"]
    rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    tl = rm["pictures"]["timeline"]
    assert tl["auto_attempts"] <= 2 and tl["limit_spent"] and tl["first_start_s"] is not None
    assert tl["first_asked_s"] is not None and tl["first_asked_s"] <= tl["first_start_s"]


def test_a_scene_of_a_slide_of_mathematics_is_never_a_bare_diagram():
    """Live lecture 20.10: «Сцена по смыслу слайда — … Производная характеризует скорость изменения функции» was drawn as
    a «flat vector diagram» — a lone curve. A scene Verstka chose is a real situation; the author's «касательная к
    параболе» stays a diagram."""
    from verstka.images.prompt import build_prompt

    scene = ImageAsk(hint=f"{SCENE} — Значение дифференцирования. Производная характеризует скорость изменения функции", label=AUTO_LABEL,
                     subject_en="A cyclist speeding up on a country road")
    assert build_prompt(scene, None)[1] != "diagram"
    author = ImageAsk(hint="касательная к параболе в точке", label="Изображение", subject_en="A tangent line touching a parabola")
    assert build_prompt(author, None)[1] == "diagram"
