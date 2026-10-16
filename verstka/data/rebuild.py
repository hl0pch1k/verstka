"""«Пересобрать слайд так»: a data slide of one variant built again with another visualization option of its dataset.

`prepare_rebuild(...)` checks the request before any work (the slide shows a dataset, the option exists, is another one
and suits the data — `NotBuilt` gives its reason) and builds the new slides; `rebuild_data_slide(...)` puts them into
the variant. Everything else stays: the other slides are kept byte for byte (the new slide is rendered in a scratch deck
and spliced in, `pipeline/revise.splice_slide`), the previous version is kept (versions/vN — «верни как было» undoes
the rebuild like any edit) and the rebuild is logged in edits.json. When the new option takes another number of slides
than the old one (a chart in place of a table split over three slides), the variant is laid out again from its plan
(`revise.rerender_variant`). The deck's audit runs without the brief: the figures of a data deck are checked against
the data (audit/checks/data.py), not against the text."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from verstka.data.plan import NotBuilt, slides_of
from verstka.data.story import slide_for
from verstka.data.words import count_words
from verstka.schemas.data import VIZ_TITLES, DatasetPlan, Table
from verstka.schemas.outline import DeckOutline, OutlineSlide

log = logging.getLogger(__name__)

__all__ = ["RebuildRefused", "RebuildPlan", "Rebuilt", "prepare_rebuild", "rebuild_data_slide", "dataset_of_slide"]


class RebuildRefused(ValueError):
    """The rebuild cannot be done: `status` — the HTTP status the API answers with, the message is for people."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class RebuildPlan:
    """What the rebuild will do: the dataset's slides now (1-based positions) and the slides that replace them."""

    n: int
    option: int
    title: str
    kind: str
    positions: list[int]
    slides: list[OutlineSlide]
    outline: DeckOutline  # the variant's plan with the new slides


@dataclass
class Rebuilt:
    applied: bool
    reply: str
    slides: list[int] = field(default_factory=list)
    score_before: Optional[float] = None
    score_after: Optional[float] = None
    errors: int = 0
    warnings: int = 0
    version: Optional[int] = None
    at: Optional[float] = None
    n_slides: int = 0


def dataset_of_slide(outline: DeckOutline, n: int) -> Optional[str]:
    """The id of the dataset slide `n` shows (None: the slide is not made from a data file)."""
    if not 1 <= n <= len(outline.slides):
        return None
    d = outline.slides[n - 1].data
    return d.dataset_id if d is not None else None


def prepare_rebuild(outline: DeckOutline, n: int, option: int, plan: DatasetPlan, table: Table) -> RebuildPlan:
    """The new slides of slide `n`'s dataset with option `option` — or RebuildRefused with a calm reason."""
    total = len(outline.slides)
    if not 1 <= n <= total:
        raise RebuildRefused(422, f"В этом варианте {count_words(total, 'слайд', 'слайда', 'слайдов')} — слайда {n} нет")
    osl = outline.slides[n - 1]
    d = osl.data
    if d is None:
        raise RebuildRefused(422, f"Слайд {n} собран не из файла с данными — другой вид визуализации для него не выбрать")
    if not 0 <= option < len(plan.options):
        raise RebuildRefused(422, f"У данных «{d.file}» {count_words(len(plan.options), 'вариант', 'варианта', 'вариантов')} визуализации — варианта {option + 1} нет")
    opt = plan.options[option]
    title = opt.title or VIZ_TITLES[opt.kind]
    if option == d.chosen:
        raise RebuildRefused(422, f"Слайд {n} уже показан так: {title.lower()}")
    positions = [k for k, s in enumerate(outline.slides, 1) if s.data is not None and s.data.dataset_id == d.dataset_id]
    first = outline.slides[positions[0] - 1]
    want = plan.model_copy(update={"chosen": option})
    want.slides = slides_of(want, table, option)
    if want.slides <= 0:
        raise RebuildRefused(422, f"«{title}» к этим данным не подходит")
    new: list[OutlineSlide] = []
    for part in range(1, want.slides + 1):
        sid = first.id if part == 1 else f"{first.id.split('~')[0]}~{option + 1}-{part}"
        s = slide_for(want, table, part, slide_id=sid)
        if isinstance(s, NotBuilt) or s is None:
            if part == 1:
                reason = s.reason if isinstance(s, NotBuilt) else "этим данным нечего показать в таком виде"
                raise RebuildRefused(422, f"«{title}» не подходит: {reason[:1].lower() + reason[1:]}")
            break
        new.append(s)
    # the slide keeps the deck's own words: its headline (the storyteller may have said it better) and section
    base_head = (first.headline or "").replace(" (продолжение)", "")
    for j, s in enumerate(new):
        s.headline = base_head if j == 0 else f"{base_head.rstrip('. ')} (продолжение)"
        s.section = first.section
        if s.data is not None:
            s.data.part = (j + 1, len(new))
        s.rationale = f"Пересобрано по вашей просьбе: {title.lower()}. " + (s.rationale or "")
    out = outline.model_copy(deep=True)
    at = positions[0] - 1
    out.slides[at : at + len(positions)] = [s.model_copy(deep=True) for s in new]
    return RebuildPlan(n=n, option=option, title=title, kind=opt.kind, positions=positions, slides=new, outline=out)


def _with_entries(plan0, plan1, ids: list[str]):
    """The layout plan `plan0` with the entries of `ids` taken from `plan1` (in their places)."""
    out = plan0.model_copy(deep=True)
    for oid in ids:
        entry = plan1.for_outline(oid)
        if entry is None:
            continue
        entry = entry.model_copy(deep=True)
        k = next((i for i, s in enumerate(out.slides) if s.outline_id == oid), None)
        if k is None:
            out.slides.append(entry)
        else:
            out.slides[k] = entry
    return out


def _previews(vdir: Path) -> list[Path]:
    root = vdir / "slides"
    return sorted(root.glob("slide-*.jpg")) if root.is_dir() else []


def rebuild_data_slide(
    vdir: Path,
    strategy: str,
    rp: RebuildPlan,
    *,
    manifest,
    ws,
    template_source: Path,
    workspace_root: Path,
    exports: Optional[list[str]] = None,
    progress: Optional[Callable[..., None]] = None,
) -> Rebuilt:
    """Put the rebuilt slides into the variant in `vdir` (see the module's doc). Nothing in `vdir` changes before the
    new deck is made, audited and its previews rendered: a failure leaves the variant as it was."""
    from verstka.api.remarks import carry_report_ids
    from verstka.audit.runner import run_audit
    from verstka.matching.matcher import match_outline
    from verstka.pipeline import revise as R
    from verstka.pipeline.generate import render_outputs
    from verstka.planning.strategies import load_strategies
    from verstka.rendering.renderer import render_deck, strip_outline_marks
    from verstka.schemas.audit import AuditReport
    from verstka.schemas.layout import LayoutPlan

    def say(msg: str, frac: float) -> None:
        if progress is not None:
            try:
                progress(msg, frac)
            except Exception:  # noqa: BLE001
                log.debug("progress listener failed", exc_info=True)

    vdir = Path(vdir)
    outline0 = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
    plan0 = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
    report0 = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
    deck0 = vdir / "deck.pptx"
    before = report0.summary.score
    request = f"Пересобери слайд {rp.n} так: {rp.title.lower()}"
    exports = [e for e in (exports or []) if e in ("pdf", "html")]

    if len(rp.slides) != len(rp.positions):
        # another number of slides: the variant is laid out again from its plan (the other slides keep their content)
        say(f"Собираю слайд {rp.n} заново — вариант перестраивается", 0.3)
        version = R.snapshot(vdir)
        v = R.rerender_variant(vdir, strategy, rp.outline, template_source, workspace_root, brief=None, exports=exports, pictures=False)
        rep = v.audit
        after = rep.summary.score if rep is not None else None
        changed = list(range(rp.positions[0], rp.positions[0] + len(rp.slides)))
        reply = _reply(rp, before, after)
        at = time.time()
        R.log_edit(vdir, {"at": at, "version": version, "undo_of": None, "kind": "rebuild", "slides": changed, "request": request, "reply": reply, "score_before": before, "score_after": after, "option": rp.option, "viz": rp.kind})
        return Rebuilt(True, reply, changed, before, after, rep.summary.errors if rep else 0, rep.summary.warnings if rep else 0, version, at, len(v.outline.slides))

    scratch = vdir.parent / f".{strategy}.rebuild"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        say(f"Собираю слайд {rp.n}: {rp.title.lower()}", 0.15)
        st = load_strategies()
        strategy_obj = st.get(strategy) or next(iter(st.values()))
        ids = [s.id for s in rp.slides]
        plan1 = _with_entries(plan0, match_outline(rp.outline, manifest, strategy_obj), ids)
        work = scratch / "work.pptx"
        render_deck(rp.outline.model_copy(deep=True), plan1, manifest, ws, work)  # the whole scratch deck; only the new slides are used
        final = scratch / "final.pptx"
        shutil.copy2(deck0, final)
        for pos in rp.positions:
            R.splice_slide(final, work, pos, scratch / "spliced.pptx")
            (scratch / "spliced.pptx").replace(final)
        try:
            strip_outline_marks(final)
        except Exception:  # noqa: BLE001
            log.warning("outline markers left in the notes", exc_info=True)
        say("Проверяю слайд и остальные", 0.5)
        rep = carry_report_ids(report0, run_audit(final, manifest, rp.outline, ws, render=False, use_vlm=False, use_llm=False, strategy=strategy))
        # the model's own remarks of the other slides stay (they cannot be checked again without a model)
        rep.issues.extend(i.model_copy(deep=True) for i in report0.issues if i.kind == "model" and i.slide not in rp.positions)
        rep.applied_fixes = list(report0.applied_fixes) + [{"action": "rebuild", "slide": rp.n, "option": rp.option, "viz": rp.kind}]
        rep.iterations = report0.iterations
        rep.recompute()
        fp0, fp1 = R.slide_fingerprints(deck0), R.slide_fingerprints(final)
        other = R.changed_slides(fp0, fp1, skip=set(rp.positions))

        say("Готовлю превью", 0.7)
        out = scratch / "out"
        out.mkdir()
        shutil.copy2(final, out / "deck.pptx")
        _, images, warns, render_ok = render_outputs(out, manifest, rp.outline.title, exports, images=True)
        for w in warns:
            log.warning("rebuild: %s", w)
        if render_ok is False:
            from verstka.schemas.audit import Issue

            rep.issues.append(Issue(id="file_opens-0-render", slide=0, check_id="file_opens", severity="warn", kind="deterministic", message="LibreOffice не смог отрендерить файл"))
            rep.recompute()
        merged = scratch / "slides"
        merged.mkdir()
        old_images = {int(p.stem.rsplit("-", 1)[-1]): p for p in _previews(vdir)}
        new_images = {k: p for k, p in enumerate(images, 1)}
        for k in range(1, len(rp.outline.slides) + 1):
            fresh = k in rp.positions or k in other or k not in old_images
            src = (new_images.get(k) if fresh else old_images.get(k)) or old_images.get(k)
            if src is not None:
                shutil.copy2(src, merged / f"slide-{k:03d}.jpg")

        # the previous version kept, the files replaced, the rebuild logged
        version = R.snapshot(vdir)
        (out / "deck.pptx").replace(deck0)
        for fmt in ("pdf", "html"):
            made = out / f"deck.{fmt}"
            if made.exists():
                made.replace(vdir / f"deck.{fmt}")
            elif (vdir / f"deck.{fmt}").exists():
                (vdir / f"deck.{fmt}").unlink()  # it would show the deck before the rebuild
        if any(merged.iterdir()):
            shutil.rmtree(vdir / "slides", ignore_errors=True)
            merged.replace(vdir / "slides")
        new_outline = rp.outline.model_copy(deep=True)
        new_outline.agent_log = [*outline0.agent_log, f"Пересборка: слайд {rp.n} — {rp.title.lower()}."]
        rep.deck = str(deck0)
        rep.slide_images = {k: str(p) for k, p in enumerate(_previews(vdir), 1)}
        (vdir / "outline.json").write_text(new_outline.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "layout_plan.json").write_text(plan1.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "audit_report.json").write_text(rep.model_dump_json(indent=2), encoding="utf-8")
        rm_path = vdir / "run_manifest.json"
        try:
            rm = json.loads(rm_path.read_text(encoding="utf-8"))
            rm["audit"] = rep.summary.model_dump()
            rm["applied_fixes"] = rep.applied_fixes
            slides = rm.get("slides")
            for pos, oid in zip(rp.positions, ids):
                e = plan1.for_outline(oid)
                if e is not None and isinstance(slides, list) and len(slides) >= pos and isinstance(slides[pos - 1], dict):
                    slides[pos - 1].update({"outline_id": oid, "mode": e.mode, "pattern_id": e.pattern_id, "composition": e.composition})
            rm_path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            log.warning("rebuild: run_manifest.json not updated", exc_info=True)
        after = rep.summary.score
        reply = _reply(rp, before, after)
        at = time.time()
        R.log_edit(vdir, {"at": at, "version": version, "undo_of": None, "kind": "rebuild", "slides": list(rp.positions), "request": request, "reply": reply, "score_before": before, "score_after": after, "option": rp.option, "viz": rp.kind, "other_slides": other})
        say("Готово", 1.0)
        return Rebuilt(True, reply, list(rp.positions), before, after, rep.summary.errors, rep.summary.warnings, version, at, len(new_outline.slides))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _reply(rp: RebuildPlan, before: Optional[float], after: Optional[float]) -> str:
    text = f"Пересобрал слайд {rp.n}: {rp.title.lower()}."
    if len(rp.slides) != len(rp.positions):
        text += f" Теперь данные занимают {count_words(len(rp.slides), 'слайд', 'слайда', 'слайдов')}."
    if before is not None and after is not None and round(after) != round(before):
        text += f" Проверка качества: {before:g} → {after:g}."
    elif after is not None:
        text += f" Проверка качества: {after:g} из 100."
    return text + " Если не понравится — скажите «верни как было»."
