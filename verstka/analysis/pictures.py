"""What the pictures of a sample slide are: the template's art (kept when the slide is used for new content) or the
sample's own story (a photo, a screenshot, a data graphic) that new content cannot keep.

A designer filling a template slide keeps its 3D renders, abstract shapes and illustrations — they are what makes the
template beautiful — and replaces or drops the photo of a speaker, a product screenshot or bars drawn for the sample's
figures. The kinds are measured on the pictures themselves, so any template is read the same way:

- ``icon``    small picture (a pictogram, a chip): part of a card's design
- ``panel``   a flat picture of a few colours (a card background, a frame drawn as an image)
- ``art``     a cut-out render, an illustration or a smooth one-hue image: decoration that suits any content
- ``line``    a thin strip (a timeline axis, a rule)
- ``bar``     one of two or more elongated pictures (bars of a chart or a Gantt drawn as images): the sample's data
- ``photo``   a photograph (people, places, a cut-out product shot), muted shots of a dark template included
- ``content`` the sample's own information drawn as a picture: a screenshot, a diagram with logos, a chart with its
              axis labels and legend («Item 1 … Item 5», «40 30 20»), words set as an image, a pie or a graph on a
              slide that says it shows charts
- ``ground``  a picture that covers the whole slide (the slide's background)
"""

from __future__ import annotations

import io
import json
import re
import logging
from dataclasses import asdict, dataclass
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q
from verstka.schemas.common import BboxFrac
from verstka.schemas.template import Pattern, TemplateManifest

log = logging.getLogger(__name__)

PICTURES_VERSION = "5"
KEEPABLE = frozenset({"icon", "panel", "art", "line"})  # pictures that may stay on a slide with new content
STORY = frozenset({"photo", "content"})  # pictures that tell the sample's own story


@dataclass(frozen=True)
class SamplePicture:
    shape_id: str
    x: float
    y: float
    w: float
    h: float
    kind: str

    @property
    def box(self) -> BboxFrac:
        return BboxFrac(x=self.x, y=self.y, w=self.w, h=self.h)

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)


@dataclass
class _Stats:
    coverage: float  # share of opaque pixels
    colours: int  # distinct colours (5 bits a channel) of the opaque pixels
    texture: float  # share of mid-contrast neighbour steps: photographic grain
    sharp: float  # share of hard steps: UI text, thin lines
    hue_sd: float  # spread of the hues of saturated pixels
    white: float  # share of near-white opaque pixels
    lum_sd: float = 0.0  # spread of the luminance of the opaque pixels: a photograph's light and shade
    glyphs: int = 0  # small separate marks on a transparent or plain ground: letters, figures, ticks of a chart
    hollow: bool = False  # a ring: its middle is empty (a doughnut drawn for a sample's share)


def _components(mask) -> list[tuple[int, int, int, int, int]]:
    """Connected parts (8-neighbour) of a boolean mask as (y0, x0, y1, x1, pixels): runs of each row joined across
    rows (no image library is needed; a sparse mask has few runs)."""
    import numpy as np

    h = mask.shape[0]
    runs: list[tuple[int, int, int]] = []
    rows: list[list[int]] = []
    for y in range(h):
        r = mask[y]
        if not r.any():
            rows.append([])
            continue
        d = np.diff(np.concatenate(([0], r.astype(np.int8), [0])))
        ids = []
        for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            ids.append(len(runs))
            runs.append((y, int(a), int(b)))
        rows.append(ids)
        if len(runs) > 60000:
            return []  # a busy picture (a photograph): no marks to count
    parent = list(range(len(runs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(1, h):
        prev, cur = rows[y - 1], rows[y]
        if not prev or not cur:
            continue
        for i in cur:
            _, a, b = runs[i]
            for k in prev:
                _, c, e = runs[k]
                if c < b + 1 and e > a - 1:
                    ri, rk = find(i), find(k)
                    if ri != rk:
                        parent[ri] = rk
    comp: dict[int, list[int]] = {}
    for i, (y, a, b) in enumerate(runs):
        r = find(i)
        c = comp.get(r)
        if c is None:
            comp[r] = [y, a, y, b, b - a]
        else:
            c[0], c[1], c[2], c[3], c[4] = min(c[0], y), min(c[1], a), max(c[2], y), max(c[3], b), c[4] + b - a
    return [tuple(v) for v in comp.values()]  # type: ignore[misc]


def _glyphs(x) -> int:
    """How many small separate marks (letters, figures, ticks) a picture shows on a transparent or a plain ground:
    the axis labels and legend of a chart drawn as an image, words set as a picture. A render, a ring, an illustration
    or a photograph is one or a few large parts. `x`: the RGBA pixels."""
    import numpy as np
    from PIL import Image

    h0, w0 = x.shape[:2]
    if w0 > 600:
        im = Image.fromarray(x.astype(np.uint8), "RGBA").resize((600, max(int(h0 * 600 / w0), 1)), Image.BILINEAR)
        x = np.asarray(im).astype(np.int32)
    a = x[..., 3]
    if (a > 200).mean() < 0.5:
        mask = a > 24
    else:
        q5 = x[..., :3] >> 3
        keys = (q5[..., 0] * 1024 + q5[..., 1] * 32 + q5[..., 2])[a > 200]
        vals, counts = np.unique(keys, return_counts=True)
        if not len(vals) or counts.max() < 0.55 * len(keys):
            return 0  # no plain ground: a photograph
        top = vals[counts.argmax()]
        ground = np.array([(top >> 10) & 31, (top >> 5) & 31, top & 31]) * 8 + 4
        if 0.299 * ground[0] + 0.587 * ground[1] + 0.114 * ground[2] < 200:
            return 0  # a dark plate: the sparks and streaks of a render, not letters (a chart on a page is light)
        mask = (np.abs(x[..., :3] - ground).sum(axis=2) > 60) & (a > 200)
    h, w = mask.shape
    if mask.mean() > 0.6:
        return 0
    return sum(1 for (y0, x0, y1, x1, n) in _components(mask) if 0.006 * h <= y1 - y0 + 1 <= 0.07 * h and x1 - x0 <= 0.06 * w and n >= 3)


def _stats(blob: bytes) -> Optional[_Stats]:
    try:
        import numpy as np
        from PIL import Image

        full = Image.open(io.BytesIO(blob)).convert("RGBA")
        try:
            glyphs = _glyphs(np.asarray(full).astype(np.int32))
        except Exception:  # noqa: BLE001
            glyphs = 0
        im = full.copy()
        im.thumbnail((160, 160))
        x = np.asarray(im).astype(np.int32)
        op = x[..., 3] > 200
        n = int(op.sum())
        a40 = x[..., 3] > 40
        hh, ww = a40.shape
        mid = a40[int(hh * 0.35) : int(hh * 0.65) + 1, int(ww * 0.35) : int(ww * 0.65) + 1]
        hollow = bool(0.75 <= ww / max(hh, 1) <= 1.33 and a40.mean() >= 0.12 and mid.size and mid.mean() < 0.08)
        if n < 50:
            return _Stats(coverage=float(op.mean()), colours=0, texture=0.0, sharp=0.0, hue_sd=0.0, white=0.0, glyphs=glyphs, hollow=hollow)
        rgb = x[..., :3][op] >> 3
        colours = int(len(np.unique(rgb[:, 0] * 1024 + rgb[:, 1] * 32 + rgb[:, 2])))
        g = np.asarray(im.convert("L"), dtype=np.float32)
        d = np.abs(np.diff(g, axis=1))
        both = op[:, 1:] & op[:, :-1]
        texture = float(((d > 4) & (d < 40))[both].mean()) if both.any() else 0.0
        sharp = float((d >= 40)[both].mean()) if both.any() else 0.0
        hsv = np.asarray(im.convert("RGB").convert("HSV")).astype(np.int32)
        hues = hsv[..., 0][op & (hsv[..., 1] > 60) & (hsv[..., 2] > 40)]
        if len(hues) > 20:
            # hue is circular: the spread around the mean direction
            ang = hues.astype(np.float64) / 256.0 * 2 * np.pi
            r = np.hypot(np.cos(ang).mean(), np.sin(ang).mean())
            hue_sd = float(np.sqrt(max(-2 * np.log(max(r, 1e-9)), 0.0)) * 256 / (2 * np.pi))
        else:
            hue_sd = 0.0
        white = float(((x[..., :3].min(axis=2) > 235) & op).sum() / n)
        lum_sd = float(g[op].std()) if op.any() else 0.0
        return _Stats(coverage=float(op.mean()), colours=colours, texture=texture, sharp=sharp, hue_sd=hue_sd, white=white, lum_sd=lum_sd, glyphs=glyphs, hollow=hollow)
    except Exception:  # noqa: BLE001 - an unreadable picture (EMF, broken data) is treated as art
        return None


_DETAIL: dict[str, Optional[tuple[float, float, float, float]]] = {}


def detail_frac(part) -> Optional[tuple[float, float, float, float]]:
    """Where a picture shows something (x, y, w, h as fractions of the picture): its opaque pixels that differ from
    the picture's own plain ground. A white card drawn as one picture with a 3D render at its foot shows the render;
    a cut-out render shows itself. None when it cannot be read."""
    key = str(getattr(part, "partname", id(part)))
    if key in _DETAIL:
        return _DETAIL[key]
    out = None
    try:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(part.blob)).convert("RGBA")
        im.thumbnail((200, 200))
        x = np.asarray(im).astype(np.int32)
        op = x[..., 3] > 40
        if op.any():
            rgb = x[..., :3][op]
            # the plain ground: the most frequent colour of the opaque pixels (5 bits a channel)
            q5 = rgb >> 3
            keys = q5[:, 0] * 1024 + q5[:, 1] * 32 + q5[:, 2]
            vals, counts = np.unique(keys, return_counts=True)
            top = vals[counts.argmax()]
            ground = np.array([(top >> 10) & 31, (top >> 5) & 31, top & 31]) * 8 + 4
            share = counts.max() / max(len(keys), 1)
            dist = np.abs(x[..., :3] - ground).sum(axis=2)
            busy = op & (dist > 36) if share >= 0.3 else op
            ys, xs = np.nonzero(busy)
            if len(xs):
                hh, ww = busy.shape
                out = (xs.min() / ww, ys.min() / hh, (xs.max() + 1 - xs.min()) / ww, (ys.max() + 1 - ys.min()) / hh)
            else:
                out = (0.0, 0.0, 0.0, 0.0)
    except Exception:  # noqa: BLE001
        out = None
    _DETAIL[key] = out
    return out


def classify_blob(st: Optional[_Stats], w: float, h: float, layout: bool = False, covers: Optional[bool] = None) -> str:
    """The kind of one picture of `w` × `h` (fractions of the slide, the part on the slide) from its pixel statistics.
    `layout`: a picture the sample's own layout draws over the whole slide (an export's baked design: tiles, tags, a
    staircase, or a collage of photos) — only a photograph or a many-hued picture is the sample's story there.
    `covers`: the picture covers the whole slide (None: judged by its area alone)."""
    if layout:
        if st is None or st.coverage < 0.05:
            return "art"
        if st.colours >= 500 and st.texture >= 0.2 and st.hue_sd >= 20:
            return "photo"
        return "content" if st.hue_sd >= 30 and st.sharp >= 0.01 else "art"
    if covers if covers is not None else w * h >= 0.85:
        return "ground"
    if (w < 0.06 and h < 0.1) or w * h < 0.006:
        return "icon"
    if min(w, h) < 0.012:
        return "line"
    if st is None:
        return "art"
    if st.glyphs >= 12:
        # letters and figures drawn into the picture — a chart's axis labels and legend, a list of product names
        # set as an image: the sample's own information, never decoration for new content
        return "content"
    if st.coverage < 0.05:
        return "art"  # a glow, a soft shadow, a hairline ornament
    if st.colours <= 16 and st.texture < 0.05:
        return "panel"
    cut = st.coverage < 0.85
    if st.colours >= 500 and st.texture >= 0.2 and st.hue_sd >= 20:
        return "photo"
    if not cut and st.colours >= 700 and st.texture >= 0.2:
        return "photo"  # a muted photograph (a dark template's toned shots): grain and many shades, few hues
    if not cut and st.colours >= 400 and st.hue_sd >= 15 and st.lum_sd >= 60:
        return "photo"  # a portrait on a plain backdrop: smooth, but lit like a photograph
    if not cut and (st.hue_sd >= 25 or (st.sharp >= 0.02 and st.white >= 0.5)):
        return "content"
    return "art"


# a slide that says it shows charts («Примеры диаграмм», «Графики», «Market data chart»): its large pictures are the
# sample's figures, whatever their pixels look like (a pie of four hues, bars without labels)
_CHART_WORDS = re.compile(r"диаграм|график|гистограм|инфограф|\bchart|\bgraph|\bplot\b", re.I)


def _pic_parts(slide, el) -> list:
    out = []
    for bl in el.iter(q("a:blip")):
        rid = bl.get(q("r:embed"))
        if not rid:
            continue
        try:
            out.append(slide.part.related_part(rid))
        except KeyError:
            continue
    return out


def _bbox(el) -> Optional[tuple[int, int, int, int]]:
    from verstka.rendering.deck import element_bbox

    return element_bbox(el)


_STORY_RANK = {"photo": 5, "content": 4, "bar": 3, "art": 2, "panel": 1, "line": 1, "icon": 0, "ground": 0}


def _classify_layout(slide, W: int, H: int, cache: dict) -> list[SamplePicture]:
    """The big pictures the slide's layout draws (a layout of its own: a Google Slides export bakes each sample's
    design into one), as pictures of the sample with ids «L<id>»."""
    out: list[SamplePicture] = []
    try:
        layout = slide.slide_layout
    except Exception:  # noqa: BLE001
        return out
    tree = layout._element.cSld.find(q("p:spTree"))
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("pic", "grpSp", "sp") or el.find(".//" + q("p:ph")) is not None:
            continue
        if el.find(".//" + q("a:blip")) is None:
            continue
        b = _bbox(el)
        nv = el.find(".//" + q("p:cNvPr"))
        if not b or nv is None or b[2] <= 0 or b[3] <= 0 or (b[2] * b[3]) / (W * H) < 0.3:
            continue
        kinds = []
        for part in _pic_parts(layout, el):
            key = str(part.partname)
            if key not in cache:
                cache[key] = _stats(part.blob)
            kinds.append(classify_blob(cache[key], b[2] / W, b[3] / H, layout=True))
        if kinds:
            kind = max(kinds, key=lambda k: _STORY_RANK.get(k, 0))
            out.append(SamplePicture(shape_id="L" + nv.get("id"), x=b[0] / W, y=b[1] / H, w=b[2] / W, h=b[3] / H, kind=kind))
    return out


def _classify_slide(slide, W: int, H: int, cache: dict) -> list[SamplePicture]:
    tree = slide._element.cSld.find(q("p:spTree"))
    out: list[SamplePicture] = []
    charts = bool(_CHART_WORDS.search(" ".join(t.text or "" for t in tree.iter(q("a:t")))))
    hollow: set[str] = set()
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("pic", "grpSp", "sp"):
            continue
        if tag in ("grpSp", "sp") and el.find(".//" + q("a:blip")) is None:
            continue  # (a shape filled with a picture — a photo in a rounded leaf — is a picture too)
        b = _bbox(el)
        nv = el.find(".//" + q("p:cNvPr"))
        if not b or nv is None or b[2] <= 0 or b[3] <= 0:
            continue
        # the part of the picture on the slide: a chart image running off the slide's foot is no background
        x0, y0 = max(b[0] / W, 0.0), max(b[1] / H, 0.0)
        x1, y1 = min((b[0] + b[2]) / W, 1.0), min((b[1] + b[3]) / H, 1.0)
        if x1 <= x0 or y1 <= y0:
            continue
        w, h = x1 - x0, y1 - y0
        covers = x0 <= 0.03 and y0 <= 0.03 and x1 >= 0.97 and y1 >= 0.97
        kinds = []
        for part in _pic_parts(slide, el):
            key = str(part.partname)
            if key not in cache:
                cache[key] = _stats(part.blob)
            kinds.append(classify_blob(cache[key], w, h, covers=covers))
            if cache[key] is not None and cache[key].hollow:
                hollow.add(nv.get("id"))
        if not kinds:
            continue
        kind = max(kinds, key=lambda k: _STORY_RANK.get(k, 0))
        if charts and kind in ("art", "panel") and w * h >= 0.05 and nv.get("id") not in hollow:
            # a pie, bars or a graph on a slide that shows charts: the sample's figures (a ring stays: the renderer
            # redraws a ring for a share, `clone._true_rings`)
            kind = "content"
        out.append(SamplePicture(shape_id=nv.get("id"), x=b[0] / W, y=b[1] / H, w=b[2] / W, h=b[3] / H, kind=kind))
    # elongated pictures of different lengths in the content area are the bars of a data graphic (a chart, a Gantt)
    # drawn for the sample's own figures; plates of one size under the lines of a list are the list's design
    ids: set[str] = set()
    for horizontal in (True, False):
        long_ = [p for p in out if p.kind in ("art", "panel") and p.area >= 0.004 and 0.12 < p.y + p.h / 2 < 0.95
                 and ((p.w * W >= 3.5 * p.h * H) if horizontal else (p.h * H >= 3.5 * p.w * W))]
        if len(long_) < 2:
            continue
        lengths = [p.w if horizontal else p.h for p in long_]
        if max(lengths) >= 1.15 * min(lengths):
            ids |= {p.shape_id for p in long_}
    if ids:
        out = [SamplePicture(**{**asdict(p), "kind": "bar"}) if p.shape_id in ids else p for p in out]
    return out


_MEMO: dict[str, dict[str, list[SamplePicture]]] = {}


def sample_pictures(ws, manifest: TemplateManifest) -> dict[str, list[SamplePicture]]:
    """pattern id → the classified pictures of its sample slide (cached in the template's workspace)."""
    key = f"{manifest.template_id}:{manifest.analysis_version}:{PICTURES_VERSION}"
    if key in _MEMO:
        return _MEMO[key]
    path = ws.dir / "pictures.json" if ws is not None else None
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("key") == key:
                got = {pid: [SamplePicture(**p) for p in pics] for pid, pics in data["patterns"].items()}
                _MEMO[key] = got
                return got
        except Exception:  # noqa: BLE001 - recomputed
            pass
    out: dict[str, list[SamplePicture]] = {}
    if ws is None:
        return out
    try:
        from pptx import Presentation

        prs = Presentation(str(ws.source))
        W, H = int(prs.slide_width), int(prs.slide_height)
        cache: dict = {}
        slides = list(prs.slides)
        from collections import Counter

        users = Counter(str(s.slide_layout.part.partname) for s in slides)
        for p in manifest.patterns:
            if 1 <= p.source_slide <= len(slides):
                s = slides[p.source_slide - 1]
                out[p.id] = _classify_slide(s, W, H, cache)
                if users.get(str(s.slide_layout.part.partname), 0) <= 2:
                    out[p.id] += _classify_layout(s, W, H, cache)
    except Exception:  # noqa: BLE001 - without the classification every picture counts as art (the scorer is cautious)
        log.warning("sample pictures not classified", exc_info=True)
        return out
    _MEMO[key] = out
    if path is not None:
        try:
            path.write_text(json.dumps({"key": key, "patterns": {pid: [asdict(x) for x in pics] for pid, pics in out.items()}}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def story_pictures(pics: list[SamplePicture], min_area: float = 0.03) -> list[SamplePicture]:
    """The pictures of a sample that tell its own story and are big enough to leave a hole when dropped."""
    return [p for p in pics if p.kind in STORY and p.area >= min_area]


def art_pictures(pics: list[SamplePicture], min_area: float = 0.02) -> list[SamplePicture]:
    return [p for p in pics if p.kind == "art" and p.area >= min_area]


def pattern_pictures(ws, manifest: TemplateManifest, pattern: Pattern) -> list[SamplePicture]:
    return sample_pictures(ws, manifest).get(pattern.id, [])
