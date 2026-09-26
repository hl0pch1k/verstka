"""Revising one variant of a finished generation — the chat agent's edits («на слайде 3 покажи расходы таблицей»,
«убери слайд 5», «поменяй местами 2 и 3», «верни как было»).

Every revision keeps the variant's previous version (versions/vN/: its plan, layout, audit, deck and run manifest), so
«верни как было» restores it exactly; the edited plan is rendered again with the template the variant was built on and
audited against the brief (the figures on the slides included), and the variant's edit log (edits.json) records what was
asked, what changed and the scores before and after — the versioning of the agent's work the ТЗ asks for.

A fix of one slide's remarks («Исправить слайд», fix_slide) never re-renders the variant: the fixed slide is built in a
scratch deck and spliced into the current deck (splice_slide), every other slide is checked by its fingerprint
(slide_fingerprints: the slide's XML with every related part hashed), and «верни как было» puts the kept files back
exactly (restore_version) instead of rendering the old plan again."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import math
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from verstka.schemas.outline import Brief, DeckOutline

log = logging.getLogger(__name__)

# what a version of a variant is: enough to show it again without re-rendering (the deck) and to rebuild it (the plan)
VERSION_FILES = ("outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json", "deck.pptx")
# kept with a version too, so «верни как было» shows exactly the old previews and files without LibreOffice (older
# versions lack them: their previews and exports are rendered again from the kept deck)
VERSION_EXTRA = ("deck.pdf", "deck.html")
# what a re-render replaces in the variant's folder (planner_raw.json, the model's own answer, stays)
RENDER_OUTPUTS = ("outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json", "deck.pptx", "deck.pdf", "deck.html")


def versions_dir(vdir: Path) -> Path:
    return vdir / "versions"


def version_numbers(vdir: Path) -> list[int]:
    root = versions_dir(vdir)
    if not root.is_dir():
        return []
    return sorted(int(p.name[1:]) for p in root.iterdir() if p.is_dir() and p.name[:1] == "v" and p.name[1:].isdigit())


def snapshot(vdir: Path) -> int:
    """Keep the variant as it is now (versions/vN/) before it changes; returns N."""
    n = (version_numbers(vdir) or [0])[-1] + 1
    dst = versions_dir(vdir) / f"v{n}"
    dst.mkdir(parents=True, exist_ok=True)
    for name in VERSION_FILES + VERSION_EXTRA:
        src = vdir / name
        if src.exists():
            shutil.copy2(src, dst / name)
    if (vdir / "slides").is_dir():
        shutil.rmtree(dst / "slides", ignore_errors=True)
        shutil.copytree(vdir / "slides", dst / "slides")
    return n


def last_version(vdir: Path) -> Optional[tuple[int, DeckOutline]]:
    """The newest kept version and its plan (None when the variant was never edited)."""
    nums = version_numbers(vdir)
    if not nums:
        return None
    path = versions_dir(vdir) / f"v{nums[-1]}" / "outline.json"
    if not path.exists():
        return None
    return nums[-1], DeckOutline.model_validate_json(path.read_text(encoding="utf-8"))


def drop_version(vdir: Path, n: int) -> None:
    shutil.rmtree(versions_dir(vdir) / f"v{n}", ignore_errors=True)


def read_edits(vdir: Path) -> list[dict]:
    path = vdir / "edits.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def log_edit(vdir: Path, entry: dict) -> None:
    edits = read_edits(vdir)
    edits.append({"at": time.time(), **entry})
    tmp = vdir / "edits.json.tmp"
    tmp.write_text(json.dumps(edits, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(vdir / "edits.json")


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_audit(path: Path):
    """The AuditReport at `path`, or None (missing or unreadable)."""
    from verstka.schemas.audit import AuditReport

    try:
        return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rerender_variant(
    vdir: Path,
    strategy: str,
    outline: DeckOutline,
    template_source: Path,
    workspace_root: Path,
    *,
    brief: Optional[Brief] = None,
    exports: Optional[list[str]] = None,
):
    """Render the edited plan of one variant into a scratch folder, then put its files in place of the variant's (the
    slide previews too). No model is asked anything here: the plan is final; the audit and its autofix run as for a new
    deck, against the brief. Returns the pipeline's VariantResult."""
    from verstka.pipeline.generate import generate_variants

    scratch = vdir.parent / f".{strategy}.revise"
    shutil.rmtree(scratch, ignore_errors=True)
    # who planned the deck (the agent, its model and calls) stays the variant's: an edit re-renders a supplied plan
    old_manifest = _read_json(vdir / "run_manifest.json")
    old_audit = _read_audit(vdir / "audit_report.json")
    try:
        res = generate_variants(
            template_source, brief=brief, outline=outline, strategies=[strategy], out_dir=scratch, workspace_root=workspace_root,
            providers=None, skills=None, use_llm=False, use_vlm=False, audit=True, autofix=True, exports=list(exports or []),
        )
        v = res.variants[0]
        made = scratch / strategy
        for name in RENDER_OUTPUTS:
            src = made / name
            if src.exists():
                src.replace(vdir / name)
            elif name in ("deck.pdf", "deck.html") and (vdir / name).exists() and name.split(".")[-1] not in (exports or []):
                (vdir / name).unlink()  # an export the variant no longer has would show the old deck
        if (made / "slides").is_dir():
            shutil.rmtree(vdir / "slides", ignore_errors=True)
            (made / "slides").replace(vdir / "slides")
        # the audit report and the run manifest name the previews and exports by path: they now live in the variant's
        # own folder
        for name in ("audit_report.json", "run_manifest.json"):
            path = vdir / name
            if path.exists():
                path.write_text(path.read_text(encoding="utf-8").replace(str(made), str(vdir)), encoding="utf-8")
        new_manifest = _read_json(vdir / "run_manifest.json")
        if new_manifest is not None and old_manifest is not None and old_manifest.get("planner"):
            new_manifest["planner"] = old_manifest["planner"]
            (vdir / "run_manifest.json").write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        # the remarks that stayed keep their ids (the audit numbers them through the deck, so an edit of one slide would
        # rename the remarks of every slide after it)
        new_audit = _read_audit(vdir / "audit_report.json")
        if old_audit is not None and new_audit is not None:
            from verstka.api.remarks import carry_report_ids

            carry_report_ids(old_audit, new_audit)
            (vdir / "audit_report.json").write_text(new_audit.model_dump_json(indent=2), encoding="utf-8")
            v.audit = new_audit
        v.out_dir = vdir
        return v
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------- one slide into a deck: splice, fingerprints


_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_R_ATTRS = tuple(f"{{{_R_NS}}}{a}" for a in ("embed", "link", "id", "pict", "dm", "lo", "qs", "cs"))


def _elements(el) -> Iterable:
    from lxml import etree

    return el.iter(tag=etree.Element)


def _remap_rids(el, rid_map: dict[str, str]) -> list[str]:
    """Rewrite every r:* reference by `rid_map` in one pass; returns the references it had no mapping for."""
    unknown = []
    for node in _elements(el):
        for attr in _R_ATTRS:
            v = node.get(attr)
            if v is None:
                continue
            if v in rid_map:
                node.set(attr, rid_map[v])
            else:
                unknown.append(v)
    return unknown


def _next_partname(pkg, template: str, reserved: set[str]):
    """A free part name for `template` ("/ppt/charts/chart%d.xml"): unused in the package and not handed out yet (a
    part cloned but not related yet is not in the package's graph)."""
    from pptx.opc.packuri import PackURI

    used = {str(p.partname) for p in pkg.iter_parts()} | reserved
    for i in range(1, 100000):
        cand = template % i
        if cand not in used:
            reserved.add(cand)
            return PackURI(cand)
    raise RuntimeError(f"no free part name for {template}")


def _clone_part(pkg, src, memo: dict[int, Any], reserved: set[str]):
    """A copy of `src` (and of the parts it relates to) inside `pkg`, with its references renamed."""
    from pptx.opc.package import PartFactory

    hit = memo.get(id(src))
    if hit is not None:
        return hit
    name = str(src.partname)
    template = re.sub(r"\d+(\.[^./]+)$", r"%d\1", name)
    if "%d" not in template:
        stem, dot, ext = name.rpartition(".")
        template = f"{stem}%d.{ext}" if dot else f"{name}%d"
    new = PartFactory(_next_partname(pkg, template, reserved), src.content_type, pkg, src.blob)
    memo[id(src)] = new
    rid_map: dict[str, str] = {}
    for rid, rel in list(src.rels.items()):
        if rel.is_external:
            rid_map[rid] = new.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        else:
            rid_map[rid] = new.relate_to(_clone_part(pkg, rel.target_part, memo, reserved), rel.reltype)
    el = getattr(new, "_element", None)
    if el is not None and any(k != v for k, v in rid_map.items()):
        _remap_rids(el, rid_map)
    return new


def splice_slide(base: Path, donor: Path, index: int, out: Path) -> None:
    """`out` = `base` with slide `index` (1-based) taken from `donor` (the same template); every other part of `base`
    stays as it is. The slide's pictures, charts (with their workbooks) and links come along; its notes (the outline-id
    marker the audit reads) are replaced; the old slide's own parts that nothing uses any more are not written."""
    from pptx import Presentation
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    bp, dp = Presentation(str(base)), Presentation(str(donor))
    if not (1 <= index <= len(bp.slides) and index <= len(dp.slides)):
        raise IndexError(f"slide {index} is not in both decks ({len(bp.slides)} and {len(dp.slides)} slides)")
    bs, ds = bp.slides[index - 1], dp.slides[index - 1]
    pkg = bp.part.package
    layouts = [lay for m in bp.slide_masters for lay in m.slide_layouts]
    want = ds.slide_layout
    layout = next((lay for lay in layouts if lay.part.partname == want.part.partname), None) or next((lay for lay in layouts if lay.name == want.name), None)
    if layout is None:
        raise ValueError(f"the base deck has no layout {want.part.partname} «{want.name}»")
    # the base slide keeps only its notes; the layout is related again (the donor's may be another one)
    for rid, rel in list(bs.part.rels.items()):
        if rel.reltype != RT.NOTES_SLIDE:
            bs.part.rels.pop(rid)
    bs.part.relate_to(layout.part, RT.SLIDE_LAYOUT)
    donor_slides = {id(s.part): i for i, s in enumerate(dp.slides)}
    memo: dict[int, Any] = {}
    reserved: set[str] = set()
    rid_map: dict[str, str] = {}
    used = {node.get(attr) for node in _elements(ds._element) for attr in _R_ATTRS if node.get(attr) is not None}
    for rid, rel in ds.part.rels.items():
        if rel.reltype in (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE):
            continue
        if rid not in used:  # a part the slide no longer shows (a sample's chart the render replaced): left behind
            continue
        if rel.is_external:
            rid_map[rid] = bs.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        elif rel.reltype == RT.SLIDE:  # a link to another slide of the deck: the base deck's slide at that place
            j = donor_slides.get(id(rel.target_part))
            if j is not None and j < len(bp.slides):
                rid_map[rid] = bs.part.relate_to(bp.slides[j].part, RT.SLIDE)
        elif rel.reltype == RT.IMAGE:
            try:
                _, rid_map[rid] = bs.part.get_or_add_image_part(io.BytesIO(rel.target_part.blob))  # the same picture is shared
            except Exception:  # noqa: BLE001 - a format python-pptx cannot size (svg, wdp): copied as it is
                rid_map[rid] = bs.part.relate_to(_clone_part(pkg, rel.target_part, memo, reserved), rel.reltype)
        else:  # a chart with its workbook, media, anything else: copied with the parts it relates to
            rid_map[rid] = bs.part.relate_to(_clone_part(pkg, rel.target_part, memo, reserved), rel.reltype)
    new_el = copy.deepcopy(ds._element)
    unknown = _remap_rids(new_el, rid_map)
    if unknown:
        log.warning("splice: slide %d refers to %s that the donor slide does not relate", index, sorted(set(unknown)))
    old = bs._element
    for child in list(old):
        old.remove(child)
    old.attrib.clear()
    old.attrib.update(dict(new_el.attrib))
    for child in list(new_el):
        old.append(child)
    if ds.has_notes_slide:
        d_tree = ds.notes_slide._element.cSld.spTree
        b_tree = bs.notes_slide._element.cSld.spTree  # created from the notes master when the base slide had none
        b_tree.getparent().replace(b_tree, copy.deepcopy(d_tree))
    out.parent.mkdir(parents=True, exist_ok=True)
    bp.save(str(out))


_ZIP_VOLATILE = frozenset({"docProps/core.xml"})  # an embedded workbook's creation time: new on every render


def _blob_digest(blob: bytes) -> str:
    """A binary part's hash; an embedded package (a chart's workbook) by its entries, without its timestamps."""
    if blob[:2] == b"PK":
        import zipfile

        try:
            h = hashlib.sha1()
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for name in sorted(z.namelist()):
                    if name in _ZIP_VOLATILE:
                        continue
                    h.update(name.encode("utf-8") + b"\0" + z.read(name) + b"\0")
            return h.hexdigest()
        except (zipfile.BadZipFile, OSError, ValueError):
            pass
    return hashlib.sha1(blob).hexdigest()


def _part_digest(part, memo: dict[int, str], depth: int) -> str:
    key = id(part)
    if key in memo:
        return memo[key]
    memo[key] = "cycle"
    el = getattr(part, "_element", None)
    if el is not None:
        from lxml import etree

        el = copy.deepcopy(el)
        _hash_refs(el, part.rels, memo, depth + 1)
        digest = hashlib.sha1(etree.tostring(el, method="c14n", exclusive=True)).hexdigest()
    else:
        digest = _blob_digest(part.blob)
    memo[key] = digest
    return digest


def _hash_refs(el, rels, memo: dict[int, str], depth: int) -> None:
    """Every r:* value of `el` replaced by what it points at (the target's content, the external url)."""
    for node in _elements(el):
        for attr in _R_ATTRS:
            v = node.get(attr)
            if v is None:
                continue
            rel = rels.get(v)
            if rel is None:
                node.set(attr, "missing")
            elif rel.is_external:
                node.set(attr, "ext:" + str(rel.target_ref))
            elif depth > 4:
                node.set(attr, str(rel.target_part.partname))
            else:
                node.set(attr, _part_digest(rel.target_part, memo, depth))


def slide_fingerprints(pptx: Path) -> list[str]:
    """Per slide: the SHA-1 of its XML (exclusive C14N) with every r:* reference replaced by a hash of its target (the
    part's C14N or blob, `ext:{url}`), plus its layout's part name. Equal fingerprints — the same slide."""
    from lxml import etree
    from pptx import Presentation

    prs = Presentation(str(pptx))
    memo: dict[int, str] = {}
    out = []
    for s in prs.slides:
        el = copy.deepcopy(s._element)
        _hash_refs(el, s.part.rels, memo, 1)
        data = etree.tostring(el, method="c14n", exclusive=True) + str(s.slide_layout.part.partname).encode()
        out.append(hashlib.sha1(data).hexdigest())
    return out


def changed_slides(a: Path | list[str], b: Path | list[str], skip: Iterable[int] = ()) -> list[int]:
    """The 1-based slides whose fingerprints differ between two decks (or fingerprint lists), every slide past the
    shorter deck included; `skip` is left out."""
    fa = a if isinstance(a, list) else slide_fingerprints(Path(a))
    fb = b if isinstance(b, list) else slide_fingerprints(Path(b))
    skip = set(skip)
    out = [i for i, (x, y) in enumerate(zip(fa, fb), 1) if x != y and i not in skip]
    out += [i for i in range(min(len(fa), len(fb)) + 1, max(len(fa), len(fb)) + 1) if i not in skip]
    return out


def image_drift(a: Path, b: Path) -> Optional[float]:
    """The mean absolute grey difference (0–255) of two slide previews at 64×36; None when one cannot be read."""
    try:
        from PIL import Image, ImageChops, ImageStat

        with Image.open(a) as ia, Image.open(b) as ib:
            ga, gb = ia.convert("L").resize((64, 36)), ib.convert("L").resize((64, 36))
            return float(ImageStat.Stat(ImageChops.difference(ga, gb)).mean[0])
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------- «верни как было»: the kept files back


def _previews(vdir: Path) -> list[Path]:
    root = vdir / "slides"
    return sorted(root.glob("slide-*.jpg")) if root.is_dir() else []


def restore_version(vdir: Path, n: int, manifest, title: Optional[str], exports: Optional[list[str]] = None):
    """Put version `n` back exactly: its deck, plan, layout, audit and run manifest; its previews and exports when it
    kept them, else they are rendered again from the kept deck (a failed render keeps the files and warns). Nothing is
    planned or rendered as a deck again. Returns the restored AuditReport (None when the version had none)."""
    from verstka.pipeline.generate import render_outputs
    from verstka.schemas.audit import AuditReport

    src = versions_dir(vdir) / f"v{n}"
    if not src.is_dir():
        raise FileNotFoundError(f"version {n} of {vdir} is gone")
    exports = [e for e in (exports or []) if e in ("pdf", "html")]
    for name in VERSION_FILES:
        if (src / name).exists():
            shutil.copy2(src / name, vdir / name)
    kept_slides = (src / "slides").is_dir()
    if kept_slides:
        tmp = vdir / ".slides.restore"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src / "slides", tmp)
        shutil.rmtree(vdir / "slides", ignore_errors=True)
        tmp.replace(vdir / "slides")
    missing = []
    for fmt in ("pdf", "html"):
        kept = src / f"deck.{fmt}"
        if kept.exists():
            shutil.copy2(kept, vdir / f"deck.{fmt}")
        elif fmt in exports:
            missing.append(fmt)
        elif (vdir / f"deck.{fmt}").exists():
            (vdir / f"deck.{fmt}").unlink()  # an export the version did not have would show another deck
    if missing or not kept_slides:
        try:
            _, _, warns, _ = render_outputs(vdir, manifest, title, exports, images=not kept_slides)
            for w in warns:
                log.warning("restore v%d: %s", n, w)
        except Exception as e:  # noqa: BLE001 - the files are back; the previews may lag behind
            log.warning("restore v%d: render failed: %s", n, e)
    path = vdir / "audit_report.json"
    if not path.exists():
        return None
    report = AuditReport.model_validate_json(path.read_text(encoding="utf-8"))
    report.deck = str(vdir / "deck.pptx")
    images = _previews(vdir)
    if images:
        report.slide_images = {k: str(p) for k, p in enumerate(images, 1)}
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------- «Исправить слайд»


@dataclass
class SlideFix:
    """What a fix of one slide did (REMARKS_SPEC §2.6)."""

    applied: bool
    how: str  # "model" | "rules" | "autofix"
    what: str
    reply: str
    report: Any  # the variant's AuditReport after the fix (the old one when not applied)
    requested: list = field(default_factory=list)  # the Issues asked to fix, numbered like the UI
    fixed: list[str] = field(default_factory=list)
    remaining: list[dict] = field(default_factory=list)
    other: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    why: Optional[str] = None
    version: Optional[int] = None
    at: Optional[float] = None
    score_before: Optional[float] = None
    score_after: Optional[float] = None
    n_slides: int = 0


_EVENT_PREFIX = re.compile(r"^(?:Аналитик|Архитектор|Дизайнер|Критик|Правка|Сборка|Вёрстка|Проверка)\s*:\s*")
_EVENT_SLIDE_LEAD = re.compile(r"^слайд\s*\d+\s*[—–:]\s*", re.I)


def _event_text(message: str) -> str:
    """An event's text as the timeline shows it under its step: no step name and no «слайд N —» in front (the event
    carries the slide), like the planning agent's events."""
    text = _EVENT_PREFIX.sub("", message.strip(), count=1)
    text = _EVENT_SLIDE_LEAD.sub("", text, count=1).strip()
    return text[:1].upper() + text[1:] if text else message


class _Voice:
    """The fix's progress: plain job messages and agent events {"type": "agent", step, message, slide, variant}."""

    def __init__(self, progress: Optional[Callable[..., None]], slide: int, variant: str) -> None:
        self.progress = progress
        self.slide = slide
        self.variant = variant
        self.lines: list[str] = []
        self.designer_events = 0

    def _send(self, *args: Any) -> None:
        if self.progress is None:
            return
        try:
            self.progress(*args)
        except Exception:  # noqa: BLE001 - a listener never stops the fix
            log.debug("slide fix: progress listener failed", exc_info=True)

    def plain(self, message: str, share: Optional[float] = None) -> None:
        self._send(message, share)

    def agent(self, step: str, message: str, share: Optional[float] = None) -> None:
        self.lines.append(message)
        ev = {"type": "agent", "step": step, "message": _event_text(message), "slide": self.slide, "variant": self.variant}
        if share is not None:
            ev["progress"] = share
        self._send(ev)

    def relay(self) -> Callable[..., None]:
        """The designer's progress callback (redesign_slide): its events get this slide, this variant and a share."""

        def progress(msg: Any = "", frac: Any = None, *args: Any, **kwargs: Any) -> None:
            ev = msg if isinstance(msg, dict) else kwargs.get("event")
            if isinstance(ev, dict) and ev.get("type") == "agent":
                ev = {**ev, "slide": self.slide, "variant": self.variant}
                if ev.get("step") in ("designer", "revise"):
                    ev["progress"] = min(0.15 + 0.12 * self.designer_events, 0.5)
                    self.designer_events += 1
                self._send(ev)
            elif msg:
                self._send(msg, frac)

        return progress


class _Creep:
    """A long step with no steps of its own (LibreOffice rendering the previews): while it runs, the job's bar creeps
    from `start` toward `end` without reaching it — the person sees the work go on, never a bar that stopped."""

    def __init__(self, voice: "_Voice", message: str, start: float, end: float, every: float = 1.5, tau: float = 12.0) -> None:
        self.voice, self.message, self.start, self.end, self.every, self.tau = voice, message, start, end, every, tau
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _run(self) -> None:
        t0 = time.monotonic()
        while not self._stop.wait(self.every):
            share = self.start + (self.end - self.start) * (1.0 - math.exp(-(time.monotonic() - t0) / self.tau))
            self.voice.plain(self.message, round(share, 3))

    def __enter__(self) -> "_Creep":
        if self.voice.progress is not None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="slide-fix-creep")
            self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _with_slide(base: DeckOutline, src: DeckOutline, n: int) -> DeckOutline:
    """`base` with slide n taken from `src`, and the registry entries `src` added (series, facts, tables)."""
    out = base.model_copy(deep=True)
    out.slides[n - 1] = src.slides[n - 1].model_copy(deep=True)
    have = {x.id for x in out.series}
    out.series.extend(x.model_copy(deep=True) for x in src.series if x.id not in have)
    have = {x.id for x in out.facts}
    out.facts.extend(x.model_copy(deep=True) for x in src.facts if x.id not in have)
    for t in src.tables:
        if not any(t.columns == u.columns and t.rows == u.rows for u in out.tables):
            out.tables.append(t.model_copy(deep=True))
    return out


def _with_entry(base, entry, oid: str):
    """The layout plan `base` with slide `oid`'s entry replaced by `entry`."""
    out = base.model_copy(deep=True)
    if entry is None:
        return out
    entry = entry.model_copy(deep=True)
    for k, s in enumerate(out.slides):
        if s.outline_id == oid:
            out.slides[k] = entry
            return out
    out.slides.append(entry)
    return out


_ACTION_RU = {"move_inside": "элемент возвращён на место", "shrink_text": "шрифт уменьшен, чтобы текст поместился", "recolor": "цвет приведён к палитре шаблона", "refont": "шрифт заменён на шрифт шаблона", "drop_element": "убран лишний элемент"}


def _what_of(records: list[dict]) -> str:
    """What the rules did to the slide (the edits that stayed), in plain Russian («элемент возвращён внутрь слайда; …»)."""
    out: list[str] = []
    for r in records:
        act, res = r.get("action"), str(r.get("result") or "")
        if act == "xml":
            text = res or _ACTION_RU.get(str(r.get("kind")), "")
        elif act in ("rematch", "synth") and res and res != "skip":
            text = "слайд собран на другом макете шаблона" if res.startswith("rematch") else "слайд собран заново по его содержанию"
        elif act == "condense_text" and res and res != "skip":
            text = "тексты сокращены"
        else:
            continue
        text = text[:1].lower() + text[1:]
        if text and text not in out:
            out.append(text)
    return "; ".join(out[:3])


def _frame_name(kind: str) -> tuple[str, str]:
    """(the slide in the designer's line, the note for wishes) of a cover, a divider or a closing slide."""
    if kind == "section":
        return "разделитель", "Разделители агент собирает из разделов текста — исправлено только оформление"
    if kind == "thanks":
        return "финальный слайд", "Финальный слайд агент собирает из названия текста — исправлено только оформление"
    return "обложку", "Обложку агент собирает из названия и разделов текста — исправлено только оформление"


def fix_label(n: int, wishes: Optional[str]) -> str:
    """The history line of a fix («Ваши правки»)."""
    wishes = (wishes or "").strip()
    return f"Исправь слайд {n}: {wishes}" if wishes else f"Исправь замечания на слайде {n}"


def fix_slide(
    vdir: Path,
    strategy: str,
    n: int,
    *,
    manifest,
    ws,
    remarks: list,
    wishes: Optional[str] = None,
    brief: Optional[Brief] = None,
    use_models: bool = False,
    skills: Any = None,
    providers: Any = None,
    exports: Optional[list[str]] = None,
    progress: Optional[Callable[..., None]] = None,
) -> SlideFix:
    """Fix the remarks of slide `n` of one variant — only this slide (REMARKS_SPEC §2.2).

    A: the remarks' in-place edits (an element moved back, a smaller size); B: the slide designer redesigns the slide
    when its content is at stake (or the person wished something), the slide is rendered by the template's layouts and
    fixed in place again; C: the structural fixes of what is left (another layout, a composed one, shorter texts),
    rolled back when worse; D: the slide is spliced into the current deck, every other slide is checked by its
    fingerprint, the deck is audited; E: when the slide got better, the previous version is kept (versions/vN), the
    files are replaced, the previews rendered and the fix logged. Nothing in `vdir` is written before E, so a failure
    leaves the variant as it was."""
    from verstka.api import remarks as RM
    from verstka.audit.autofix import RERENDER_ACTIONS, autofix_loop, plan_fixes
    from verstka.audit.runner import run_audit
    from verstka.matching.matcher import match_outline
    from verstka.pipeline.generate import render_outputs
    from verstka.planning.slide_edit import FRAME_KINDS, describe_change, redesign_slide
    from verstka.planning.strategies import load_strategies
    from verstka.rendering.renderer import render_deck
    from verstka.schemas.audit import AuditReport, Issue
    from verstka.schemas.layout import LayoutPlan

    vdir = Path(vdir)
    voice = _Voice(progress, n, strategy)
    titles = RM.check_titles()
    outline0 = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
    plan0 = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
    report0 = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
    deck0 = vdir / "deck.pptx"
    brief_text = brief.text if brief is not None else None
    wishes = (wishes or "").strip() or None
    remarks = RM.order_remarks(remarks)
    before_stage = RM.stage_remarks(report0.issues, n)
    osl0 = outline0.slides[n - 1]
    oid = osl0.id
    frame = osl0.kind.value in FRAME_KINDS
    asked_checks = {r.check_id for r in remarks}
    notes: list[str] = []
    records: list[dict] = []  # every fix record of this fix, rolled-back tries included (the history)
    kept: list[dict] = []  # the edits that stayed (what the reply says was done)
    how, what = "autofix", ""
    redesigned = False

    voice.plain("Критик читает замечания", 0.03)
    voice.agent("critic", RM.critic_line(n, remarks, titles), 0.05)

    def fixable(rep: AuditReport, xml_only: bool) -> set[str]:
        return {
            i.id for i in rep.issues
            if i.slide == n and i.severity in ("error", "warn") and i.kind != "model" and i.autofix is not None and i.autofix.action != "none"
            and (not xml_only or i.autofix.action not in RERENDER_ACTIONS)
        }

    def loop(rep: AuditReport, outline: DeckOutline, plan: LayoutPlan, ids: set[str], iterations: int):
        start = len(rep.applied_fixes)
        rep2, plan2, outline2, _ = autofix_loop(work, rep, outline, plan, manifest, ws, max_iterations=iterations, only_ids=ids, render=False, brief_text=brief_text)
        new = [dict(r, slide=n) for r in rep2.applied_fixes[start:]]
        rolled = {r.get("iteration") for r in new if r.get("action") == "rollback"}
        records.extend(new)
        kept.extend(r for r in new if r.get("action") != "rollback" and r.get("iteration") not in rolled)
        return rep2, outline2, plan2

    def mark() -> tuple[int, int]:
        return len(records), len(kept)

    def back_to(m: tuple[int, int]) -> tuple[list[dict], list[dict]]:
        """Forget the records since mark `m`; returns them (to put them back)."""
        gone = (records[m[0]:], kept[m[1]:])
        del records[m[0]:]
        del kept[m[1]:]
        return gone

    def slide_score(rep: AuditReport) -> tuple[int, int]:
        own = [i for i in rep.issues if i.slide == n and i.kind != "model"]
        return sum(1 for i in own if i.severity == "error"), sum(1 for i in own if i.severity == "warn")

    def inplace(rep: AuditReport, outline: DeckOutline, plan: LayoutPlan, ids: set[str]):
        """The XML edits of `ids`. A move into the template's margins can land on another block (a footnote at the
        bottom edge moved up onto the text above it): the same edits with the move kept inside the slide only are
        tried too, and the version with fewer errors, then fewer warnings on this slide wins."""
        into_margins = {i.id for i in rep.issues if i.id in ids and i.autofix is not None and i.autofix.action == "move_inside" and i.autofix.params.get("safe")}
        if not into_margins:
            return loop(rep, outline, plan, ids, 1)
        start_deck, m = scratch / "inplace_start.pptx", mark()
        shutil.copy2(work, start_deck)
        first = loop(rep, outline, plan, ids, 1)
        if slide_score(first[0]) == (0, 0):
            return first
        first_records = back_to(m)
        shutil.copy2(work, scratch / "inplace_first.pptx")
        shutil.copy2(start_deck, work)
        soft = rep.model_copy(deep=True)
        for i in soft.issues:
            if i.id in into_margins and i.autofix is not None:
                i.autofix.params = {**i.autofix.params, "safe": False}
        second = loop(soft, outline, plan, ids, 1)
        if slide_score(second[0]) < slide_score(first[0]):
            log.info("slide fix: slide %d — moved inside the slide rather than into the margins (%s < %s)", n, slide_score(second[0]), slide_score(first[0]))
            return second
        back_to(m)
        records.extend(first_records[0])
        kept.extend(first_records[1])
        shutil.copy2(scratch / "inplace_first.pptx", work)
        return first

    scratch = vdir.parent / f".{strategy}.fix"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        work = scratch / "work.pptx"
        shutil.copy2(deck0, work)
        outline, plan = outline0.model_copy(deep=True), plan0.model_copy(deep=True)
        # autofix reads the slides' outline ids from report.deck; nothing below renders images or touches vdir
        report = report0.model_copy(update={"deck": str(work)}, deep=True)
        audit_kw = dict(render=False, strategy=strategy, brief_text=brief_text)
        rerendered = False

        # A. in place first: the remarks' own XML edits
        ids_xml = {r.id for r in remarks if r.autofix is not None and r.autofix.action not in RERENDER_ACTIONS and r.autofix.action != "none" and r.kind != "model"}
        rep = report
        if ids_xml:
            rep, outline, plan = inplace(report, outline, plan, ids_xml)
        # what is left of the asked remarks (the model's own remarks stay until the designer has redesigned the slide)
        left = [i for i in rep.issues if i.slide == n and RM.is_stage(i) and i.kind != "model" and i.check_id in asked_checks]
        left += [r for r in remarks if r.kind == "model"]

        # B. the designer, when content is at stake
        need_designer = not frame and bool(wishes or any(i.check_id in RM.CONTENT_CHECKS for i in left))
        if need_designer and use_models:
            voice.plain(f"Дизайнер переделывает слайд {n}", 0.1)
            left_ids = {id(i) for i in left}
            source = left if left else remarks
            note_items = [i for i in source if i.check_id not in RM.TEMPLATE_CHECKS and (i.check_id not in RM.INPLACE_FIRST or id(i) in left_ids)]
            if note_items:
                start = "переделываю по замечаниям" + (f" и пожеланию «{wishes[:120]}»" if wishes else "")
            else:
                start = f"переделываю по пожеланию «{(wishes or '')[:120]}»"
            named = RM.titles_phrase(remarks, titles)
            rationale = (f"Исправлены замечания: {named}" + (f" · по вашей просьбе «{wishes}»" if wishes else "")) if named else f"По вашей просьбе «{wishes or ''}»"

            def design(base: DeckOutline, note: str, start_line: str):
                """One designer's version of the slide, rendered in the scratch deck, audited and fixed in place."""
                try:
                    r = redesign_slide(
                        base, n, brief, manifest, request=wishes or "", note=note, start_line=start_line, rationale=rationale,
                        log_line=f"Исправление: слайд {n} — {{what}}.", skills=skills, providers=providers, progress=voice.relay(),
                    )
                except ValueError as e:
                    return None, str(e)
                o = _with_slide(outline0, r.outline, n)
                strategy_obj = load_strategies().get(strategy) or next(iter(load_strategies().values()))
                pl = _with_entry(plan0, match_outline(o, manifest, strategy_obj).for_outline(oid), oid)
                voice.plain(f"Собираю слайд {n}", 0.52)
                render_deck(o, pl, manifest, ws, work)  # the whole scratch deck; only slide n is used
                rp = run_audit(work, manifest, o, ws, **audit_kw)
                ids = fixable(rp, xml_only=True)
                if ids:
                    rp, o, pl = inplace(rp, o, pl, ids)
                return (r, o, pl, rp), None

            got, reason = design(outline0, RM.remarks_note(note_items, titles, wishes), start)
            if got is not None:
                r, o, pl, rp = got
                still = [i for i in rp.issues if i.slide == n and RM.is_stage(i) and i.check_id in RM.CONTENT_CHECKS and i.check_id in asked_checks]
                if still and r.how == "model":
                    # one more try: the form the designer kept cannot show the slide's content
                    first_deck, m = scratch / "design_first.pptx", mark()
                    shutil.copy2(work, first_deck)
                    retry_note = RM.remarks_note(still, titles, wishes) + "\n" + RM.retry_line(o.slides[n - 1].kind.value)
                    again, _ = design(o, retry_note, "пробую другую форму — прежняя не вместила всё")
                    if again is not None and slide_score(again[3]) < slide_score(rp):
                        got = again
                    else:
                        back_to(m)
                        shutil.copy2(first_deck, work)
                r, o, pl, rp = got
                how, redesigned, rerendered = r.how, True, True
                what = describe_change(osl0, o.slides[n - 1])
                outline, plan, rep = o, pl, rp
            elif reason == "model_unavailable":
                if wishes:
                    notes.append("Пожелания не учтены: модель не ответила")
                voice.agent("designer", "Дизайнер: модель не ответила — правлю оформление по правилам.", 0.3)
            else:
                if wishes:
                    notes.append(f"Пожелания не учтены: {reason}")
                voice.agent("designer", f"Дизайнер: слайд {n} — {reason}; правлю оформление по правилам.", 0.3)
        elif need_designer:
            if wishes:
                notes.append("Пожелания не учтены: модель недоступна")
            voice.agent("designer", f"Дизайнер: слайд {n} — правлю оформление по правилам шаблона.", 0.15)
        elif frame:
            name, note = _frame_name(osl0.kind.value)
            if wishes:
                notes.append(note)
            voice.agent("designer", f"Дизайнер: {name} не переделываю — правлю только оформление.", 0.15)
        else:
            voice.agent("designer", f"Дизайнер: слайд {n} — правлю оформление по правилам шаблона.", 0.15)

        # C. structural fixes of what is left on the slide, rolled back when worse
        ids = fixable(rep, xml_only=False)
        if ids:
            structural = any(a.action in RERENDER_ACTIONS for acts in plan_fixes(rep, plan, ids).values() for a in acts)
            if structural and not rerendered:
                # the other slides as a re-render shows them, so the loop's before/after compares this slide only
                try:
                    baseline = scratch / "baseline.pptx"
                    render_deck(outline.model_copy(deep=True), plan.model_copy(deep=True), manifest, ws, baseline)
                    splice_slide(baseline, work, n, scratch / "work_c.pptx")
                    (scratch / "work_c.pptx").replace(work)
                    rep = run_audit(work, manifest, outline, ws, **audit_kw)
                    ids = fixable(rep, xml_only=False)
                    rerendered = True
                except Exception:  # noqa: BLE001 - the loop still runs on the work deck as it is
                    log.warning("slide fix: no baseline for the structural pass", exc_info=True)
            if ids:
                rep, outline, plan = loop(rep, outline, plan, ids, 2)
        if not what:
            what = _what_of(kept)

        voice.plain(f"Собираю слайд {n}", 0.58)
        if rerendered:
            voice.agent("compile", f"Вёрстка: слайд {n} собран по макету шаблона, остальные слайды не трогаю.", 0.6)
        else:
            voice.agent("compile", f"Вёрстка: слайд {n} поправлен на месте, остальные слайды не трогаю.", 0.6)

        # D. splice + verify
        voice.plain("Проверяю слайд и остальные", 0.65)
        final = scratch / "final.pptx"
        try:
            splice_slide(deck0, work, n, final)
        except Exception:  # noqa: BLE001 - the verification below tells the truth about the other slides
            log.warning("slide fix: splice failed, the scratch deck is used as it is", exc_info=True)
            shutil.copy2(work, final)
        final_outline = _with_slide(outline0, outline, n)
        final_plan = _with_entry(plan0, plan.for_outline(oid), oid)
        # the audit numbers its remarks through the deck: the ids of the remarks that stayed (on every slide) are carried
        # over, so the person's remark keeps its id through the fix and a fixed remark's id never comes back
        report = RM.carry_report_ids(report0, run_audit(final, manifest, final_outline, ws, **audit_kw))
        # the model's remarks cannot be checked again without a model: the other slides keep theirs, and this slide
        # keeps its own unless the designer redesigned it
        report.issues.extend(i.model_copy(deep=True) for i in report0.issues if i.kind == "model" and (i.slide != n or not redesigned))
        report.applied_fixes = list(report0.applied_fixes) + [{"action": "slide_fix", "slide": n, "outline_id": oid, "result": how}] + records
        report.iterations = report0.iterations
        report.recompute()
        fp0, fp1 = slide_fingerprints(deck0), slide_fingerprints(final)
        other = changed_slides(fp0, fp1, skip={n})
        slide_changed = len(fp1) >= n and fp0[n - 1] != fp1[n - 1]
        after_stage = RM.stage_remarks(report.issues, n)
        known = {i.id for i in before_stage}
        fixed, remaining = RM.match_fixed(remarks, after_stage, before=before_stage + [r for r in remarks if r.id not in known])
        errors_before = sum(1 for i in report0.issues if i.slide == n and i.severity == "error")
        errors_after = sum(1 for i in report.issues if i.slide == n and i.severity == "error")
        worse = errors_after > errors_before
        applied = not worse and slide_changed and (bool(fixed) or bool(wishes))
        why = None
        if not applied:
            why = "Новая версия слайда вышла хуже — оставил как было" if worse else "Замечания остались — попробуйте добавить пожелание"
        voice.agent("check", RM.check_line(fixed, remarks, remaining, applied, worse, titles, other=other), 0.8)
        if applied and other:
            voice.agent("check", f"Проверка: изменились и слайды {RM.slides_phrase(other)}.", 0.8)
        score_before, score_after = report0.summary.score, report.summary.score
        result = SlideFix(
            applied=applied, how=how, what=what, reply="", report=report if applied else report0, requested=remarks, fixed=fixed if applied else [],
            remaining=remaining if applied else [{"id": i.id, "check_id": i.check_id, "severity": i.severity, "message": i.message, "new": False} for i in before_stage],
            other=other if applied else [], notes=notes, why=why, score_before=score_before, score_after=score_after if applied else score_before,
            n_slides=len(final_outline.slides),
        )
        result.reply = RM.fix_reply(n, result.fixed, remarks, result.remaining, score_before, result.score_after, notes, applied, why, result.other, what, titles)
        if not applied:
            return result

        # E. apply: previews, the previous version kept, the files replaced, the fix logged. LibreOffice takes a while
        # (≈ 20 s): the check step says the previews are on their way and the bar keeps moving, so the timeline never
        # reads as finished while the job still works
        voice.plain("Готовлю превью", 0.85)
        voice.agent("check", RM.preview_line(result.fixed, remarks, result.remaining), 0.85)
        out = scratch / "out"
        out.mkdir()
        shutil.copy2(final, out / "deck.pptx")
        exports = [e for e in (exports or []) if e in ("pdf", "html")]
        with _Creep(voice, "Готовлю превью", 0.85, 0.95):
            _, images, warns, render_ok = render_outputs(out, manifest, final_outline.title, exports, images=True)
        for w in warns:
            log.warning("slide fix: %s", w)
        if render_ok is False:
            report.issues.append(Issue(id="file_opens-0-render", slide=0, check_id="file_opens", severity="warn", kind="deterministic", message="LibreOffice не смог отрендерить файл"))
            report.recompute()
            result.score_after = report.summary.score
        voice.plain("Готовлю превью", 0.95)
        # previews: the fixed slide (and any slide that changed) from the new render; every other slide keeps its image
        merged = scratch / "slides"
        merged.mkdir()
        old_images = {int(p.stem.rsplit("-", 1)[-1]): p for p in _previews(vdir)}
        new_images = {k: p for k, p in enumerate(images, 1)}
        for k in range(1, len(final_outline.slides) + 1):
            src = new_images.get(k) if (k == n or k in other or k not in old_images) else old_images[k]
            if src is None:
                src = old_images.get(k)
            if src is None:
                continue
            if k != n and k not in other and k in new_images and k in old_images:
                d = image_drift(old_images[k], new_images[k])
                if d is not None and d > 3:
                    log.info("slide fix: image drift on slide %d (%.1f) with an equal fingerprint — the old preview is kept", k, d)
            shutil.copy2(src, merged / f"slide-{k:03d}.jpg")
        version = snapshot(vdir)
        (out / "deck.pptx").replace(deck0)
        for fmt in ("pdf", "html"):
            made = out / f"deck.{fmt}"
            if made.exists():
                made.replace(vdir / f"deck.{fmt}")
            elif (vdir / f"deck.{fmt}").exists():
                (vdir / f"deck.{fmt}").unlink()  # it would show the deck before the fix
                if fmt in exports:
                    log.warning("slide fix: deck.%s was not exported again", fmt)
        if any(merged.iterdir()):
            shutil.rmtree(vdir / "slides", ignore_errors=True)
            merged.replace(vdir / "slides")
        final_outline.agent_log = [*outline0.agent_log, f"Исправление: слайд {n} — {what or 'поправлено оформление'}."]
        report.deck = str(deck0)
        report.slide_images = {k: str(p) for k, p in enumerate(_previews(vdir), 1)}
        (vdir / "outline.json").write_text(final_outline.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "layout_plan.json").write_text(final_plan.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "audit_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        rm = _read_json(vdir / "run_manifest.json")
        if rm is not None:
            rm["audit"] = report.summary.model_dump()
            rm["applied_fixes"] = report.applied_fixes
            rm.setdefault("inputs", {})["outline_sha256"] = hashlib.sha256(final_outline.model_dump_json().encode("utf-8")).hexdigest()[:16]
            entry = final_plan.for_outline(oid)
            slides = rm.get("slides")
            if entry is not None and isinstance(slides, list) and len(slides) >= n and isinstance(slides[n - 1], dict):
                slides[n - 1].update({"mode": entry.mode, "pattern_id": entry.pattern_id, "composition": entry.composition})
            (vdir / "run_manifest.json").write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
        result.report, result.version, result.at = report, version, time.time()
        result.reply = RM.fix_reply(n, result.fixed, remarks, result.remaining, score_before, result.score_after, notes, applied, why, result.other, what, titles)
        log_edit(vdir, {
            "at": result.at, "version": version, "undo_of": None, "kind": "fix", "slides": [n], "request": fix_label(n, wishes),
            "reply": result.reply, "score_before": score_before, "score_after": result.score_after, "issue_ids": [r.id for r in remarks],
            "fixed": result.fixed, "wishes": wishes, "how": how, "other_slides": result.other,
        })
        return result
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
