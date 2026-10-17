"""Раунд 9 (третья проверка сходимости, conv3): взвешенные средние, прогноз отдельно от факта, двухуровневые шапки
«год → квартал», часть «сильнее всех» по средним окна и с базой, дневные ряды целыми неделями и всплески, точность
процентов у самой сотни и цели строк, ответы на вопросы цели (кто быстрее всех растёт, кто за порогом, с каким
отрывом, какое среднее по всем, сколько всего), строка, названная целью, и формулировки (год к году, единица из
строки над таблицей в тексте, доли единицы в процентах, коды строчными, перцентиль назван)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from tests.unit.test_data_factcheck import corpus_conv3, corpus_conv3_probes
from verstka.data.plan import chart_spec_of, plan_dataset, plan_datasets
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes, read_file
from verstka.data.words import fmt_value
from verstka.schemas.data import DatasetPlan, Table

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
SCIENCE = ROOT / "examples" / "data-science-2026"


def _sp(s: str) -> str:
    return " ".join((s or "").replace(" ", " ").split())


def _t(name: str, rows: list[list]) -> Table:
    buf = io.StringIO(newline="")
    csv.writer(buf, delimiter=";").writerows(rows)
    return read_bytes(name, buf.getvalue().encode("utf-8"))[0]


def _plan(t: Table, brief: str = "") -> DatasetPlan:
    prof = profile_table(t)
    return plan_datasets([t], brief, profiles=[prof])[0] if brief else plan_dataset(prof, t)


_C3 = None


def _conv3(key: str, which: str = "nb") -> list[tuple[Table, DatasetPlan]]:
    """Таблицы и планы корпуса conv3 по ключу: без цели (nb), с целью-вопросом (A) или с целью-командой (B)."""
    global _C3
    if _C3 is None:
        _C3 = {k: (files, a, b) for k, files, a, b in corpus_conv3()}
    files, a, b = _C3[key]
    tables = [t for n, data in files for t in read_bytes(n, data)]
    brief = {"nb": "", "A": a, "B": b}[which]
    return list(zip(tables, plan_datasets(tables, brief, profiles=[profile_table(t) for t in tables])))


def _probe(prefix: str) -> list[Table]:
    return [t for n, data in corpus_conv3_probes() if n.startswith(prefix) for t in read_bytes(n, data)]


# ── M3: шапка «год → квартал» ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("prefix", ["v19a", "v19b", "v19c", "v19d", "v19e"])
def test_two_level_year_quarter_header_keeps_the_year(prefix):
    """Год над кварталами — в имени периода («I кв. 2025»), а не «I кв. (2)»; колонки-кварталы — ось времени: с
    названием над таблицей и без, год строкой и числом, с объединением ячеек и без."""
    t = _probe(prefix)[0]
    assert "Квартал" in t.columns and not any("(2)" in c for c in t.columns), t.columns
    p = _plan(t)
    assert p.task.task == "dynamics"
    s = chart_spec_of(p, t)
    assert s.categories[0] == "I кв. 2025" and s.categories[-1] == "II кв. 2026"
    if prefix in ("v19a", "v19d"):  # мера — по названию над таблицей, а не «Значение»
        assert "Выручка" in t.columns and _sp(p.headline) == "Выручка — на 17% больше, чем во II квартале 2025"


def test_year_over_year_is_said_without_ambiguity():
    """«к II кварталу 2025» читается и как «к сроку»: год к году — «на 50% больше, чем во II квартале 2025»."""
    (t, p), = _conv3("06")
    assert _sp(p.headline) == "Объём данных — на 50% больше, чем во II квартале 2025", p.headline
    rows = [["Месяц", "Выручка, млн ₽"]] + [[f"{m:02d}.{y}", 100 + 3 * k]
                                             for k, (y, m) in enumerate([(2025, m) for m in range(1, 13)]
                                                                        + [(2026, m) for m in range(1, 10)])]
    p = _plan(_t("Выручка по месяцам.csv", rows))
    assert _sp(p.headline).endswith("больше, чем в сентябре 2025"), p.headline


def test_fastest_growing_region_answers_the_question():
    """«Какой регион растёт быстрее всех?» по кварталам: темп каждого региона, ответ — Казань (+44%), а не рост
    целого; малые базы в счёт не идут."""
    t = _probe("v19a")[0]
    p = _plan(t, "Какой регион растёт быстрее всех?")
    assert _sp(p.headline) == "Казань растёт быстрее всех: +44%", p.headline
    assert "Казань: с 52 млн ₽ до 75 млн ₽ — быстрее всех." in _sp(p.caption)
    assert not any("не подтвердил" in r for r in p.task.reasons)


# ── M4, M5: «сильнее всех» у части, дневной шум и всплеск ─────────────────────────────────────────────────────────
def test_part_mover_by_window_means_and_a_base():
    """Критичные P1 (3, 2, 4 … 1, 0): «−100%» по концам — неправда; малая база в «сильнее всех» не идёт, а цель о
    критичных — средние первых и последних трёх недель."""
    (t, p), = _conv3("02")
    assert _sp(p.headline) == "Число инцидентов снизилось на 34% за 11 недель, сильнее всех — высокие (P2): −53%"
    assert "в среднем с 10,7 до 5" in _sp(p.caption)
    assert "как они менялись" in p.task.reasons[0]  # не «как средние менялись» (ряд «Средние (P3)»)
    (t, p), = _conv3("02", "B")
    assert _sp(p.headline) == "Критичные (P1) в среднем снизились на 67%: последние 3 недели к первым 3", p.headline


def test_daily_spike_is_the_headline():
    """Ошибки 5xx по дням: всплеск 8 сентября в 5,2 раза выше медианы — главное; не «−28%» трёх дней против трёх."""
    (t, p), = _conv3("32", "B")
    assert _sp(p.headline) == "Число ошибок 5xx: всплеск 9 640 (8 сен 2026) — в 5,2 раза выше медианы", p.headline
    assert _sp(p.caption) == "8 сентября 2026 — 9 640, медиана за 14 дней — 1 855."


def test_daily_noise_compares_whole_weeks():
    """Дни с недельным циклом и без тренда: средние целых недель (7 дней), разница в шуме — «без выраженного
    тренда», и подпись не спорит с заголовком."""
    base = [1800, 1760, 1900, 2240, 980, 870, 1810]
    rows = [["Дата", "Заказов"]] + [[f"2026-09-{d + 1:02d}", base[d % 7] + (15 if d >= 7 else 0)] for d in range(14)]
    p = _plan(_t("Заказы по дням.csv", rows))
    assert "без выраженного тренда" in p.headline, p.headline
    assert _sp(p.caption).startswith("Тренд не выражен") and "первые 7" in _sp(p.caption)


# ── M6: точность у сотни и цели строк ─────────────────────────────────────────────────────────────────────────────
def test_percent_near_hundred_keeps_its_decisive_digit():
    assert fmt_value(99.874, "%") == "99,87%" and fmt_value(99.999, "%") == "99,999%"
    assert fmt_value(99.912, "%") == "99,912%" and fmt_value(99.5, "%") == "99,5%" and fmt_value(100, "%") == "100%"
    assert fmt_value(87.4, "%") == "87,4%"


def test_row_targets_count_and_name_the_misses():
    """SLA по сервисам: у каждого своя цель. Вывод — кто не дотянул (2 из 7), значения рядом со своей целью без
    округления до цели, акцент — на самом далёком от цели. Цель «не уложились в SLA» — о доступности, а не о
    колонке «Цель SLA»."""
    for which in ("nb", "A", "B"):
        (t, p), = _conv3("03", which)
        assert _sp(p.headline) == "Ниже цели SLA — 2 из 7: CDN и Почта для бизнеса", (which, p.headline)
        assert _sp(p.caption) == "CDN — 99,912% при цели 99,95%; Почта для бизнеса — 99,87% при 99,9%."
        s = chart_spec_of(p, t)
        assert s.series[0].name == "Доступность" and s.categories[s.highlight_index] == "CDN"


def test_kpi_targets_met_and_missed():
    """Одна строка показателей и их целей («Цель MAU», «Цель по оттоку»): сколько целей выполнено и какие нет; у
    оттока меньше — лучше."""
    (t, p), = _conv3("25", "A")
    assert _sp(p.headline) == "Выполнены 2 цели из 4: выручка и отток; MAU и NPS — ниже цели", p.headline
    assert _sp(p.caption) == "MAU — 14,2 млн при цели 15 млн; NPS — 41 при цели 45."


# ── ответы на вопросы цели ────────────────────────────────────────────────────────────────────────────────────────
def test_threshold_question_names_who_is_past_it():
    (t, p), = _conv3("24", "A")
    assert _sp(p.headline) == "Выше 80% — 2 сервера из 8: node-05 и node-03", p.headline
    assert _sp(p.caption) == "node-05 — 92%, node-03 — 83%." and not any("не подходит" in r for r in p.task.reasons)
    t = _t("NPS по продуктам.csv", [["Продукт", "NPS"], ["Почта", 41], ["Диск", 28], ["Облако", 55], ["Мессенджер", 22],
                                     ["Календарь", 35]])
    p = _plan(t, "Какие продукты с NPS ниже 30?")
    assert _sp(p.headline) == "Ниже 30 — 2 продукта из 5: Мессенджер и Диск", p.headline


def test_margin_mean_and_total_questions():
    (t, p), = _conv3("38", "A")
    assert _sp(p.headline) == "«Нейроны» впереди: 84,5, «404» — 55,5"
    assert _sp(p.caption) == "Отрыв от второго места («Байтики» — 81) — 3,5."
    (t, p), = _conv3("11", "A")  # «какой средний NPS по всем продуктам»: с весом ответов, сводная строка — не продукт
    assert _sp(p.headline) == "NPS в среднем — 30,1: от 18 (VK WorkSpace) до 55 (Объектное хранилище)", p.headline
    assert "Все продукты" not in chart_spec_of(p, t).categories
    (t, p), = _conv3("20", "A")  # «сколько всего отгрузили за полугодие»: итог строк, а не «июнь — 19%»
    assert _sp(p.headline) == "Всего — 3 006 тыс. шт., больше всего — Подольск: 40%", p.headline


def test_goal_naming_one_row_follows_that_row():
    """«Покажите рост облачной платформы за последний год»: ряд — по строке «Облачная платформа» (+36%), а не по
    всей выручке (+28%); прогноз в подписи — её же, на графике — отдельным рядом без повтора факта у столбцов."""
    (t, p), = _conv3("17", "A")
    assert _sp(p.headline) == "Выручка облачной платформы выросла на 36% за год", p.headline
    assert "Прогноз на 2026 год — 21,5 млрд ₽, не в выводе." in _sp(p.caption)
    assert not any("в колонках нет" in r for r in p.task.reasons)
    s = chart_spec_of(p, t)
    assert s.categories == ["2023", "2024", "2025", "2026"] and s.series[-1].values == [None, None, None, 21.5]
    a, b = _conv3("26", "B")
    assert _sp(a[1].headline) == "Выручка облака выросла на 14% за квартал", a[1].headline
    assert _sp(b[1].headline) == "Численность разработки выросла на 6,3% за квартал", b[1].headline


def test_goal_naming_a_column_in_its_own_words():
    """«У кого самая большая просрочка свыше 90 дней?»: «просрочки» в колонках нет, но «свыше 90 дней» — имя колонки;
    ответ — по ней, величина названа по таблице («задолженности свыше 90 дней»), а не «свышя 90 дней»."""
    (t, p), = _conv3("31", "A")
    assert p.task.goal and _sp(p.headline) == "ЗАО «Ладога Логистик» — больше половины задолженности свыше 90 дней: 64%"
    assert not any("не подходит" in r for r in p.task.reasons)


# ── формулировки ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_wording_of_round_9():
    (t, p), = _conv3("21")  # доли единицы — в процентах
    assert _sp(p.headline) == "Email впереди: 5,8%, Таргет — 1,2%"
    (t, p), = _conv3("24")  # код строки — как в файле, мера названа
    assert _sp(p.headline) == "node-05 — первое место по загрузке CPU: 92%"
    (t, p), = _conv3("36")  # какой перцентиль показан
    assert _sp(p.headline) == "Медленнее всего — Владивосток: 72 мс (p50), быстрее всего — Москва: 18 мс"
    (t, p), = _conv3("04")  # после «Всего N:» — со строчной
    assert "Всего 8 448: решено — 7 322, в работе — 865, эскалировано — 261." in _sp(p.caption)
    (t, p), = _conv3("38")  # баллы команд не складывают в «всего 508»: сравнение по итогу
    assert p.task.task == "comparison" and _sp(p.headline) == "«Нейроны» впереди: 84,5, «404» — 55,5"
    (t, p), = _conv3("17")  # колонка-год — «выручки за 2025 год», годы не складывают как категории
    assert _sp(p.headline) == "Облачная платформа — больше половины выручки за 2025 год: 56%"
    assert "Сумма" not in (chart_spec_of(p, t).y_title or "")
    (t, p), = _conv3("14")  # причастие «Утверждено» — со словом
    assert _sp(p.headline) == "Облачная инфраструктура — крупнейшая доля утверждённого бюджета: 37%"
    (t, p), = _conv3("05", "A")  # больше свободных мест — не «впереди»
    assert _sp(p.headline) == "Больше всего — VK WorkSpace Диск: 213, меньше всего — Вики: 9"
    (t, p), = _conv3("34")  # ряд «На начало месяца» — не подлежащее
    assert _sp(p.headline).startswith("Численность на начало месяца выросла на 6% за 5 месяцев")
    (t, p), = _conv3("07")  # «Доля неудачных изменений» — не колонка роста
    assert "растёт быстрее" not in p.task.reasons[0]


def test_text_table_takes_its_title_line():
    """Две таблицы в тексте: строка над каждой («Выручка по продуктам, млн ₽:») — её единица и имя."""
    a, b = _conv3("26")
    assert a[0].units[1:] == ["млн ₽", "млн ₽"] and a[0].sheet == "Выручка по продуктам"
    assert b[0].units[1:] == ["чел.", "чел."] and b[0].sheet == "Численность команды на конец квартала"
    assert _sp(a[1].headline) == "Облако — больше половины выручки за II кв. 2026: 63%"


def test_forecasts_stay_apart_from_actuals():
    """«2026 (прогноз)» строкой, «2026П», «Факт · Прогноз» по месяцам: рост — по фактам, прогноз — в подписи и
    отдельным рядом; хвост прогноза — не «пустые месяцы»; «Оценка» без периода — балл, а не прогноз."""
    t = _probe("v2")[0]
    p = _plan(t)
    assert _sp(p.headline) == "Выручка выросла в 2,3 раза за 4 года"
    assert "Прогноз на 2026 год — 36,8 млрд ₽, не в выводе." in _sp(p.caption)
    s = chart_spec_of(p, t)
    assert s.categories[-1] == "2026" and s.series[-1].name == "Выручка (прогноз)"
    t = _probe("v3")[0]
    p = _plan(t)
    assert _sp(p.headline) == "Выручка выросла на 31% за 5 месяцев" and "пуст" not in p.task.reasons[0]
    t = _t("Оценки.csv", [["Отдел", "Оценка"], ["Продажи", "3,8"], ["ИТ", "3,2"], ["Склад", "3,2"]])
    assert _sp(_plan(t).headline) == "Продажи впереди: 3,8, ИТ и Склад — 3,2"


def test_residual_row_is_never_the_leader():
    (t, p), = _conv3("08")
    assert _sp(p.headline) == "ТехноСофт приносит 19% выручки"
    assert chart_spec_of(p, t).highlight_index == 0


def test_structure_and_share_headlines_state_a_conclusion():
    """Заголовок структуры — не перечень долей («Платное — 53% приёма, бюджет — 35%»): что преобладает или какая
    часть крупнейшая. Ни один заголовок обоих наборов-примеров и корпуса conv3 не описание чисел (правило аудита)."""
    from verstka.data.story import is_description

    heads = []
    for folder in (SALES, SCIENCE):
        files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in {".csv", ".xlsx", ".json", ".txt"}]
        tables = [t for p in files for t in read_file(p)]
        heads += [(p.profile.file, p.headline, p.task.task) for p in plan_datasets(tables, "")]
    for key in ("04", "09", "15", "16", "20", "39"):
        for which in ("nb", "B"):
            heads += [(t.file, p.headline, p.task.task) for t, p in _conv3(key, which)]
    bad = [(f, h) for f, h, task in heads if task != "kpi" and is_description(h)]
    assert not bad, bad
    d: dict[str, str] = {}
    for f, h, _ in heads:
        d.setdefault(f, h)  # без цели — первым
    assert _sp(d["Приём по направлениям.xlsx"]) == "Больше половины приёма — платное: 53%"
    assert _sp(d["16 Источники трафика сайта, сентябрь.csv"]) == "Поиск — крупнейшая доля визитов: 42%"


# ── живая проверка 2: A4 и N-A3 ───────────────────────────────────────────────────────────────────────────────────
def test_regions_slide_accents_the_growth_leader_end_to_end():
    """«Москва даёт 41% выручки, Казань растёт быстрее всех»: на слайде колоды выделена Казань — та, о ком вывод
    сверх очевидного (самый длинный столбец — Москва — виден и так)."""
    from verstka.data.story import build_data_story
    from verstka.schemas.outline import Brief

    files = [p for p in sorted(SALES.iterdir()) if p.suffix.lower() in {".csv", ".xlsx", ".json", ".txt"}]
    tables = [t for p in files for t in read_file(p)]
    st = build_data_story(Brief(text="Итоги продаж VK Cloud за 9 месяцев 2026 года. Сравни регионы.", slide_count=9), tables)
    slide = next(s for s in st.outline.slides if s.data is not None and s.data.file == "Регионы.xlsx")
    chart = slide.content.chart
    assert "Казань растёт быстрее всех" in slide.headline
    assert chart.categories[chart.highlight_index] == "Казань"


def test_publications_caption_keeps_the_peak_and_the_gap():
    """Подпись сокращают — оговорки остаются: «РИНЦ: максимум 985 статей в 2019 году, затем ниже» и пропуск 2016
    года не теряются из-за того, что они вторые (заголовок «РИНЦ — в 3,4 раза» без них скрывает спад)."""
    t = read_file(SCIENCE / "Публикации по годам.json")[0]
    p = _plan(t)
    c = _sp(p.caption)
    assert "РИНЦ: максимум 985 статей в 2019 году, затем ниже." in c and "За 2016 год данных нет." in c
    assert len(c) <= 160
