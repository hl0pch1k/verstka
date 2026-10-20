"""Поломки жюри 5b (20.10): UI1 — план из одной таблицы и «5 слайдов» фразой, обложка не имя файла; итог «в цифрах» без
нуля, коэффициента корреляции и первого периода; «ниже всех» не спорит с ростом; вопрос автора в скобках не печатается."""

from __future__ import annotations

from pathlib import Path

from verstka.data.goals import Goal
from verstka.data.plan import plan_datasets
from verstka.data.readers import read_file
from verstka.data.story import _position_to_growth, _summary_card_figure, build_data_story
from verstka.planning.brief import parse_brief_text
from verstka.planning.plan_data import _no_questions
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import OutlineSlide, SlideContent

UI1_BRIEF = """Квартал по хранилищу VK Cloud — для команды
1) общий итог Q3 против Q2
2) что растёт
3) резервное копирование просело — почему, пока не знаем, разбираемся
4) план на Q4: акция на резервное копирование для текущих клиентов
5 слайдов
"""
UI1_CSV = "Сервис,Выручка Q2 млн ₽,Выручка Q3 млн ₽\nОбъектное хранилище,190,214\nБлочные диски,86,88\nРезервное копирование,35,32\n"
CLIENTS_CSV = ("Отрасль,Клиентов на 30.06,Клиентов на 30.09\nРитейл,420,465\nФинансы,180,192\nГоссектор,95,131\n"
               "Промышленность,140,151\nПрочие,610,640\n")


def _table(tmp_path: Path, name: str, text: str):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return read_file(p)


def test_ui1_plan_of_one_table_gives_five_slides_and_the_authors_cover(tmp_path):
    st = build_data_story(parse_brief_text(UI1_BRIEF), _table(tmp_path, "hranilishe_q3.csv", UI1_CSV))
    o = st.outline
    heads = [s.headline for s in o.slides]
    assert len(o.slides) == 5, heads
    assert o.slides[0].kind == PatternKind.title and o.slides[0].headline == "Квартал по хранилищу VK Cloud"
    assert not any("Hranilishe" in (h or "") for h in heads)
    assert any("растёт быстрее всех" in (h or "") for h in heads)  # «что растёт» — рост по сервисам Q2 → Q3
    assert any((h or "").startswith("Резервное копирование просело") for h in heads)
    assert any("Акция на резервное копирование" in " ".join(s.content.bullets) for s in o.slides)


def test_summary_card_figure_is_never_zero_correlation_or_first_period():
    base = {"title": "t", "conclusion": "c", "plan": 0, "kind": "conclusion"}
    assert _summary_card_figure({**base, "text": "Дешевле всего — Excel вручную: 0 ₽", "number": "0 ₽"}) is None
    assert _summary_card_figure({**base, "text": "Ожидание и неявки связаны: r = 0,99", "number": "0,99"}) is None
    c = _summary_card_figure({**base, "text": "MRR: от 980 тыс. ₽ (январь) до 1 820 тыс. ₽ (сентябрь)", "number": "980 тыс. ₽"})
    assert c is not None and c["number"].replace(" ", " ") == "1 820 тыс. ₽"
    ok = {**base, "text": "Госсектор растёт быстрее всех: +38% за квартал", "number": "+38%"}
    assert _summary_card_figure(ok) == ok


def test_position_of_the_growth_leader_is_its_growth(tmp_path):
    t = _table(tmp_path, "klienty.csv", CLIENTS_CSV)
    g = Goal(phrase="клиенты по отраслям — госсектор выстрелил, проверь", task="comparison", viz="bar", to="", given=True,
             column="Клиентов на 30.09", dimension="Отрасль", categories=["Госсектор"], ask="position")
    plans = plan_datasets(t, "", goals=[g])
    assert "ниже всех" in plans[0].headline
    got = _position_to_growth(plans, t)
    assert got[0].headline.startswith("Госсектор растёт быстрее всех") and got[0].task.goal == plans[0].task.goal


def test_authors_question_in_brackets_is_not_printed():
    s = OutlineSlide(id="x", kind=PatternKind.section, headline="Риск", subtitle="Зависимость от Compute (больше половины выручки?)",
                     content=SlideContent())
    assert _no_questions(s).subtitle == "Зависимость от Compute"
