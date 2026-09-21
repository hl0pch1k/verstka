from lxml import etree

from verstka.analysis.theme import ThemeResolver
from verstka.analysis.xmlns import NS
from verstka.ingest.package import PptxPackage

A = NS["a"]


def _el(xml: str):
    return etree.fromstring(xml)


def test_scheme_and_modifiers(simple_deck):
    with PptxPackage.open(simple_deck) as pkg:
        res = ThemeResolver(pkg, "ppt/slideMasters/slideMaster1.xml")
        assert res.scheme["accent1"] and len(res.scheme["accent1"]) == 6
        accent = res.resolve_color(_el(f'<a:schemeClr xmlns:a="{A}" val="accent1"/>'))
        assert accent == res.scheme["accent1"]
        # bg1 maps through clrMap to lt1
        assert res.resolve_color(_el(f'<a:schemeClr xmlns:a="{A}" val="bg1"/>')) == res.scheme["lt1"]
        assert res.resolve_color(_el(f'<a:srgbClr xmlns:a="{A}" val="0077ff"/>')) == "0077FF"
        half = res.resolve_color(_el(f'<a:srgbClr xmlns:a="{A}" val="FFFFFF"><a:lumMod val="50000"/></a:srgbClr>'))
        assert half in ("808080", "7F7F7F", "808080")
        tinted = res.resolve_color(_el(f'<a:srgbClr xmlns:a="{A}" val="0077FF"><a:tint val="50000"/></a:srgbClr>'))
        assert tinted != "0077FF" and int(tinted[0:2], 16) > 0x00  # moved towards white
        assert res.resolve_color(_el(f'<a:prstClr xmlns:a="{A}" val="black"/>')) == "000000"
        assert res.font_for("+mj-lt") == res.major_font and res.font_for("Play") == "Play"
