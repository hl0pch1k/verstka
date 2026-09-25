"""The chat agent reads an edit of the deck on screen into one operation (verstka/api/edits.py, api/app.py)."""

import pytest

from verstka.api.app import _is_edit, _intent
from verstka.api.edits import parse_edit, slide_refs


@pytest.mark.parametrize(
    "message, on_screen, kind, slides, target",
    [
        ("на слайде 3 покажи расходы таблицей", 2, "slide", [3], None),
        ("Сделай заголовок третьего слайда короче", 2, "slide", [3], None),
        ("сделай тут крупнее цифры", 5, "slide", [5], None),
        ("перепиши заголовок", 4, "slide", [4], None),
        ("добавь на последний слайд вывод про риски", 2, "slide", [10], None),
        ("убери вывод на слайде 4", 2, "slide", [4], None),
        ("убери слайд 5", 2, "delete", [5], None),
        ("удали этот слайд", 4, "delete", [4], None),
        ("поменяй местами слайды 2 и 3", 2, "swap", [2, 3], None),
        ("поменяй местами 4-й и 5-й слайды", 2, "swap", [4, 5], None),
        ("перенеси слайд 6 после второго", 2, "move", [6], 3),
        ("перенеси слайд 2 в конец", 2, "move", [2], 10),
        ("верни как было", 2, "undo", [], None),
        ("отмени последнюю правку", 2, "undo", [], None),
    ],
)
def test_parse_edit(message, on_screen, kind, slides, target):
    req = parse_edit(message, on_screen, 10)
    assert req is not None
    assert (req.kind, req.slides, req.target) == (kind, slides, target)


def test_no_slide_named_and_none_on_screen():
    assert parse_edit("сделай покрупнее", None, 6) is None


def test_slide_refs_stay_in_the_deck():
    assert slide_refs("на слайде 12 и на втором слайде", 6) == [2]


@pytest.mark.parametrize(
    "message, expected",
    [
        ("на слайде 3 покажи расходы таблицей", True),
        ("сделай слайд 4 таблицей", True),  # «сделай … слайд» is not a new deck when one is open
        ("поменяй макет слайда 3", True),
        ("покажи план", False),
        ("почему слайд 3 такой?", False),
        ("проверь качество", False),
        ("исправь всё", False),
        ("сделай презентацию про кофейню на 5 слайдов", False),
    ],
)
def test_edit_or_other_intent(message, expected):
    intent, _ = _intent(message)
    assert _is_edit(message, intent) is expected
