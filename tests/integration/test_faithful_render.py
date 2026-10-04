"""A dictated text rendered as written on a real template (planning/faithful.py → matching → rendering): the cover is
the user's first slide, the code stands as code in a monospace face, three charts stand side by side, the picture's
place says what goes there, nothing is cut inside a sentence."""

import re
from pathlib import Path

import pytest
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "workspace"
EDU = WS / "templates" / "9ef2323ed5f49f46" / "source.pptx"
BRIEF = ROOT / "tests" / "fixtures" / "briefs" / "smart_greenhouse.md"

pytestmark = pytest.mark.skipif(not EDU.exists(), reason="the VK Education template is not in the workspace")


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import parse_brief_text

    out = tmp_path_factory.mktemp("faithful")
    res = generate_variants(EDU, brief=parse_brief_text(BRIEF.read_text(encoding="utf-8")), strategies=["structured"], out_dir=out,
                            workspace_root=WS, providers=None, skills=None, use_llm=False, use_vlm=False, audit=False, autofix=False, exports=[])
    v = res.variants[0]
    return v, Presentation(str(out / "structured" / "deck.pptx"))


def _texts(slide) -> list[str]:
    # (line breaks and no-break spaces of the typesetting read as spaces)
    return [" ".join(sh.text_frame.text.replace("\x0b", " ").replace("\u00a0", " ").split()) for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]


def test_the_users_first_slide_is_the_cover_and_nothing_is_added_before_it(deck):
    v, prs = deck
    assert len(prs.slides) == 14
    assert any("Умная теплица" in t for t in _texts(prs.slides[0]))
    assert not any(re.search(r"Слайд\s+1\b", t) for s in prs.slides for t in _texts(s))
    assert any("Спасибо за внимание" in t for t in _texts(prs.slides[13]))


def test_code_stands_as_written_in_a_monospace_face(deck):
    v, prs = deck
    for i, first_line in ((4, '"timestamp": "2026-06-15T10:30:00+03:00",'), (6, "def irrigation_decision(")):
        runs = [(r.text, r.font.name) for sh in prs.slides[i].shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs]
        code = [(t, f) for t, f in runs if first_line in t.replace(" ", " ")]
        assert code, f"slide {i + 1}: the code's line is not on the slide"
        assert re.search(r"consolas|courier|mono|menlo", code[0][1] or "", re.I), code[0]


def test_three_charts_stand_side_by_side(deck):
    v, prs = deck
    charts = [sh for sh in prs.slides[8].shapes if sh.has_chart]
    assert len(charts) == 3
    tops = sorted(round(sh.top / prs.slide_height, 2) for sh in charts)
    assert tops[-1] - tops[0] <= 0.02  # on one line under captions of one, two or three lines


def test_the_picture_place_says_what_goes_there(deck):
    v, prs = deck
    texts = _texts(prs.slides[3])
    assert any("Место под изображение" in t and "Вид теплицы сверху" in t for t in texts)
