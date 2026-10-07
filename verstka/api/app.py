"""Verstka HTTP API."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from verstka import __version__
from verstka.api.agent_view import describe_agent_work, describe_slide_design, job_progress, link_alternatives, read_agent_events, slide_design, variant_agent, write_agent_file
from verstka.api.jobs import Job, JobRunner
from verstka.api.model_status import ChainContext, active_chain_context, config_label, generation_planner, models_status, planner_info
from verstka.api.narrator import describe_audit, describe_plan, describe_slide_choice, describe_template
from verstka.api.store import SAFE_ID_RE, Store
from verstka.ingest.workspace import file_sha256
from verstka.planning.brief import normalize_purpose, parse_brief_text
from verstka.planning.strategies import STRATEGY_NAMES, load_strategies
from verstka.ru import ru_count
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.audit import AuditReport
from verstka.schemas.layout import LayoutPlan
from verstka.schemas.template import TemplateManifest
from verstka.schemas.outline import Brief, DeckOutline
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"  # Vite dev server; the built UI is same-origin
_UPLOAD_CHUNK = 1 << 20
_MAX_CHAT_SESSIONS = 500


def cors_origins() -> list[str]:
    raw = os.environ.get("VERSTKA_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_upload_bytes() -> int:
    try:
        mb = float(os.environ.get("VERSTKA_MAX_UPLOAD_MB", "200"))
    except ValueError:
        mb = 200.0
    return int(mb * 1024 * 1024)


app = FastAPI(title="Verstka API", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["*"], allow_headers=["*"])
store = Store()
runner = JobRunner()
_providers: Optional[ProviderRegistry] = None
_skills: Optional[SkillsRegistry] = None
_chat_sessions: dict[str, dict] = {}
_chat_lock = threading.Lock()
_fix_active: set[tuple[str, str]] = set()  # (generation id, strategy) with an autofix job or an edit in flight
_fix_lock = threading.Lock()
_VARIANT_BUSY = "Этот вариант уже меняется — дождитесь, пока агент закончит"


def providers() -> Optional[ProviderRegistry]:
    global _providers
    if _providers is None:
        from verstka.providers.registry import default_models_path

        path = default_models_path()
        try:
            _providers = ProviderRegistry.from_yaml(path)
        except Exception as e:  # noqa: BLE001
            log.warning("providers unavailable: %s", e)
            return None
    return _providers


def models_configured() -> bool:
    p = providers()
    if p is None:
        return False
    try:
        llm = p.get("llm")
        return llm.name == "mock" or bool(getattr(llm, "api_key", ""))
    except Exception:  # noqa: BLE001
        return False


def _chain_ctx() -> ChainContext:
    """The active model chain (the advice under a deck depends on it)."""
    from verstka.providers.registry import default_models_path

    return active_chain_context(providers(), config=config_label(default_models_path(), _REPO_ROOT))


def skills() -> SkillsRegistry:
    global _skills
    if _skills is None:
        _skills = SkillsRegistry.load()
    return _skills


# ---------------------------------------------------------------------------- schemas


class GenerateRequest(BaseModel):
    template_id: str
    brief: Optional[str] = None
    outline: Optional[dict] = None
    audience: Optional[str] = None
    purpose: Optional[str] = None
    slides: Optional[int] = None
    language: str = "ru"
    extra_instructions: Optional[str] = None
    strategies: list[str] = Field(default_factory=lambda: list(STRATEGY_NAMES))
    use_models: bool = True
    audit_models: bool = False
    autofix: bool = True
    exports: list[str] = Field(default_factory=lambda: ["pdf", "html"])
    # «Генерировать изображения»: the places the author described get pictures (verstka/images); None — the config
    # (on when a text-to-image model has a key), False — the places stay free
    pictures: Optional[bool] = None
    # «Взгляд дизайнера» (verstka/audit/eyes.py): the vision model looks at the finished slides and the slides it sends
    # back are laid out again. None — with the text model (use_models); True — on its own too (an improved deck keeps
    # its author's text as written, the model still looks at the slides)
    eyes: Optional[bool] = None
    # «Улучшить презентацию»: what the original deck was (its name, slides and audit), for «было → стало»
    improved_from: Optional[dict] = None


class PictureBody(BaseModel):
    """«Заменить изображение» on slide n: a new picture (on the person's `wish`) or the free place back («remove»)."""

    wish: Optional[str] = Field(default=None, max_length=600)
    action: Literal["generate", "remove"] = "generate"


class FixRequest(BaseModel):
    issue_ids: list[str] = Field(default_factory=list)
    all_deterministic: bool = False


class ChatRequest(BaseModel):
    session_id: str
    message: str
    template_id: Optional[str] = None
    generation_id: Optional[str] = None
    strategy: Optional[str] = None  # the variant on screen: «почему слайд 3 такой» is about it
    slide: Optional[int] = None  # the slide on screen: «сделай тут цифры крупнее» is about it


class EditRequestBody(BaseModel):
    message: str  # what the person asks, in their words: «на слайде 3 покажи расходы таблицей»
    slide: Optional[int] = None  # the slide on screen (1-based)


class SlideFixBody(BaseModel):
    wishes: Optional[str] = Field(None, max_length=500)  # what the person wants of the fixed slide: «покажи этапами»
    issue_ids: Optional[list[str]] = None  # the remarks to fix (default: every remark the stage shows on the slide)


# ---------------------------------------------------------------------------- helpers


def _validation_message(e: ValidationError, limit: int = 5) -> str:
    errors = e.errors()
    parts = []
    for err in errors[:limit]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    more = len(errors) - limit
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")


def _serve_file(base: Path, rel: str, **kwargs) -> FileResponse:
    """Serve `base/rel` only if it resolves to a regular file inside `base`."""
    base = base.resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(target, **kwargs)


def _variant_dir(gid: str, strategy: str) -> Path:
    gdir = store.generation_dir(gid)
    if gdir is None or strategy not in STRATEGY_NAMES:
        raise HTTPException(404, "Не найдено")
    return gdir / strategy


def _brief_from_request(req: GenerateRequest) -> Brief:
    """Parse the brief text (YAML front matter, «не более N слайдов», title) and let explicit request fields override it."""
    brief = parse_brief_text(req.brief or "")
    if req.audience is not None:
        brief.audience = req.audience
    if req.purpose is not None:
        brief.purpose = normalize_purpose(req.purpose)
    if req.slides is not None:
        brief.slide_count = req.slides
    if req.extra_instructions is not None:
        brief.extra_instructions = req.extra_instructions
    if "language" not in brief.model_fields_set and req.language:
        brief.language = req.language
    return brief


def _discard_failed_upload(path: Path) -> None:
    """After a failed analysis: drop the upload and the template directory it created (unless an older analysis lives there)."""
    try:
        if path.exists():
            tdir = store.root / "templates" / file_sha256(path)[:16]
            if tdir.is_dir() and not (tdir / "manifest.json").exists():
                shutil.rmtree(tdir, ignore_errors=True)
    except OSError as e:
        log.warning("cleanup after failed analysis: %s", e)
    path.unlink(missing_ok=True)
    if path.parent != store.uploads and not any(path.parent.iterdir()):
        path.parent.rmdir()


def _variant_payload(gdir: Path, strategy: str, use_models: Optional[bool] = None, ctx: Optional[ChainContext] = None, supplied: bool = False, agent_events: Optional[list[dict]] = None) -> Optional[dict]:
    vdir = gdir / strategy
    if not (vdir / "deck.pptx").exists():
        return None
    outline = json.loads((vdir / "outline.json").read_text(encoding="utf-8")) if (vdir / "outline.json").exists() else None
    plan = json.loads((vdir / "layout_plan.json").read_text(encoding="utf-8")) if (vdir / "layout_plan.json").exists() else None
    audit = json.loads((vdir / "audit_report.json").read_text(encoding="utf-8")) if (vdir / "audit_report.json").exists() else None
    run_manifest = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8")) if (vdir / "run_manifest.json").exists() else None
    slides = sorted((vdir / "slides").glob("slide-*.jpg")) if (vdir / "slides").is_dir() else []
    gid = gdir.name
    files = {name: f"/api/generations/{gid}/{strategy}/files/{name}" for name in ("deck.pptx", "deck.pdf", "deck.html") if (vdir / name).exists()}
    edits = _edits_of(vdir)
    return {
        "strategy": strategy,
        "planner": planner_info(outline, run_manifest, use_models=use_models, ctx=ctx, supplied=supplied),
        "outline": outline,
        "plan": plan,
        "audit": audit,
        "run_manifest": run_manifest,
        "slides": [f"/api/generations/{gid}/{strategy}/slides/{p.name}" for p in slides],
        "files": files,
        # Agent v2: what the agent did (its log, the timeline the build screen showed, the critic's notes) and, per
        # slide, why the designer chose the form and what else it proposed — empty for older runs
        "agent": _current_agent(outline, agent_events if agent_events is not None else read_agent_events(gdir), strategy, edits),
        "design": slide_design(outline),
        # the chat agent's edits of this variant (pipeline/revise.py): what was asked and answered, oldest first; the
        # count versions the slide previews (their names stay slide-001.jpg…)
        "edits": [{k: e.get(k) for k in ("at", "request", "reply", "kind", "slides", "score_before", "score_after", "fixed", "how", "version", "undo_of", "wish", "action")} for e in edits],
        # the pictures inside the slides and the places kept for them (verstka/images): what each shows, by which model
        "pictures": _pictures_of(vdir),
        # «Взгляд дизайнера» (audit/eyes.py): what the vision model saw on which slide, the slides it laid out again —
        # the slide before and after — and the ones that kept their layout; None when the review did not run
        "eyes": _eyes_of(vdir, run_manifest, outline, gid, strategy, edits),
    }


def _eyes_of(vdir: Path, run_manifest: Optional[dict], outline: Optional[dict], gid: str, strategy: str, edits: list[dict]) -> Optional[dict]:
    """The review of the variant for the result screen, by the slides' current numbers (an edit may have added or taken
    slides away since the build). The pictures of a slide redesigned since the build are not its pictures any more."""
    from verstka.audit.eyes import CODES

    eyes = (run_manifest or {}).get("eyes")
    if not isinstance(eyes, dict):
        return None
    order = {s.get("id"): k for k, s in enumerate((outline or {}).get("slides") or [], 1)}
    redone = _redone_slides(edits)
    fixed = {f.get("outline_id"): f for f in eyes.get("fixed") or [] if isinstance(f, dict)}
    kept = {k.get("outline_id"): k for k in eyes.get("kept") or [] if isinstance(k, dict)}

    def picture(stage: str, n: Any) -> Optional[str]:
        name = f"slide-{int(n):03d}.jpg" if isinstance(n, int) else ""
        return f"/api/generations/{gid}/{strategy}/eyes/{stage}/{name}" if name and (vdir / "eyes" / stage / name).is_file() else None

    slides = []
    for f in eyes.get("flagged") or []:
        if not isinstance(f, dict):
            continue
        oid, then = f.get("outline_id"), f.get("slide")
        now = order.get(oid)
        if now is None:
            continue  # the slide is gone
        problems = [
            {"code": p.get("code"), "label": CODES.get(p.get("code"), p.get("code")), "severity": p.get("severity"), "where": p.get("where") or "", "evidence": p.get("evidence") or ""}
            for p in f.get("problems") or [] if isinstance(p, dict)
        ]
        status = "fixed" if oid in fixed else "kept" if oid in kept else "seen"
        fresh = now not in redone
        slides.append({
            "outline_id": oid, "slide": now, "status": status, "problems": problems,
            "reason": (fixed.get(oid) or {}).get("reason") or (kept.get(oid) or {}).get("why") or "",
            "before": picture("before", then) if fresh and status == "fixed" else None,
            "after": picture("after", then) if fresh and status == "fixed" else None,
            "redone": not fresh,
        })
    slides.sort(key=lambda x: x["slide"])
    return {"looked": eyes.get("looked") or 0, "seconds": eyes.get("seconds"), "skipped": eyes.get("skipped"), "slides": slides}


def _pictures_of(vdir: Path) -> list[dict]:
    from verstka.images.fill import public_records, read_records

    return public_records(read_records(vdir))


def _edits_of(vdir: Path) -> list[dict]:
    from verstka.pipeline.revise import read_edits

    return read_edits(vdir)


def _redone_slides(edits: list[dict]) -> set[int]:
    """The slides redesigned or fixed since the build by an edit that is still in place (not undone): the critic's
    notes of the build are about their previous version."""
    active: dict[Any, dict] = {}
    for e in edits:
        if e.get("undo_of") is not None:
            active.pop(e.get("undo_of"), None)
        elif e.get("version") is not None:
            active[e.get("version")] = e
    return {int(n) for e in active.values() if e.get("kind") in ("fix", "slide") for n in (e.get("slides") or []) if isinstance(n, int)}


def _current_agent(outline: Optional[dict], events: list[dict], strategy: str, edits: list[dict]) -> dict:
    """variant_agent without the critic's notes of the slides redone since the build."""
    agent = variant_agent(outline, events, strategy)
    redone = _redone_slides(edits)
    if redone:
        agent["critic"] = [e for e in agent["critic"] if e.get("slide") not in redone]
    return agent


INTERRUPTED = "Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз"


def _settle_orphan(meta: dict) -> dict:
    """A build whose job this server does not run (started before a restart) is not being built any more: it ends as
    failed, so the list and the deck page stop showing it as in progress and its template can be deleted again. A
    build that has no job id yet is a few milliseconds old (create_generation writes the meta, then submits)."""
    if meta.get("status") != "running":
        return meta
    jid = meta.get("job_id")
    if jid and runner.get(str(jid)) is not None:
        return meta
    if not jid and time.time() - float(meta.get("created_at") or 0) < 60:
        return meta
    gid = str(meta.get("id") or "")
    done = {"status": "failed", "error": INTERRUPTED}
    return (store.merge_generation_meta(gid, done) if SAFE_ID_RE.fullmatch(gid) else None) or {**meta, **done}


def _generation_payload(gid: str) -> dict:
    gdir = store.generation_dir(gid)
    if gdir is None:
        raise HTTPException(404, "Презентация не найдена")
    meta = _settle_orphan(store.read_generation_meta(gid) or {"id": gid})
    use_models = meta.get("use_models")
    supplied = bool(meta.get("outline_supplied"))
    ctx = _chain_ctx()
    events = read_agent_events(gdir)
    variants = [v for s in meta.get("strategies", list(STRATEGY_NAMES)) if (v := _variant_payload(gdir, s, use_models, ctx, supplied, events))]
    link_alternatives(variants)
    # who planned the decks and, if no model did, why — derived from the variants' warnings, so older runs get it too
    planner = generation_planner(variants, use_models=use_models, supplied=supplied) if variants else meta.get("planner")
    return {**meta, "planner": planner, "variants": variants}


def _run_generation(gid: str, gdir: Path, req: GenerateRequest, job: Job) -> dict:
    from verstka.pipeline.generate import generate_variants

    manifest = store.manifest(req.template_id)
    if manifest is None:
        raise ValueError("Шаблон ещё не разобран — загрузите его снова")
    brief = None
    outline = None
    if req.outline is not None:
        outline = DeckOutline.model_validate(req.outline)
    else:
        brief = _brief_from_request(req)
    # «Модель пишет тексты слайдов» off: the user's own text, laid out as written (planning/faithful.py) — no model
    # plans or rewrites it; «Модель проверяет слайды по картинке» is a switch of its own
    use_models = req.use_models and models_configured()
    audit_models = req.audit_models and models_configured()
    eyes = bool(req.use_models if req.eyes is None else req.eyes) and models_configured()
    # «Улучшить готовую» laid out in another template: the original deck's pictures come from its own workspace
    source_pictures = None
    src_tid = (req.improved_from or {}).get("template_id")
    if src_tid and src_tid != req.template_id:
        try:
            source_pictures = store.workspace(str(src_tid)).dir
        except FileNotFoundError:
            source_pictures = None
    res = generate_variants(
        store.workspace(req.template_id).source,
        brief=brief,
        outline=outline,
        strategies=req.strategies,
        out_dir=gdir,
        workspace_root=store.root,
        providers=providers() if (use_models or audit_models or eyes) else None,
        skills=skills() if (use_models or audit_models or eyes) else None,
        use_llm=use_models,
        use_vlm=use_models or audit_models or eyes,
        eyes=eyes,
        source_pictures=source_pictures,
        audit=True,
        autofix=req.autofix,
        audit_models=audit_models,
        exports=req.exports,
        # plain progress messages and the planning agent's step events (the live timeline of the build screen)
        progress=job_progress(job),
        pictures=req.pictures,
        image_provider=image_provider() if req.pictures is not False else None,
    )
    write_agent_file(gdir, job.agent_events())
    planners = {}
    supplied = req.outline is not None  # the plan came with the request: no model was asked to plan
    ctx = _chain_ctx()
    for v in res.variants:
        rm = {"planner": v.planner, "warnings": v.warnings, "providers": providers().describe() if use_models and providers() else {}}
        planners[v.strategy] = planner_info(v.outline.model_dump(mode="json"), rm, use_models=use_models, ctx=ctx, supplied=supplied)
    first_outline = res.variants[0].outline if res.variants else None
    meta = {
        "id": gid,
        "template_id": req.template_id,
        "template_file": manifest.source_file,
        # the deck's title for «Мои презентации» (older runs have none: the UI falls back to the brief's first line)
        "title": (getattr(first_outline, "title", None) or None) if first_outline is not None else None,
        "strategies": req.strategies,
        "brief": req.brief,
        "audience": req.audience,
        "purpose": req.purpose,
        "slides": req.slides,
        "use_models": use_models,
        **_request_options(req),
        "seconds": res.seconds,
        "created_at": gdir.stat().st_mtime,
        "status": "done",
        "job_id": job.id,
        "summary": {
            v.strategy: {
                "n_slides": len(v.outline.slides), "score": v.audit.summary.score if v.audit else None, "errors": v.audit.summary.errors if v.audit else None, "warnings": v.audit.summary.warnings if v.audit else None, "seconds": v.seconds,
                # which model planned the variant and, when the built-in planner did, why (plain Russian)
                "planned_by": planners[v.strategy]["planned_by"], "model": planners[v.strategy]["model"], "model_label": planners[v.strategy]["model_label"],
                "reason_code": planners[v.strategy]["reason_code"], "reason": planners[v.strategy]["reason"],
            }
            for v in res.variants
        },
        "planner": generation_planner([{"planner": planners[v.strategy]} for v in res.variants], use_models=use_models, supplied=supplied),
    }
    if getattr(res, "writer", None) is not None:
        # writer mode: the text the agent wrote from the topic (the result screen shows it; edits ground against it)
        meta["writer"] = res.writer.meta()
    store.write_generation_meta(gid, meta)
    return meta


def _request_options(req: GenerateRequest) -> dict:
    """The request's switches, kept in generation.json: «Собрать ещё раз» repeats the deck with the same inputs."""
    return {"audit_models": req.audit_models, "autofix": req.autofix, "exports": list(req.exports), "language": req.language, "extra_instructions": req.extra_instructions, "outline_supplied": req.outline is not None, "pictures": req.pictures, "eyes": req.eyes, "improved_from": req.improved_from}


def _generation_job(gid: str, gdir: Path, req: GenerateRequest) -> Callable[[Job], dict]:
    """Wrap the pipeline so generation.json always ends in status done or failed (the UI lists both)."""

    def run(job: Job) -> dict:
        store.merge_generation_meta(gid, {"status": "running", "job_id": job.id})
        try:
            return _run_generation(gid, gdir, req, job)
        except BaseException as e:
            write_agent_file(gdir, job.agent_events())  # how far the agent got
            store.merge_generation_meta(gid, {"status": "failed", "job_id": job.id, "error": str(e)[:300]})
            raise

    return run


# ---------------------------------------------------------------------------- routes: meta


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "models_configured": models_configured(), "workspace": str(store.root), "writer": _writer_enabled(), "images": images_status()}


def image_provider():
    """The `t2i` role's chain (verstka/images/providers.py), None when the models config has none."""
    from verstka.images.providers import load_image_provider

    try:
        return load_image_provider()
    except Exception:  # noqa: BLE001 - a broken config: no pictures
        log.warning("t2i role unavailable", exc_info=True)
        return None


def _t2i_hint() -> str:
    """Which variables the active t2i role needs (for the log): Polza's key, or the VK profile's endpoint and model."""
    p = image_provider()
    names = {getattr(lk, "name", "") for lk in (getattr(p, "links", None) or [])}
    if "openai_images" in names:
        return "VK_INFERENCE_BASE_URL, VK_INFERENCE_API_KEY and VK_T2I_MODEL in .env"
    return "POLZA_API_KEY in .env"


def _picture_failure_reply(error: str, states: Optional[list] = None) -> str:
    """The reply to a picture change the model could not make: when building again helps, and when it does not.
    `states`: the picture models' states after the failure (ImageChain.describe()) — a hold the chain recorded (Polza's
    daily cap told by its Retry-After, no money, a refused key) says more than the error's wording."""
    from verstka.api.model_status import classify

    held = [s for s in (states or []) if s in ("quota", "no_credits", "auth", "missing")]
    code = held[0] if held else classify(f"provider: {error}")
    if code in ("no_credits", "auth", "missing"):
        return "Не получилось: модель изображений недоступна — слайд остался как был."
    if code == "quota":
        return "Не получилось: дневной лимит модели изображений исчерпан — слайд остался как был. Попробуйте после полуночи по московскому времени."
    if code == "error":
        return "Не получилось: модель изображений отказалась рисовать по этому описанию — слайд остался как был. Попробуйте описать картинку иначе."
    return "Не получилось: модель изображений не ответила — слайд остался как был. Попробуйте ещё раз чуть позже."


def images_configured() -> bool:
    p = image_provider()
    return p is not None and not getattr(p, "off", True)


def images_status() -> dict:
    """Pictures inside slides: on (a text-to-image model has a key), the models in order, the config's default."""
    from verstka.images.prompt import load_config

    p = image_provider()
    links = p.describe() if p is not None else []
    return {"configured": images_configured(), "enabled": bool(load_config().get("enabled", True)), "models": [{"label": d["label"], "state": d["state"]} for d in links]}


def _writer_enabled() -> bool:
    """Writer mode (planning/writer.py) is on: a topic-only text is written by the agent. Off by default (configs/writer.yaml)."""
    try:
        from verstka.planning.writer import load_config

        return bool(load_config().get("enabled", False))
    except Exception:  # noqa: BLE001 - a broken config: the mode is off
        return False


@app.get("/api/models/status")
def model_status() -> dict:
    """Which models are configured and how they answered lately (the providers' own records, no network probing)."""
    from verstka.providers.registry import default_models_path

    return models_status(providers(), configured=models_configured(), config_path=default_models_path(), repo_root=_REPO_ROOT)


@app.get("/api/strategies")
def strategies() -> list[dict]:
    return [{"name": s.name, "title": s.title, "description": s.description} for s in load_strategies().values()]


@app.get("/api/skills")
def list_skills() -> dict:
    reg = skills()
    return {"skills": [{"name": s.name, "version": s.version, "role": s.role, "sha256": s.sha256, "description": s.description, "changelog": s.changelog} for s in sorted(reg.skills.values(), key=lambda s: s.name)], "agents": [{"name": a.name, "version": a.version, "sha256": a.sha256} for a in reg.agents.values()]}


@app.get("/api/checks")
def list_checks() -> list[dict]:
    from verstka.audit.model_checks import model_check_specs
    from verstka.audit.registry import all_checks

    specs = [spec for spec, _ in all_checks()] + list(model_check_specs())
    return [s.model_dump() for s in specs]


# ---------------------------------------------------------------------------- routes: templates


@app.get("/api/templates")
def list_templates() -> list[dict]:
    return store.list_templates()


@app.post("/api/templates")
async def upload_template(file: UploadFile = File(...), use_models: bool = Form(True), improve: bool = Form(False)) -> dict:
    """A template in any presentation format (verstka/ingest/convert.py: .pptx, .potx, .pptm, .ppsx, .thmx, .ppt,
    .odp …): the file is checked by its bytes, converted to .pptx in the job, then analysed. Errors are said in Russian —
    the UI shows them as they are."""
    from verstka.ingest.convert import ACCEPTED_EXTS, ConvertError, check_upload, reason, sniff

    name = file.filename or ""
    if not name:
        raise HTTPException(400, "Выберите файл шаблона: .pptx, .potx, .ppt или .odp")
    limit = max_upload_bytes()
    path = store.upload_path(name)
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Файл больше {limit // (1024 * 1024)} МБ — уменьшите картинки в шаблоне или удалите лишние слайды")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Файл пустой — выберите шаблон ещё раз")
        try:
            check_upload(path)  # by the bytes: a .pptx renamed to .ppt still works, a PDF named .pptx does not
        except ConvertError as e:
            raise HTTPException(400, str(e))
        if not path.suffix.lower() in ACCEPTED_EXTS and sniff(path) not in ("pptx", "thmx", "legacy", "odp"):
            raise HTTPException(400, reason("unknown"))
    except BaseException:
        if path.is_file():
            path.unlink(missing_ok=True)
        if path.parent != store.uploads and path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()
        raise
    use = use_models and models_configured()

    def run(job: Job) -> dict:
        from verstka.analysis.manifest import analyze_template
        from verstka.ingest.convert import to_pptx

        pptx = path
        try:
            if sniff(path) != "pptx" or path.suffix.lower() != ".pptx":
                job.emit("Открываю файл шаблона", 0.02)
            pptx = to_pptx(path)
            m = analyze_template(pptx, workspace_root=store.root, providers=providers() if use else None, skills=skills() if use else None, use_llm=use, use_vlm=use, progress=lambda msg, frac: job.emit(msg, frac), display_name=path.name)
        except BaseException:
            if pptx != path:
                _discard_failed_upload(pptx)
            _discard_failed_upload(path)
            raise
        # the workspace keeps its own copy (templates/<id>/source.pptx): the upload and its converted copy go
        if pptx != path:
            _discard_failed_upload(pptx)
        _discard_failed_upload(path)
        result: dict = {"template_id": m.template_id, "n_slides": m.n_slides, "n_patterns": len(m.patterns)}
        if improve:
            # «Улучшить презентацию»: the deck is the template and, read back, the author's text
            job.emit("Читаю текст, таблицы, диаграммы и картинки презентации", 0.97)
            result["improve"] = _improve_source(m, path.name)
        return result

    job = runner.submit("analyze", run)
    return {"job_id": job.id, "filename": file.filename, "use_models": use}


def _improve_source(m: TemplateManifest, name: str) -> dict:
    """«Улучшить презентацию»: the analysed deck read back as the author's text (ingest/deck_text.py), its pictures kept
    for the improved deck, and its own deterministic audit — the «было» of «было → стало»."""
    from verstka.audit.runner import run_audit
    from verstka.ingest.deck_text import deck_text, keep_pictures

    ws = store.workspace(m.template_id)
    dt = deck_text(ws.source)
    keep_pictures(dt, ws.dir / "source_images")
    audit = None
    problems: list[dict] = []
    try:
        rep = run_audit(ws.source, m, None, ws, render=False)
        if models_configured():
            # «Взгляд дизайнера» on the original: what is wrong with it, said before anything is rebuilt — and counted
            # in its score as in the new decks' (audit/eyes.py)
            from verstka.audit.eyes import CODES, look_only, problem_issues

            titles = {i: dt_title for i, dt_title in _slide_titles(dt.brief).items()}
            seen = look_only(ws.source, ws.dir / "eyes", providers=providers().with_deadline(time.monotonic() + 90), skills=skills(), titles=titles)
            rep.issues.extend(problem_issues(seen))
            rep.recompute()
            problems = [{"slide": i, "code": p.code, "text": CODES[p.code], "where": p.where} for i, ps in sorted(seen.items()) for p in ps if p.severity == "major"]
        audit = {"score": rep.summary.score, "errors": rep.summary.errors, "warnings": rep.summary.warnings}
    except Exception:  # noqa: BLE001 - the improved deck is built all the same
        log.warning("audit of the original deck failed", exc_info=True)
    return {"brief": dt.brief, "name": name, "template_id": m.template_id, **dt.summary(), "audit": audit, "problems": problems}


def _slide_titles(brief: str) -> dict[int, str]:
    """«Слайд N. Заголовок» lines of a read-back deck: slide number → its title."""
    out = {}
    for m in re.finditer(r"^Слайд (\d+)\.\s*(.*)$", brief or "", re.M):
        out[int(m.group(1))] = m.group(2).strip()
    return out


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str) -> dict:
    """Delete a template from the library (the trash button on its tile, after a confirmation). Not while a deck is
    being built on it or the template is still being analysed."""
    try:
        store.workspace(template_id)
    except FileNotFoundError:
        raise HTTPException(404, "Шаблон не найден")
    if any(g.get("template_id") == template_id and _settle_orphan(g).get("status") == "running" for g in store.list_generations()):
        raise HTTPException(409, "На этом шаблоне сейчас собирается презентация — удалите его, когда она будет готова")
    if not store.delete_template(template_id):
        raise HTTPException(500, "Не удалось удалить шаблон — попробуйте ещё раз")
    return {"deleted": True}


class TemplateRename(BaseModel):
    title: str = ""


@app.patch("/api/templates/{template_id}")
def rename_template(template_id: str, body: TemplateRename) -> dict:
    """Rename a template for people (the pencil next to its name in the template's preview): the cards, the build and
    the deck show the new name; the file and its analysis stay as they are. An empty name brings back the file's."""
    item = store.set_template_title(template_id, body.title)
    if item is None:
        raise HTTPException(404, "Шаблон не найден")
    return item


@app.get("/api/templates/{template_id}")
def get_template(template_id: str) -> dict:
    m = store.manifest(template_id)
    if m is None:
        raise HTTPException(404, "Шаблон не найден или ещё не разобран")
    data = m.model_dump()
    for p in data["patterns"]:
        if p.get("thumbnail"):
            p["thumbnail_url"] = f"/api/templates/{template_id}/files/{p['thumbnail']}"
    data["gallery_url"] = f"/api/templates/{template_id}/files/gallery.html"
    data["title"] = store.template_title(template_id)
    data["narration"] = describe_template(m, data["title"])
    return data


@app.get("/api/templates/{template_id}/files/{path:path}")
def template_file(template_id: str, path: str):
    try:
        ws = store.workspace(template_id)
    except FileNotFoundError:
        raise HTTPException(404, "Шаблон не найден")
    return _serve_file(ws.dir, path)


# ---------------------------------------------------------------------------- routes: jobs


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "Задание не найдено — возможно, сервер перезапускался")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str):
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "Задание не найдено — возможно, сервер перезапускался")

    def gen():
        q = job.subscribe()
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    # JobRunner sets job.status before the terminal emit, so only the last event carries done/failed
                    if ev.get("status") in ("done", "failed"):
                        break
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    if job.status in ("done", "failed"):
                        break
        finally:
            job.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------- routes: generations


_TITLE_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def _outline_title(gid: str, strategy: str) -> Optional[str]:
    """The deck title of a finished run written before generation.json carried it (read once per outline version)."""
    d = store.generation_dir(gid)
    path = d / strategy / "outline.json" if d is not None else None
    if path is None or not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        hit = _TITLE_CACHE.get(gid)
        if hit and hit[0] == mtime:
            return hit[1]
        title = json.loads(path.read_text(encoding="utf-8")).get("title") or None
    except Exception:  # noqa: BLE001  (a broken outline only costs the title)
        return None
    _TITLE_CACHE[gid] = (mtime, title)
    return title


LIST_BRIEF = 400  # the list shows a deck's first line; its whole text comes with the deck (GET /api/generations/{gid})


def _list_entry(meta: dict) -> dict:
    """A deck in «Мои презентации»: its meta without the bulk — the brief cut to its start, the writer's text left out
    (the list is fetched after every job; 76 decks shipped 583 KB, the briefs most of it)."""
    out = dict(meta)
    brief = out.get("brief")
    if isinstance(brief, str) and len(brief) > LIST_BRIEF:
        out["brief"] = brief[:LIST_BRIEF]
    if isinstance(out.get("writer"), dict):
        out["writer"] = {"status": out["writer"].get("status")}
    out.pop("extra_instructions", None)
    return out


@app.get("/api/generations")
def list_generations() -> list[dict]:
    out = [_list_entry(_settle_orphan(m)) for m in store.list_generations()]
    for meta in out:
        if meta.get("title") or meta.get("status") != "done" or not meta.get("strategies"):
            continue
        title = _outline_title(str(meta.get("id", "")), str(meta["strategies"][0]))
        if title:
            meta["title"] = title
    return out


@app.post("/api/generations")
def create_generation(req: GenerateRequest) -> dict:
    if store.manifest(req.template_id) is None:
        raise HTTPException(404, "Шаблон не найден или ещё не разобран")
    if req.brief is None and req.outline is None:
        raise HTTPException(400, "Нужен текст презентации")
    bad = [s for s in req.strategies if s not in STRATEGY_NAMES]
    if bad:
        raise HTTPException(400, f"Неизвестные варианты: {bad}")
    if not req.strategies:
        req.strategies = list(STRATEGY_NAMES)  # (none chosen: all three — the pipeline builds them, the page shows them)
    if req.outline is not None:
        try:
            DeckOutline.model_validate(req.outline)
        except ValidationError as e:
            raise HTTPException(422, "План слайдов не прочитан: " + _validation_message(e))
    elif not _brief_from_request(req).text.strip():
        raise HTTPException(422, "Текст презентации пуст")
    gid, gdir = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": req.template_id, "strategies": req.strategies, "brief": req.brief, "audience": req.audience, "purpose": req.purpose, "slides": req.slides, **_request_options(req), "status": "running", "created_at": time.time()})
    job = runner.submit("generate", _generation_job(gid, gdir, req))
    store.merge_generation_meta(gid, {"job_id": job.id}, only_missing=True)  # visible at once, whatever the thread did
    return {"job_id": job.id, "generation_id": gid}


@app.get("/api/generations/{gid}")
def get_generation(gid: str) -> dict:
    return _generation_payload(gid)


@app.delete("/api/generations/{gid}")
def delete_generation(gid: str) -> dict:
    if not SAFE_ID_RE.fullmatch(gid):
        raise HTTPException(404, "Не найдено")
    return {"deleted": store.delete_generation(gid)}


@app.get("/api/generations/{gid}/writer.md")
def writer_text_file(gid: str):
    """The text the agent wrote from the topic (writer mode) as it built the deck from it: «Скачать текст»."""
    gdir = store.generation_dir(gid)
    if gdir is None:
        raise HTTPException(404, "Не найдено")
    return _serve_file(gdir, "writer.md", media_type="text/markdown; charset=utf-8", filename="text.md")


@app.get("/api/generations/{gid}/{strategy}/slides")
def slide_list(gid: str, strategy: str) -> dict:
    """The slide previews a variant has so far, by name: the build screen asks for these while the export renders them
    (an image that is not there yet would be a failed request on the page)."""
    d = _variant_dir(gid, strategy) / "slides"
    return {"slides": sorted(p.name for p in d.glob("slide-*.jpg")) if d.is_dir() else []}


@app.get("/api/generations/{gid}/{strategy}/slides/{name}")
def slide_image(gid: str, strategy: str, name: str):
    vdir = _variant_dir(gid, strategy)
    if not re.fullmatch(r"slide-\d{3}\.jpg", name):
        raise HTTPException(404, "Не найдено")
    return _serve_file(vdir / "slides", name, media_type="image/jpeg")


@app.get("/api/generations/{gid}/{strategy}/eyes/{stage}/{name}")
def eyes_image(gid: str, strategy: str, stage: str, name: str):
    """«Взгляд дизайнера»: a slide as the vision model saw it before it was laid out again, and after."""
    vdir = _variant_dir(gid, strategy)
    if stage not in ("before", "after") or not re.fullmatch(r"slide-\d{3}\.jpg", name):
        raise HTTPException(404, "Не найдено")
    return _serve_file(vdir / "eyes" / stage, name, media_type="image/jpeg")


@app.get("/api/generations/{gid}/{strategy}/files/{name}")
def generation_file(gid: str, strategy: str, name: str):
    vdir = _variant_dir(gid, strategy)
    if name not in ("deck.pptx", "deck.pdf", "deck.html", "outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json"):
        raise HTTPException(404, "Не найдено")
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pdf": "application/pdf", "html": "text/html", "json": "application/json"}[name.rsplit(".", 1)[-1]]
    # the web version opens in the browser («Веб» → a new tab); the other files are downloads
    how = "inline" if name == "deck.html" else "attachment"
    return _serve_file(vdir, name, media_type=media, filename=name, content_disposition_type=how)


@app.get("/api/generations/{gid}/{strategy}/explain/{index}")
def explain_slide(gid: str, strategy: str, index: int) -> dict:
    vdir = _variant_dir(gid, strategy)
    meta = store.read_generation_meta(gid) or {}
    manifest = store.manifest(meta.get("template_id", ""))
    if manifest is None or not (vdir / "outline.json").exists():
        raise HTTPException(404, "Вариант не найден")
    raw = json.loads((vdir / "outline.json").read_text(encoding="utf-8"))
    outline = DeckOutline.model_validate(raw)
    plan = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
    gdir = vdir.parent
    return {"index": index, "text": _explain_text(raw, outline, plan, manifest, index, _current_agent(raw, read_agent_events(gdir), strategy, _edits_of(vdir))["critic"])}


def _explain_text(raw: Optional[dict], outline: DeckOutline, plan: LayoutPlan, manifest, index: int, critic: list[dict]) -> str:
    """«Почему слайд N такой»: the designer's reason, the other forms and the critic's notes first (Agent v2), then how
    the slide was laid out in the template."""
    design = next((d for d in slide_design(raw) if d["index"] == index), None)
    return describe_slide_choice(outline, plan, manifest, index, design_note=describe_slide_design(design, critic, index))


@app.post("/api/generations/{gid}/{strategy}/fixes")
def apply_fixes(gid: str, strategy: str, req: FixRequest) -> dict:
    vdir = _variant_dir(gid, strategy)
    meta = store.read_generation_meta(gid) or {}
    manifest = store.manifest(meta.get("template_id", ""))
    if manifest is None or not (vdir / "audit_report.json").exists():
        raise HTTPException(404, "Вариант не найден")
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, _VARIANT_BUSY)
        _fix_active.add(key)

    def run(job: Job) -> dict:
        from verstka.api.remarks import carry_report_ids
        from verstka.audit.autofix import autofix_loop
        from verstka.pipeline.generate import render_outputs

        from verstka.pipeline import revise as R

        scratch = vdir.parent / f".{strategy}.fixall"
        try:
            ws = store.workspace(meta["template_id"])
            outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
            plan = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
            report = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
            only = None if req.all_deterministic else set(req.issue_ids)
            # the loop works on a copy: nothing of the variant changes before the fixes are done and the previews made,
            # and the version before them is kept («верни как было» restores it, like any edit)
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            shutil.copy2(vdir / "deck.pptx", scratch / "deck.pptx")
            job.emit("Применяю исправления", 0.2)
            final, plan2, outline2, _ = autofix_loop(scratch / "deck.pptx", report, outline, plan, manifest, ws, max_iterations=2, only_ids=only, images_dir=scratch / "slides", brief_text=_brief_text_of_meta(gid, meta),
                                                    writer=meta.get("writer") if isinstance(meta.get("writer"), dict) else None)
            try:
                from verstka.rendering.renderer import strip_outline_marks

                strip_outline_marks(scratch / "deck.pptx")  # a fix re-rendered slides with their markers
            except Exception:  # noqa: BLE001
                log.warning("outline markers left in the notes", exc_info=True)
            job.emit("Готовлю превью и файлы", 0.8)
            # previews and the exports that existed before are rebuilt from one LibreOffice run
            exports = [fmt for fmt in ("pdf", "html") if (vdir / f"deck.{fmt}").exists()]
            out = scratch / "out"
            out.mkdir()
            shutil.copy2(scratch / "deck.pptx", out / "deck.pptx")
            _, images, warns, _ = render_outputs(out, manifest, outline2.title, exports, images=True)
            for w in warns:
                log.warning("re-export: %s", w)
            before = report.summary.score
            version = R.snapshot(vdir)
            (out / "deck.pptx").replace(vdir / "deck.pptx")
            for fmt in ("pdf", "html"):
                if (out / f"deck.{fmt}").exists():
                    (out / f"deck.{fmt}").replace(vdir / f"deck.{fmt}")
            if images and (out / "slides").is_dir():
                shutil.rmtree(vdir / "slides", ignore_errors=True)
                (out / "slides").replace(vdir / "slides")
                final.slide_images = {k: str(vdir / "slides" / Path(p).name) for k, p in enumerate(images, 1)}
            final.deck = str(vdir / "deck.pptx")
            # the remarks that stayed keep the ids the person saw (the audit numbers them through the deck)
            carry_report_ids(report, final)
            (vdir / "audit_report.json").write_text(final.model_dump_json(indent=2), encoding="utf-8")
            (vdir / "outline.json").write_text(outline2.model_dump_json(indent=2), encoding="utf-8")
            (vdir / "layout_plan.json").write_text(plan2.model_dump_json(indent=2), encoding="utf-8")
            _sync_run_manifest(vdir, final, outline2)
            fixed = [f.get("issue_id") for f in final.applied_fixes if isinstance(f, dict) and f.get("issue_id")]
            R.log_edit(vdir, {"version": version, "undo_of": None, "kind": "fix_all", "slides": sorted({int(f["slide"]) for f in final.applied_fixes if isinstance(f, dict) and isinstance(f.get("slide"), int)}),
                              "request": "Исправить все замечания" if only is None else "Исправить выбранные замечания", "reply": "", "score_before": before, "score_after": final.summary.score, "fixed": fixed})
            store.merge_variant_summary(gid, strategy, {"score": final.summary.score, "errors": final.summary.errors, "warnings": final.summary.warnings})
            return {"score": final.summary.score, "errors": final.summary.errors, "warnings": final.summary.warnings, "applied": final.applied_fixes, "version": version}
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("fix", run)
    except BaseException:
        with _fix_lock:
            _fix_active.discard(key)
        raise
    return {"job_id": job.id}


def _sync_run_manifest(vdir: Path, report: AuditReport, outline: DeckOutline) -> None:
    """The run manifest says what the variant is now: its audit, the fixes applied, the plan's hash."""
    import hashlib

    p = vdir / "run_manifest.json"
    try:
        rm = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rm["audit"] = report.summary.model_dump()
    rm["applied_fixes"] = report.applied_fixes
    rm.setdefault("inputs", {})["outline_sha256"] = hashlib.sha256(outline.model_dump_json().encode("utf-8")).hexdigest()[:16]
    p.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")


def _written_text(gid: Optional[str], meta: dict) -> Optional[str]:
    """The text the writer wrote from the topic (writer mode), when the deck was built from it: writer.md of the
    generation (the whole text), else the copy in generation.json; None for a deck built from the user's own text."""
    w = meta.get("writer") if isinstance(meta.get("writer"), dict) else None
    if not w or w.get("status") != "written":
        return None
    gdir = store.generation_dir(gid) if gid else None
    if gdir is not None and (gdir / "writer.md").is_file():
        try:
            text = (gdir / "writer.md").read_text(encoding="utf-8")
            if text.strip():
                return text
        except OSError:
            pass
    return (w.get("text") or "").strip() or None


def _brief_text_of_meta(gid: Optional[str], meta: dict) -> Optional[str]:
    """The text the deck's figures were checked against: the writer's text in writer mode, else the user's brief."""
    return _written_text(gid, meta) or meta.get("brief")


def _brief_of_meta(meta: dict) -> Optional[Brief]:
    """The generation's brief as it was parsed for the build (grounding and the figures check need the same one): in
    writer mode the text the agent wrote from the topic — edits, «Исправить слайд» and the remarks ground against it
    (against the topic they would strip every figure the deck shows)."""
    written = _written_text(str(meta.get("id") or "") or None, meta)
    if written:
        from verstka.planning.writer import with_rules

        w = meta.get("writer") or {}
        return _brief_from_request(GenerateRequest(
            template_id=meta.get("template_id") or "x", brief=with_rules(written), audience=meta.get("audience"), purpose=meta.get("purpose"),
            slides=w.get("slides") or meta.get("slides"), language=meta.get("language") or "ru", extra_instructions=meta.get("extra_instructions"),
        ))
    if not (meta.get("brief") or "").strip():
        return None
    return _brief_from_request(GenerateRequest(
        template_id=meta.get("template_id") or "x", brief=meta.get("brief"), audience=meta.get("audience"), purpose=meta.get("purpose"),
        slides=meta.get("slides"), language=meta.get("language") or "ru", extra_instructions=meta.get("extra_instructions"),
    ))


def _slide_name(o: DeckOutline, i: int) -> str:
    return f"{i} «{o.slides[i - 1].headline}»" if 1 <= i <= len(o.slides) else str(i)


def _edit_job(gid: str, strategy: str, body: EditRequestBody) -> Callable[[Job], dict]:
    """One chat edit of one variant: read the request, change the plan (exactly, or by the slide designer), keep the
    previous version, render and audit the variant again, log the edit, answer in plain words."""
    from verstka.api.edits import parse_edit
    from verstka.pipeline import revise as R

    def run(job: Job) -> dict:
        vdir = _variant_dir(gid, strategy)
        meta = store.read_generation_meta(gid) or {}
        manifest = store.manifest(meta.get("template_id", ""))
        if manifest is None or not (vdir / "outline.json").exists():
            raise ValueError("Вариант не найден")
        outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
        total = len(outline.slides)
        req = parse_edit(body.message, body.slide, total)
        if req is None:
            return {"reply": "Не понял, какой слайд поменять. Назовите номер: «на слайде 3 покажи расходы таблицей».", "changed": False}
        before = None
        if (vdir / "audit_report.json").exists():
            before = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8")).summary.score
        brief = _brief_of_meta(meta)
        focus: Optional[int] = None
        new = outline.model_copy(deep=True)
        undone: Optional[int] = None
        if req.kind == "undo":
            last = R.last_version(vdir)
            if last is None:
                # a variant changed and then restored has a log but no kept version: say so, not «never changed»
                if R.read_edits(vdir):
                    return {"reply": "Все правки уже отменены — возвращать нечего.", "changed": False}
                return {"reply": "Этот вариант ещё не меняли — возвращать нечего.", "changed": False}
            undone, new = last
            edits = R.read_edits(vdir)
            what = next((e.get("request") for e in reversed(edits) if e.get("version") == undone), None)
            reply = "Вернул как было" + (f" до правки «{what}»" if what else "") + "."
        elif req.kind == "delete":
            i = req.slides[0]
            if not 1 <= i <= total:
                return {"reply": f"В этом варианте {total} слайдов — слайда {i} нет.", "changed": False}
            if i == 1 or new.slides[i - 1].kind.value == "title":
                return {"reply": "Обложку убирать не буду — без неё презентация начнётся с середины. Могу поменять на ней заголовок или подзаголовок.", "changed": False}
            gone = new.slides.pop(i - 1)
            focus = min(i, len(new.slides))
            reply = f"Убрал слайд {i} «{gone.headline}» — теперь слайдов {len(new.slides)}."
        elif req.kind in ("swap", "move"):
            idx = [i - 1 for i in req.slides]
            if any(new.slides[i].kind.value == "title" for i in idx) or (req.kind == "move" and req.target == 1):
                return {"reply": "Обложка остаётся первой — остальные слайды могу переставить как скажете.", "changed": False}
            if req.kind == "swap":
                a, b = idx
                new.slides[a], new.slides[b] = new.slides[b], new.slides[a]
                focus = req.slides[1]
                reply = f"Поменял местами слайды {req.slides[0]} и {req.slides[1]}."
            else:
                s = new.slides.pop(idx[0])
                new.slides.insert(req.target - 1, s)
                focus = req.target
                reply = f"Перенёс слайд «{s.headline}» на место {req.target}."
        else:
            from verstka.planning.slide_edit import revise_slide

            i = req.slides[0]
            job.emit(f"Дизайнер переделывает слайд {i}", 0.1)
            use_models = bool(meta.get("use_models", True)) and models_configured()
            try:
                new, reply = revise_slide(
                    outline, i, req.text, brief, manifest,
                    skills=skills() if use_models else None, providers=providers() if use_models else None,
                    progress=job_progress(job),
                )
            except ValueError as e:
                msg = str(e)
                return {"reply": f"Не получилось: {msg[:1].lower() + msg[1:]}.", "changed": False}
            focus = i
        version = None
        if undone is not None:
            # the kept files come back exactly (deck, plan, audit, previews): nothing is planned or rendered again
            job.emit("Возвращаю как было", 0.55)
            audit = R.restore_version(vdir, undone, manifest, new.title, list(meta.get("exports") or []))
            R.drop_version(vdir, undone)
            n_slides = len(new.slides)
        else:
            job.emit("Перерисовываю вариант", 0.55)
            version = R.snapshot(vdir)
            v = R.rerender_variant(vdir, strategy, new, store.workspace(meta["template_id"]).source, store.root, brief=brief, exports=list(meta.get("exports") or []), pictures=meta.get("pictures"))
            audit, n_slides = v.audit, len(v.outline.slides)
        after = audit.summary.score if audit else None
        R.log_edit(vdir, {"version": version, "undo_of": undone, "request": body.message, "kind": req.kind, "slides": req.slides, "reply": reply, "score_before": before, "score_after": after})
        if audit is not None:
            store.merge_variant_summary(gid, strategy, {"n_slides": n_slides, "score": audit.summary.score, "errors": audit.summary.errors, "warnings": audit.summary.warnings})
        if before is not None and after is not None and round(after) != round(before):
            reply += f" Проверка качества: {before:g} → {after:g}."
        elif after is not None:
            reply += f" Проверка качества: {after:g} из 100."
        tail = " Можно вернуть и более раннюю версию — снова «верни как было»." if undone is not None and R.version_numbers(vdir) else "" if undone is not None else " Если не понравится — скажите «верни как было»."
        return {"reply": reply + tail, "changed": True, "slide": focus, "strategy": strategy, "score": after, "kind": req.kind}

    return run


@app.post("/api/generations/{gid}/{strategy}/edits")
def edit_variant(gid: str, strategy: str, body: EditRequestBody) -> dict:
    """The chat agent's edit of one variant (a job: the model may redesign a slide, the variant is rendered again)."""
    _variant_dir(gid, strategy)
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, _VARIANT_BUSY)
        _fix_active.add(key)
    inner = _edit_job(gid, strategy, body)

    def run(job: Job) -> dict:
        try:
            return inner(job)
        finally:
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("edit", run)
    except BaseException:
        with _fix_lock:
            _fix_active.discard(key)
        raise
    return {"job_id": job.id}



def _slide_fix_job(gid: str, strategy: str, n: int, requested: list, wishes: Optional[str]) -> Callable[[Job], dict]:
    """«Исправить слайд»: the remarks of one slide fixed on that slide only (pipeline/revise.py fix_slide) — the critic
    reads them, the designer redesigns the slide when its content is at stake (with the person's wishes), the rules fix
    the rest in place, the slide is spliced into the deck and checked with the others, and the fix is logged so «верни
    как было» can undo it."""
    from verstka.pipeline import revise as R

    def run(job: Job) -> dict:
        vdir = _variant_dir(gid, strategy)
        meta = store.read_generation_meta(gid) or {}
        manifest = store.manifest(meta.get("template_id", ""))
        if manifest is None or not (vdir / "outline.json").exists() or not (vdir / "audit_report.json").exists():
            raise ValueError("Вариант не найден")
        use_models = bool(meta.get("use_models", True)) and models_configured()
        res = R.fix_slide(
            vdir, strategy, n, manifest=manifest, ws=store.workspace(meta["template_id"]), remarks=requested, wishes=wishes,
            brief=_brief_of_meta(meta), use_models=use_models, skills=skills() if use_models else None,
            providers=providers() if use_models else None, exports=list(meta.get("exports") or []), progress=job_progress(job),
        )
        s = res.report.summary
        if res.applied:
            store.merge_variant_summary(gid, strategy, {"n_slides": res.n_slides, "score": s.score, "errors": s.errors, "warnings": s.warnings})
        return {
            "reply": res.reply, "changed": res.applied, "applied": res.applied, "kind": "fix", "strategy": strategy, "slide": n,
            "requested": [i.id for i in res.requested], "fixed": res.fixed, "remaining": res.remaining,
            "score_before": res.score_before, "new_score": res.score_after, "errors": s.errors, "warnings": s.warnings,
            "changed_other_slides": bool(res.other), "other_slides": res.other,
            "how": res.how, "notes": res.notes, "why": res.why, "version": res.version, "at": res.at,
        }

    return run


@app.post("/api/generations/{gid}/{strategy}/slides/{n}/fix")
def fix_slide(gid: str, strategy: str, n: int, body: SlideFixBody) -> dict:
    """Fix the remarks of slide `n` (and follow the person's wishes) on that slide only — a job."""
    from verstka.api.remarks import is_stage

    try:
        vdir = _variant_dir(gid, strategy)
    except HTTPException:
        raise HTTPException(404, "Вариант не найден")
    meta = store.read_generation_meta(gid) or {}
    if store.manifest(meta.get("template_id", "")) is None or not all((vdir / f).exists() for f in ("deck.pptx", "outline.json", "audit_report.json", "layout_plan.json")):
        raise HTTPException(404, "Вариант не найден")
    try:
        outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
        report = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "Вариант не найден")
    total = len(outline.slides)
    if not 1 <= n <= total:
        raise HTTPException(422, f"В этом варианте {ru_count(total, 'слайд', 'слайда', 'слайдов')} — слайда {n} нет")
    wishes = (body.wishes or "").strip() or None
    on_slide = [i for i in report.issues if i.slide == n]
    if body.issue_ids is not None and body.issue_ids:
        wanted = set(body.issue_ids)
        requested = [i for i in on_slide if i.id in wanted]
        if not requested:
            raise HTTPException(422, f"На слайде {n} нет таких замечаний")
    else:
        requested = [i for i in on_slide if is_stage(i)]
    if not requested and not wishes:
        raise HTTPException(422, f"На слайде {n} нет замечаний")
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, _VARIANT_BUSY)
        _fix_active.add(key)
    inner = _slide_fix_job(gid, strategy, n, requested, wishes)

    def run(job: Job) -> dict:
        try:
            return inner(job)
        finally:
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("slide_fix", run)
    except BaseException:
        with _fix_lock:
            _fix_active.discard(key)
        raise
    return {"job_id": job.id}


@app.post("/api/generations/{gid}/{strategy}/slides/{n}/image")
def change_slide_picture(gid: str, strategy: str, n: int, body: PictureBody) -> dict:
    """«Заменить изображение»: a new picture for slide n's place on the person's wish, or the free place back (a job;
    «верни как было» undoes it like any edit)."""
    from verstka.images.replace import has_place

    try:
        vdir = _variant_dir(gid, strategy)
    except HTTPException:
        raise HTTPException(404, "Вариант не найден")
    meta = store.read_generation_meta(gid) or {}
    if store.manifest(meta.get("template_id", "")) is None or not all((vdir / f).exists() for f in ("deck.pptx", "outline.json", "audit_report.json")):
        raise HTTPException(404, "Вариант не найден")
    try:
        total = len(DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8")).slides)
    except (OSError, ValueError):
        raise HTTPException(404, "Вариант не найден")
    if not 1 <= n <= total:
        raise HTTPException(422, f"В этом варианте {ru_count(total, 'слайд', 'слайда', 'слайдов')} — слайда {n} нет")
    if body.action == "generate" and not images_configured():
        # what the owner has to set goes to the log: a person reads only that pictures are off
        log.warning("picture change refused: the t2i role has no model with a key (%s)", _t2i_hint())
        raise HTTPException(503, "Модель изображений не подключена")
    if not has_place(vdir, n):
        raise HTTPException(422, f"На слайде {n} нет изображения и места под него")
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, _VARIANT_BUSY)
        _fix_active.add(key)

    def run(job: Job) -> dict:
        from verstka.images.replace import change_picture

        try:
            manifest = store.manifest(meta.get("template_id", ""))
            if manifest is None:
                raise ValueError("Шаблон этой презентации больше не в библиотеке")
            use_models = bool(meta.get("use_models", True)) and models_configured()
            brief = _brief_of_meta(meta)
            try:
                res = change_picture(
                    vdir, strategy, n, manifest=manifest, ws=store.workspace(meta["template_id"]), provider=image_provider(), action=body.action,
                    wish=body.wish, skills=skills() if use_models else None, providers=providers() if use_models else None,
                    exports=list(meta.get("exports") or []), brief_text=brief.text if brief is not None else None, progress=job_progress(job),
                )
            except ValueError as e:
                msg = str(e)
                return {"reply": f"Не получилось: {msg[:1].lower() + msg[1:]}.", "changed": False, "applied": False, "kind": "picture", "action": body.action, "strategy": strategy, "slide": n}
            except Exception as e:  # noqa: BLE001 - the model failed: the slide stays as it was
                from verstka.providers.base import ProviderError

                if isinstance(e, ProviderError):
                    log.warning("picture change: %s", e)
                    try:
                        states = [d.get("state") for d in image_provider().describe()]
                    except Exception:  # noqa: BLE001 - no picture model left to describe
                        states = []
                    return {"reply": _picture_failure_reply(str(e), states), "changed": False, "applied": False, "kind": "picture", "action": body.action, "strategy": strategy, "slide": n}
                raise
            if res.score_after is not None:
                audit = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
                store.merge_variant_summary(gid, strategy, {"score": audit.summary.score, "errors": audit.summary.errors, "warnings": audit.summary.warnings})
            return res.result(strategy)
        finally:
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("picture", run)
    except BaseException:
        with _fix_lock:
            _fix_active.discard(key)
        raise
    return {"job_id": job.id}


@app.get("/api/generations/{gid}/{strategy}/diff/{other_gid}/{other_strategy}")
def diff_runs(gid: str, strategy: str, other_gid: str, other_strategy: str) -> dict:
    from verstka.pipeline.run_manifest import diff_manifests

    pa = _variant_dir(gid, strategy) / "run_manifest.json"
    pb = _variant_dir(other_gid, other_strategy) / "run_manifest.json"
    if not pa.exists() or not pb.exists():
        raise HTTPException(404, "Паспорт сборки не найден")
    ma = json.loads(pa.read_text(encoding="utf-8"))
    mb = json.loads(pb.read_text(encoding="utf-8"))
    return {"a": {"generation": gid, "strategy": strategy, "score": ma.get("audit", {}).get("score")}, "b": {"generation": other_gid, "strategy": other_strategy, "score": mb.get("audit", {}).get("score")}, "diff": diff_manifests(ma, mb)}


# ---------------------------------------------------------------------------- routes: chat agent

# "generate" is decided first: a brief pasted into the chat mentions audiences, plans, templates and audits all at once.
_GEN_RX = re.compile(r"сгенерируй|(сделай|собери|создай|подготовь)(?:те)?\s+(?:(?:мне|нам)\s+)?(?:(?:нов|друг)\w*\s+|(?:ещё|еще)\s+одн\w*\s+)?(презентац|слайд|дек|колод)|\bgenerate\b", re.I)
# the object of the command, left after «сгенерируй» / the rest of the noun «презентац|ию»
_GEN_OBJECT_RX = re.compile(r"^[а-яё]*\s*(?:(?:мне|нам)\s+)?(?:(?:нов|друг)\w*\s+|(?:ещё|еще)\s+одн\w*\s+)?(?:(?:презентац|слайд|дек|колод)[а-яё]*)?"
                            r"\s*(?:(?:me\s+)?(?:an?|the)\s+)?(?:(?:new|another)\s+)?(?:presentation|deck|slides?)?", re.I)
_INTENT_RULES = [
    # «как там?», «готово?», «сколько ещё?» — about the build in progress (short messages only reach these rules)
    ("status", re.compile(r"^(?!.*слайд\w*\s*\d)\W*(?:ну\s+)?(?:что\s+там|как\s+там|как\s+(?:идёт|идет|продвигается)|долго\s+(?:ещё|еще)|сколько\s+(?:ещё|еще|осталось)|скоро\b|(?:уже\s+)?готово\b|статус|прогресс)", re.I)),
    ("explain_slide", re.compile(r"(почему|объясни|как выбран|why).*слайд\w*\s*(\d+)|слайд\w*\s*(\d+).*(почему|объясни|why)", re.I)),
    ("agent", re.compile(r"как\s+(ты\s+|агент\s+)?(работал|действовал|думал|рассуждал)|что\s+(ты\s+|агент\s+)?(сделал|делал)|журнал|ход\s+работы|шаги\s+агента|работ\w*\s+агента|критик", re.I)),
    ("fix_all", re.compile(r"(исправь|почини|поправь)\s+(вс|ошибк|замечан)|fix all|автофикс", re.I)),
    ("audit", re.compile(r"\bаудит(?!ор)\w*|\bпроверь|\bошибк|замечани|\baudit\b|\bissues\b", re.I)),
    ("export", re.compile(r"экспорт|скачать|\bpdf\b|\bhtml\b|download", re.I)),
    ("template", re.compile(r"\bшаблон|template|дизайн-систем|палитр|шрифт", re.I)),
    ("plan", re.compile(r"\bплан\w*|структур|какие слайды|outline|макет", re.I)),
]


# «замени картинку на слайде 2 на вид сверху», «нарисуй другое изображение», «убери картинку со слайда 3»: the picture
# of a slide of the deck on screen (verstka/images/replace.py) — never «оставь место под фото» (an edit of the slide)
_PICTURE_RX = re.compile(
    r"\b(?:замени|поменяй|смени|перерисуй|сгенерируй|нарисуй|обнови|переделай)(?:те)?\s+(?:\S+\s+){0,2}?(?:картинк|изображени|иллюстрац|рисун)\w*"
    r"|\b(?:друг|нов)\w+\s+(?:картинк|изображени|иллюстрац)\w*"
    r"|\b(?:убери|удали)(?:те)?\s+(?:\S+\s+){0,2}?(?:картинк|изображени|иллюстрац)\w*",
    re.I,
)
_PICTURE_REMOVE_RX = re.compile(r"\b(?:убери|удали)(?:те)?\b", re.I)
_SLIDE_NO_RX = re.compile(r"(?:(?:на|со?|для)\s+)?слайд\w*\s*№?\s*(\d{1,2})", re.I)


def _picture_ask(message: str) -> tuple[Optional[int], Optional[str], str]:
    """(the slide named, the wish — what the new picture should show —, the action) of a picture request in the chat."""
    m = _SLIDE_NO_RX.search(message)
    n = int(m.group(1)) if m else None
    action = "remove" if _PICTURE_REMOVE_RX.search(message) else "generate"
    t = _PICTURE_RX.sub(" ", message, count=1)
    t = _SLIDE_NO_RX.sub(" ", t)
    t = re.sub(r"^[\s,.:;—–-]*(?:(?:на|где|с|со)\s+)?", "", " ".join(t.split()), flags=re.I).strip(" .,:;—–-")
    return n, (t if action == "generate" and len(t) >= 3 else None), action


def _is_edit(message: str, intent: str) -> bool:
    """A change of the deck on screen («на слайде 3 покажи расходы таблицей», «сделай слайд 4 таблицей», «верни как
    было») — not a question about it, a new deck («сделай презентацию…») or «покажи план»."""
    from verstka.api.edits import looks_like_edit

    if intent in ("explain_slide", "agent", "fix_all", "audit", "export") or not looks_like_edit(message):
        return False
    return not (intent == "plan" and re.search(r"(покажи|какой|расскажи)\s+(мне\s+)?план", message, re.I))


def _edit_ack(req) -> str:
    """What the agent says at once, before the job: which change it is making."""
    if req.kind == "undo":
        return "Возвращаю предыдущую версию варианта…"
    if req.kind == "delete":
        return f"Убираю слайд {req.slides[0]} и пересобираю вариант…"
    if req.kind == "swap":
        return f"Меняю местами слайды {req.slides[0]} и {req.slides[1]}…"
    if req.kind == "move":
        return f"Переношу слайд {req.slides[0]} на место {req.target}…"
    return f"Понял. Дизайнер переделывает слайд {req.slides[0]}: «{req.text[:120]}». Цифры возьму только из вашего текста…"


def _looks_like_brief(text: str) -> bool:
    return len(text) > 200 or text.count("\n") >= 3


# what follows «сделай презентацию»: a topic the writer can write about («про историю VK», «на тему…»)
_TOPIC_RX = re.compile(r"^\s*(?:,\s*)?(?:про|о|об|обо|на\s+тему|по\s+теме|about|on)\s+\S", re.I)


def _build_from(message: str) -> Optional[str]:
    """What a «generate» message builds from: «brief» — a text of its own (a pasted brief), «topic» — a topic the writer
    can write about («сделай презентацию про историю VK»); None when it only asks for a deck — «сделай презентацию
    короче», «собери заново» speak about the deck on screen, a bare «сделай презентацию» has nothing to build from."""
    if _looks_like_brief(message):
        return "brief"
    m = _GEN_RX.search(message)
    rest = message[m.end():] if m else message
    rest = _GEN_OBJECT_RX.sub("", rest, count=1)
    return "topic" if _TOPIC_RX.match(rest) else None


def _live_builds() -> list[Job]:
    return [j for j in list(runner.jobs.values()) if j.kind == "generate" and j.status in ("queued", "running")]


def _build_status(gen_id: Optional[str]) -> str:
    """«Как там?» in the chat: the build in progress (its share done), a change being made, or what is ready."""
    live = _live_builds()
    if live:
        pct = round(max(live, key=lambda j: j.created_at).progress * 100)
        return f"Собираю презентацию — готово примерно на {pct}%. Покажу её, как только закончу." if pct else "Начинаю собирать презентацию — покажу её, как только закончу."
    if any(j.status in ("queued", "running") for j in list(runner.jobs.values())):
        return "Вношу изменения — ещё немного."
    if gen_id:
        return "Всё готово: презентация на экране. Могу объяснить или изменить любой слайд."
    return "Сейчас ничего не собирается. Выберите шаблон и пришлите текст — соберу три варианта."


def _intent(message: str) -> tuple[str, dict]:
    if _GEN_RX.search(message) or _looks_like_brief(message):
        return "generate", {}
    for name, rx in _INTENT_RULES:
        m = rx.search(message)
        if m:
            params: dict[str, Any] = {}
            if name == "explain_slide":
                num = next((g for g in m.groups() if g and g.isdigit()), None)
                if num:
                    params["index"] = int(num)
            return name, params
    return "help", {}


def _session(session_id: str) -> dict:
    """Fetch (or create) a chat session; the most recently used one moves to the end and the oldest are evicted beyond the cap."""
    with _chat_lock:
        session = _chat_sessions.pop(session_id, None) or {"history": []}
        _chat_sessions[session_id] = session
        while len(_chat_sessions) > _MAX_CHAT_SESSIONS:
            _chat_sessions.pop(next(iter(_chat_sessions)))
    return session


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    session = _session(req.session_id)
    if req.template_id:
        session["template_id"] = req.template_id
    if req.generation_id:
        session["generation_id"] = req.generation_id
    intent, params = _intent(req.message)
    template_id = session.get("template_id")
    gen_id = session.get("generation_id")
    reply: str
    actions: list[dict] = []
    if gen_id and _PICTURE_RX.search(req.message) and not _looks_like_brief(req.message):
        intent = "picture"
    elif gen_id and _is_edit(req.message, intent):
        intent = "edit"
    if intent == "picture":
        if req.strategy:
            session["strategy"] = req.strategy
        payload = _generation_payload(gen_id)
        variants = payload.get("variants", [])
        v = next((vv for vv in variants if vv["strategy"] == session.get("strategy")), variants[0] if variants else None)
        n, wish, action = _picture_ask(req.message)
        n = n or req.slide
        if v is None:
            reply = "Презентация ещё собирается — подождите немного, потом поменяю изображение."
        elif n is None:
            reply = "На каком слайде заменить изображение? Например: «замени картинку на слайде 2 на вид сверху»."
        else:
            try:
                r = change_slide_picture(gen_id, v["strategy"], n, PictureBody(wish=wish, action=action))
            except HTTPException as e:
                r = None
                reply = (e.detail if isinstance(e.detail, str) else "Не получилось") + ("." if isinstance(e.detail, str) and not e.detail.endswith(".") else "")
            if r is not None:
                reply = (f"Убираю изображение со слайда {n} — место останется под ваше фото…" if action == "remove"
                         else f"Рисую новое изображение для слайда {n}" + (f": «{wish}»" if wish else "") + "…")
                actions.append({"type": "edit", "job_id": r["job_id"], "strategy": v["strategy"], "generation_id": gen_id, "slide": n})
    if intent == "picture":
        pass  # answered above
    elif intent == "edit":
        from verstka.api.edits import parse_edit

        if req.strategy:
            session["strategy"] = req.strategy
        payload = _generation_payload(gen_id)
        variants = payload.get("variants", [])
        v = next((vv for vv in variants if vv["strategy"] == session.get("strategy")), variants[0] if variants else None)
        if v is None:
            reply = "Презентация ещё собирается — подождите немного, потом поменяю."
        else:
            total = len((v.get("outline") or {}).get("slides") or [])
            parsed = parse_edit(req.message, req.slide, total)
            cover_first = (v.get("outline") or {}).get("slides", [{}])[0].get("kind") == "title"
            if parsed is None:
                reply = "Какой слайд поменять? Назовите номер: «на слайде 3 покажи расходы таблицей»."
            elif cover_first and (parsed.kind == "delete" and parsed.slides == [1] or parsed.kind in ("swap", "move") and (1 in parsed.slides or parsed.target == 1)):
                reply = "Обложка остаётся первой — без неё презентация начнётся с середины. На ней могу поменять заголовок или подзаголовок."
            else:
                try:
                    r = edit_variant(gen_id, v["strategy"], EditRequestBody(message=req.message, slide=req.slide))
                except HTTPException as e:
                    if e.status_code != 409:
                        raise
                    r = None
                if r is None:
                    reply = "Этот вариант уже меняется — дождитесь, пока закончу."
                else:
                    reply = _edit_ack(parsed)
                    actions.append({"type": "edit", "job_id": r["job_id"], "strategy": v["strategy"], "generation_id": gen_id, "slide": parsed.slides[0] if parsed.slides else None})
    elif intent == "template":
        m = store.manifest(template_id) if template_id else None
        reply = describe_template(m) if m else "Сначала выберите или загрузите шаблон (.pptx) — расскажу, какие в нём цвета, шрифты и макеты слайдов."
        actions.append({"type": "open_tab", "tab": "template"})
    elif intent in ("plan", "explain_slide", "audit", "export", "agent") and gen_id:
        if req.strategy:
            session["strategy"] = req.strategy
        payload = _generation_payload(gen_id)
        variants = payload.get("variants", [])
        if not variants:
            reply = "Презентация ещё собирается — подождите немного."
        else:
            # the variant on screen (the UI sends it), else the first one
            v = next((vv for vv in variants if vv["strategy"] == session.get("strategy")), variants[0])
            manifest = store.manifest(payload["template_id"])
            outline = DeckOutline.model_validate(v["outline"])
            plan = LayoutPlan.model_validate(v["plan"])
            titles = {s.name: s.title for s in load_strategies().values()}
            name = lambda vv: titles.get(vv["strategy"], vv["strategy"])  # noqa: E731
            # plan, audit and files speak about the variant on screen, like the drawer tab they open beside the chat
            if intent == "plan":
                reply = describe_plan(outline, plan, manifest, name(v))
                actions.append({"type": "open_tab", "tab": "plan"})
            elif intent == "explain_slide":
                index = int(params.get("index", 1))
                reply = _explain_text(v["outline"], outline, plan, manifest, index, v.get("agent", {}).get("critic", []))
                if len(variants) > 1:
                    reply = f"Вариант «{name(v)}». " + reply
                if 1 <= index <= len(outline.slides):
                    actions.append({"type": "open_tab", "tab": "why", "slide": index})
            elif intent == "agent":
                reply = describe_agent_work(v.get("agent") or {}, name(v))
                actions.append({"type": "open_tab", "tab": "agent"})
            elif intent == "audit":
                reply = f"Вариант «{name(v)}». " + (describe_audit(AuditReport.model_validate(v["audit"])) if v.get("audit") else "Проверка качества для него не запускалась.")
                actions.append({"type": "open_tab", "tab": "audit"})
            else:
                kinds = {"deck.pptx": "PowerPoint", "deck.pdf": "PDF", "deck.html": "веб-версия"}
                have = [kinds[f] for f in kinds if f in (v.get("files") or {})]
                listed = ", ".join(have[:-1]) + " и " + have[-1] if len(have) > 1 else "".join(have)
                reply = f"Вариант «{name(v)}»: {listed} — открыл «Файлы»." if have else "Файлы ещё сохраняются — подождите немного."
                actions.append({"type": "open_tab", "tab": "export"})
    elif intent == "fix_all" and gen_id:
        payload = _generation_payload(gen_id)
        jobs = []
        for vv in payload.get("variants", []):
            try:
                r = apply_fixes(gen_id, vv["strategy"], FixRequest(all_deterministic=True))
            except HTTPException as e:
                if e.status_code != 409:
                    raise
                continue  # already running for this variant
            jobs.append({"strategy": vv["strategy"], "job_id": r["job_id"]})
        reply = "Запустил автоматические исправления для всех вариантов — расскажу, что изменилось." if jobs else "Исправления уже выполняются — дождитесь результата."
        actions.append({"type": "jobs", "jobs": jobs})
    elif intent == "status":
        reply = _build_status(gen_id)
    elif intent == "generate":
        source = _build_from(req.message)
        if not template_id:
            reply = "Сначала выберите шаблон, затем пришлите текст — соберу три варианта."
        elif _live_builds():
            reply = "Сейчас собирается другая презентация — пришлите текст, когда она будет готова."
        elif source is None:
            reply = ("Эту презентацию могу изменить по слайдам — например: «на слайде 3 покажи расходы таблицей». Чтобы собрать новую, пришлите её текст."
                     if gen_id else "Пришлите текст презентации — соберу три варианта.")
        elif source == "topic" and not models_configured():
            reply = "Без подключённой модели я не пишу текст сам — пришлите текст презентации, и я разложу его по слайдам шаблона."
        else:
            brief_text = req.message
            r = create_generation(GenerateRequest(template_id=template_id, brief=brief_text, use_models=models_configured()))
            session["generation_id"] = r["generation_id"]
            reply = "Принял текст. Выделяю факты и цифры, составляю план и собираю три варианта по макетам шаблона — прогресс видно на экране."
            actions.append({"type": "generation_started", "job_id": r["job_id"], "generation_id": r["generation_id"]})
    else:
        # one short answer for where the person is: a deck on screen, a template only, or nothing yet
        if gen_id:
            reply = "Могу объяснить любой слайд или изменить его — например: «на слайде 3 покажи расходы таблицей»."
        elif template_id:
            reply = "Пришлите текст — соберу три варианта."
        else:
            reply = "Выберите шаблон и пришлите текст."
    session["history"].append({"role": "user", "text": req.message})
    session["history"].append({"role": "assistant", "text": reply})
    return {"reply": reply, "intent": intent, "actions": actions, "template_id": template_id, "generation_id": session.get("generation_id")}


# ---------------------------------------------------------------------------- static web app

_WEB_DIST = _REPO_ROOT / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
