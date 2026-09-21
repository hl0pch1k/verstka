import pytest
from PIL import Image

from verstka.ingest.render import find_pdftoppm, find_soffice, render_slides
from verstka.ingest.workspace import TemplateWorkspace, file_sha256

needs_office = pytest.mark.skipif(find_soffice() is None or find_pdftoppm() is None, reason="LibreOffice/poppler not installed")


@needs_office
def test_render_slides_produces_one_image_per_slide(simple_deck, tmp_path):
    out = tmp_path / "slides"
    images = render_slides(simple_deck, out, dpi=50)
    assert [p.name for p in images] == ["slide-001.jpg", "slide-002.jpg", "slide-003.jpg"]
    with Image.open(images[0]) as im:
        assert im.width > im.height > 0


def test_workspace_is_keyed_by_hash(simple_deck, tmp_path):
    ws = TemplateWorkspace.create(simple_deck, tmp_path / "ws")
    assert ws.template_id == file_sha256(simple_deck)[:16]
    assert ws.source.exists() and not ws.is_analyzed
    again = TemplateWorkspace.create(simple_deck, tmp_path / "ws")
    assert again.dir == ws.dir
    assert TemplateWorkspace.open(ws.template_id, tmp_path / "ws").original_name == "simple.pptx"
