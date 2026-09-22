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
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from verstka import __version__
from verstka.api.jobs import Job, JobRunner
from verstka.api.narrator import describe_audit, describe_plan, describe_slide_choice, describe_template
from verstka.api.store import SAFE_ID_RE, Store
from verstka.ingest.workspace import file_sha256
from verstka.planning.brief import normalize_purpose, parse_brief_text
from verstka.planning.strategies import STRATEGY_NAMES, load_strategies
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.audit import AuditReport
from verstka.schemas.layout import LayoutPlan
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
_fix_active: set[tuple[str, str]] = set()  # (generation id, strategy) with an autofix job in flight
_fix_lock = threading.Lock()


def providers() -> Optional[ProviderRegistry]:
    global _providers
    if _providers is None:
        path = Path(os.environ.get("VERSTKA_MODELS", _REPO_ROOT / "configs" / "models.yaml"))
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


class FixRequest(BaseModel):
    issue_ids: list[str] = Field(default_factory=list)
    all_deterministic: bool = False


class ChatRequest(BaseModel):
    session_id: str
    message: str
    template_id: Optional[str] = None
    generation_id: Optional[str] = None


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
        raise HTTPException(404, "file not found")
    return FileResponse(target, **kwargs)


def _variant_dir(gid: str, strategy: str) -> Path:
    gdir = store.generation_dir(gid)
    if gdir is None or strategy not in STRATEGY_NAMES:
        raise HTTPException(404, "not found")
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


def _looks_like_pptx(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "ppt/presentation.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


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


def _variant_payload(gdir: Path, strategy: str) -> Optional[dict]:
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
    return {
        "strategy": strategy,
        "outline": outline,
        "plan": plan,
        "audit": audit,
        "run_manifest": run_manifest,
        "slides": [f"/api/generations/{gid}/{strategy}/slides/{p.name}" for p in slides],
        "files": files,
    }


def _generation_payload(gid: str) -> dict:
    gdir = store.generation_dir(gid)
    if gdir is None:
        raise HTTPException(404, "generation not found")
    meta = store.read_generation_meta(gid) or {"id": gid}
    variants = [v for s in meta.get("strategies", list(STRATEGY_NAMES)) if (v := _variant_payload(gdir, s))]
    return {**meta, "variants": variants}


def _run_generation(gid: str, gdir: Path, req: GenerateRequest, job: Job) -> dict:
    from verstka.pipeline.generate import generate_variants

    manifest = store.manifest(req.template_id)
    if manifest is None:
        raise ValueError("template is not analyzed")
    brief = None
    outline = None
    if req.outline is not None:
        outline = DeckOutline.model_validate(req.outline)
    else:
        brief = _brief_from_request(req)
    use_models = req.use_models and models_configured()
    res = generate_variants(
        store.workspace(req.template_id).source,
        brief=brief,
        outline=outline,
        strategies=req.strategies,
        out_dir=gdir,
        workspace_root=store.root,
        providers=providers() if use_models else None,
        skills=skills() if use_models else None,
        use_llm=use_models,
        use_vlm=use_models,
        audit=True,
        autofix=req.autofix,
        audit_models=req.audit_models and use_models,
        exports=req.exports,
        progress=lambda msg, frac: job.emit(msg, frac),
    )
    meta = {
        "id": gid,
        "template_id": req.template_id,
        "template_file": manifest.source_file,
        "strategies": req.strategies,
        "brief": req.brief,
        "audience": req.audience,
        "purpose": req.purpose,
        "slides": req.slides,
        "use_models": use_models,
        "seconds": res.seconds,
        "created_at": gdir.stat().st_mtime,
        "status": "done",
        "job_id": job.id,
        "summary": {v.strategy: {"n_slides": len(v.outline.slides), "score": v.audit.summary.score if v.audit else None, "errors": v.audit.summary.errors if v.audit else None, "warnings": v.audit.summary.warnings if v.audit else None, "seconds": v.seconds} for v in res.variants},
    }
    store.write_generation_meta(gid, meta)
    return meta


def _generation_job(gid: str, gdir: Path, req: GenerateRequest) -> Callable[[Job], dict]:
    """Wrap the pipeline so generation.json always ends in status done or failed (the UI lists both)."""

    def run(job: Job) -> dict:
        store.merge_generation_meta(gid, {"status": "running", "job_id": job.id})
        try:
            return _run_generation(gid, gdir, req, job)
        except BaseException as e:
            store.merge_generation_meta(gid, {"status": "failed", "job_id": job.id, "error": str(e)[:300]})
            raise

    return run


# ---------------------------------------------------------------------------- routes: meta


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "models_configured": models_configured(), "workspace": str(store.root)}


@app.get("/api/strategies")
def strategies() -> list[dict]:
    return [{"name": s.name, "title": s.title, "description": s.description} for s in load_strategies().values()]


@app.get("/api/skills")
def list_skills() -> dict:
    reg = skills()
    return {"skills": [{"name": s.name, "version": s.version, "role": s.role, "sha256": s.sha256, "description": s.description, "changelog": s.changelog} for s in sorted(reg.skills.values(), key=lambda s: s.name)], "agents": [{"name": a.name, "version": a.version, "sha256": a.sha256} for a in reg.agents.values()]}


@app.get("/api/checks")
def list_checks() -> list[dict]:
    from verstka.audit.model_checks import DECK_COHERENCE, SLIDE_CONTENT
    from verstka.audit.registry import all_checks

    specs = [spec for spec, _ in all_checks()] + [SLIDE_CONTENT, DECK_COHERENCE]
    return [s.model_dump() for s in specs]


# ---------------------------------------------------------------------------- routes: templates


@app.get("/api/templates")
def list_templates() -> list[dict]:
    return store.list_templates()


@app.post("/api/templates")
async def upload_template(file: UploadFile = File(...), use_models: bool = Form(True)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(400, "only .pptx files are accepted")
    limit = max_upload_bytes()
    path = store.upload_path(file.filename)
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"file is larger than {limit // (1024 * 1024)} MB")
                out.write(chunk)
        if not _looks_like_pptx(path):
            raise HTTPException(400, "not a PowerPoint file: expected a zip package with ppt/presentation.xml")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    use = use_models and models_configured()

    def run(job: Job) -> dict:
        from verstka.analysis.manifest import analyze_template

        try:
            m = analyze_template(path, workspace_root=store.root, providers=providers() if use else None, skills=skills() if use else None, use_llm=use, use_vlm=use, progress=lambda msg, frac: job.emit(msg, frac))
        except BaseException:
            _discard_failed_upload(path)
            raise
        return {"template_id": m.template_id, "n_slides": m.n_slides, "n_patterns": len(m.patterns)}

    job = runner.submit("analyze", run)
    return {"job_id": job.id, "filename": file.filename, "use_models": use}


@app.get("/api/templates/{template_id}")
def get_template(template_id: str) -> dict:
    m = store.manifest(template_id)
    if m is None:
        raise HTTPException(404, "template not found or not analyzed")
    data = m.model_dump()
    for p in data["patterns"]:
        if p.get("thumbnail"):
            p["thumbnail_url"] = f"/api/templates/{template_id}/files/{p['thumbnail']}"
    data["gallery_url"] = f"/api/templates/{template_id}/files/gallery.html"
    data["narration"] = describe_template(m)
    return data


@app.get("/api/templates/{template_id}/files/{path:path}")
def template_file(template_id: str, path: str):
    try:
        ws = store.workspace(template_id)
    except FileNotFoundError:
        raise HTTPException(404, "template not found")
    return _serve_file(ws.dir, path)


# ---------------------------------------------------------------------------- routes: jobs


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str):
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")

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


@app.get("/api/generations")
def list_generations() -> list[dict]:
    return store.list_generations()


@app.post("/api/generations")
def create_generation(req: GenerateRequest) -> dict:
    if store.manifest(req.template_id) is None:
        raise HTTPException(404, "template not found or not analyzed")
    if req.brief is None and req.outline is None:
        raise HTTPException(400, "brief or outline is required")
    bad = [s for s in req.strategies if s not in STRATEGY_NAMES]
    if bad:
        raise HTTPException(400, f"unknown strategies: {bad}")
    if req.outline is not None:
        try:
            DeckOutline.model_validate(req.outline)
        except ValidationError as e:
            raise HTTPException(422, "invalid outline: " + _validation_message(e))
    elif not _brief_from_request(req).text.strip():
        raise HTTPException(422, "brief is empty")
    gid, gdir = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": req.template_id, "strategies": req.strategies, "brief": req.brief, "audience": req.audience, "purpose": req.purpose, "slides": req.slides, "status": "running", "created_at": time.time()})
    job = runner.submit("generate", _generation_job(gid, gdir, req))
    store.merge_generation_meta(gid, {"job_id": job.id}, only_missing=True)  # visible at once, whatever the thread did
    return {"job_id": job.id, "generation_id": gid}


@app.get("/api/generations/{gid}")
def get_generation(gid: str) -> dict:
    return _generation_payload(gid)


@app.delete("/api/generations/{gid}")
def delete_generation(gid: str) -> dict:
    if not SAFE_ID_RE.fullmatch(gid):
        raise HTTPException(404, "not found")
    return {"deleted": store.delete_generation(gid)}


@app.get("/api/generations/{gid}/{strategy}/slides/{name}")
def slide_image(gid: str, strategy: str, name: str):
    vdir = _variant_dir(gid, strategy)
    if not re.fullmatch(r"slide-\d{3}\.jpg", name):
        raise HTTPException(404, "not found")
    return _serve_file(vdir / "slides", name, media_type="image/jpeg")


@app.get("/api/generations/{gid}/{strategy}/files/{name}")
def generation_file(gid: str, strategy: str, name: str):
    vdir = _variant_dir(gid, strategy)
    if name not in ("deck.pptx", "deck.pdf", "deck.html", "outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json"):
        raise HTTPException(404, "not found")
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pdf": "application/pdf", "html": "text/html", "json": "application/json"}[name.rsplit(".", 1)[-1]]
    return _serve_file(vdir, name, media_type=media, filename=name)


@app.get("/api/generations/{gid}/{strategy}/explain/{index}")
def explain_slide(gid: str, strategy: str, index: int) -> dict:
    vdir = _variant_dir(gid, strategy)
    meta = store.read_generation_meta(gid) or {}
    manifest = store.manifest(meta.get("template_id", ""))
    if manifest is None or not (vdir / "outline.json").exists():
        raise HTTPException(404, "variant not found")
    outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
    plan = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
    return {"index": index, "text": describe_slide_choice(outline, plan, manifest, index)}


@app.post("/api/generations/{gid}/{strategy}/fixes")
def apply_fixes(gid: str, strategy: str, req: FixRequest) -> dict:
    vdir = _variant_dir(gid, strategy)
    meta = store.read_generation_meta(gid) or {}
    manifest = store.manifest(meta.get("template_id", ""))
    if manifest is None or not (vdir / "audit_report.json").exists():
        raise HTTPException(404, "variant or audit not found")
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, "autofix is already running for this variant")
        _fix_active.add(key)

    def run(job: Job) -> dict:
        from verstka.audit.autofix import autofix_loop
        from verstka.pipeline.generate import render_outputs

        try:
            ws = store.workspace(meta["template_id"])
            outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
            plan = LayoutPlan.model_validate_json((vdir / "layout_plan.json").read_text(encoding="utf-8"))
            report = AuditReport.model_validate_json((vdir / "audit_report.json").read_text(encoding="utf-8"))
            only = None if req.all_deterministic else set(req.issue_ids)
            job.emit("применяю исправления", 0.2)
            final, plan2, outline2, _ = autofix_loop(vdir / "deck.pptx", report, outline, plan, manifest, ws, max_iterations=2, only_ids=only, images_dir=vdir / "slides")
            job.emit("экспортирую", 0.8)
            # previews and the exports that existed before are rebuilt from one LibreOffice run
            exports = [fmt for fmt in ("pdf", "html") if (vdir / f"deck.{fmt}").exists()]
            _, images, warns, _ = render_outputs(vdir, manifest, outline2.title, exports, images=True)
            for w in warns:
                log.warning("re-export: %s", w)
            if images:
                final.slide_images = {k: str(p) for k, p in enumerate(images, 1)}
            (vdir / "audit_report.json").write_text(final.model_dump_json(indent=2), encoding="utf-8")
            (vdir / "outline.json").write_text(outline2.model_dump_json(indent=2), encoding="utf-8")
            (vdir / "layout_plan.json").write_text(plan2.model_dump_json(indent=2), encoding="utf-8")
            summary = meta.get("summary", {})
            summary[strategy] = {**summary.get(strategy, {}), "score": final.summary.score, "errors": final.summary.errors, "warnings": final.summary.warnings}
            meta["summary"] = summary
            store.write_generation_meta(gid, meta)
            return {"score": final.summary.score, "errors": final.summary.errors, "warnings": final.summary.warnings, "applied": final.applied_fixes}
        finally:
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("fix", run)
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
        raise HTTPException(404, "run manifest not found")
    ma = json.loads(pa.read_text(encoding="utf-8"))
    mb = json.loads(pb.read_text(encoding="utf-8"))
    return {"a": {"generation": gid, "strategy": strategy, "score": ma.get("audit", {}).get("score")}, "b": {"generation": other_gid, "strategy": other_strategy, "score": mb.get("audit", {}).get("score")}, "diff": diff_manifests(ma, mb)}


# ---------------------------------------------------------------------------- routes: chat agent

# "generate" is decided first: a brief pasted into the chat mentions audiences, plans, templates and audits all at once.
_GEN_RX = re.compile(r"сгенерируй|(сделай|собери|создай|подготовь)\s+(презентац|слайд|дек|колод)|\bgenerate\b", re.I)
_INTENT_RULES = [
    ("explain_slide", re.compile(r"(почему|объясни|как выбран|why).*слайд\w*\s*(\d+)|слайд\w*\s*(\d+).*(почему|объясни|why)", re.I)),
    ("fix_all", re.compile(r"(исправь|почини|поправь)\s+(вс|ошибк|замечан)|fix all|автофикс", re.I)),
    ("audit", re.compile(r"\bаудит(?!ор)\w*|\bпроверь|\bошибк|замечани|\baudit\b|\bissues\b", re.I)),
    ("export", re.compile(r"экспорт|скачать|\bpdf\b|\bhtml\b|download", re.I)),
    ("template", re.compile(r"\bшаблон|template|дизайн-систем|палитр|шрифт", re.I)),
    ("plan", re.compile(r"\bплан\w*|структур|какие слайды|outline|макет", re.I)),
]


def _looks_like_brief(text: str) -> bool:
    return len(text) > 200 or text.count("\n") >= 3


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
    if intent == "template":
        m = store.manifest(template_id) if template_id else None
        reply = describe_template(m) if m else "Загрузите шаблон (.pptx) — я разберу его дизайн-систему и паттерны слайдов."
    elif intent in ("plan", "explain_slide", "audit", "export") and gen_id:
        payload = _generation_payload(gen_id)
        variants = payload.get("variants", [])
        if not variants:
            reply = "Генерация ещё не завершена."
        else:
            v = variants[0]
            manifest = store.manifest(payload["template_id"])
            outline = DeckOutline.model_validate(v["outline"])
            plan = LayoutPlan.model_validate(v["plan"])
            if intent == "plan":
                titles = {s.name: s.title for s in load_strategies().values()}
                reply = "\n\n".join(describe_plan(DeckOutline.model_validate(vv["outline"]), LayoutPlan.model_validate(vv["plan"]), manifest, titles.get(vv["strategy"], vv["strategy"])) for vv in variants)
            elif intent == "explain_slide":
                reply = describe_slide_choice(outline, plan, manifest, int(params.get("index", 1)))
            elif intent == "audit":
                reply = "\n\n".join(f"Вариант «{vv['strategy']}». " + describe_audit(AuditReport.model_validate(vv["audit"])) for vv in variants if vv.get("audit"))
            else:
                reply = "Файлы готовы: " + "; ".join(f"{vv['strategy']}: " + ", ".join(vv["files"]) for vv in variants)
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
        reply = "Запустил автофикс для всех вариантов. Результаты появятся в панели аудита." if jobs else "Автофикс уже выполняется — дождитесь результатов в панели аудита."
        actions.append({"type": "jobs", "jobs": jobs})
    elif intent == "generate":
        if not template_id:
            reply = "Сначала загрузите шаблон, затем пришлите бриф — и я соберу три варианта презентации."
        else:
            brief_text = req.message
            r = create_generation(GenerateRequest(template_id=template_id, brief=brief_text, use_models=models_configured()))
            session["generation_id"] = r["generation_id"]
            reply = "Принял бриф. Извлекаю факты, планирую структуру, подбираю макеты шаблона и собираю три варианта — следите за прогрессом справа."
            actions.append({"type": "generation_started", "job_id": r["job_id"], "generation_id": r["generation_id"]})
    else:
        reply = (
            "Я помогу собрать презентацию в стиле вашего шаблона. Что умею: «расскажи о шаблоне», «сгенерируй презентацию: <бриф>», "
            "«почему слайд 4 такой», «покажи аудит», «исправь всё», «экспорт». Загрузите шаблон и пришлите бриф текстом."
        )
    session["history"].append({"role": "user", "text": req.message})
    session["history"].append({"role": "assistant", "text": reply})
    return {"reply": reply, "intent": intent, "actions": actions, "template_id": template_id, "generation_id": session.get("generation_id")}


# ---------------------------------------------------------------------------- static web app

_WEB_DIST = _REPO_ROOT / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
