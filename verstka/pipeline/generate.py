"""generate_variants: one template + one brief/outline → decks for the requested strategies (+ audit, autofix, export)."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from verstka.analysis.manifest import analyze_template
from verstka.audit.autofix import autofix_loop
from verstka.audit.runner import run_audit
from verstka.export.html import export_html
from verstka.export.pdf import export_pdf
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, pdf_to_images
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.matcher import match_outline
from verstka.pipeline.run_manifest import build_run_manifest, write_run_manifest
from verstka.planning.facts import basic_facts, extract_facts
from verstka.planning.outline import adapt_outline, plan_outline, target_slide_count
from verstka.planning.strategies import STRATEGY_NAMES, Strategy, load_strategies
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.audit import AuditReport, Issue
from verstka.schemas.layout import LayoutPlan
from verstka.schemas.outline import Brief, DeckOutline, FactsExtraction, OutlineSlide
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)
ProgressFn = Callable[..., None]
# the plans a model wrote: the outline planner's ("model") and the planning agent's ("agent")
MODEL_PLANNED = ("model", "agent")
# the progress share of each agent step (the plan phase runs from 0.15 to _AGENT_PLAN_END when the agent plans)
_AGENT_PLAN_END = 0.4
# a slow first analysis of a template leaves the models at least this much of the budget (then the rules)
_MIN_MODEL_BUDGET_S = 30.0
_AGENT_SHARE = {"writer": 0.16, "analyst": 0.17, "architect": 0.19, "designer": 0.2, "critic": 0.33, "revise": 0.36, "compile": 0.38}


@dataclass
class VariantResult:
    strategy: str
    out_dir: Path
    outline: DeckOutline
    plan: LayoutPlan
    render: RenderResult
    images: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0
    audit: Optional[AuditReport] = None
    exports: dict[str, Path] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    # who wrote the plan: {"planned_by": "agent" | "model" | "rules" | "skeleton" | "shared:<strategy>", "model": the model
    # that answered, "supplied": True when the outline came with the request, "agent": what the planning agent did}
    planner: dict = field(default_factory=dict)


@dataclass
class GenerateResult:
    template_id: str
    manifest: TemplateManifest
    variants: list[VariantResult] = field(default_factory=list)
    seconds: float = 0.0
    # writer mode (planning/writer.py): what the agent wrote from a topic and how (None: the brief was not a topic,
    # models off, or the writer switched off)
    writer: Optional[Any] = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class _Recorder:
    """A provider that notes which model answered each call (CompletionResult.model — with a fallback chain it may be
    a backup model), so a deck can say which model planned it; and what every call cost (`stats`: the skill's answer
    schema, seconds, HTTP requests sent — attempts, retries and repairs included —, prompt and completion tokens, also
    of a call that failed), for the run manifest."""

    # a caller may name the call's skill (`skill=`) when it parses the answer itself (schema None: the writer's calls)
    labels_calls = True

    def __init__(self, inner, sink: list, stats: Optional[list] = None) -> None:
        self.inner = inner
        self.sink = sink
        self.stats = stats if stats is not None else []
        self.name = getattr(inner, "name", "provider")
        self.model = getattr(inner, "model", None)

    def complete(self, messages, **kwargs):
        from verstka.providers.openai_compat import requests_sent

        schema = kwargs.get("schema")
        label = kwargs.pop("skill", None)
        if label and getattr(self.inner, "labels_calls", False):
            kwargs["skill"] = label  # a recorder inside this one (the agent's in the generation's) names the call too
        rec = {"skill": label or getattr(schema, "__name__", None) or "text", "ok": False}
        t, sent = time.monotonic(), requests_sent()
        try:
            res = self.inner.complete(messages, **kwargs)
        except Exception as e:
            u = getattr(e, "usage", None)
            rec.update(tokens_in=getattr(u, "prompt_tokens", 0) or 0, tokens_out=getattr(u, "completion_tokens", 0) or 0, cost_rub=getattr(u, "cost_rub", None), error=str(e)[:120])
            raise
        else:
            u = getattr(res, "usage", None)
            rec.update(ok=True, tokens_in=getattr(u, "prompt_tokens", 0) or 0, tokens_out=getattr(u, "completion_tokens", 0) or 0, cost_rub=getattr(u, "cost_rub", None), attempts=getattr(res, "attempts", 1))
            self.sink.append(getattr(res, "model", None) or self.model)
            return res
        finally:
            n = requests_sent() - sent
            # a provider without HTTP (a mock, a replay) sends nothing: its call counts as its attempts
            rec.update(seconds=round(time.monotonic() - t, 2), requests=n if n > 0 else int(rec.get("attempts", 1)))
            self.stats.append(rec)

    def __getattr__(self, item: str):
        return getattr(self.inner, item)


def _recording(providers: Optional[ProviderRegistry], stats: Optional[list] = None) -> tuple[Optional[ProviderRegistry], list]:
    """The registry with every role wrapped in a _Recorder (one sink per call site, `stats` for what the calls cost);
    the registry itself if it cannot be."""
    sink: list = []
    if providers is None:
        return None, sink
    try:
        reg = copy.copy(providers)
        reg.roles = {role: _Recorder(p, sink, stats) for role, p in providers.roles.items()}
        return reg, sink
    except Exception:  # noqa: BLE001 - recording is a nicety, planning must not depend on it
        return providers, sink


def call_totals(stats: list) -> dict:
    """What the model calls of a step cost: calls, HTTP requests, tokens in and out, failed calls, rubles (Polza's
    usage.cost_rub; failed requests cost nothing; None when no call said what it cost — the final's VK inference),
    by skill."""
    by: dict[str, dict] = {}
    for r in stats:
        b = by.setdefault(r.get("skill") or "text", {"calls": 0, "requests": 0, "tokens_in": 0, "tokens_out": 0, "failed": 0, "seconds": 0.0, "cost_rub": None})
        b["calls"] += 1
        b["requests"] += int(r.get("requests") or 0)
        b["tokens_in"] += int(r.get("tokens_in") or 0)
        b["tokens_out"] += int(r.get("tokens_out") or 0)
        b["failed"] += 0 if r.get("ok") else 1
        b["seconds"] = round(b["seconds"] + float(r.get("seconds") or 0.0), 2)
        if r.get("cost_rub") is not None:
            b["cost_rub"] = round((b["cost_rub"] or 0.0) + float(r["cost_rub"]), 4)
    tot = {k: sum(b[k] for b in by.values()) for k in ("calls", "requests", "tokens_in", "tokens_out", "failed")}
    known = [b["cost_rub"] for b in by.values() if b["cost_rub"] is not None]
    tot["cost_rub"] = round(sum(known), 4) if known else None
    return {**tot, "by_skill": by}


def _cost_of(stats: list) -> dict:
    """The agent's model use for run_manifest.planner.agent: every call (the analyst's data_extractor included), the
    HTTP requests they sent (retries, repairs), tokens in and out."""
    if not stats:
        return {}
    t = call_totals(stats)
    return {"calls_made": t["calls"], "requests": t["requests"], "tokens_in": t["tokens_in"], "tokens_out": t["tokens_out"], "failed_calls": t["failed"], "cost_rub": t["cost_rub"], "by_skill": t["by_skill"]}


def _event_sink(progress: Optional[ProgressFn]) -> Callable[[dict], None]:
    """The planning agent's events ({"type": "agent", "step", "message", "slide", "variant"}) for a progress callback:
    one that takes an `event` keyword (or any keyword: api.agent_view.job_progress) gets the event as `event=`, one
    that takes (message, share) only gets the message; the share grows with the agent's steps."""
    if progress is None:
        return lambda ev: None
    try:
        params = inspect.signature(progress).parameters
    except (TypeError, ValueError):
        params = {}
    takes_event = "event" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())
    state = {"designed": 0}

    def sink(ev: dict) -> None:
        step = ev.get("step") or "analyst"
        share = _AGENT_SHARE.get(step, 0.2)
        if step == "designer":
            state["designed"] += 1
            share = min(0.32, 0.2 + 0.01 * state["designed"])
        if "share" in ev:
            # a line said after the plan (the pipeline's own planner, _say_designs) keeps the bar where the plan left it
            ev = dict(ev)
            share = float(ev.pop("share"))
        try:
            if takes_event:
                progress(ev["message"], share, event=ev)
            else:
                progress(ev["message"], share)
        except Exception:  # noqa: BLE001 - a listener never stops the deck
            log.debug("progress listener failed on an agent event", exc_info=True)

    return sink


def _design_line(pos: int, s: OutlineSlide, by: str) -> str:
    """The designer's line for a slide of a plan the pipeline made itself — what the agent says of the slides it plans
    (planning/agent.py design_all): the build's storyboard draws each slide from it, the agent's timeline lists it."""
    from verstka.planning.agent import form_ru

    k = s.kind.value
    if k == "title":
        return f"Дизайнер: слайд {pos} — обложка «{s.headline}»."
    if k == "thanks":
        return f"Дизайнер: слайд {pos} — финальный слайд «{s.headline}»."
    how = "" if by in MODEL_PLANNED or by.startswith("shared:") else " собран по правилам"
    return f"Дизайнер: слайд {pos} «{s.headline}»{how} — {form_ru(s)}."


def _say_designs(progress: Optional[ProgressFn], outlines: dict[str, DeckOutline], share: float) -> None:
    """Every slide of the variants planned here (the agent did not plan them: no model, no time, a failed agent), one
    designer line each, as the agent says them — so the build shows the deck taking shape without a model too. At the
    plan's own share of the bar: the layout starts from there."""
    from verstka.planning.agent import event_message

    sink = _event_sink(progress)
    for name, o in outlines.items():
        for pos, s in enumerate(o.slides, 1):
            # the event does not name its step and slide (the timeline shows it under its step, with the slide's badge)
            sink({"type": "agent", "step": "designer", "message": event_message(_design_line(pos, s, o.planned_by), pos), "slide": pos, "variant": name, "share": share})


def render_outputs(vdir: Path, manifest: TemplateManifest, title: Optional[str], exports: list[str], *, images: bool = True, dpi: int = 110) -> tuple[dict[str, Path], list[Path], list[str], Optional[bool]]:
    """PDF, HTML and slide previews of `vdir/deck.pptx` with a single LibreOffice run.

    Returns (export paths, slide images, warnings, render_ok) — render_ok is None when LibreOffice was not needed
    or is not installed, False when it failed on the deck.
    """
    deck = vdir / "deck.pptx"
    paths: dict[str, Path] = {}
    warnings: list[str] = []
    imgs: list[Path] = []
    render_ok: Optional[bool] = None
    pdf: Optional[Path] = None
    if ("pdf" in exports or images) and find_soffice():
        try:
            pdf = export_pdf(deck, vdir / "deck.pdf")
            render_ok = True
            if "pdf" in exports:
                paths["pdf"] = pdf
        except Exception as e:  # noqa: BLE001
            render_ok = False
            warnings.append(f"export pdf failed: {str(e)[:160]}")
    if images and pdf is not None and find_pdftoppm():
        try:
            imgs = pdf_to_images(pdf, vdir / "slides", dpi=dpi)
        except RenderError as e:
            warnings.append(f"render images failed: {e}")
    if pdf is not None and "pdf" not in exports:
        pdf.unlink(missing_ok=True)
    if "html" in exports:
        try:
            paths["html"] = export_html(deck, manifest, vdir / "deck.html", title=title)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"export html failed: {str(e)[:160]}")
    return paths, imgs, warnings, render_ok


def _shown_samples(taken0: dict, outline: DeckOutline, render: RenderResult) -> dict:
    """`taken` for the next variants: what the earlier ones showed, and the samples this deck shows on its slides."""
    from verstka.matching.matcher import headline_key

    taken = {k: set(v) for k, v in taken0.items()}
    by_id = {s.id: s for s in outline.slides}
    for rs in render.slides:
        o = by_id.get(rs.outline_id)
        if o is not None and rs.mode == "clone" and rs.pattern_id:
            taken.setdefault(headline_key(o), set()).add(rs.pattern_id)
    return taken


def _rematched(outline0: DeckOutline, manifest: TemplateManifest, strategy: Strategy, ws: TemplateWorkspace, taken0: dict, render: RenderResult, vdir: Path):
    """The deck rendered once more with its samples chosen again without those that read badly on their slides
    (`RenderResult.failed_samples`). Returns (outline, plan, render, taken) when it stands on more template slides —
    or as many, more of them different — than the first render, else None (the first render stays)."""
    try:
        v_outline = outline0.model_copy(deep=True)
        taken = {k: set(v) for k, v in taken0.items()}
        plan = match_outline(v_outline, manifest, strategy, ws=ws, taken=taken, exclude=set(render.failed_samples))
        first = [s.pattern_id if s.mode == "clone" else None for s in render.slides]
        again = [s.pattern_id if s.mode == "clone" else None for s in plan.slides]
        if again == first:
            return None  # the same samples on the same slides: nothing to gain
        tmp = vdir / "deck.retry.pptx"
        r2 = render_deck(v_outline, plan, manifest, ws, tmp, skip=set(render.failed_samples), shown=taken0)
        better = (len(r2.clones), len(set(r2.clones))) > (len(render.clones), len(set(render.clones)))
        if not better:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(vdir / "deck.pptx")
        r2.pptx_path = vdir / "deck.pptx"
        r2.failed_samples |= render.failed_samples
        log.info("%s: samples chosen again without the %d that read badly: %d → %d template slides", strategy.name, len(render.failed_samples), len(render.clones), len(r2.clones))
        return v_outline, plan, r2, taken
    except Exception:  # noqa: BLE001 - the first render stands
        log.warning("re-matching the deck's samples failed", exc_info=True)
        return None


def generate_variants(
    template: Path | str,
    *,
    brief: Optional[Brief] = None,
    outline: Optional[DeckOutline] = None,
    strategies: Optional[list[str]] = None,
    out_dir: Path | str = "out",
    workspace_root: Optional[Path | str] = None,
    providers: Optional[ProviderRegistry] = None,
    skills: Optional[SkillsRegistry] = None,
    use_llm: bool = True,
    use_vlm: bool = True,
    render_images: bool = True,
    force_analyze: bool = False,
    audit: bool = True,
    autofix: bool = True,
    audit_models: bool = False,
    exports: Optional[list[str]] = None,
    progress: Optional[ProgressFn] = None,
    agent: Optional[bool] = None,
    writer: Optional[bool] = None,
    pictures: Optional[bool] = None,
    image_provider: Any = None,
    picture_dir: Optional[Path] = None,
    picture_reuse: Optional[dict[str, list[dict]]] = None,
    eyes: Optional[bool] = None,
    source_pictures: Optional[Path] = None,
) -> GenerateResult:
    """`writer`: writer mode (planning/writer.py) — a brief that is only a topic («История VK», «презентация про
    вторую мировую войну») gets its text written by the agent before planning (the model's text, checked against the
    topic's Wikipedia article when it is on), and the deck is built from that text as from a user's brief; None = as
    configs/writer.yaml says (on), False = never. A brief with material of its own is never touched (faithful mode).
    `pictures`: generate the pictures of the places the author described («[Место под изображение: …]», verstka/images)
    with the `t2i` role (configs/models.yaml; `image_provider` replaces it, tests); None = as configs/images.yaml says
    (on when a text-to-image model has a key), False = the places stay free. The author's own photo place never gets one.
    `picture_dir`: where the generation keeps its pictures (default out_dir/images); `picture_reuse`: strategy → the
    variant's records before this render (an edit re-renders the plan) — a place keeps its picture, no new call.
    `agent`: plan with the planning agent (planning/agent.py: analyst → designer per slide → critic → compiler);
    None = for every brief: with models the designer writes each slide, without them (or past the budget) the
    deterministic designer builds the slides the brief describes («Слайд 1…N») with their charts, tables, formulas and
    takeaways. The agent's variants that it could not plan (a brief without slide specs and no storyline — no model
    for the architect —, a deck grounding emptied) are planned as before (plan_outline, its model plan shared,
    basic_outline)."""
    if brief is None and outline is None:
        raise ValueError("either brief or outline is required")
    t0 = time.time()
    t_start = time.monotonic()  # the model budget counts from here: template analysis is part of the 5 minutes
    gen_stats: list = []  # what every model call of this generation cost (run_manifest.usage)
    out_dir = Path(out_dir)
    strategies = strategies or list(STRATEGY_NAMES)
    all_strategies = load_strategies()
    exports = exports or []

    def report(msg: str, frac: float) -> None:
        log.info(msg)
        if progress:
            progress(msg, frac)

    ta = time.time()
    manifest = analyze_template(template, workspace_root=workspace_root, providers=providers, skills=skills, use_llm=use_llm, use_vlm=use_vlm, force=force_analyze, progress=lambda s, f: report(f"analyze: {s}", 0.15 * f))
    analyze_s = round(time.time() - ta, 2)
    budget_end: Optional[float] = None
    if providers is not None:
        # brief → decks gets a fixed model budget: past it every model step takes its deterministic path, so a slow
        # or congested backend costs quality, never the 5 minutes a deck may take. It counts from the start of the
        # generation: a template analysed now (the jury's own, not cached yet) takes its time out of the same budget,
        # so analysis + planning + rendering stay inside the limit (the analysis itself is never cut: it is cached)
        budget = float(providers.limits.time_budget_s)
        budget_end = t_start + budget
        if budget >= 2 * _MIN_MODEL_BUDGET_S:
            budget_end = max(budget_end, time.monotonic() + _MIN_MODEL_BUDGET_S)
        providers = providers.with_deadline(budget_end)
        # every model call of this generation (the agent's, the planner's, the checks'): what it cost goes to usage
        providers, _ = _recording(providers, gen_stats)
    ws = TemplateWorkspace.open(manifest.template_id, workspace_root)
    result = GenerateResult(template_id=manifest.template_id, manifest=manifest)
    facts: Optional[FactsExtraction] = None
    fact_warnings: list[str] = []
    models_on = bool(use_llm and providers is not None and skills is not None and providers.has("llm"))
    use_agent = (True if agent is None else bool(agent)) and brief is not None and outline is None
    agent_result = None
    agent_raw: list = []
    agent_models: list = []
    agent_stats: list = []  # what the agent's model calls cost (the analyst's included): the run manifest
    writer_res = None
    rec = None
    if brief is not None and brief.text:
        # the agent's written text as the person edited it («Изменить»): the agent reads it with its rules line again
        from verstka.planning.writer import with_rules

        ruled = with_rules(brief.text)
        if ruled != brief.text:
            brief = brief.model_copy(update={"text": ruled})
    if use_agent:
        rec, agent_models = _recording(providers if models_on else None, agent_stats)
    if use_agent and models_on and writer is not False:
        # writer mode: a topic without material of its own gets its text written first (no plain report() here: the
        # build screen maps «plan: …» to the analyst; the writer's own events put it on «Автор»)
        writer_res = _write_text(brief, skills, rec, budget_end, progress, agent_raw, workspace_root, force=writer is True)
        if writer_res is not None:
            fact_warnings.extend(writer_res.warnings)
            if writer_res.written:
                brief = writer_res.brief
                try:
                    writer_res.write_files(out_dir)
                except OSError as e:
                    fact_warnings.append(f"writer: the text was not saved ({str(e)[:120]})")
    written = writer_res is not None and writer_res.written
    # the audit sees the writer's record: a topic whose text was not written is a skeleton, never a 100-scored success
    # (gate 4 G4-21, checks/writing.py writer_failed)
    writer_audit = writer_res.summary() if writer_res is not None else None
    if use_agent:
        from verstka.planning.agent import run_agent

        report("plan: agent", 0.15)
        try:
            # the analyst reads the brief's data per block (data_extractor), so the registry needs no model call of
            # its own here: run_agent takes the rules' figures with the analyst's series, tables and facts
            agent_result = run_agent(
                brief, manifest, [all_strategies[nm] for nm in strategies], facts=None,
                skills=skills if models_on else None, providers=rec if models_on else None, progress=_event_sink(progress), raw=agent_raw,
                written=written,
            )
        except Exception as e:  # noqa: BLE001 - the planner takes over
            log.warning("planning agent failed, the planner takes over", exc_info=True)
            fact_warnings.append(f"agent failed, the planner takes over: {str(e)[:200]}")
            agent_result = None
    agent_done = agent_result is not None and all(nm in agent_result.outlines for nm in strategies)
    if brief is not None and outline is None and not agent_done:
        # the analyst has read the brief per block (with the model when there is one): no second whole-brief call
        st = agent_result.structure if agent_result is not None else None
        facts, more = extract_facts(brief, skills if use_llm else None, providers if use_llm else None, structure=st)
        fact_warnings.extend(more)
    elif brief is not None and outline is None:
        facts = basic_facts(brief.text, structure=agent_result.structure)
    n = len(strategies)
    audit_render = bool(audit_models and use_vlm)  # the VLM checks look at slide images; deterministic ones read XML
    planned: dict[str, tuple[DeckOutline, list[str], float]] = {}
    plan_models: dict[str, Optional[str]] = {}  # strategy → the model that wrote its plan (None: the rules did)
    plan_raw: dict[str, list] = {}  # strategy → the planner's answers as the model wrote them (planner_raw.json)
    plan_end = 0.15
    agent_info: dict[str, dict] = {}
    if agent_result is not None and agent_result.outlines:
        plan_end = _AGENT_PLAN_END
        model_of_agent = next((m for m in agent_models if m), None)
        for name in strategies:
            o = agent_result.outlines.get(name)
            if o is None:
                continue
            planned[name] = (o, list(agent_result.warnings.get(name, [])), agent_result.seconds)
            plan_models[name] = model_of_agent if o.planned_by in MODEL_PLANNED else None
            plan_raw[name] = [e for e in agent_raw if not e.get("variant") or e.get("variant") == name]
            agent_info[name] = {**agent_result.summary(name), **_cost_of(agent_stats)}
    if outline is None and len(planned) < len(strategies):
        # the strategies are independent: with a model each plan is a chain of 2–3 calls (plan, fact check, repair),
        # so they run side by side and the deck waits for the slowest chain, not for the sum of them
        def _plan(name: str) -> tuple[str, DeckOutline, list[str], float]:
            tp = time.time()
            strategy = all_strategies[name]
            rec, answered = _recording(providers if use_llm else None)
            raw: list = []
            plan_raw[name] = raw
            # own copy of the facts: the deterministic planner adds the brief's table series to them
            o, w = plan_outline(brief, manifest, strategy, facts.model_copy(deep=True), skills if use_llm else None, rec, target=target_slide_count(brief, strategy), raw=raw)
            plan_models[name] = answered[0] if answered and o.planned_by in MODEL_PLANNED else None
            if agent_result is not None:
                w = list(agent_result.warnings.get(name, [])) + w  # why the agent did not plan this variant
            return name, o, w, round(time.time() - tp, 2)

        todo = [name for name in strategies if name not in planned]
        report(f"plan: {len(todo)} variants", plan_end)
        workers = min(len(todo), providers.limits.max_concurrency) if (use_llm and providers is not None and skills is not None) else 1
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                done = list(ex.map(_plan, todo))
        else:
            done = [_plan(name) for name in todo]
        planned.update({name: (o, w, sec) for name, o, w, sec in done})
        # a congested endpoint may answer one variant and not the others: the variants whose own model plan failed
        # take the model's content (reshaped for their strategy) rather than a thin plan made by the rules
        order = sorted(planned, key=lambda nm: STRATEGY_NAMES.index(nm) if nm in STRATEGY_NAMES else len(STRATEGY_NAMES))
        donor = next((nm for nm in order if planned[nm][0].planned_by in MODEL_PLANNED), None)
        if donor is not None:
            for name in todo:
                o, w, sec = planned[name]
                if o.planned_by in MODEL_PLANNED:
                    continue
                st = all_strategies[name]
                aw: list[str] = []
                adapted = adapt_outline(planned[donor][0], st, manifest, target_slide_count(brief, st), hard_limit=bool(brief.slide_count), brief=brief, warnings=aw)
                planned[name] = (adapted, w + [f"own model plan failed: the model plan of «{donor}» adapted to «{name}»"] + aw, sec)
                plan_models[name] = plan_models.get(donor)
        _say_designs(progress, {name: planned[name][0] for name in todo}, plan_end)
    pic_dir = Path(picture_dir) if picture_dir is not None else out_dir / "images"
    # «Улучшить презентацию»: the pictures of the original deck go back to their places (ingest/deck_text.py)
    from verstka.ingest.deck_text import source_records

    # (`source_pictures`: the original deck's workspace when it is laid out in another template)
    src_pictures = source_records(Path(source_pictures) if source_pictures else ws.dir, pic_dir)
    if src_pictures:
        picture_reuse = {name: [*(picture_reuse or {}).get(name, []), *src_pictures] for name in strategies}
    maker, icfg = _picture_maker(pictures, image_provider, manifest, pic_dir, t_start, skills if models_on else None, providers if models_on else None, brief, outline, planned)
    pending: list[dict] = []
    said_pictures: set = set()  # the timeline tells each place once, not once per variant
    from verstka.audit.eyes import load_config as eyes_config, look as look_at_slides

    eyes_cfg = eyes_config()
    eyes_on = bool(audit and eyes is not False and eyes_cfg.get("enabled", True) and use_vlm and providers is not None and skills is not None and providers.has("vlm"))
    eyes_seen: dict[str, dict] = {}
    # the variants differ in the template slides they show too: each one knows which samples the earlier ones took
    # for the same slide (matching/matcher.py `taken`)
    taken: dict[str, set[str]] = {}

    def _close_variant(v: dict, look: bool) -> dict:
        """The variant's last steps before its pictures are put in: «Взгляд дизайнера» (audit/eyes.py) when `look`, the
        machine markers off the notes, the picture places read and their pictures asked for."""
        name, vdir = v["name"], v["vdir"]
        if look:
            tey = time.time()
            report(f"{name}: design review", v["share"])
            sink = _event_sink(progress)
            from verstka.planning.agent import event_message

            def say(message: str, slide: Optional[int] = None, fix: Optional[str] = None) -> None:
                sink({"type": "agent", "step": "eyes", "message": event_message(message, slide), "slide": slide, "variant": name, "share": v["share"], **({"fix": fix} if fix else {})})

            try:
                v["audit"], v["plan"], v["outline"], rr, looked = look_at_slides(
                    vdir, v["audit"], v["outline"], v["plan"], manifest, ws, providers=providers, skills=skills, deadline=budget_end, others=v["others"],
                    brief_text=brief.text if brief else None, writer=writer_audit, emit=say, cfg=eyes_cfg,
                )
                if rr is not None:
                    v["render"] = rr
                eyes_seen[name] = looked.summary()
            except Exception as e:  # noqa: BLE001 - the deck stays as the deterministic steps made it
                log.warning("design review failed on %s", name, exc_info=True)
                v["warnings"].append(f"design review failed: {str(e)[:160]}")
            v["timings"]["eyes"] = round(time.time() - tey, 2)
        try:
            from verstka.rendering.renderer import strip_outline_marks

            strip_outline_marks(vdir / "deck.pptx")  # the presenter's notes without the machine markers
        except Exception:  # noqa: BLE001 - the markers stay rather than the deck being lost
            log.warning("outline markers left in the notes", exc_info=True)
        try:
            from verstka.images.fill import plan_pictures

            v["pictures"] = plan_pictures(vdir / "deck.pptx", v["outline"], maker, enabled=maker is not None, reuse=(picture_reuse or {}).get(name), folder=pic_dir)
            if any(p.future is not None for p in v["pictures"]):
                report(f"{name}: pictures for {sum(1 for p in v['pictures'] if p.future is not None)} slides", v["pic_share"])
            _say_pictures(progress, name, v["pictures"], said_pictures, v["pic_share"], maker)
        except Exception as e:  # noqa: BLE001 - the deck stays as rendered, its places free
            log.warning("picture places not read", exc_info=True)
            v["warnings"].append(f"pictures: the places were not read ({str(e)[:120]})")
        return v

    eyes_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="eyes") if eyes_on else None
    eyes_jobs: list = []
    for i, name in enumerate(strategies):
        strategy: Strategy = all_strategies[name]
        ts = time.time()
        timings: dict[str, float] = {"analyze": analyze_s}
        vdir = out_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        warnings = list(fact_warnings)
        base = plan_end + (0.85 - plan_end) * i / n
        span = (0.85 - plan_end) / n
        if outline is not None:
            v_outline = outline.model_copy(deep=True)
            v_outline.strategy = name
            timings["plan"] = 0.0
        else:
            v_outline, w, timings["plan"] = planned[name]
            warnings.extend(w)
            if written:
                v_outline = _mark_written(v_outline, writer_res)
        taken0 = {k: set(v) for k, v in taken.items()}
        outline0 = v_outline.model_copy(deep=True)
        plan = match_outline(v_outline, manifest, strategy, ws=ws, taken=taken)
        report(f"{name}: planned {len(v_outline.slides)} slides, rendering", base + span * 0.2)
        tr = time.time()
        render = render_deck(v_outline, plan, manifest, ws, vdir / "deck.pptx", progress=lambda s, f: report(f"{name}: {s}", base + span * (0.2 + 0.4 * f)), shown=taken0)
        if render.failed_samples:
            # a sample that read badly on its slide (`clone_check.content_trouble`) kept its place in the deck-level
            # choice: its neighbours gave it up and the slide itself fell back to its first alternatives. The samples
            # are chosen again without it and the deck rendered again — kept when it stands on more template slides
            retry = _rematched(outline0, manifest, strategy, ws, taken0, render, vdir)
            if retry is not None:
                v_outline, plan, render, taken = retry
        timings["render"] = round(time.time() - tr, 2)
        warnings.extend(render.warnings)
        audit_report: Optional[AuditReport] = None
        if audit:
            tau = time.time()
            report(f"{name}: audit", base + span * 0.65)
            audit_report = run_audit(vdir / "deck.pptx", manifest, v_outline, ws, providers=providers if audit_models else None, skills=skills if audit_models else None, use_vlm=audit_models and use_vlm, use_llm=audit_models and use_llm, render=audit_render, images_dir=vdir / "slides", strategy=name, brief_text=brief.text if brief else None, writer=writer_audit)
            if autofix and audit_report.summary.errors + audit_report.summary.warnings > 0:
                report(f"{name}: autofix ({audit_report.summary.errors} errors)", base + span * 0.8)
                audit_report, plan, v_outline, rr = autofix_loop(vdir / "deck.pptx", audit_report, v_outline, plan, manifest, ws, providers=providers, skills=skills, use_models=audit_models, images_dir=vdir / "slides", render=audit_render, brief_text=brief.text if brief else None, writer=writer_audit, others=taken0)
                if rr is not None:
                    render = rr
            timings["audit"] = round(time.time() - tau, 2)
        # the variants after this one know what it SHOWS on each slide — the sample a fallback or the autofix put
        # there, nothing for a slide composed — not what it planned (three variants converged on one sample)
        taken = _shown_samples(taken0, v_outline, render)
        v = {"name": name, "ts": ts, "timings": timings, "vdir": vdir, "warnings": warnings, "outline": v_outline, "plan": plan, "render": render, "audit": audit_report, "pictures": [],
             "share": base + span * 0.85, "pic_share": base + span * 0.95, "others": taken0}
        if eyes_on and audit_report is not None:
            # «Взгляд дизайнера» looks at this variant while the next one is laid out: its model calls and LibreOffice
            # wait on the network and a subprocess, the next variant's render on the CPU
            eyes_jobs.append(eyes_pool.submit(_close_variant, v, True))
        else:
            _close_variant(v, False)
        pending.append(v)

    for job in eyes_jobs:
        job.result()  # (each one catches its own failure: the variant keeps its deck as laid out)
    if eyes_pool is not None:
        eyes_pool.shutdown(wait=True)
    # the pictures in their places (each waited for at most until the generation's picture budget ends), the decks
    # that got one audited again (the deterministic checks: the picture stands where its place stood)
    if any(v["pictures"] for v in pending):
        report("pictures: putting them in", 0.855)
    for v in pending:
        if not v["pictures"]:
            continue
        tp = time.time()
        try:
            from verstka.images.fill import apply_pictures, write_records

            left = (maker.deadline - time.monotonic()) if maker is not None and maker.deadline is not None else 0.0
            applied = apply_pictures(v["vdir"] / "deck.pptx", v["pictures"], wait_s=max(0.0, min(float(icfg.get("wait_s", 75)), left)), cfg=icfg)
            write_records(v["vdir"], applied.records)
        except Exception as e:  # noqa: BLE001
            log.warning("pictures not put in", exc_info=True)
            v["warnings"].append(f"pictures: not put in ({str(e)[:120]})")
            continue
        v["warnings"].extend(applied.warnings)
        v["picture_records"] = applied.records
        _say_pictures_made(progress, v["name"], applied.records, said_pictures)
        if applied.changed:
            v["pictures_changed"] = True
            if v["audit"] is not None:
                try:
                    v["audit"] = _audit_with_pictures(v, manifest, ws, brief, writer_audit)
                except Exception:  # noqa: BLE001 - the report before the pictures stays
                    log.warning("audit after the pictures failed", exc_info=True)
        v["timings"]["pictures"] = round(time.time() - tp, 2)
    if maker is not None:
        maker.close()

    # LibreOffice once per deck, all decks at once: the PDF export and the slide previews come from the same PDF
    report("export: pdf, html, slide previews", 0.86)

    def _finish(v: dict) -> dict:
        te = time.time()
        want_images = (render_images or audit) and (v.get("pictures_changed") or not (v["audit"] is not None and v["audit"].slide_images))
        v["exports"], v["images"], w, v["render_ok"] = render_outputs(v["vdir"], manifest, v["outline"].title, exports, images=want_images)
        v["warnings"].extend(w)
        if not want_images and v["audit"] is not None:
            v["images"] = [Path(p) for _, p in sorted(v["audit"].slide_images.items())]
        v["timings"]["export"] = round(time.time() - te, 2)
        return v

    workers = min(len(pending), 3) or 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            finished = list(ex.map(_finish, pending))
    else:
        finished = [_finish(v) for v in pending]

    for v in finished:
        name, vdir, audit_report = v["name"], v["vdir"], v["audit"]
        if audit_report is not None:
            if v["images"]:
                audit_report.slide_images = {k: str(p) for k, p in enumerate(v["images"], 1)}
            if v["render_ok"] is False:
                audit_report.issues.append(Issue(id="file_opens-0-render", slide=0, check_id="file_opens", severity="warn", kind="deterministic", message="LibreOffice не смог отрендерить файл"))
                audit_report.recompute()
            (vdir / "audit_report.json").write_text(audit_report.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "outline.json").write_text(v["outline"].model_dump_json(indent=2), encoding="utf-8")
        (vdir / "layout_plan.json").write_text(v["plan"].model_dump_json(indent=2), encoding="utf-8")
        if plan_raw.get(name):
            # the planner's own answer (before grounding and validation): what the model wrote, for the audit trail
            (vdir / "planner_raw.json").write_text(json.dumps({"strategy": name, "answers": plan_raw[name]}, ensure_ascii=False, indent=2), encoding="utf-8")
        export_paths = {"pptx": vdir / "deck.pptx", **v["exports"]}
        timings = v["timings"]
        vr = VariantResult(strategy=name, out_dir=vdir, outline=v["outline"], plan=v["plan"], render=v["render"], images=v["images"], warnings=v["warnings"], seconds=round(time.time() - v["ts"], 2), audit=audit_report, exports=export_paths, timings=timings)
        timings["total"] = vr.seconds
        vr.planner = {"planned_by": v["outline"].planned_by, "model": plan_models.get(name)}
        if name in agent_info and v["outline"].planned_by in ("agent", "rules"):
            vr.planner["agent"] = agent_info[name]  # the planning agent's own plan (not another variant's, shared)
        if outline is not None:
            vr.planner["supplied"] = True  # the plan came with the request: no model was asked to plan it
        if written:
            # the deck was built from the writer's text (a topic the writer did not write — private, refused, failed — is
            # built as before; its record is writer.json of the generation and the generation's `writer`)
            vr.planner["writer"] = writer_res.summary()
        slides_info = [{"index": s.index, "outline_id": s.outline_id, "mode": s.mode, "pattern_id": s.pattern_id, "composition": s.composition, "warnings": s.warnings} for s in v["render"].slides]
        rm = build_run_manifest(
            template_id=manifest.template_id,
            template_file=manifest.source_file,
            strategy=name,
            brief_hash=_sha(brief.text) if brief else None,
            outline_hash=_sha(v["outline"].model_dump_json()),
            skills=skills,
            providers=providers,
            timings=timings,
            applied_fixes=audit_report.applied_fixes if audit_report else [],
            audit_summary=audit_report.summary.model_dump() if audit_report else {},
            slides=slides_info,
            usage=_usage_of(gen_stats),
            extra={"warnings": v["warnings"], "exports": {k: str(p) for k, p in export_paths.items()}, "planner": vr.planner, **_pictures_extra(v), **({"eyes": eyes_seen[name]} if name in eyes_seen else {})},
        )
        write_run_manifest(vdir / "run_manifest.json", rm)
        result.variants.append(vr)
        report(f"{name}: done in {vr.seconds}s", 0.86 + 0.14 * len(result.variants) / n)
    result.writer = writer_res
    if writer_res is not None and not writer_res.written:
        try:
            writer_res.write_files(out_dir)  # why no text was written (private, refused, the model failed): the audit trail
        except OSError:
            log.debug("writer.json not written", exc_info=True)
    result.seconds = round(time.time() - t0, 2)
    return result


def _picture_maker(pictures: Optional[bool], image_provider, manifest: TemplateManifest, folder: Path, t_start: float, skills, providers, brief: Optional[Brief], outline: Optional[DeckOutline], planned: dict):
    """The generation's ImageMaker (verstka/images), or None: pictures off, no t2i model, every link without a key."""
    from verstka.images.prompt import load_config

    icfg = load_config()
    if pictures is False or (pictures is None and not icfg.get("enabled", True)):
        return None, icfg
    chain = image_provider
    if chain is None:
        from verstka.images.providers import load_image_provider

        chain = load_image_provider()
    if chain is None or getattr(chain, "off", False):
        return None, icfg
    from verstka.images.service import ImageMaker

    title = (outline.title if outline is not None else None) or next((o.title for o, _, _ in planned.values() if o.title), None) or (brief.title_hint if brief else None) or ""
    deadline = t_start + float(icfg.get("budget_s", 240))
    return ImageMaker(chain, manifest, folder, cfg=icfg, skills=skills, providers=providers, deadline=deadline, deck_title=title), icfg


def _short(text: str, n: int = 90) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def _say_pictures(progress: Optional[ProgressFn], name: str, pics: list, said: set, share: float, maker) -> None:
    """The layout step's lines about the picture places (once per place, whatever the variant): a picture asked by its
    description, the author's own photo place left free."""
    sink = _event_sink(progress)
    model = getattr(getattr(maker, "provider", None), "label", None) if maker is not None else None
    for p in pics:
        k = ("ask", p.place.hint or p.place.label, p.place.slide)
        if k in said:
            continue
        said.add(k)
        if p.future is not None:
            text = f"Вёрстка: слайд {p.place.slide} — рисую изображение по описанию автора «{_short(p.place.hint or p.place.label)}»" + (f", модель {model}." if model else ".")
        elif p.place.own:
            text = f"Вёрстка: слайд {p.place.slide} — место под ваше фото оставлено свободным, как просили в тексте."
        else:
            continue
        sink({"type": "agent", "step": "compile", "message": text, "slide": p.place.slide, "variant": name, "share": share})


def _say_pictures_made(progress: Optional[ProgressFn], name: str, records: list[dict], said: set) -> None:
    sink = _event_sink(progress)
    for r in records:
        if r.get("status") == "generated" and r.get("model") == "original":
            k = ("made", r.get("hint") or r.get("label"), r.get("slide"))
            text = f"Вёрстка: слайд {r.get('slide')} — изображение из исходной презентации на месте."
        elif r.get("status") == "generated":
            k = ("made", r.get("hint") or r.get("label"), r.get("slide"))
            text = f"Вёрстка: слайд {r.get('slide')} — изображение на месте, в палитре шаблона" + (f" ({round(float(r['palette_match']) * 100)}% цветов)." if r.get("palette_match") is not None else ".")
        elif r.get("error") or (r.get("why") and r.get("why") not in ("место под ваше фото — вставьте его в PowerPoint", "генерация изображений выключена")):
            k = ("free", r.get("hint") or r.get("label"), r.get("slide"))
            text = f"Вёрстка: слайд {r.get('slide')} — место под изображение осталось свободным: {r.get('why')}."
        else:
            continue
        if k in said:
            continue
        said.add(k)
        sink({"type": "agent", "step": "compile", "message": text, "slide": r.get("slide"), "variant": name, "share": 0.855})


def _audit_with_pictures(v: dict, manifest: TemplateManifest, ws: TemplateWorkspace, brief: Optional[Brief], writer_audit) -> AuditReport:
    """The deck with its pictures audited again by the deterministic checks; the fixes applied and the model's own
    remarks (made on the deck before the pictures) carry over."""
    old: AuditReport = v["audit"]
    new = run_audit(v["vdir"] / "deck.pptx", manifest, v["outline"], ws, providers=None, skills=None, use_vlm=False, use_llm=False, render=False, strategy=v["name"], brief_text=brief.text if brief else None, writer=writer_audit)
    new.issues.extend(i for i in old.issues if i.kind == "model")
    new.applied_fixes = list(old.applied_fixes)
    new.iterations = old.iterations
    new.recompute()
    return new


def _usage_of(stats: list) -> dict:
    """The generation's model calls so far (all variants share them: the plan, the checks): calls, HTTP requests,
    tokens, failed calls, rubles (Polza's usage.cost_rub), by skill. Pictures cost in `pictures.cost_rub`."""
    if not stats:
        return {}
    t = call_totals(list(stats))
    return {"scope": "generation", **t}


def _pictures_extra(v: dict) -> dict:
    recs = v.get("picture_records")
    if not recs:
        return {}
    from verstka.images.fill import summary

    return {"pictures": summary(recs)}


def _write_text(brief: Brief, skills, providers, budget_end: Optional[float], progress: Optional[ProgressFn], raw: list, workspace_root, *, force: bool = False):
    """Writer mode's phase (planning/writer.py) when the brief is a topic: None when writer mode does not apply (a
    brief with material, the writer switched off). Never raises: a failure is a result the pipeline builds around (the
    skeleton or the user's own text, as before)."""
    from verstka.ingest.workspace import default_workspace_root
    from verstka.planning.writer import load_config, write_deck, writer_mode

    try:
        cfg = load_config()
        if not (cfg.get("enabled", True) or force):
            return None
        mode = writer_mode(brief)
        if mode.kind == "off":
            return None
        root = Path(workspace_root) if workspace_root else default_workspace_root()
        return write_deck(
            brief, mode, skills, providers, budget_end=budget_end, progress=_event_sink(progress), raw=raw,
            cache_dir=root / "cache" / "reference", config=cfg,
        )
    except Exception:  # noqa: BLE001 - the writer never stops the deck: the brief is built as it is
        log.warning("writer mode failed, the brief is built as it is", exc_info=True)
        return None


def _mark_written(o: DeckOutline, res) -> DeckOutline:
    """A deck built from the writer's text: the agent's log starts with the writer's lines («Автор: …») and the first
    slide's notes name the source («Текст написан агентом Verstka по статье «…» из Википедии…»)."""
    from verstka.planning.writer import attribution

    o = o.model_copy(deep=True)
    if res.log_lines and not any(str(x).startswith("Автор:") for x in o.agent_log[:1]):
        o.agent_log = list(res.log_lines) + list(o.agent_log)
    line = attribution(res)
    if o.slides and line not in (o.slides[0].notes or ""):
        notes = (o.slides[0].notes or "").strip()
        o.slides[0].notes = f"{notes}\n\n{line}" if notes else line
    return o
