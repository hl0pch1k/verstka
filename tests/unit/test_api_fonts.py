"""Подбор шрифтов в сборке (интеграция verstka/brand/fontpick.py в API): шаблон со стандартными шрифтами — колода на
копии с подобранной парой; свой шрифт шаблона, выключатель, «Собрать ещё раз» на копии; generation.json `fonts`,
«Почему так», копии не в библиотеке шаблонов. Без модели, без отрисовки LibreOffice."""

from __future__ import annotations

import functools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
import verstka.brand.fontpick as fpk
from verstka.analysis.manifest import analyze_template
from verstka.api.store import Store

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tpl_audit"


@pytest.fixture
def api(tmp_path, monkeypatch):
    st = Store(tmp_path)
    monkeypatch.setattr(A, "store", st)
    monkeypatch.setattr(fpk, "fonted_template", functools.partial(fpk.fonted_template, render=False))
    return st


def _tid(st: Store, path: Path) -> str:
    return analyze_template(path, workspace_root=st.root, use_llm=False, use_vlm=False, render=False).template_id


def test_a_standard_font_template_is_built_on_its_copy_with_a_pair(api):
    base = _tid(api, FIX / "templates" / "lo_focus.pptx")
    said: list[str] = []
    steps: dict = {}
    tid, ch = A._fonted_template_id(base, A.GenerateRequest(template_id=base, brief="x"), A.GenerationData(), lambda m, f=0, **k: said.append(m), steps)
    assert tid != base and ch.apply and ch.heading and ch.body
    assert said and all(s.startswith("Шрифты:") for s in said) and "fonts" in steps
    meta = A._fonts_meta(ch, True)
    assert meta["applied"] and meta["heading"] == ch.heading
    assert A.fonts_line(meta).startswith(f"Шрифты: {ch.heading}")
    # «Собрать ещё раз» на копии: подбор по её исходному шаблону — та же копия; выключатель — исходный шаблон
    assert A._fonted_template_id(tid, A.GenerateRequest(template_id=tid, brief="x"), A.GenerationData(), lambda *a, **k: None, {})[0] == tid
    off, ch_off = A._fonted_template_id(tid, A.GenerateRequest(template_id=tid, brief="x", pick_fonts=False), A.GenerationData(), lambda *a, **k: None, {})
    assert off == base and not ch_off.apply
    assert A.fonts_line(A._fonts_meta(ch_off, False)).startswith("Шрифты шаблона сохранены")
    # копия — кэш сборки: в библиотеке шаблонов её нет
    listed = [t["template_id"] for t in TestClient(A.app).get("/api/templates").json()]
    assert base in listed and tid not in listed


def test_a_template_with_its_own_font_is_left_as_it_is(api):
    base = _tid(api, FIX / "vktech_short.pptx")
    tid, ch = A._fonted_template_id(base, A.GenerateRequest(template_id=base, brief="x"), A.GenerationData(), lambda *a, **k: None, {})
    assert tid == base and not ch.apply and "Play" in ch.reason
    assert A.fonts_line(A._fonts_meta(ch, True)).startswith("Шрифты шаблона сохранены — у шаблона свой шрифт (Play)")


def test_the_request_and_its_options_carry_the_switch():
    req = A.GenerateRequest(template_id="t", brief="x")
    assert req.pick_fonts is True and A._request_options(req)["pick_fonts"] is True
    assert A._request_options(A.GenerateRequest(template_id="t", brief="x", pick_fonts=False))["pick_fonts"] is False
