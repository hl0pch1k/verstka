"""Брендбук из файла Figma `.fig` без Figma и без токена (`verstka/brand/fig.py`, `kiwi.py`, `zstd.py`).

- распаковщик zstd на чистом Python — по эталонам CLI `zstd` (уровни 1–22, без размера в заголовке);
- настоящие `.fig` (frame, components из gridaco/grida, Apache-2.0): ZIP → kiwi → zstd → узлы, палитра по заливкам;
- синтетический `.fig` (кодировщик kiwi в `fig_helpers.py`): семантические переменные → роли, стили текста → шрифты, сетка
  фрейма 16:9 → поля и колонки, шкала «Space/…» → правило, логотип-вектор → PNG, значок соцсети — не логотип;
- документ не читается → палитра превью и картинки + честное предупреждение; мусор → понятная ошибка;
- через API: `.fig` принимается (не 400), мусор с расширением `.fig` — 400 сразу."""

from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from fig_helpers import fig_bytes, fig_zip, identity, node, path_blob, rgb, solid
from verstka.brand.common import BrandReadError
from verstka.brand.fig import PREVIEW_ONLY, read_fig
from verstka.brand.kiwi import KiwiError, decode_message, decode_schema, read_fig_archive
from verstka.brand.read import read_brandbook
from verstka.brand.zstd import ZstdError, decompress

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fig"


# ---- zstd ---------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["text_l3", "text_l19", "rle_nosize", "random_ultra"])
def test_zstd_matches_cli_reference(name):
    ref = {ln.split()[0]: (int(ln.split()[1]), ln.split()[2]) for ln in (FIX / "zstd" / "SHA256").read_text().splitlines()}
    out = decompress((FIX / "zstd" / f"{name}.zst").read_bytes())
    assert (len(out), hashlib.sha256(out).hexdigest()) == ref[name]


def test_zstd_errors_and_bomb_limit():
    with pytest.raises(ZstdError):
        decompress(b"not zstd at all")
    with pytest.raises(ZstdError):
        decompress((FIX / "zstd" / "rle_nosize.zst").read_bytes(), max_output=1000)


# ---- kiwi -------------------------------------------------------------------------------------------------------------------------
def test_kiwi_roundtrip_of_encoder():
    from fig_helpers import SCHEMA, encode_message, encode_schema

    defs = decode_schema(encode_schema(SCHEMA))
    msg = {"nodeChanges": [node(1, None, "DOCUMENT", "Документ", size={"x": -1.5, "y": 1e6}, visible=False)],
           "blobs": [{"bytes": b"\x01\x02"}]}
    got, partial = decode_message(defs, encode_message(msg))
    assert not partial
    n = got["nodeChanges"][0]
    assert n["type"] == "DOCUMENT" and n["name"] == "Документ" and n["visible"] is False
    assert n["size"] == {"x": -1.5, "y": 1e6} and got["blobs"][0]["bytes"] == b"\x01\x02"


def test_kiwi_broken_data_is_an_error_not_a_crash():
    with pytest.raises(KiwiError):
        read_fig_archive(b"fig-kiwi\x10\x00\x00\x00\x03\x00\x00\x00abc")
    with pytest.raises(KiwiError):
        read_fig_archive(b"PK\x03\x04 not a fig")


# ---- real files ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["frame.fig", "components.fig"])
def test_real_fig_files_read(name, tmp_path):
    arc = read_fig_archive(__import__("zipfile").ZipFile(FIX / name).read("canvas.fig"))
    assert arc.header == "fig-kiwi" and arc.message["nodeChanges"]
    spec = read_brandbook(FIX / name, assets_dir=tmp_path)
    assert spec.source == "figma" and spec.file == name and spec.colors
    assert any("заливкам макетов" in w for w in spec.warnings)  # no styles or variables in these files — said so


# ---- synthetic design system ------------------------------------------------------------------------------------------------------
def _var(local: int, set_id: int, mode: int, name: str, kind: str, value: dict) -> dict:
    return node(local, 2, "VARIABLE", name, variableSetID={"guid": {"sessionID": 1, "localID": set_id}}, variableResolvedType=kind,
                variableDataValues={"entries": [{"modeID": {"sessionID": 1, "localID": mode}, "variableData": {"value": value, "dataType": kind}}]})


def _design_system() -> dict:
    sq = path_blob([("M", 0, 0), ("L", 40, 0), ("L", 40, 40), ("L", 0, 40), ("Z",)])
    circle = path_blob([("M", 0, 20), ("C", 0, 9, 9, 0, 20, 0), ("C", 31, 0, 40, 9, 40, 20), ("C", 40, 31, 31, 40, 20, 40),
                        ("C", 9, 40, 0, 31, 0, 20), ("Z",)])
    nodes = [
        node(1, None, "DOCUMENT", "Document"),
        node(2, 1, "CANVAS", "Internal Only Canvas"),
        node(3, 1, "CANVAS", "Слайды"),
        node(10, 2, "VARIABLE_SET", "Color Primitives", variableSetModes=[{"id": {"sessionID": 1, "localID": 100}, "name": "Value"}]),
        node(11, 2, "VARIABLE_SET", "Color", variableSetModes=[{"id": {"sessionID": 1, "localID": 110}, "name": "Light"},
                                                               {"id": {"sessionID": 1, "localID": 111}, "name": "Dark"}]),
        node(12, 2, "VARIABLE_SET", "Size", variableSetModes=[{"id": {"sessionID": 1, "localID": 120}, "name": "Default"}]),
        _var(20, 10, 100, "Green/700", "COLOR", {"colorValue": rgb("#1B5E20")}),
        _var(21, 10, 100, "Orange/500", "COLOR", {"colorValue": rgb("#FF6F00")}),
        _var(22, 10, 100, "Black/100", "COLOR", {"colorValue": rgb("#000000", 0.05)}),
        _var(30, 11, 110, "Background/Brand/Default", "COLOR", {"alias": {"guid": {"sessionID": 1, "localID": 20}}}),
        _var(31, 11, 110, "Background/Brand/Hover", "COLOR", {"colorValue": rgb("#0D3311")}),
        _var(32, 11, 110, "Background/Default/Default", "COLOR", {"colorValue": rgb("#F5F1E8")}),
        _var(33, 11, 110, "Text/Default/Default", "COLOR", {"colorValue": rgb("#212121")}),
        _var(34, 11, 110, "Background/Accent/Default", "COLOR", {"alias": {"guid": {"sessionID": 1, "localID": 21}}}),
        _var(35, 11, 110, "Background/Danger/Default", "COLOR", {"colorValue": rgb("#D32F2F")}),
        _var(36, 11, 110, "Text/Brand/On Brand", "COLOR", {"colorValue": rgb("#FFFFFF")}),
        _var(40, 12, 120, "Space/100", "FLOAT", {"floatValue": 4.0}),
        _var(41, 12, 120, "Space/200", "FLOAT", {"floatValue": 8.0}),
        _var(42, 12, 120, "Space/400", "FLOAT", {"floatValue": 16.0}),
        _var(43, 12, 120, "Space/800", "FLOAT", {"floatValue": 32.0}),
        node(50, 2, "TEXT", "Title Hero", styleType="TEXT", fontName={"family": "PT Serif", "style": "Bold"}, fontSize=72.0),
        node(51, 2, "TEXT", "Body Base", styleType="TEXT", fontName={"family": "PT Sans", "style": "Regular"}, fontSize=16.0),
        node(52, 2, "TEXT", "Code", styleType="TEXT", fontName={"family": "Roboto Mono", "style": "Regular"}, fontSize=14.0),
        # слайд 16:9 с сеткой: 12 колонок, поле 96 и промежуток 24 на ширине 3840 → 48 и 12 px на 1920
        node(60, 3, "FRAME", "Slide / Cover", size={"x": 3840.0, "y": 2160.0}, transform=identity(),
             fillPaints=[solid("#F5F1E8")],
             layoutGrids=[{"type": "STRETCH", "axis": "X", "visible": True, "numSections": 12, "offset": 96.0, "sectionSize": 10.0, "gutterSize": 24.0}]),
        # логотип: знак из двух контуров; значок соцсети рядом — не логотип бренда
        node(70, 60, "FRAME", "Logo", size={"x": 100.0, "y": 40.0}, transform=identity(80, 80)),
        node(71, 70, "VECTOR", "Square", size={"x": 40.0, "y": 40.0}, transform=identity(0, 0), fillPaints=[solid("#1B5E20")],
             fillGeometry=[{"windingRule": "NONZERO", "commandsBlob": 0}]),
        node(72, 70, "VECTOR", "Dot", size={"x": 40.0, "y": 40.0}, transform=identity(60, 0), fillPaints=[solid("#FF6F00")],
             fillGeometry=[{"windingRule": "NONZERO", "commandsBlob": 1}]),
        node(80, 60, "FRAME", "Logo Instagram", size={"x": 40.0, "y": 40.0}, transform=identity(3000, 80)),
        node(81, 80, "VECTOR", "Glyph", size={"x": 40.0, "y": 40.0}, transform=identity(), fillPaints=[solid("#E1306C")],
             fillGeometry=[{"windingRule": "NONZERO", "commandsBlob": 1}]),
    ]
    return {"nodeChanges": nodes, "blobs": [sq, circle]}


def _png(color: str, size=(400, 225), alpha: bool = False) -> bytes:
    im = Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else color)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, size[0], size[1] // 6), fill="#1B5E20")
    d.rectangle((20, size[1] // 2, size[0] // 2, size[1] // 2 + 20), fill="#FF6F00")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_design_system_fig_roles_fonts_grid_logo(tmp_path):
    p = tmp_path / "Северный лес.fig"
    p.write_bytes(fig_zip(fig_bytes(_design_system()), thumbnail=_png("#F5F1E8"), meta={"file_name": "Северный лес (Copy)"}))
    spec = read_brandbook(p, assets_dir=tmp_path / "assets")
    roles = {c.role: c.hex for c in spec.colors}
    assert roles["primary"] == "#1B5E20"  # Background/Brand/Default → alias → Green/700
    assert roles["background"] == "#F5F1E8" and roles["text"] == "#212121"
    assert roles["accent"] == "#FF6F00" and roles["danger"] == "#D32F2F"
    hexes = [c.hex for c in spec.colors]
    assert "#0D3311" not in hexes and "#FFFFFF" not in hexes and "#000000" not in hexes  # hover, «on brand», 5% alpha
    assert {f.role: f.family for f in spec.fonts} == {"heading": "PT Serif", "body": "PT Sans"}
    assert spec.margins_px == 48.0 and spec.grid and spec.grid.startswith("12 колонок") and "12 px" in spec.grid
    assert any(r.text.startswith("Шаг отступов: 4, 8, 16, 32") for r in spec.rules)
    assert spec.name == "Северный лес"
    assert len(spec.logos) == 1  # «Logo», not «Logo Instagram»
    png = tmp_path / "assets" / spec.logos[0].file
    assert png.suffix == ".png" and png.exists()
    with Image.open(png) as im:
        px = im.convert("RGBA")
        w, h = px.size
        assert px.getpixel((int(w * 0.2), h // 2))[:3] == (0x1B, 0x5E, 0x20)
        assert px.getpixel((int(w * 0.8), h // 2))[:3] == (0xFF, 0x6F, 0x00)
    assert not any("превью" in w for w in spec.warnings)


def test_old_binary_fig_without_zip(tmp_path):
    p = tmp_path / "old.fig"
    p.write_bytes(fig_bytes(_design_system()))
    spec = read_fig(p)
    assert spec.color("primary").hex == "#1B5E20" and spec.logos == []  # no store for logos: none kept


def test_fig_without_styles_takes_fills_and_text(tmp_path):
    nodes = [node(1, None, "DOCUMENT", "D"), node(2, 1, "CANVAS", "P"),
             node(3, 2, "FRAME", "Bg", size={"x": 1920.0, "y": 1080.0}, fillPaints=[solid("#0B1220")]),
             node(4, 3, "FRAME", "Card", size={"x": 600.0, "y": 300.0}, fillPaints=[solid("#00C2FF")]),
             node(5, 3, "TEXT", "H", size={"x": 900.0, "y": 80.0}, fontName={"family": "Manrope", "style": "Bold"}, fontSize=64.0,
                  textData={"characters": "Заголовок"}),
             node(6, 3, "TEXT", "P", size={"x": 900.0, "y": 300.0}, fontName={"family": "Inter", "style": "Regular"}, fontSize=18.0,
                  textData={"characters": "Основной текст " * 20})]
    p = tmp_path / "plain.fig"
    p.write_bytes(fig_zip(fig_bytes({"nodeChanges": nodes, "blobs": []})))
    spec = read_fig(p)
    assert spec.colors[0].hex == "#0B1220" and "#00C2FF" in [c.hex for c in spec.colors]
    assert {f.role: f.family for f in spec.fonts} == {"heading": "Manrope", "body": "Inter"}
    assert any("заливкам макетов" in w for w in spec.warnings)


def test_unreadable_document_falls_back_to_preview_and_pictures(tmp_path):
    p = tmp_path / "broken.fig"
    p.write_bytes(fig_zip(b"fig-kiwi\x0f\x00\x00\x00\x05\x00\x00\x00junk!", thumbnail=_png("#F5F1E8"),
                          images={"3f2a9c0b1d": _png("#000000", (300, 120), alpha=True), "aa11": _png("#336699", (800, 600))}))
    spec = read_brandbook(p, assets_dir=tmp_path / "assets")
    hexes = [c.hex for c in spec.colors]
    assert "#1B5E20" in hexes and "#F5F1E8" in hexes
    assert PREVIEW_ONLY in spec.warnings
    assert len(spec.logos) == 1  # the transparent picture, not the photo


def test_garbage_fig_is_said_in_words(tmp_path):
    p = tmp_path / "x.fig"
    p.write_bytes(b"\x00\x01garbage")
    with pytest.raises(BrandReadError, match="не похож на файл Figma"):
        read_brandbook(p)
    p.write_bytes(fig_zip(b"fig-kiwi\x0f\x00\x00\x00\x05\x00\x00\x00junk!"))  # nothing readable and no preview
    with pytest.raises(BrandReadError, match="ссылку на файл"):
        read_brandbook(p)


def test_big_document_stops_on_time_and_says_so(tmp_path):
    msg = _design_system()
    msg["nodeChanges"] += [node(1000 + i, 3, "FRAME", f"f{i}", size={"x": 10.0, "y": 10.0}, fillPaints=[solid("#123456")]) for i in range(3000)]
    p = tmp_path / "big.fig"
    p.write_bytes(fig_bytes(msg))
    spec = read_fig(p, time_budget=0.0)
    assert any("очень большой" in w for w in spec.warnings)


# ---- API ---------------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import verstka.api.app as A
    from verstka.api.store import Store

    monkeypatch.setattr(A, "store", Store(tmp_path / "ws"))
    monkeypatch.setattr(A, "models_configured", lambda: False)
    return TestClient(A.app), A


def test_api_takes_fig_file(client):
    c, A = client
    r = c.post("/api/brandbooks", files={"file": ("Бренд.fig", fig_zip(fig_bytes(_design_system())))}, data={"use_models": "false"})
    assert r.status_code == 200, r.text
    t0 = time.time()
    while time.time() - t0 < 30:
        job = A.runner.get(r.json()["job_id"])
        if job is not None and job.events and job.events[-1].get("status") in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job.status == "done", job.events[-1]
    brand = job.result["brand"]
    assert brand["source"] == "figma" and len(brand["logos"]) == 1
    r = c.post("/api/brandbooks", files={"file": ("Бренд.fig", b"garbage")})
    assert r.status_code == 400 and "не похож на файл Figma" in r.json()["detail"]
