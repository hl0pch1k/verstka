from verstka.ingest.package import PptxPackage, resolve_target


def test_resolve_target():
    assert resolve_target("ppt/slides/slide1.xml", "../slideLayouts/slideLayout1.xml") == "ppt/slideLayouts/slideLayout1.xml"
    assert resolve_target("ppt/presentation.xml", "slides/slide1.xml") == "ppt/slides/slide1.xml"
    assert resolve_target("ppt/slides/slide1.xml", "/ppt/media/image1.png") == "ppt/media/image1.png"


def test_package_structure(simple_deck):
    with PptxPackage.open(simple_deck) as pkg:
        assert pkg.slide_size == (12192000, 6858000)
        assert pkg.slide_parts == ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "ppt/slides/slide3.xml"]
        layout = pkg.layout_of("ppt/slides/slide1.xml")
        assert layout and layout.startswith("ppt/slideLayouts/slideLayout")
        master = pkg.master_of(layout)
        assert master == "ppt/slideMasters/slideMaster1.xml"
        assert pkg.theme_of(master) == "ppt/theme/theme1.xml"
        images = pkg.rel_targets("ppt/slides/slide3.xml", "image")
        assert len(images) == 1 and images[0].startswith("ppt/media/") and images[0].endswith(".png")
        assert pkg.content_type(images[0]) == "image/png"
        assert pkg.embedded_fonts == []
