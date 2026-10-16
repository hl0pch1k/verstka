"""Брендбук, папка и Figma: логотипы (больше восьми, версия по заливке SVG, растр SVG), Tokens Studio в нескольких файлах,
ссылки Figma (без схемы, ветка, /make/), переменные Figma с ответом 200 (разбор замечаний ревью задачи 5). Сеть подменена."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

import verstka.brand.folder as folder_mod
from verstka.brand.common import BrandReadError
from verstka.brand.figma import figma_key, is_figma_url, normalize_url, read_figma_url
from verstka.brand.folder import logo_variant_of, rasterize_svg
from verstka.brand.read import read_brandbook
from verstka.brand.svg_raster import render_svg

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "brand"
SAMPLE = ROOT / "examples" / "brandbook-vk-cloud"

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{body}</svg>'
WIDE = "0 0 400 100"


def _svg(path: Path, body: str, vb: str = WIDE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SVG.format(vb=vb, body=body), encoding="utf-8")
    return path


def _roles(spec) -> dict[str, str]:
    return {c.hex: c.role for c in spec.colors}


# ---- 8. больше восьми логотипов -----------------------------------------------------------------------------------------------------
def test_more_than_eight_logos_keep_one_of_every_version(tmp_path):
    root = tmp_path / "Logos"
    for i in range(1, 11):  # десять одинаковых цветных SVG — по картинке все «основные», по алфавиту идут первыми
        _svg(root / f"{i:02d}_variant.svg", '<path fill="#7B2CBF" d="M0 0h50v50z"/>')
    _svg(root / "Zeta-white.svg", '<path fill="white" d="M0 0h50v50z"/>')
    _svg(root / "Zeta-mark.svg", '<path fill="#7B2CBF" d="M0 0h50v50z"/>', "0 0 100 100")
    _svg(root / "Zeta-black.svg", '<path fill="#000" d="M0 0h50v50z"/>')
    spec = read_brandbook(root)
    variants = [lg.variant for lg in spec.logos]
    assert len(spec.logos) == 8
    assert {"primary", "white", "mark", "mono"} <= set(variants)  # белая версия не потеряна из-за алфавита
    assert variants == sorted(variants, key=["primary", "white", "mark", "mono"].index)  # основные впереди, затем белый, знак, монохром
    assert [lg.name for lg in spec.logos][:3] == ["Основной", "Основной 2", "Основной 3"]
    by = {lg.variant: lg for lg in spec.logos if lg.variant != "primary"}
    assert by["white"].file.endswith("Zeta-white.svg") and by["white"].ground == "dark"
    assert any("13 логотипов" in w and "взял 8" in w for w in spec.warnings)


def test_a_logo_named_for_its_version_is_preferred_over_one_guessed_from_the_picture(tmp_path):
    root = tmp_path / "logo"
    _svg(root / "a-unnamed.svg", '<path fill="white" d="M0 0h50v50z"/>')
    _svg(root / "b-inverse.svg", '<path fill="white" d="M0 0h50v50z"/>')
    spec = read_brandbook(root)
    assert [(lg.variant, Path(lg.file).name) for lg in spec.logos][0] == ("white", "b-inverse.svg")


# ---- версия SVG по заливке ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name, body, vb, expected", [
    ("white-word", '<path fill="white" d="M0 0h50v50z"/>', WIDE, ("white", "dark")),
    ("white-rgb", '<path fill="rgb(255, 255, 255)" d="M0 0h50v50z"/>', WIDE, ("white", "dark")),
    ("white-style", '<path style="fill:#ffffff;fill-rule:evenodd" d="M0 0h50v50z"/>', WIDE, ("white", "dark")),
    ("white-class", '<defs><style>.cls-1{fill:#fff;}</style></defs><path class="cls-1" d="M0 0h50v50z"/>', WIDE, ("white", "dark")),
    ("white-with-none", '<rect fill="none" width="1" height="1"/><path fill="#fff" d="M0 0h50v50z"/>', WIDE, ("white", "dark")),
    ("black-word", '<path fill="black" d="M0 0h50v50z"/>', WIDE, ("mono", "light")),
    ("black-hex", '<path fill="#000" d="M0 0h50v50z"/>', WIDE, ("mono", "light")),
    ("no-fill-is-black", '<path d="M0 0h50v50z"/>', WIDE, ("mono", "light")),
    ("colour", '<path fill="#0044CC" d="M0 0h50v50z"/><path fill="#101820" d="M60 0h50v50z"/>', WIDE, ("primary", "light")),
    ("square", '<path fill="#0044CC" d="M0 0h50v50z"/>', "0 0 100 100", ("mark", "any")),
    ("gradient-fill", '<defs><linearGradient id="g"><stop stop-color="#0044CC"/></linearGradient></defs><path fill="url(#g)" d="M0 0h50v50z"/>', WIDE, ("primary", "light")),
])
def test_svg_logo_version_by_fills_and_proportions(tmp_path, name, body, vb, expected):
    assert logo_variant_of(_svg(tmp_path / f"{name}.svg".replace("white-", "w-").replace("black-", "k-"), body, vb)) == expected


# ---- растр SVG-логотипа -------------------------------------------------------------------------------------------------------------------------
def test_an_svg_only_logo_is_exposed_as_a_png_next_to_its_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_mod.shutil, "which", lambda name: None)  # без внешних программ — встроенный растеризатор
    root = tmp_path / "brand" / "logos"
    _svg(root / "acme-white.svg", '<path fill="#fff" d="M10 10h80v80h-80z"/>', "0 0 400 100")
    _svg(root / "acme.svg", '<path fill="#0044CC" d="M10 10h80v80h-80z"/>', "0 0 400 100")
    assets = tmp_path / "assets"
    spec = read_brandbook(tmp_path / "brand", assets_dir=assets)
    assert sorted(lg.file for lg in spec.logos) == ["logos/acme-white.png", "logos/acme.png"]
    for lg in spec.logos:
        assert (assets / lg.file).is_file() and (assets / lg.file).with_suffix(".svg").is_file()
        with Image.open(assets / lg.file) as im:
            assert im.mode == "RGBA" and im.size[1] == 480
            assert im.getpixel((2, 2))[3] == 0  # фон прозрачный
            assert im.getpixel((im.size[0] // 8, im.size[1] // 2))[3] == 255
    with Image.open(assets / "logos" / "acme-white.png") as im:
        assert im.getpixel((im.size[0] // 8, im.size[1] // 2))[:3] == (255, 255, 255)
    # без assets_dir писать некуда — остаётся SVG из папки
    assert {lg.file for lg in read_brandbook(tmp_path / "brand").logos} == {"logos/acme-white.svg", "logos/acme.svg"}


def test_an_svg_the_rasteriser_cannot_draw_stays_svg_with_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_mod.shutil, "which", lambda name: None)
    root = tmp_path / "brand" / "logos"
    _svg(root / "wordmark.svg", '<text x="0" y="50" font-size="40">Acme</text>', WIDE)
    spec = read_brandbook(tmp_path / "brand", assets_dir=tmp_path / "assets")
    assert [lg.file for lg in spec.logos] == ["logos/wordmark.svg"]
    assert any("wordmark.svg" in w and "PNG" in w for w in spec.warnings)


@pytest.mark.skipif(not shutil.which("rsvg-convert"), reason="нет rsvg-convert")
def test_the_external_rasteriser_is_used_when_present(tmp_path):
    out = tmp_path / "logo.png"
    assert rasterize_svg(SAMPLE / "logos" / "primary.svg", out, height=240)
    with Image.open(out) as im, Image.open(SAMPLE / "logos" / "primary.png") as ref:
        assert im.size == ref.size


def test_builtin_rasteriser_matches_the_sample_logos(tmp_path):
    import numpy as np

    for variant, height in (("primary", 240), ("white", 240), ("mark", 512), ("mono", 240)):
        im = render_svg(SAMPLE / "logos" / f"{variant}.svg", height)
        with Image.open(SAMPLE / "logos" / f"{variant}.png") as ref:
            ref = ref.convert("RGBA")
        assert im is not None and im.size == ref.size
        diff = np.abs(np.asarray(im.getchannel("A")).astype(int) - np.asarray(ref.getchannel("A")).astype(int))
        assert diff.mean() < 2.0, variant  # контур совпадает с rsvg-convert


def test_builtin_rasteriser_shapes_holes_transforms_and_opacity(tmp_path):
    def px(body: str, vb: str = "0 0 100 100", at=(50, 50), height: int = 100):
        im = render_svg(_svg(tmp_path / "t.svg", body, vb), height)
        assert im is not None
        return im.getpixel(at)

    assert px('<rect x="10" y="10" width="80" height="80" fill="#FF0000"/>') == (255, 0, 0, 255)
    assert px('<rect x="10" y="10" width="80" height="80" fill="#FF0000"/>', at=(3, 3))[3] == 0
    assert px('<circle cx="50" cy="50" r="30" fill="#00FF00"/>', at=(50, 25))[3] == 255
    assert px('<circle cx="50" cy="50" r="30" fill="#00FF00"/>', at=(50, 15))[3] == 0
    # дыра: evenodd и противоположный обход при nonzero
    hole = 'd="M0 0H100V100H0Z M30 30H70V70H30Z"'
    assert px(f'<path fill="#000" fill-rule="evenodd" {hole}/>')[3] == 0
    assert px(f'<path fill="#000" {hole}/>')[3] == 255  # nonzero, один обход — закрашено
    assert px('<path fill="#000" d="M0 0H100V100H0Z M30 30V70H70V30Z"/>')[3] == 0
    # группа с преобразованием, прозрачность и стиль из <style>
    assert px('<g transform="translate(50 0) scale(.5)"><rect width="100" height="100" fill="#0000FF"/></g>', at=(75, 25)) == (0, 0, 255, 255)
    assert px('<rect width="100" height="100" fill="#000" opacity=".5"/>')[3] in range(126, 130)
    assert px('<defs><style>.a{fill:#112233}</style></defs><rect class="a" width="100" height="100"/>')[:3] == (17, 34, 51)
    assert px('<defs><linearGradient id="g"><stop offset="0" stop-color="#FF0000"/></linearGradient></defs><rect width="100" height="100" fill="url(#g)"/>')[:3] == (255, 0, 0)
    # арка с флагами, записанными слитно, и относительные команды
    assert px('<path fill="#000" d="M10 50a40 40 0 1080 0a40 40 0 10-80 0z"/>', at=(50, 50))[3] == 255
    # то, чего растеризатор не умеет, — отказ, а не пустая картинка
    assert render_svg(_svg(tmp_path / "s.svg", '<path fill="none" stroke="#000" d="M0 0L50 50"/>')) is None
    assert render_svg(_svg(tmp_path / "x.svg", '<text>A</text>')) is None
    (tmp_path / "bad.svg").write_text("<svg", encoding="utf-8")
    assert render_svg(tmp_path / "bad.svg") is None


# ---- 9. Tokens Studio в нескольких файлах ------------------------------------------------------------------------------------------------------------
def test_multi_file_tokens_studio_folder_is_merged_before_parsing(tmp_path):
    root = tmp_path / "tokens"
    shutil.copytree(FIX / "ts-multi", root)  # $metadata.json, $themes.json, global.json, semantic.json
    spec = read_brandbook(root)
    assert _roles(spec) == {"#0055FF": "primary", "#111111": "text", "#FFFFFF": "background", "#FF6A00": "accent"}  # ссылки между файлами раскрыты
    assert spec.fonts == [] or spec.fonts[0].family == "Inter"
    assert spec.warnings == []  # без «нет ни цветов» от $-файлов и набора со ссылками
    # отдельно взятый набор со ссылками на другой файл читать нечем — но и молча терять его нельзя
    (root / "broken.json").write_text("{", encoding="utf-8")
    spec = read_brandbook(root)
    assert any("broken.json" in w for w in spec.warnings) and _roles(spec)["#0055FF"] == "primary"


def test_dollar_files_are_never_read_on_their_own(tmp_path):
    root = tmp_path / "bb"
    root.mkdir()
    (root / "$themes.json").write_text("[]", encoding="utf-8")
    (root / "tokens.json").write_text('{"color": {"primary": "#0077FF", "text": "#0B1220"}}', encoding="utf-8")
    spec = read_brandbook(root)
    assert _roles(spec) == {"#0077FF": "primary", "#0B1220": "text"} and spec.warnings == [
        "Шрифтов в брендбуке нет — шрифты останутся из шаблона."]


# ---- Figma: ссылки ----------------------------------------------------------------------------------------------------------------------------------------
KEY = "AbCdEf1234567890xyzABC"
BRANCH = "BrAnCh1234567890QWErty"


@pytest.mark.parametrize("url", [
    f"https://www.figma.com/design/{KEY}/Brand-Book?node-id=0-1&t=abc",
    f"figma.com/design/{KEY}/Brand-Book",
    f"www.figma.com/file/{KEY}/Brand-Book",
    f"  https://www.figma.com/design/{KEY}/Brand-Book  ",
    f"<https://www.figma.com/design/{KEY}/Brand-Book>",
    f"https://www.figma.com/make/{KEY}/App",
    f"https://embed.figma.com/design/{KEY}/Brand?embed-host=share",
    f"https://www.figma.com/board/{KEY}/Jam",
])
def test_figma_links_in_the_ways_people_paste_them(url):
    assert is_figma_url(url) and normalize_url(url).startswith("https://") and figma_key(url) == KEY


def test_a_branch_link_reads_the_branch_not_the_main_file():
    assert figma_key(f"https://www.figma.com/design/{KEY}/branch/{BRANCH}/Brand-Book") == BRANCH
    assert figma_key(f"https://www.figma.com/design/{KEY}/branch/{BRANCH}") == BRANCH
    for bad in ("https://www.figma.com/community/file/1234567890123456789", "https://www.figma.com/files/team/1/project/2", "figma://file/" + KEY):
        with pytest.raises(BrandReadError):
            figma_key(bad)
    assert not is_figma_url("https://example.com/design/" + KEY)


def _client(seen: list[httpx.Request], *, key: str = KEY, variables: dict | None = None) -> httpx.Client:
    styles = {"1:1": {"name": "Accent", "styleType": "FILL", "description": "Акцент — только для главного числа"}}
    fill = {"document": {"fills": [{"type": "SOLID", "color": {"r": 1, "g": 57 / 255, "b": 133 / 255, "a": 1}}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == f"/v1/files/{key}":
            return httpx.Response(200, json={"name": "Брендбук VK Cloud", "styles": styles})
        if path.endswith("/variables/local"):
            if variables is None:
                return httpx.Response(403, json={"status": 403, "error": True})
            return httpx.Response(200, json={"status": 200, "error": False, "meta": variables})
        if path.endswith("/nodes"):
            return httpx.Response(200, json={"nodes": {"1:1": fill}})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_scheme_less_branch_and_make_links_go_through_the_api(monkeypatch):
    monkeypatch.setenv("FIGMA_TOKEN", "t")
    seen: list[httpx.Request] = []
    spec = read_brandbook(f"figma.com/design/{KEY}/branch/{BRANCH}/Brandbook", figma_client=_client(seen, key=BRANCH))
    assert spec.source == "figma" and spec.file.startswith("https://figma.com/design/") and _roles(spec) == {"#FF3985": "accent"}
    assert {r.url.path for r in seen} >= {f"/v1/files/{BRANCH}"} and not any(KEY in r.url.path for r in seen)
    seen.clear()
    spec = read_brandbook(f"https://www.figma.com/make/{KEY}/App", figma_client=_client(seen))
    assert _roles(spec) == {"#FF3985": "accent"}
    with pytest.raises(BrandReadError, match="только файлы Figma"):
        read_brandbook("ftp://example.com/brand.pdf")
    with pytest.raises(BrandReadError, match="Не нашёл"):
        read_brandbook("figma-brand.pdf")  # обычное имя файла, не ссылка


# ---- Figma: переменные, ответ 200 --------------------------------------------------------------------------------------------------------------------
VARIABLES = {
    "variableCollections": {"c1": {"defaultModeId": "m1", "modes": [{"modeId": "m1", "name": "Light"}, {"modeId": "m2", "name": "Dark"}]}},
    "variables": {
        "v1": {"name": "palette/VK Blue", "resolvedType": "COLOR", "variableCollectionId": "c1",
               "valuesByMode": {"m1": {"r": 0, "g": 0.4667, "b": 1, "a": 1}, "m2": {"r": 0.2, "g": 0.6, "b": 1, "a": 1}}},
        "v2": {"name": "brand/primary", "resolvedType": "COLOR", "variableCollectionId": "c1",
               "valuesByMode": {"m1": {"type": "VARIABLE_ALIAS", "id": "v1"}, "m2": {"r": 0.2, "g": 0.6, "b": 1, "a": 1}}},
        "v3": {"name": "text/default", "resolvedType": "COLOR", "variableCollectionId": "c1",
               "valuesByMode": {"m1": {"r": 0.043, "g": 0.0706, "b": 0.1255, "a": 1}, "m2": {"r": 1, "g": 1, "b": 1, "a": 1}}},
        "v4": {"name": "bg/default", "resolvedType": "COLOR", "variableCollectionId": "c1",
               "valuesByMode": {"m1": {"r": 1, "g": 1, "b": 1, "a": 1}, "m2": {"r": 0.04, "g": 0.04, "b": 0.04, "a": 1}}},
        "v5": {"name": "font/heading", "resolvedType": "STRING", "variableCollectionId": "c1", "valuesByMode": {"m1": "VK Sans Display", "m2": "VK Sans Display"}},
        "v6": {"name": "font/body", "resolvedType": "STRING", "variableCollectionId": "c1", "valuesByMode": {"m1": "VK Sans Text", "m2": "VK Sans Text"}},
        "v7": {"name": "layout/margin", "resolvedType": "FLOAT", "variableCollectionId": "c1", "valuesByMode": {"m1": 48, "m2": 48}},
        "v8": {"name": "brand/hover", "resolvedType": "COLOR", "variableCollectionId": "c1", "valuesByMode": {"m1": {"r": 0, "g": 0, "b": 0.5, "a": 1}}},
    },
}


def test_figma_link_with_variables_200_merges_variables_and_styles(monkeypatch):
    monkeypatch.setenv("FIGMA_TOKEN", "t")
    seen: list[httpx.Request] = []
    spec = read_brandbook(f"https://www.figma.com/design/{KEY}/Brandbook", figma_client=_client(seen, variables=VARIABLES))
    assert {r.url.path for r in seen} == {f"/v1/files/{KEY}", f"/v1/files/{KEY}/variables/local", f"/v1/files/{KEY}/nodes"}
    # режим по умолчанию (Light), а не тёмный; состояние hover пропущено; стиль «Accent» добавлен к переменным
    assert _roles(spec) == {"#0077FF": "primary", "#0B1220": "text", "#FFFFFF": "background", "#FF3985": "accent"}
    assert {c.hex: c.name for c in spec.colors}["#0077FF"] == "VK Blue"  # имя — из переменной палитры, не «Primary»
    assert {f.role: f.family for f in spec.fonts} == {"heading": "VK Sans Display", "body": "VK Sans Text"}
    assert spec.margins_px == 48 and any("главного числа" in r.text for r in spec.rules)
    assert spec.name == "VK Cloud" and spec.source == "figma"


def test_figma_variables_export_names_are_not_role_words():
    spec = read_brandbook(FIX / "tokens" / "figma_vars_export_modes.json")
    assert [(c.hex, c.role, c.name) for c in spec.colors] == [("#0077FF", "primary", None), ("#0A121F", "text", None)]
    spec = read_figma_url(f"https://www.figma.com/design/{KEY}/x", token="t", client=_client([], variables=VARIABLES))
    assert {c.hex: c.name for c in spec.colors}["#0B1220"] is None  # «Default» — не имя цвета
