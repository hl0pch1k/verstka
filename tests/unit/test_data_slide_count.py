"""Число слайдов колоды из данных — в обе стороны (жюри 20.10: «слайдов 8–10» → 7): недостающее — только слайдами со
своим проверенным выводом (другая величина показанного файла, ключевые цифры), без пустых и повторов; лишнее —
сначала наименее нужное."""

from __future__ import annotations

from pathlib import Path

from verstka.data.readers import read_file
from verstka.data.story import _count_bounds, build_data_story
from verstka.schemas.data import Table
from verstka.schemas.outline import Brief

ROOT = Path(__file__).resolve().parents[2]
SLA = ROOT / "tests" / "fixtures" / "support_sla"
PLANS = ROOT / "tests" / "fixtures" / "plans"
SALES = ROOT / "examples" / "data-sales-2026"


def _files(folder: Path) -> list[Table]:
    out: list[Table] = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".csv", ".xlsx", ".json", ".txt"):
            out += read_file(f)
    return out


def _no_repeats(o) -> None:
    heads = [(s.headline or "").strip().lower() for s in o.slides]
    assert len(heads) == len(set(heads)), heads
    for s in o.slides[1:]:
        c = s.content
        assert c.chart is not None or c.table is not None or c.numbers or c.items or c.bullets, s.id


def test_bounds_of_the_count():
    assert _count_bounds(Brief(text="Итоги, слайдов 8–10."), None, 10) == (8, 10)
    assert _count_bounds(Brief(text="Итоги, не более 10 слайдов."), None, 10) == (None, 10)
    assert _count_bounds(Brief(text="Сделай 12 слайдов про итоги."), None, 12) == (12, 12)
    assert _count_bounds(Brief(text="Итоги"), 9, 9) == (9, 9)  # число из интерфейса — размер колоды
    assert _count_bounds(None, None, None) == (None, None)


def test_eight_to_ten_is_at_least_eight_with_slides_of_their_own():
    st = build_data_story(Brief(text=(ROOT / "tests" / "fixtures" / "support_sla_plan.md").read_text(encoding="utf-8")), _files(SLA))
    o = st.outline
    assert 8 <= len(o.slides) <= 10, [s.headline for s in o.slides]
    _no_repeats(o)
    extra = next(s for s in o.slides if s.id.endswith("-m1"))
    assert extra.data is not None and extra.content.chart.series[0].name.startswith("Решено в первый день")
    assert "61,7%" in extra.headline.replace(" ", " ") and "снизился" not in extra.headline


def test_the_interface_count_both_ways():
    brief = Brief(text=(PLANS / "sales_plan_with_data.md").read_text(encoding="utf-8"))
    small = build_data_story(brief, _files(SALES), slide_count=8).outline
    assert len(small.slides) <= 8 and small.slides[0].kind.value == "title"
    st = build_data_story(brief, _files(SALES), slide_count=14)
    big = st.outline
    assert len(big.slides) >= 11, [s.id for s in big.slides]
    # short of 14: said plainly, not filled with empty or repeated slides
    assert len(big.slides) == 14 or any("осмысленных слайдов из" in x for x in st.log)
    assert not any(s.id == "data-3-m1" for s in big.slides)  # «Число клиентов +18%» — figure of the key figures
    _no_repeats(big)
    # the files' own key figures are a slide already: no second row of figures
    assert not any(s.id == "key-figures" for s in big.slides)
    assert not any("Казань впереди" in (s.headline or "") for s in big.slides)  # the growth is said once
