"""«Взгляд дизайнера» (Verstka 3.0): the vision model looks at every rendered slide of a variant like an art director
checking a proof before it goes to the client.

The deterministic audit reads the deck's XML: it measures overflow, fonts, colours and contrast, but it never sees
the slide. The model does (skill `slide_design_review`): a word broken mid-word in a narrow card, an empty row of a
ruled grid under a callout, text over a rule, a half-empty slide. A slide with a major problem is laid out again —
the autofix ladder's next rung: the slide's next template sample, then the composer (autofix._rematch) — and the
change has to pass two gates: the deterministic audit of the slide must not get worse, and the model, shown the two
layouts side by side in either order (skill `slide_design_compare`), must prefer the new one. Otherwise the slide goes
back as it was. Problems no new layout cured stay in the audit report as the model's remarks (check `design_review`),
with the model's own words, so the person sees them and may ask the helper to fix them.

Bounded by the generation's time: it starts only with `min_seconds_left` of the model budget left, stops asking when
the budget runs out, lays out at most `max_fixes` slides per variant (configs/eyes.yaml). Without a vision model, a
skills registry or LibreOffice it does nothing.

Checked live on Qwen3.8-27B (2026-10-07): it found the four words broken mid-word on Marketing Report slide 8 and the
empty grid row of Классика slide 3, passed a clean VK Tech slide, and chose the layout without the broken words in
both orders of the pair (≈ 2–7 s and 0.03–0.11 ₽ a look).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from verstka.schemas.audit import AuditReport, CheckSpec, Issue

log = logging.getLogger(__name__)

_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "eyes.yaml"
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "max_fixes": 4,  # slides laid out again per variant
    "min_seconds_left": 40.0,  # the model budget left to start the review
    "fix_seconds_left": 20.0,  # ... to lay out again and compare
    "compare": True,  # a new layout stays only when the model prefers it side by side
    "dpi": 100,  # the slide images the model sees
    "skip_kinds": ["thanks", "agenda"],
    "workers": 4,
}

# the problems the review may name — and their words for the person (the timeline, the remarks)
CODES: dict[str, str] = {
    "text_cut": "текст обрезан или выходит за блок",
    "word_broken": "слова разорваны посередине",
    "overlap": "элементы наезжают друг на друга",
    "cramped": "текст набит слишком плотно",
    "too_small": "текст слишком мелкий",
    "low_contrast": "текст плохо читается на фоне",
    "unbalanced": "пустоты и перекос композиции",
    "leftover": "пустая рамка или лишний элемент",
    "chart_unreadable": "диаграмма или таблица не читается",
}
_SYNONYMS = {"word_break": "word_broken", "broken_word": "word_broken", "cut": "text_cut", "overflow": "text_cut", "contrast": "low_contrast",
             "empty": "unbalanced", "imbalance": "unbalanced", "placeholder": "leftover", "small_text": "too_small", "crowded": "cramped"}

DESIGN_REVIEW = CheckSpec(
    id="design_review", title="Взгляд дизайнера (VLM)", severity="warn", kind="model", category="layout",
    description=(
        "Модель смотрит на картинку готового слайда, как арт-директор на вёрстку перед отправкой клиенту: обрезанный "
        "текст, слова, разорванные посередине, наложения, тесный или мелкий текст, плохой контраст, перекос и пустоты, "
        "пустые рамки, нечитаемые диаграммы. Слайд с серьёзной проблемой собирается заново (следующий образец шаблона, "
        "затем композиция); новая вёрстка остаётся, только если детерминированный аудит не стал хуже и модель, сравнив "
        "две вёрстки рядом, выбрала новую. Замечание здесь — то, что новая вёрстка не исправила."
    ),
)


class ReviewProblem(BaseModel):
    code: str = ""
    severity: str = "minor"
    where: str = ""
    evidence: str = ""

    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, v: Any) -> str:
        c = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        return _SYNONYMS.get(c, c)

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: Any) -> str:
        s = str(v or "").strip().lower()
        return "major" if s.startswith(("maj", "crit", "high", "серьёз", "серьез", "крит", "сильн")) else "minor"

    @field_validator("where", "evidence", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return " ".join(str(v or "").split())[:300]


class DesignReview(BaseModel):
    """Output of the `slide_design_review` skill."""

    ok: bool = True
    problems: list[ReviewProblem] = Field(default_factory=list)
    verdict: str = ""

    @field_validator("problems", mode="before")
    @classmethod
    def _problems(cls, v: Any) -> Any:
        return [p for p in v if isinstance(p, dict)] if isinstance(v, list) else []

    def known(self) -> list[ReviewProblem]:
        return [p for p in self.problems if p.code in CODES]

    def major(self) -> list[ReviewProblem]:
        return [p for p in self.known() if p.severity == "major"]


class DesignCompare(BaseModel):
    """Output of the `slide_design_compare` skill."""

    better: str = "same"
    reason: str = ""

    @field_validator("better", mode="before")
    @classmethod
    def _better(cls, v: Any) -> str:
        s = str(v or "").strip().strip(".«»\"'").upper()
        s = {"А": "A", "В": "B", "Б": "B"}.get(s, s)  # Cyrillic letters the model may answer with
        return s if s in ("A", "B") else "same"


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path else _CONFIG
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


@dataclass
class EyesOutcome:
    """What the review did on one variant (run_manifest.json `eyes`, the timeline)."""

    looked: int = 0
    calls: int = 0
    flagged: list[dict] = field(default_factory=list)  # {"slide", "outline_id", "problems": [{code, severity, where, evidence}]}
    fixed: list[dict] = field(default_factory=list)  # {"slide", "outline_id", "result", "reason"}: the new layout stayed
    kept: list[dict] = field(default_factory=list)  # tried again, the old layout stayed: {"slide", "outline_id", "why"}
    skipped: Optional[str] = None
    seconds: float = 0.0

    def summary(self) -> dict:
        return {
            "looked": self.looked, "calls": self.calls, "flagged": self.flagged, "fixed": self.fixed, "kept": self.kept,
            "skipped": self.skipped, "seconds": round(self.seconds, 2),
        }


def slide_images(pptx: Path, out_dir: Path, dpi: int = 100) -> dict[int, Path]:
    """Slide number → image of the deck as it is now (LibreOffice → PDF → JPEG)."""
    from verstka.export.pdf import export_pdf
    from verstka.ingest.render import pdf_to_images

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink(missing_ok=True)
    pdf = export_pdf(pptx, out_dir / "deck.pdf")
    try:
        imgs = pdf_to_images(pdf, out_dir, dpi=dpi)
    finally:
        pdf.unlink(missing_ok=True)
    return {i: p for i, p in enumerate(imgs, 1)}


def _left(deadline: Optional[float]) -> float:
    return float("inf") if deadline is None else deadline - time.monotonic()


def _form(osl: Any) -> str:
    if osl is None:
        return "слайд"
    try:
        from verstka.planning.agent import form_ru

        return form_ru(osl)
    except Exception:  # noqa: BLE001 - the form only helps the model read the slide
        return str(getattr(osl.kind, "value", osl.kind))


def _said(problems: list[ReviewProblem]) -> str:
    return "; ".join(f"{CODES.get(p.code, p.code)} ({p.where})" if p.where else CODES.get(p.code, p.code) for p in problems) or "—"


def look(
    vdir: Path,
    report: AuditReport,
    outline: Any,
    plan: Any,
    manifest: Any,
    ws: Any,
    *,
    providers: Any,
    skills: Any,
    deadline: Optional[float] = None,
    others: Optional[dict] = None,
    brief_text: Optional[str] = None,
    writer: Any = None,
    emit: Optional[Callable[..., None]] = None,
    cfg: Optional[dict] = None,
    images: Optional[Callable[[Path, Path, int], dict[int, Path]]] = None,
) -> tuple[AuditReport, Any, Any, Any, EyesOutcome]:
    """Review the variant in `vdir` (its deck.pptx, audit report, outline and plan) and lay out again the slides the
    model sees a major problem on. Returns (audit report, plan, outline, render result or None, outcome); the deck on
    disk is the one the report describes."""
    from verstka.analysis.classify import image_bytes_for_vlm
    from verstka.audit.autofix import _ir_slides, _restore_slide, _slide_weight, _Snapshot, _unsay
    from verstka.audit.runner import run_audit
    from verstka.rendering.renderer import render_deck

    cfg = {**DEFAULTS, **(cfg or {})}
    shoot = images or slide_images
    out = EyesOutcome()
    t0 = time.monotonic()
    say = emit or (lambda message, slide=None, fix=None: None)
    pptx = Path(vdir) / "deck.pptx"
    render_result = None

    def done(why: Optional[str] = None) -> tuple[AuditReport, Any, Any, Any, EyesOutcome]:
        out.skipped = why
        out.seconds = time.monotonic() - t0
        return report, plan, outline, render_result, out

    if not cfg.get("enabled", True):
        return done("off in configs/eyes.yaml")
    if providers is None or skills is None or not providers.has("vlm"):
        return done("no vision model")
    if _left(deadline) < float(cfg["min_seconds_left"]):
        return done("no time left in the generation's model budget")
    try:
        before = shoot(pptx, Path(vdir) / "eyes" / "before", int(cfg["dpi"]))
    except Exception as e:  # noqa: BLE001 - no LibreOffice, a deck it cannot open: the deck stays as it is
        log.warning("design review: slide images failed: %s", e)
        return done(f"no slide images ({str(e)[:120]})")

    ir = _ir_slides(report, outline)
    oid_of = {s.index: s.outline_id for s in ir}
    by_id = {s.id: s for s in outline.slides}
    skip = set(cfg.get("skip_kinds") or ())
    todo = [i for i in sorted(before) if (by_id.get(oid_of.get(i) or "") is not None) and by_id[oid_of[i]].kind.value not in skip]
    title = getattr(outline, "title", "") or ""

    def review(i: int) -> tuple[int, Optional[DesignReview]]:
        if _left(deadline) < 8.0:
            return i, None
        osl = by_id.get(oid_of.get(i) or "")
        try:
            res = skills.run(
                "slide_design_review", providers,
                {"slide_index": i, "deck_title": title, "form": _form(osl), "headline": (osl.headline if osl else "") or ""},
                images=[image_bytes_for_vlm(before[i])],
            )
            return i, res.parsed
        except Exception as e:  # noqa: BLE001 - one slide unseen never stops the deck
            log.info("design review of slide %s failed: %s", i, str(e)[:160])
            return i, None

    workers = max(1, min(int(cfg["workers"]), getattr(getattr(providers, "limits", None), "max_concurrency", 4) or 4, len(todo) or 1))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        reviews = dict(ex.map(review, todo))
    out.calls += len(todo)
    out.looked = sum(1 for r in reviews.values() if r is not None)
    seen: dict[int, list[ReviewProblem]] = {}
    for i, r in reviews.items():
        if r is None or not r.known():
            continue
        seen[i] = r.known()
        out.flagged.append({"slide": i, "outline_id": oid_of.get(i), "problems": [p.model_dump() for p in r.known()]})
    majors = sorted(((i, [p for p in ps if p.severity == "major"]) for i, ps in seen.items()), key=lambda x: (-len(x[1]), x[0]))
    majors = [(i, ps) for i, ps in majors if ps][: int(cfg["max_fixes"])]
    if not seen:
        say(f"Взгляд дизайнера: посмотрел на {ru_slides(out.looked)} — замечаний нет.", None)
    else:
        say(f"Взгляд дизайнера: посмотрел на {ru_slides(out.looked)} — замечания на {_slides_list(sorted(seen))}.", None)

    fixed_ids: set[str] = set()
    if majors and _left(deadline) >= float(cfg["fix_seconds_left"]):
        snapshot = _Snapshot(pptx, plan, outline, None, "eyes")
        try:
            moved: dict[str, tuple[int, str]] = {}
            taken: set = set()
            for i, _ in majors:
                oid = oid_of.get(i)
                if not oid:
                    continue
                res = relayout(plan, outline, oid, manifest, taken, others=others)
                if res != "skip":
                    moved[oid] = (i, res)
            if moved:
                _unsay(outline)
                render_result = render_deck(outline, plan, manifest, ws, pptx)
                trial = run_audit(pptx, manifest, outline, ws, render=False, strategy=report.strategy, brief_text=brief_text, writer=writer)
                worse = {oid for oid in moved if _slide_weight(trial, oid) > _slide_weight(report, oid)}
                for oid in worse:
                    i, res = moved.pop(oid)
                    _restore_slide(plan, outline, snapshot, oid)
                    out.kept.append({"slide": i, "outline_id": oid, "why": "автоматическая проверка нашла на новой вёрстке больше замечаний"})
                if worse:
                    render_result = render_deck(outline, plan, manifest, ws, pptx)
                if moved and cfg.get("compare", True) and _left(deadline) >= 8.0:
                    after = shoot(pptx, Path(vdir) / "eyes" / "after", int(cfg["dpi"]))

                    def compare(item: tuple[str, tuple[int, str]]) -> tuple[str, str, str]:
                        oid, (i, _) = item
                        if i not in before or i not in after or _left(deadline) < 5.0:
                            return oid, "same", "нет времени сравнить"
                        flip = i % 2 == 1  # the new layout comes first on every other slide: no side is favoured
                        old_img, new_img = image_bytes_for_vlm(before[i]), image_bytes_for_vlm(after[i])
                        osl = by_id.get(oid)
                        try:
                            res = skills.run(
                                "slide_design_compare", providers,
                                {"slide_index": i, "form": _form(osl), "headline": (osl.headline if osl else "") or "", "original": "B" if flip else "A", "problems": _said(seen.get(i, []))},
                                images=[new_img, old_img] if flip else [old_img, new_img],
                            )
                            better = res.parsed.better
                            reason = res.parsed.reason
                        except Exception as e:  # noqa: BLE001 - not compared: the old layout stays
                            return oid, "same", f"сравнение не удалось ({str(e)[:80]})"
                        if better == "same":
                            return oid, "same", reason
                        new_side = "A" if flip else "B"
                        return oid, ("new" if better == new_side else "old"), reason

                    with ThreadPoolExecutor(max_workers=workers) as ex:
                        verdicts = list(ex.map(compare, list(moved.items())))
                    out.calls += len(verdicts)
                    back = [(oid, why) for oid, v, why in verdicts if v != "new"]
                    for oid, why in back:
                        i, res = moved.pop(oid)
                        _restore_slide(plan, outline, snapshot, oid)
                        out.kept.append({"slide": i, "outline_id": oid, "why": why or "новая вёрстка не лучше"})
                    if back:
                        render_result = render_deck(outline, plan, manifest, ws, pptx)
                    reasons = {oid: why for oid, v, why in verdicts if v == "new"}
                else:
                    reasons = {}
                for oid, (i, res) in moved.items():
                    fixed_ids.add(oid)
                    out.fixed.append({"slide": i, "outline_id": oid, "result": res, "reason": reasons.get(oid, "")})
        finally:
            snapshot.discard()
        for item in out.fixed:
            problems = _said([p for p in seen.get(item["slide"], []) if p.severity == "major"])
            fix = f"Собрал заново{_how(item['result'])}" + (f": {item['reason'].rstrip('.')}." if item["reason"] else ".")
            say(f"Взгляд дизайнера: слайд {item['slide']} — {problems}.", item["slide"], fix)
        for item in out.kept:
            problems = _said([p for p in seen.get(item["slide"], []) if p.severity == "major"])
            say(f"Взгляд дизайнера: слайд {item['slide']} — {problems}.", item["slide"], f"Новая вёрстка не лучше — оставил прежнюю ({item['why'].rstrip('.')}).")

    # the report of the deck as it is now: the deterministic checks again when a slide changed, the model's remarks of
    # the slides that kept their problems
    final = report
    if fixed_ids:
        final = run_audit(pptx, manifest, outline, ws, render=False, strategy=report.strategy, brief_text=brief_text, writer=writer)
        final.applied_fixes = list(report.applied_fixes)
        final.iterations = report.iterations
        final.issues.extend(i for i in report.issues if i.kind == "model" and (i.outline_id or "") not in fixed_ids)
    final.applied_fixes = list(final.applied_fixes) + [
        {"iteration": "eyes", "outline_id": f["outline_id"], "action": "rematch", "result": f["result"], "by": "design_review", "reason": f["reason"]} for f in out.fixed
    ] + [{"iteration": "eyes", "outline_id": k["outline_id"], "action": "rematch", "result": "kept", "rolled_back": True, "by": "design_review", "reason": k["why"]} for k in out.kept]
    # the serious problems no new layout cured; a designer's polish («minor») stays in run_manifest `eyes` only
    final.issues.extend(problem_issues({i: ps for i, ps in seen.items() if oid_of.get(i) not in fixed_ids}, oid_of))
    final.recompute()
    report = final
    return done(None)


def look_only(pptx: Path, out_dir: Path, *, providers: Any, skills: Any, cfg: Optional[dict] = None, titles: Optional[dict[int, str]] = None,
              deadline: Optional[float] = None, images: Optional[Callable[[Path, Path, int], dict[int, Path]]] = None) -> dict[int, list[ReviewProblem]]:
    """The review alone, on any deck (an old deck uploaded to be improved): slide number → the problems the model sees
    on it; nothing is laid out again. {} without a vision model, slide images or time."""
    from verstka.analysis.classify import image_bytes_for_vlm

    cfg = {**DEFAULTS, **(cfg or {})}
    if providers is None or skills is None or not providers.has("vlm") or _left(deadline) < 10.0:
        return {}
    try:
        shots = (images or slide_images)(Path(pptx), Path(out_dir), int(cfg["dpi"]))
    except Exception as e:  # noqa: BLE001 - no LibreOffice: nothing to look at
        log.warning("design review of the deck: slide images failed: %s", e)
        return {}

    def review(i: int) -> tuple[int, list[ReviewProblem]]:
        if _left(deadline) < 5.0:
            return i, []
        try:
            res = skills.run("slide_design_review", providers, {"slide_index": i, "deck_title": "", "form": "слайд", "headline": (titles or {}).get(i, "")},
                             images=[image_bytes_for_vlm(shots[i])])
            return i, res.parsed.known()
        except Exception as e:  # noqa: BLE001
            log.info("design review of slide %s failed: %s", i, str(e)[:160])
            return i, []

    workers = max(1, min(int(cfg["workers"]), len(shots) or 1))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return {i: ps for i, ps in ex.map(review, sorted(shots)) if ps}


def problem_issues(problems: dict[int, list[ReviewProblem]], outline_ids: Optional[dict[int, Optional[str]]] = None) -> list[Issue]:
    """The serious problems the review saw, as the audit's model remarks (`design_review`)."""
    out: list[Issue] = []
    for i, ps in sorted(problems.items()):
        for k, p in enumerate(q for q in ps if q.severity == "major"):
            out.append(Issue(
                id=f"design_review-{i}-{k}", slide=i, check_id=DESIGN_REVIEW.id, severity="warn", kind="model",
                message=f"{CODES[p.code].capitalize()}" + (f" ({p.where})" if p.where else "") + (f": {p.evidence}" if p.evidence else ""),
                details={"code": p.code, "severity": p.severity}, outline_id=(outline_ids or {}).get(i),
            ))
    return out


_STYLES = ("compact", "visual", "structured")


def relayout(plan: Any, outline: Any, oid: str, manifest: Any, taken: Optional[set] = None, others: Optional[dict] = None) -> str:
    """The slide's next layout: a slide on a template sample takes its next untried sample, then the composer (the
    autofix ladder, autofix._rematch); a composed slide is composed again in another variant's style (each style once),
    the composer's own knob — a sample left behind because it fit worse stays behind."""
    from verstka.audit.autofix import _rematch

    ps = plan.for_outline(oid)
    if ps is None:
        return "skip"
    if ps.mode == "synth" and ps.composition and ps.composition not in ("title", "section", "thanks"):
        tried = set(ps.fit.get("styles_tried", [])) | {ps.fit.get("style") or outline.strategy}
        for style in _STYLES:
            if style not in tried:
                ps.fit["styles_tried"] = sorted(tried | {style})
                ps.fit["style"] = style
                ps.reasons.append(f"взгляд дизайнера: композиция в стиле варианта «{style}»")
                return f"restyle → {style}"
        return "skip"
    return _rematch(plan, outline, oid, manifest, taken, others=others)


def ru_slides(n: int) -> str:
    tail = n % 100
    word = "слайдов" if 11 <= tail <= 14 else {1: "слайд", 2: "слайда", 3: "слайда", 4: "слайда"}.get(n % 10, "слайдов")
    return f"{n} {word}"


def _slides_list(ids: list[int]) -> str:
    return ("слайде " if len(ids) == 1 else "слайдах ") + ", ".join(map(str, ids))


def _how(result: str) -> str:
    if result.startswith("rematch"):
        return " на другом макете шаблона"
    if result.startswith("synth"):
        return " композицией из стилей шаблона"
    if result.startswith("restyle"):
        return " в другой композиции"
    return ""
