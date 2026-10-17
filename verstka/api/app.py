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
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from verstka import __version__
from verstka.api.agent_view import describe_agent_work, describe_slide_design, job_progress, link_alternatives, read_agent_events, slide_design, variant_agent, write_agent_file
from verstka.api.jobs import Job, JobRunner
from verstka.api.model_status import ChainContext, active_chain_context, config_label, generation_planner, models_status, planner_info
from verstka.api.narrator import describe_audit, describe_plan, describe_slide_choice, describe_template
from verstka.api.store import BRAND_PARSING, SAFE_ID_RE, Store
from verstka.ingest.workspace import file_sha256
from verstka.planning.brief import normalize_purpose, parse_brief_text
from verstka.planning.strategies import STRATEGY_NAMES, load_strategies
from verstka.ru import ru_count
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.audit import AuditReport
from verstka.schemas.brand import BrandConflict, BrandPriority, BrandSpec
from verstka.schemas.data import DatasetProfile, DatasetSummary, Table
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


def _env_mb(name: str, default: float) -> int:
    try:
        mb = float(os.environ.get(name, str(default)))
    except ValueError:
        mb = default
    return int(mb * 1024 * 1024)


def _mb(limit: int) -> str:
    """Bytes as megabytes for people: «25», «0,5»."""
    return f"{round(limit / (1024 * 1024), 2):g}".replace(".", ",")


def max_upload_bytes() -> int:
    return _env_mb("VERSTKA_MAX_UPLOAD_MB", 200)


# вторая ступень: файлы с данными и брендбук. Файл с данными — как в интерфейсе (MAX_DATA_BYTES в web/src/ui/create/
# dataRules.ts), брендбук — файл, папка целиком или архив (распакованный — до _MAX_ZIP_UNPACKED)
def max_data_bytes() -> int:
    return _env_mb("VERSTKA_MAX_DATA_MB", 25)


def max_brandbook_bytes() -> int:
    return _env_mb("VERSTKA_MAX_BRAND_MB", 50)


# a file of each format reads, with its profile and preliminary choice, in ≤ ~10 s on this Mac (measured 16.10 through
# POST /api/datasets, 5 columns: CSV 24 MB / 500 000 rows — 7,4 s; JSON 24 MB — 4,4 s; text with a table 9,6 MB — 6,2 s,
# 24 MB — 11 s; a book of Excel 4,0 MB / 135 000 rows — 8,4 s, 4,7 MB — 10,7 s: openpyxl reads cell by cell)
def max_xlsx_bytes() -> int:
    return _env_mb("VERSTKA_MAX_XLSX_MB", 4)


def max_text_bytes() -> int:
    return _env_mb("VERSTKA_MAX_TEXT_MB", 15)


_MAX_DATA_FILES = 10  # файлов с данными за один запрос
_MAX_DATA_TABLES = 30  # таблиц (листов, ключей JSON, таблиц в тексте) из одного запроса
# строк одной таблицы, которые читаются в набор: дальше — «Прочитаны первые 200 000 строк из 640 000». Профиль и
# предварительный выбор 200 000 × 5 — ~3 с; у широких таблиц предел — по ячейкам
_MAX_DATA_ROWS = 200_000
_MAX_DATA_CELLS = 1_000_000
_MAX_GENERATION_DATASETS = 30  # наборов в одной сборке
_MAX_BRAND_FOLDER_FILES = 300  # файлов в папке брендбука
_MAX_ZIP_ENTRIES = 1000
_MAX_ZIP_UNPACKED = 200 * 1024 * 1024
_BRAND_EXTS = {".json", ".pdf", ".zip", ".pptx", ".potx", ".pptm", ".svg", ".png", ".jpg", ".jpeg", ".webp"}
# брендбук, чей разбор прервал перезапуск сервера (.parsing без brand.json), убирается при запуске, если он старше этого:
# разбор с моделью идёт до 150 с, а рабочую папку может делить ещё один сервер со своим разбором
_BRAND_SWEEP_AGE = 600.0
_SLACK = 1 << 20  # заголовки частей multipart сверх самих файлов


def _upload_cap(path: str) -> Optional[tuple[int, str]]:
    """The largest body an upload route can accept (all its files at their limits) and what to say past it — or None.
    Checked by Content-Length before the body is read (Starlette writes a multipart body to disk before the handler)."""
    if path == "/api/datasets":
        each = max_data_bytes()
        return _MAX_DATA_FILES * each + _SLACK, f"Файлы с данными больше {_mb(_MAX_DATA_FILES * each)} МБ за один раз — добавляйте их по одному, каждый до {_mb(each)} МБ"
    if path == "/api/brandbooks":
        limit = max_brandbook_bytes()
        return limit + _SLACK, f"Брендбук больше {_mb(limit)} МБ — сожмите картинки в PDF или загрузите токены JSON и логотипы архивом"
    if path == "/api/templates":
        limit = max_upload_bytes()
        return limit + _SLACK, f"Файл больше {_mb(limit)} МБ — уменьшите картинки в шаблоне или удалите лишние слайды"
    return None


class UploadSizeGate:
    """413 for an upload whose Content-Length is over its route's limit — before a byte of it is read or written."""

    def __init__(self, app_: Any) -> None:
        self.app = app_

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") == "http" and scope.get("method") == "POST":
            cap = _upload_cap(str(scope.get("path") or "").rstrip("/"))
            if cap is not None:
                raw = dict(scope.get("headers") or []).get(b"content-length")
                try:
                    length = int(raw) if raw is not None else None
                except ValueError:
                    length = None
                if length is not None and length > cap[0]:
                    await JSONResponse({"detail": cap[1]}, status_code=413, headers={"Connection": "close"})(scope, receive, send)
                    return
        await self.app(scope, receive, send)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _on_start()
    yield


def _on_start() -> None:
    """At launch: the models profile goes to the log (default_models_path logs it once), and the brandbooks a restart
    interrupted are cleared away."""
    from verstka.providers.registry import default_models_path

    try:
        default_models_path()
    except Exception:  # noqa: BLE001 - the server starts all the same; the status page says what is wrong
        log.warning("models profile not resolved at start", exc_info=True)
    try:
        swept = store.sweep_interrupted_brandbooks(_BRAND_SWEEP_AGE)
    except OSError:
        log.warning("interrupted brandbooks not swept", exc_info=True)
        swept = []
    if swept:
        log.info("swept %d brandbook(s) a restart interrupted: %s", len(swept), ", ".join(swept))


app = FastAPI(title="Verstka API", version=__version__, lifespan=_lifespan)
app.add_middleware(UploadSizeGate)  # inside CORS: its 413 carries the CORS headers too
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
# the deck's template was deleted from the library: nothing can be laid out again in it (fixes, edits, slide fixes)
_TEMPLATE_GONE = "Шаблона этой презентации больше нет в библиотеке — исправить её нельзя"


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
    # вторая ступень: файлы с данными (id из POST /api/datasets), брендбук (id из POST /api/brandbooks) и что важнее,
    # когда брендбук расходится с шаблоном: «brand» — брендбук (по умолчанию), «template» — бренд только дополняет шаблон
    dataset_ids: list[str] = Field(default_factory=list)
    brandbook_id: Optional[str] = None
    brand_priority: BrandPriority = "brand"


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


class RebuildBody(BaseModel):
    """«Пересобрать слайд так»: the slide's dataset shown with option `option` (0-based, the index in
    `OutlineSlide.data.options`, as «Почему так» lists them)."""

    option: int = Field(..., ge=0, le=20)


# ---------------------------------------------------------------------------- helpers


_RU_ERRORS = {
    "missing": "обязательное поле",
    "bool_parsing": "нужно «да» или «нет» (true / false)",
    "bool_type": "нужно «да» или «нет» (true / false)",
    "int_parsing": "нужно целое число",
    "int_type": "нужно целое число",
    "int_from_float": "нужно целое число",
    "float_parsing": "нужно число",
    "float_type": "нужно число",
    "string_type": "нужна строка",
    "list_type": "нужен список",
    "tuple_type": "нужен список",
    "dict_type": "нужен объект",
    "model_type": "нужен объект",
    "model_attributes_type": "нужен объект",
    "json_invalid": "запрос — не JSON",
    "json_type": "запрос — не JSON",
    "extra_forbidden": "лишнее поле",
    "none_required": "должно быть пустым",
}
_REQUEST_PARTS = ("body", "query", "path", "header", "cookie", "form")


def _ru_values(expected: str) -> str:
    """«'brand' or 'template'» → «brand» или «template» (eight values at most: a long list is cut with «…»)."""
    vals = re.findall(r"'([^']*)'", expected or "")
    if not vals:
        return ""
    shown = [f"«{v}»" for v in vals[:8]] + (["…"] if len(vals) > 8 else [])
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " или " + shown[-1]


def ru_validation_error(err: dict) -> str:
    """One pydantic error in Russian: what the value should be («нужно целое число», «нужно «brand» или «template»»)."""
    kind = str(err.get("type") or "")
    ctx = err.get("ctx") or {}
    msg = str(err.get("msg") or "")
    if kind in ("literal_error", "enum"):
        values = _ru_values(str(ctx.get("expected") or ""))
        if values:
            return f"нужно {values}"
    bounds = {"greater_than_equal": ("не меньше", "ge"), "greater_than": ("больше", "gt"), "less_than_equal": ("не больше", "le"), "less_than": ("меньше", "lt")}
    if kind in bounds and bounds[kind][1] in ctx:
        return f"{bounds[kind][0]} {ctx[bounds[kind][1]]}"
    if kind == "string_too_long" and "max_length" in ctx:
        return f"не длиннее {ru_count(int(ctx['max_length']), 'символа', 'символов', 'символов')}"
    if kind == "string_too_short" and "min_length" in ctx:
        return f"не короче {ru_count(int(ctx['min_length']), 'символа', 'символов', 'символов')}"
    if kind == "too_long" and "max_length" in ctx:
        return f"не больше {ctx['max_length']} элементов"
    if kind == "too_short" and "min_length" in ctx:
        return f"не меньше {ctx['min_length']} элементов"
    if "UploadFile" in msg:
        return "нужен файл"
    if kind in _RU_ERRORS:
        return _RU_ERRORS[kind]
    if kind == "value_error" and re.search(r"[А-Яа-яЁё]", msg):
        return re.sub(r"^Value error,\s*", "", msg)  # a validator's own words (ours are Russian)
    return "значение не подходит"


def _validation_message(e: Any, limit: int = 5) -> str:
    """Pydantic's (or a request's) errors for people: «brand_priority: нужно «brand» или «template»; slides: нужно целое
    число». The field's path stays as in the request (slides.0.kind) — the person or the client knows it by that name."""
    errors = e.errors()
    parts = []
    for err in errors[:limit]:
        loc = [x for x in err.get("loc", ()) if not (isinstance(x, str) and x in _REQUEST_PARTS)]
        # a field's path (slides.0.kind); a bare position — where the JSON broke — says nothing to a person
        where = ".".join(str(x) for x in loc) if any(isinstance(x, str) for x in loc) else ""
        text = ru_validation_error(err)
        parts.append(f"{where}: {text}" if where else text)
    more = len(errors) - limit
    return "; ".join(parts) + (f" (и ещё {more})" if more > 0 else "")


# the framework's own English words (Starlette's multipart limits, routing) said the API's way
_FRAMEWORK_RU = [
    (re.compile(r"Too many files\. Maximum number of files is (\d+)\."), lambda m: f"Слишком много файлов в одном запросе — до {m.group(1)}. Загрузите папку архивом .zip"),
    (re.compile(r"Too many fields\. Maximum number of fields is (\d+)\."), lambda m: f"Слишком много полей в одном запросе — до {m.group(1)}"),
    (re.compile(r"Part exceeded maximum size of (\d+)KB\."), lambda m: f"Поле запроса больше {m.group(1)} КБ"),
    (re.compile(r"There was an error parsing the body|Missing boundary in multipart\.|Invalid multipart"), lambda m: "Запрос не прочитан — отправьте его ещё раз"),
    (re.compile(r"Not Found"), lambda m: "Не найдено"),
    (re.compile(r"Method Not Allowed"), lambda m: "Такой запрос здесь не принимается"),
]


def ru_framework_detail(detail: str) -> str:
    for rx, say in _FRAMEWORK_RU:
        m = rx.fullmatch(detail.strip())
        if m:
            return say(m)
    return detail


@app.exception_handler(RequestValidationError)
async def _request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 in the API's own format — `detail` is one line for people, in Russian (not pydantic's English list)."""
    return JSONResponse({"detail": _validation_message(exc)}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """Every HTTP error as before; the framework's own English (multipart limits, «Not Found») said in Russian."""
    if isinstance(exc.detail, str):
        ru = ru_framework_detail(exc.detail)
        if ru != exc.detail:
            exc = StarletteHTTPException(exc.status_code, ru, headers=getattr(exc, "headers", None))
    return await http_exception_handler(request, exc)


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
    from verstka.audit.eyes import CODES, skip_code

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
    # why it did not look, by its code (eyes.SKIP_RU — the interface's words); runs before the code was kept: by the reason
    skipped = eyes.get("skipped")
    code = eyes.get("skipped_code") or skip_code(skipped)
    return {"looked": eyes.get("looked") or 0, "seconds": eyes.get("seconds"), "skipped": skipped, "skipped_code": code if skipped else None, "slides": slides}


def _slide_size(deck: Path) -> Optional[tuple[int, int]]:
    """The deck's slide size in EMU (ppt/presentation.xml `p:sldSz`); None when the file does not say.

    Intentionally unlike `PptxPackage.slide_size`, which falls back to 4:3 (9144000 × 6858000): a picture's box measured
    against a guessed size would frame it in the wrong place on a 16:9 slide, so a deck without `sldSz` gets no `bbox`
    at all. The XML is parsed without resolving entities (the deck is the person's upload)."""
    import zipfile

    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        with zipfile.ZipFile(deck) as z:
            root = etree.fromstring(z.read("ppt/presentation.xml"), parser)
        sz = root.find("{http://schemas.openxmlformats.org/presentationml/2006/main}sldSz")
        if sz is None:
            return None
        cx, cy = int(sz.get("cx")), int(sz.get("cy"))
    except (OSError, KeyError, ValueError, TypeError, zipfile.BadZipFile, etree.XMLSyntaxError):
        return None
    return (cx, cy) if cx > 0 and cy > 0 else None


def _pictures_of(vdir: Path) -> list[dict]:
    """The picture records for the interface, each with where its place is on the slide (`bbox`, slide fractions):
    the result screen frames the picture there and takes a click on it."""
    from verstka.images.fill import public_records, read_records

    records = read_records(vdir)
    out = public_records(records)
    size = _slide_size(vdir / "deck.pptx") if records else None
    for pub, rec in zip(out, records):
        box = rec.get("box")
        if size and isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(n, (int, float)) for n in box):
            w, h = size
            pub["bbox"] = {"x": round(box[0] / w, 5), "y": round(box[1] / h, 5), "w": round(box[2] / w, 5), "h": round(box[3] / h, 5)}
    return out


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


class InputGone(ValueError):
    """A file with data or a brandbook the request names is not on the server (any more) or not read yet: the message is
    for people, `status` — the HTTP status create_generation answers with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class GenerationData:
    """Вторая ступень: файлы с данными и брендбук запроса сборки. create_generation читает их из рабочей папки при запуске
    (и тем проверяет, что они есть), задача сборки получает их готовыми (`_run_generation`).

    - Таблицы и профили — в памяти: набор, удалённый во время сборки, ей не мешает. Колода-история (verstka/data/story.py)
      строится из них в начале задачи, после неё `_run_generation` их отпускает (остаются планы и слайды).
    - Брендбук: `brand` (BrandSpec) — в памяти, а файлы логотипов — на диске, в `brand_dir` (brandbooks/<id>/). Задача
      первым делом копирует их в папку сборки (`_brand_files` → runs/<gid>/brand/) и брендирует шаблон уже оттуда:
      удалить брендбук после этого можно. Если его удалили раньше — между запуском и копированием, — копия шаблона
      собирается без логотипов (предупреждение в журнале), цвета и шрифты остаются."""

    dataset_ids: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    profiles: list[DatasetProfile] = field(default_factory=list)
    brand: Optional[BrandSpec] = None
    brand_dir: Optional[Path] = None  # логотипы брендбука (BrandLogo.file — пути от неё)
    brand_priority: BrandPriority = "brand"

    @property
    def empty(self) -> bool:
        return not self.tables and self.brand is None

    def describe(self) -> dict:
        """What generation.json keeps of them besides the ids: the files' and the brandbook's names for people."""
        out: dict = {}
        if self.tables:
            out["datasets"] = [{"id": i, "file": t.file, "sheet": t.sheet, "kind": t.kind} for i, t in zip(self.dataset_ids, self.tables)]
        if self.brand is not None:
            out["brandbook"] = {"id": self.brand.id, "name": self.brand.name, "file": self.brand.file, "source": self.brand.source}
        return out


def _generation_data(req: GenerateRequest) -> GenerationData:
    """The request's datasets and brandbook read from the workspace; InputGone when one is missing."""
    ids = list(dict.fromkeys(req.dataset_ids))
    if len(ids) > _MAX_GENERATION_DATASETS:
        raise InputGone(422, f"Слишком много файлов с данными: {len(ids)} — в одну презентацию до {_MAX_GENERATION_DATASETS}")
    data = GenerationData(dataset_ids=ids, brand_priority=req.brand_priority)
    for did in ids:
        loaded = store.read_dataset(did) if isinstance(did, str) else None
        if loaded is None:
            raise InputGone(404, "Одного из файлов с данными больше нет на сервере — приложите его снова")
        data.tables.append(loaded[0])
        data.profiles.append(loaded[1])
    if req.brandbook_id:
        bid = req.brandbook_id
        spec = store.read_brandbook(bid)
        if spec is None:
            if _brand_parsing(bid):
                raise InputGone(409, "Брендбук ещё разбирается — подождите несколько секунд и соберите снова")
            raise InputGone(404, "Брендбука больше нет на сервере — загрузите его снова")
        data.brand = spec
        data.brand_dir = store.brandbook_dir(bid)
    return data


def _run_generation(gid: str, gdir: Path, req: GenerateRequest, job: Job, data: Optional[GenerationData] = None) -> dict:
    from verstka.pipeline.generate import generate_variants

    manifest = store.manifest(req.template_id)
    if manifest is None:
        raise ValueError("Шаблон ещё не разобран — загрузите его снова")
    # вторая ступень: файлы с данными и брендбук запроса (create_generation уже прочитал их): брендбук — брендированная
    # копия шаблона, на которой вёрстка идёт как на любом шаблоне; данные — колода-история (verstka/data/story.py)
    if data is None:
        data = _generation_data(req)
    progress = job_progress(job)
    template_id = req.template_id
    steps: dict = {}  # the steps before the pipeline (brandbook, data story): their seconds go into the run manifest
    if data.brand is not None:
        tb = time.monotonic()
        template_id = _branded_template_id(req, data, gdir, progress)
        manifest = store.manifest(template_id) or manifest
        steps["brand"] = time.monotonic() - tb
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
    described = data.describe()
    story = None
    if data.tables and outline is None:
        from verstka.data.story import build_data_story

        story = build_data_story(
            brief, data.tables, profiles=data.profiles, dataset_ids=data.dataset_ids, manifest=manifest, use_llm=use_models,
            skills=skills() if use_models else None, providers=providers() if use_models else None, progress=progress,
        )
        outline, brief = story.outline, None  # the figures of a data deck are checked against the data, not the text
        steps["data"] = story.seconds
        data.tables, data.profiles = [], []  # the rows are not needed any more: only the plans and the slides stay
    # «Улучшить готовую» laid out in another template: the original deck's pictures come from its own workspace
    source_pictures = None
    src_tid = (req.improved_from or {}).get("template_id")
    if src_tid and src_tid != req.template_id:
        try:
            source_pictures = store.workspace(str(src_tid)).dir
        except FileNotFoundError:
            source_pictures = None
    res = generate_variants(
        store.workspace(template_id).source,
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
        progress=progress,
        pictures=req.pictures,
        image_provider=image_provider() if req.pictures is not False else None,
    )
    from verstka.data.story import stamp_steps

    stamp_steps(res, steps)  # the brandbook and the data story: part of the run's time (timings_s.brand / .data, total)
    if data.brand is not None and req.brandbook_id:
        # the brandbook's read (its own job) — its model calls are part of this deck's usage (qa3 E4)
        bdir_ = store.brandbook_dir(str(req.brandbook_id))
        try:
            brand_usage = json.loads((bdir_ / BRAND_USAGE).read_text(encoding="utf-8")) if bdir_ is not None and (bdir_ / BRAND_USAGE).exists() else None
        except (OSError, ValueError):
            brand_usage = None
        if brand_usage:
            from verstka.data.story import stamp_usage

            stamp_usage(res, None, "brand", usage=brand_usage)
    if story is not None:
        from verstka.data.story import stamp_variants

        stamp_variants(res, story, gdir)  # who wrote the plan (the data analyst, with the model or not), data_story.json
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
        # the template the deck was laid out on (a brandbook's: its branded copy — fixes and edits lay out in it too)
        "template_id": template_id,
        **({"base_template_id": req.template_id} if template_id != req.template_id else {}),
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
        **described,
        **({"data_story": story.summary()} if story is not None else {}),
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


def _brand_files(data: GenerationData, gdir: Path) -> Optional[Path]:
    """The brandbook's logo files copied into the generation's own folder (gdir/brand/): a brandbook deleted while the
    deck is built cannot take its logos away (BrandLogo.file — paths from that folder)."""
    if data.brand is None or data.brand_dir is None:
        return data.brand_dir
    dst = gdir / "brand"
    src = Path(data.brand_dir)
    if src == dst:
        return dst  # copied already (create_generation, before the job started)
    for logo in data.brand.logos:
        rel = PurePosixPath(str(logo.file or ""))
        if not rel.parts or rel.is_absolute() or ".." in rel.parts:
            continue
        try:
            target = dst.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src.joinpath(*rel.parts), target)
        except OSError:
            log.warning("brand logo not copied: %s", rel)  # (gone already: the copy is made without it)
    dst.mkdir(parents=True, exist_ok=True)
    return dst


def _branded_template_id(req: GenerateRequest, data: GenerationData, gdir: Path, progress: Callable[..., None]) -> str:
    """The template the deck is laid out on when a brandbook is attached: the branded copy of the request's template
    (verstka/brand/apply.py, cached; «Собрать ещё раз» on a branded copy brands its base template, never the copy)."""
    from verstka.brand.apply import branded_info, branded_template

    base = req.template_id
    info = branded_info(base, store.root)
    if info and info.get("base_template_id") and store.manifest(str(info["base_template_id"])) is not None:
        base = str(info["base_template_id"])
    brand_dir = _brand_files(data, gdir)
    progress("brand: применяю брендбук к шаблону", 0.01)
    return branded_template(
        base, data.brand, data.brand_priority, workspace_root=store.root, brand_dir=brand_dir,
        progress=lambda stage, frac: progress(f"brand: {stage}", 0.01 + 0.04 * float(frac or 0.0)),
    )


def _request_options(req: GenerateRequest) -> dict:
    """The request's switches, kept in generation.json: «Собрать ещё раз» repeats the deck with the same inputs."""
    return {"audit_models": req.audit_models, "autofix": req.autofix, "exports": list(req.exports), "language": req.language, "extra_instructions": req.extra_instructions, "outline_supplied": req.outline is not None, "pictures": req.pictures, "eyes": req.eyes, "improved_from": req.improved_from,
            "dataset_ids": list(req.dataset_ids), "brandbook_id": req.brandbook_id, "brand_priority": req.brand_priority}


def _generation_job(gid: str, gdir: Path, req: GenerateRequest, data: Optional[GenerationData] = None) -> Callable[[Job], dict]:
    """Wrap the pipeline so generation.json always ends in status done or failed (the UI lists both)."""

    def run(job: Job) -> dict:
        store.merge_generation_meta(gid, {"status": "running", "job_id": job.id})
        try:
            return _run_generation(gid, gdir, req, job, data)
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
    """Which variables the t2i role needs (for the log), by its links in order: VK's own model (VK_T2I_MODEL with the
    VK inference keys — without VK_T2I_MODEL that link is off), then Polza's Z-Image (POLZA_API_KEY)."""
    p = image_provider()
    names = [getattr(lk, "name", "") for lk in (getattr(p, "links", None) or [])]
    need: list[str] = []
    for name in names:
        if name == "openai_images":
            need.append("VK_T2I_MODEL with VK_INFERENCE_API_KEY and VK_PROJECT_ID")
        elif name == "polza_media":
            need.append("POLZA_API_KEY")
    if not need:
        return "a t2i role in the models config (configs/models.yaml)" if p is None else "POLZA_API_KEY in .env"
    return " or ".join(dict.fromkeys(need)) + " in .env"


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
    try:
        dt = deck_text(ws.source)
    except Exception as e:  # noqa: BLE001 - the interface says it in Russian; the deck stays in the library as a template
        log.warning("deck text not read: %s", ws.source, exc_info=True)
        raise ValueError("Не удалось прочитать текст презентации — она добавлена как шаблон") from e
    try:
        keep_pictures(dt, ws.dir / "source_images")
    except Exception:  # noqa: BLE001 - the text stands; the places of its pictures stay free
        log.warning("pictures of the deck not kept", exc_info=True)
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
    """«Слайд N. Заголовок» lines of a read-back deck: slide number → its title (a cover written as «Слайд 1.
    Титульный» / «Название: «…».» by its name). A heading line ends where its line ends."""
    out = {}
    for m in re.finditer(r"^Слайд[ \t]+(\d+)\.[ \t]*(.*)$", brief or "", re.M):
        title = m.group(2).strip()
        named = re.match(r"\n[ \t]*Название:[ \t]*(.+)$", (brief or "")[m.end() :], re.M)
        if named and (not title or title == "Титульный"):
            title = named.group(1).strip().rstrip(".").strip().strip("«»").strip()
        out[int(m.group(1))] = title
    return out


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str) -> dict:
    """Delete a template from the library (the trash button on its tile, after a confirmation). Not while a deck is
    being built on it or the template is still being analysed."""
    try:
        store.workspace(template_id)
    except FileNotFoundError:
        raise HTTPException(404, "Шаблон не найден")
    # its branded copies go with it (store.delete_template): a deck built on one of them holds the template too
    ids = {template_id, *store.branded_copies(template_id)}
    if any(g.get("template_id") in ids and _settle_orphan(g).get("status") == "running" for g in store.list_generations()):
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


# ---------------------------------------------------------------------------- routes: data files (вторая ступень)

_BAD_NAME_CHARS = re.compile(r'[\x00-\x1f\x7f\\/:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_NAME_MAX = 120


def _cut_name(name: str) -> str:
    """At most _NAME_MAX characters, the extension kept."""
    if len(name) <= _NAME_MAX:
        return name
    stem, dot, ext = name.rpartition(".")
    ext = ext if dot and stem and len(ext) <= 10 else ""
    return (stem if ext else name)[: _NAME_MAX - len(ext) - 1].rstrip() + (f".{ext}" if ext else "")


def safe_file_name(raw: Optional[str], fallback: str) -> str:
    """A name that becomes a path (a brandbook's file or a part of its folder — BrandSpec.file is it too), safe as one
    path segment: no folders, no characters a file system refuses, not hidden, at most _NAME_MAX characters."""
    base = re.split(r"[\\/]", raw or "")[-1]
    name = " ".join(_BAD_NAME_CHARS.sub(" ", base).split()).lstrip(". ").strip()
    return _cut_name(name) if name else fallback


def data_file_name(raw: Optional[str], fallback: str = "данные") -> str:
    """A data file's name as the person gave it — the card and «Источник: …» under the chart: without its folders and
    control characters, everything else kept («Отчёт: продажи?.csv»). It never becomes a path (the file is kept as
    datasets/<id>/source.<ext>)."""
    base = re.split(r"[\\/]", raw or "")[-1]
    name = " ".join(_CONTROL_CHARS.sub(" ", base).split())
    return _cut_name(name) if name.strip(". ") else fallback


def _ext_of(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _dataset_issues(profile: DatasetProfile, cut: Optional[str] = None) -> list[str]:
    """What the card says is notable in the data, shortly: «Прочитаны первые 200 000 строк из 640 000», «Не для
    графика: …», «2 пропуска», «3 выброса»."""
    out: list[str] = [cut] if cut else []
    if not profile.typable:
        out.append(f"Не для графика: {profile.untypable_reason or 'данные не складываются в график'}")
    gaps = len(profile.time_axis.missing_periods) if profile.time_axis else 0
    missing = gaps or profile.missing_total
    if missing:
        out.append(ru_count(missing, "пропуск", "пропуска", "пропусков"))
    if profile.outliers:
        out.append(ru_count(len(profile.outliers), "выброс", "выброса", "выбросов"))
    return out


def _dataset_summary(did: str, table: Table, profile: DatasetProfile, cut: Optional[str] = None) -> DatasetSummary:
    return DatasetSummary(id=did, file=table.file, kind=table.kind, rows=profile.rows, cols=profile.cols, nature=profile.nature, line=profile.summary, issues=_dataset_issues(profile, cut), sheet=table.sheet)


def _cap_rows(table: Table) -> tuple[Table, Optional[str]]:
    """A very large table keeps its first rows (_MAX_DATA_ROWS, fewer for a wide one: _MAX_DATA_CELLS) — the profile,
    the choice and the deck work on them; the card says so: «Прочитаны первые 200 000 строк из 640 000»."""
    n = len(table.rows)
    cap = max(1000, min(_MAX_DATA_ROWS, _MAX_DATA_CELLS // max(1, len(table.columns))))
    if n <= cap:
        return table, None
    update: dict[str, Any] = {"rows": table.rows[:cap], "totals": [i for i in table.totals if i < cap]}
    row_units = getattr(table, "row_units", None)
    if row_units:
        update["row_units"] = list(row_units)[:cap]
    word = ru_count(cap, "строка", "строки", "строк").split(" ", 1)[1]
    return table.model_copy(update=update), f"Прочитаны первые {_grouped(cap)} {word} из {_grouped(n)}"


def _preliminary_plan(table: Table, profile: DatasetProfile) -> Optional[dict]:
    """The choice without the text's goals (the build makes the real one with them): computed once — at the upload, or
    at the first GET of a dataset kept before plan.json — then read from plan.json."""
    try:
        from verstka.data.plan import plan_dataset

        return plan_dataset(profile, table).model_dump(mode="json")
    except Exception:  # noqa: BLE001 - the card and the profile stand without the preliminary choice
        log.warning("preliminary plan failed: %s", table.id, exc_info=True)
        return None


_OTHER_ZIPS = {".zip", ".docx", ".pptx", ".odt", ".ods", ".odp", ".key", ".numbers", ".pages"}  # the reader refuses these by name


def _is_excel(name: str, data: bytes) -> bool:
    """A book of Excel by its bytes (a ZIP) — an «.xlsx» that is really text reads as fast as a CSV."""
    return data[:4] == b"PK\x03\x04" and _ext_of(name) not in _OTHER_ZIPS


def _slow_format_limit(name: str, data: bytes) -> Optional[tuple[int, str]]:
    """Formats that read slower than a CSV have a smaller limit (max_xlsx_bytes, max_text_bytes) and their own words."""
    if _is_excel(name, data):
        limit = max_xlsx_bytes()
        return limit, f"Книга Excel «{name}» больше {_mb(limit)} МБ — сохраните нужный лист как CSV (он прочитается быстрее) или оставьте в книге только нужные листы"
    if _ext_of(name) in (".txt", ".md", ".markdown"):
        limit = max_text_bytes()
        return limit, f"Текст «{name}» больше {_mb(limit)} МБ — сохраните таблицу из него как CSV (она прочитается быстрее)"
    return None


def _grouped(n: int) -> str:
    """640000 → «640 000» (a no-break space between the groups, as the profile writes numbers)."""
    return f"{n:,}".replace(",", "\u00a0")


def _profile_of(table: Table) -> DatasetProfile:
    """The table's profile; a table the profile cannot make sense of is still a card — «не для графика» with the reason."""
    from verstka.data.profile import profile_table

    try:
        return profile_table(table)
    except Exception:  # noqa: BLE001 - the person sees a card with the reason, not a server error
        log.warning("profile failed: %s", table.file, exc_info=True)
    rows, cols = len(table.rows), len(table.columns)
    reason = "не удалось разобрать колонки"
    return DatasetProfile(
        table_id=table.id, file=table.file, kind=table.kind, sheet=table.sheet, rows=rows, cols=cols, nature="untypable", typable=False, untypable_reason=reason,
        summary=f"Не для графика · {ru_count(rows, 'строка', 'строки', 'строк')} · {ru_count(cols, 'колонка', 'колонки', 'колонок')}",
    )


def _read_tables(name: str, data: bytes, several: bool) -> list[Table]:
    """The file's tables (verstka/data/readers.py); a file that is not a table → 400 with the reader's own words."""
    from verstka.data.readers import DataReadError, read_bytes

    prefix = f"«{name}»: " if several else ""
    try:
        tables = read_bytes(name, data)
    except DataReadError as e:
        msg = str(e).strip() or "файл не читается как таблица"
        raise HTTPException(400, prefix + (msg[:1].lower() + msg[1:] if prefix else msg))
    except Exception:  # noqa: BLE001 - a reader's slip on a broken file: said in words, not as a server error
        log.warning("data file not read: %s", name, exc_info=True)
        raise HTTPException(400, f"Не удалось прочитать «{name}» как таблицу — проверьте, что файл не повреждён, или сохраните его как CSV или XLSX")
    if not tables:
        raise HTTPException(400, prefix + ("н" if prefix else "Н") + "е нашёл таблицу в файле")
    return tables


@app.post("/api/datasets")
def upload_datasets(files: Optional[list[UploadFile]] = File(None)) -> list[dict]:
    """Файлы с данными (CSV, TSV, XLSX, JSON, текст с таблицей): чтение и профиль — сразу, по карточке на таблицу (у книги
    XLSX — на лист). Хранение — datasets/<id>/{source.<ext>, table.json, profile.json}. Ошибка — 4xx с текстом для
    человека; файл, который читается, но не годится для графика, — карточка с причиной в `issues`."""
    uploads = [f for f in files or [] if f is not None]
    if not uploads:
        raise HTTPException(400, "Выберите файл с данными: CSV, XLSX, JSON или текст с таблицей")
    if len(uploads) > _MAX_DATA_FILES:
        raise HTTPException(413, f"За один раз — до {_MAX_DATA_FILES} файлов с данными, а выбрано {len(uploads)}. Добавьте остальные следующим шагом")
    limit = max_data_bytes()
    several = len(uploads) > 1
    created: list[str] = []
    out: list[dict] = []
    try:
        for f in uploads:
            name = data_file_name(f.filename)
            data = f.file.read(limit + 1)
            if len(data) > limit:
                raise HTTPException(413, f"«{name}» больше {_mb(limit)} МБ — оставьте в файле только нужные строки и листы")
            slow = _slow_format_limit(name, data)
            if slow is not None and len(data) > slow[0]:
                raise HTTPException(413, slow[1])
            tables = _read_tables(name, data, several)
            if len(created) + len(tables) > _MAX_DATA_TABLES:
                raise HTTPException(413, f"Слишком много таблиц за один раз — до {_MAX_DATA_TABLES}. Оставьте в книге только нужные листы")
            source: Optional[Path] = None
            for t in tables:
                did, _ = store.new_dataset_dir()
                created.append(did)
                # the table is known by its dataset's id: SlideData.dataset_id, the card and the request say the same
                t, cut = _cap_rows(t.model_copy(update={"id": did}))
                profile = _profile_of(t)
                summary = _dataset_summary(did, t, profile, cut).model_dump(mode="json")
                saved = store.write_dataset(did, t, profile, source=source, data=None if source else data, ext=_ext_of(name),
                                            plan=_preliminary_plan(t, profile), summary=summary)
                source = source or saved
                out.append(summary)
    except BaseException:
        for did in created:
            store.delete_dataset(did)
        raise
    return out


@app.get("/api/datasets/{did}")
def get_dataset(did: str) -> dict:
    """Карточка набора, его профиль и предварительный выбор (без целей из текста: их учитывает сборка) — как их
    посчитала загрузка (summary.json, profile.json, plan.json); таблица читается, только если чего-то из них нет."""
    profile = store.read_dataset_profile(did)
    if profile is None:
        raise HTTPException(404, "Файл с данными не найден — приложите его снова")
    summary = store.read_dataset_json(did, "summary.json")
    plan = store.read_dataset_json(did, "plan.json")
    if summary is None or plan is None:  # a dataset kept before these files: they are made once, now
        loaded = store.read_dataset(did)
        if loaded is None:
            raise HTTPException(404, "Файл с данными не найден — приложите его снова")
        table = loaded[0]
        if summary is None:
            summary = _dataset_summary(did, table, profile).model_dump(mode="json")
            store.write_dataset_json(did, "summary.json", summary)
        if plan is None:
            plan = _preliminary_plan(table, profile)
            if plan is not None:
                store.write_dataset_json(did, "plan.json", plan)
    return {**summary, "id": did, "profile": profile.model_dump(mode="json"), "plan": plan}


@app.delete("/api/datasets/{did}")
def delete_dataset(did: str) -> dict:
    if not SAFE_ID_RE.fullmatch(did):
        raise HTTPException(404, "Файл с данными не найден")
    return {"deleted": store.delete_dataset(did)}


# ---------------------------------------------------------------------------- routes: brandbooks (вторая ступень)

_BRAND_STEPS = ("open", "palette", "fonts", "logos", "rules")  # шаги разбора (web: dataRules.ts BRAND_STEPS) и «compare»
_BRAND_STEP_AT = (0.3, 0.45, 0.6, 0.72, 0.84)
_BRAND_REMOVED = "Брендбук убрали, пока он разбирался"


def _vlm_configured() -> bool:
    """A vision model with a key: a PDF brandbook is read by the model too (without one — by its text)."""
    p = providers()
    if p is None or not p.has("vlm"):
        return False
    try:
        v = p.get("vlm")
        return v.name == "mock" or bool(getattr(v, "api_key", ""))
    except Exception:  # noqa: BLE001
        return False


def _brand_parsing(bid: str) -> bool:
    """The brandbook is being read now by a job of this server (a restart drops the job: the brandbook is gone)."""
    jid = store.brandbook_parsing(bid)
    if jid is None:
        return False
    if not jid:  # the job is being submitted this very moment
        d = store.brandbook_dir(bid)
        try:
            return d is not None and time.time() - (d / BRAND_PARSING).stat().st_mtime < 60
        except OSError:
            return False
    job = runner.get(jid)
    return job is not None and job.status in ("queued", "running")


def _brandbook_or_error(bid: str) -> BrandSpec:
    spec = store.read_brandbook(bid)
    if spec is not None:
        return spec
    if _brand_parsing(bid):
        raise HTTPException(409, "Брендбук ещё разбирается — подождите несколько секунд")
    raise HTTPException(404, "Брендбук не найден — загрузите его снова")


def _brand_conflicts(manifest: TemplateManifest, spec: BrandSpec, brand_dir: Optional[Path]) -> list[BrandConflict]:
    """Where the brandbook and the template differ, and what the deck gets with «брендбук важнее» (the web shows
    «шаблон важнее» by itself)."""
    from verstka.brand.conflicts import brand_conflicts

    return brand_conflicts(manifest, spec, priority="brand", workspace_root=store.root, brand_dir=brand_dir)


def _conflicts_with(spec: BrandSpec, template_id: Optional[str], brand_dir: Optional[Path]) -> tuple[Optional[TemplateManifest], list[BrandConflict]]:
    """The template to compare with (None — none chosen or not analysed) and the brandbook's conflicts with it."""
    if not template_id:
        return None, []
    try:
        manifest = store.manifest(template_id)
    except Exception:  # noqa: BLE001 - a broken analysis: nothing to compare with
        log.warning("template %s unreadable for brand conflicts", template_id, exc_info=True)
        manifest = None
    if manifest is None:
        return None, []
    try:
        return manifest, _brand_conflicts(manifest, spec, brand_dir)
    except Exception:  # noqa: BLE001 - the brandbook stands; the layer shows no conflicts
        log.warning("brand conflicts failed: %s × %s", spec.id, template_id, exc_info=True)
        return manifest, []


_BRAND_COMPARE_AT = 0.96
# the reader's words of its steps (verstka.brand.common.step_texts) → the client's keys; «открыт…» / «прочитаны токены» — open.
# «страница N из M», «модель читает N страниц» — the reading's progress, not steps
_BRAND_STEP_WORDS = {"палитра": "palette", "шрифты": "fonts", "логотипы": "logos", "правила": "rules"}
_PAGE_RE = re.compile(r"(\d+)\s+из\s+(\d+)")


def brand_step_key(what: str) -> Optional[str]:
    w = (what or "").strip().lower()
    if w in _BRAND_STEP_WORDS:
        return _BRAND_STEP_WORDS[w]
    return "open" if w.startswith(("открыт", "прочитаны")) else None


class BrandStepEvents:
    """The reader's `on_step(что, итог, часть)` → the job's events, as the client folds them (web/src/ui/create/dataRules.ts
    foldBrandEvent): a step — `step` (open · palette · fonts · logos · rules), `message` «Палитра: 6 цветов», `brand` — the
    part read; the reading's progress («страница 3 из 6», «модель читает 6 страниц») — `progress` with a calm message under
    the current step, never far enough to count as the next one (the client counts floor(progress × 6) steps done). A step
    the reader says again (the model refined the colours) is said again: the client keeps the latest words."""

    def __init__(self, job: Job, bid: str) -> None:
        self.job, self.bid = job, bid
        self.done = 0  # steps said, as the client counts them: the index of the latest + 1
        self.said: set[str] = set()
        self.at = 0.05
        self._lock = threading.Lock()

    def __call__(self, what: str, result: str, part: Optional[dict] = None) -> None:
        key = brand_step_key(what)
        if key is None:
            self.progress(what, result)
        else:
            self.step(key, f"{what[:1].upper()}{what[1:]}: {result}", part)

    def step(self, key: str, message: str, part: Optional[dict]) -> None:
        i = _BRAND_STEPS.index(key)
        with self._lock:
            self.done = max(self.done, i + 1)
            self.said.add(key)
            self.at = max(self.at, _BRAND_STEP_AT[i])
            brand = {"id": self.bid, **(part or {})} if key == "open" else part
            self.job.emit(message, self.at, step=key, brand=brand)

    def progress(self, what: str, result: str) -> None:
        w = (what or "").strip().lower()
        if w == "страница":
            message = f"Готовлю страницы для модели — {result}"
        elif w == "модель":
            message = f"Модель {result} — это до двух минут"
        else:
            message = f"{what[:1].upper()}{what[1:]}: {result}" if result else what
        with self._lock:
            base = _BRAND_STEP_AT[self.done - 1] if self.done else 0.05
            nxt = _BRAND_STEP_AT[self.done] if self.done < len(_BRAND_STEPS) else _BRAND_COMPARE_AT
            top = min(nxt, (self.done + 1) / 6) - 0.006  # below the next step, and below what the client counts as one
            m = _PAGE_RE.search(result or "")
            share = min(1.0, int(m.group(1)) / max(1, int(m.group(2)))) * 0.9 if m and w == "страница" else 1.0
            self.at = max(self.at, min(top, base + (top - base) * share))
            self.job.emit(message, round(self.at, 3))

    def finish(self, spec: BrandSpec) -> None:
        """The steps the reader did not say (a reader without on_step): said now, from the brandbook read."""
        from verstka.brand.read import brand_partials, brand_steps

        for key, (what, result), part in zip(_BRAND_STEPS, brand_steps(spec), brand_partials(spec)):
            if key not in self.said:
                self.step(key, f"{what[:1].upper()}{what[1:]}: {result}", part)


def _save_limited(f: UploadFile, target: Path, limit: int) -> int:
    """Copy an upload to `target` in chunks; more than `limit` bytes → -1 (the caller says how much is allowed)."""
    size = 0
    with open(target, "wb") as out:
        while chunk := f.file.read(_UPLOAD_CHUNK):
            size += len(chunk)
            if size > limit:
                return -1
            out.write(chunk)
    return size


def _check_zip(path: Path, name: str) -> None:
    """A brandbook archive within the limits by its directory, before anything is unpacked (the reader also counts the
    bytes it really writes)."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, OSError, ValueError):
        raise HTTPException(400, f"Архив «{name}» повреждён или это не ZIP")
    if not infos:
        raise HTTPException(400, f"Архив «{name}» пустой")
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise HTTPException(413, f"В архиве «{name}» больше {_MAX_ZIP_ENTRIES} файлов — оставьте в нём логотипы, токены, гайдлайн и примеры слайдов")
    if sum(max(0, i.file_size) for i in infos) > _MAX_ZIP_UNPACKED:
        raise HTTPException(413, f"Архив «{name}» в распакованном виде больше {_mb(_MAX_ZIP_UNPACKED)} МБ — уберите из него лишнее")


def folder_path(raw: Optional[str]) -> Optional[PurePosixPath]:
    """A file of an uploaded folder by its relative path («Брендбук/logos/main.svg»), every part a safe name. None — a
    file to skip (hidden, system, deeper than 8 levels); «..» anywhere → 400."""
    parts = [p for p in re.split(r"[\\/]", raw or "") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise HTTPException(400, "В папке брендбука есть файл с недопустимым путём — загрузите папку заново или архивом .zip")
    if not parts or len(parts) > 8 or any(p.startswith((".", "__MACOSX", "~$")) for p in parts):
        return None
    return PurePosixPath(*(safe_file_name(p, "файл") for p in parts))


def _brandbook_source(bdir: Path, file: Optional[UploadFile], files: list[UploadFile], figma_url: Optional[str]) -> Path | str:
    """Save the upload under brandbooks/<id>/source/ (or check the Figma link): what read_brandbook reads."""
    from verstka.brand.figma import FIG_FILE, normalize_url
    from verstka.brand.read import SUPPORTED

    limit = max_brandbook_bytes()
    src = bdir / "source"
    src.mkdir()
    if figma_url:
        url = normalize_url(figma_url.strip())
        if url is None:
            raise HTTPException(400, "Ссылка не похожа на файл Figma — скопируйте её из адресной строки: figma.com/design/… или figma.com/file/…")
        return url
    if file is not None:
        name = safe_file_name(file.filename, "брендбук")
        ext = _ext_of(name)
        if ext == ".fig":
            raise HTTPException(400, FIG_FILE)
        if ext not in _BRAND_EXTS:
            raise HTTPException(400, f"Формат «{ext or name}» для брендбука не подходит. Подойдут: {SUPPORTED}.")
        path = src / name
        size = _save_limited(file, path, limit)
        if size < 0:
            raise HTTPException(413, f"Брендбук больше {_mb(limit)} МБ — сожмите картинки в PDF или загрузите токены JSON и логотипы архивом")
        if size == 0:
            raise HTTPException(400, f"Файл «{name}» пустой — выберите брендбук ещё раз")
        if ext == ".zip":
            _check_zip(path, name)
        return path
    # a folder: each part's name is its path inside the folder («Брендбук VK Cloud/logos/primary.svg»)
    if len(files) > _MAX_BRAND_FOLDER_FILES:
        raise HTTPException(413, f"В папке брендбука больше {_MAX_BRAND_FOLDER_FILES} файлов — оставьте логотипы, токены, гайдлайн и примеры слайдов или загрузите архив .zip")
    rels = [(folder_path(f.filename), f) for f in files]
    kept = [(rel, f) for rel, f in rels if rel is not None]
    if not kept:
        raise HTTPException(400, "Папка брендбука пустая — в ней нужны токены JSON, PDF-гайдлайн, логотипы или примеры слайдов")
    tops = {rel.parts[0] for rel, _ in kept}
    # one folder chosen in the browser: its files all start with its name; loose files go into a folder of their own
    wrap = None if len(tops) == 1 and all(len(rel.parts) > 1 for rel, _ in kept) else "Брендбук"
    left = limit
    for rel, f in kept:
        target = src.joinpath(*((wrap,) if wrap else ()), *rel.parts)
        clash = HTTPException(400, f"В папке брендбука файл и папка называются одинаково («{rel.as_posix()}») — переименуйте один из них или загрузите папку архивом .zip")
        if target.is_dir():
            raise clash  # «a/b.png», then «a»; names that clean to the same one («a?», «a*») too
        if target.exists():
            continue  # the same path twice: the first one stays
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            size = _save_limited(f, target, left)
        except OSError:
            raise clash  # «a», then «a/b.png»: a file stands where a folder should go
        if size < 0:
            raise HTTPException(413, f"Папка брендбука больше {_mb(limit)} МБ — уберите из неё лишнее или загрузите архив .zip")
        left -= size
    return src / (wrap or next(iter(tops)))


def _brand_opened(source: Path | str) -> Optional[tuple[str, dict]]:
    """The «open» step said before the reading of a folder or an archive: their reader says its steps at its end (a PDF
    inside — after the model's reading). A PDF's reader says «open» itself as soon as its text is read. None — nothing
    to say before."""
    if isinstance(source, str):
        return None  # a Figma link: nothing is open before the answer
    try:
        if source.is_dir():
            n = sum(1 for p in source.rglob("*") if p.is_file())
            return f"Открыта папка: {ru_count(n, 'файл', 'файла', 'файлов')}", {"source": "folder", "file": source.name}
        ext = source.suffix.lower()
        if ext == ".zip":
            import zipfile

            with zipfile.ZipFile(source) as z:
                n = sum(1 for i in z.infolist() if not i.is_dir())
            return f"Открыт архив: {ru_count(n, 'файл', 'файла', 'файлов')}", {"source": "folder", "file": source.name}
    except Exception:  # noqa: BLE001 - the reader says what is wrong with the file
        return None
    return None


BRAND_USAGE = "usage.json"  # the brandbook read's model calls (call_totals), beside the brandbook


@app.post("/api/brandbooks")
def upload_brandbook(
    file: Optional[UploadFile] = File(None),
    files: Optional[list[UploadFile]] = File(None),
    figma_url: Optional[str] = Form(None),
    template_id: Optional[str] = Form(None),
    use_models: bool = Form(True),
) -> dict:
    """Брендбук: файл (PDF-гайдлайн, токены JSON, архив .zip, тема .pptx, логотип), папка (`files`, имя части — путь в
    папке) или ссылка Figma. Разбор — задачей: события шагов open · palette · fonts · logos · rules · compare (`step`,
    итог шага в `message`, прочитанное — в `brand`), итог — {brand, conflicts} с шаблоном `template_id`."""
    from verstka.brand.common import BrandReadError
    from verstka.brand.read import read_brandbook

    folder = [f for f in files or [] if f is not None]
    url = (figma_url or "").strip()
    given = (file is not None) + bool(folder) + bool(url)
    if given == 0:
        raise HTTPException(400, "Выберите брендбук: PDF-гайдлайн, токены JSON, архив .zip, папку или ссылку на Figma")
    if given > 1:
        raise HTTPException(400, "Пришлите что-то одно: файл брендбука, папку или ссылку на Figma")
    bid, bdir = store.new_brandbook_dir()
    marker = bdir / BRAND_PARSING
    try:
        marker.write_text("", encoding="utf-8")
        source = _brandbook_source(bdir, file, folder, url or None)
    except BaseException:
        store.delete_brandbook(bid)
        raise
    use_vlm = use_models and _vlm_configured()

    def run(job: Job) -> dict:
        try:
            job.emit("Открываю брендбук", 0.05)
            events = BrandStepEvents(job, bid)
            opened = _brand_opened(source)
            if opened is not None:
                events.step("open", *opened)
            p = providers() if use_vlm else None
            stats: list = []  # the read's model calls: they count in the usage of every generation that uses the brandbook
            try:
                from verstka.pipeline.generate import _recording

                p_rec = _recording(p.with_deadline(time.monotonic() + 150), stats)[0] if p is not None else None
                # the steps come as the reader finishes them (a PDF's — before the model, which reads up to two minutes)
                spec = read_brandbook(
                    source, providers=p_rec, skills=skills() if use_vlm else None,
                    use_vlm=use_vlm, assets_dir=bdir, on_step=events,
                )
            except BrandReadError:
                raise
            except Exception as e:  # noqa: BLE001 - a reader's slip on a broken file: said in words
                log.warning("brandbook not read: %s", source, exc_info=True)
                raise ValueError("Не удалось прочитать брендбук — проверьте файл или загрузите токены JSON") from e
            spec.id = bid
            if stats:
                from verstka.pipeline.generate import call_totals

                (bdir / BRAND_USAGE).write_text(json.dumps(call_totals(stats), ensure_ascii=False, indent=2), encoding="utf-8")
            events.finish(spec)
            manifest, conflicts = _conflicts_with(spec, template_id, bdir)
            if not marker.exists() or not store.write_brandbook(bid, spec):
                raise ValueError(_BRAND_REMOVED)
            marker.unlink(missing_ok=True)
            found = ru_count(len(conflicts), "расхождение", "расхождения", "расхождений") if conflicts else "расхождений нет"
            job.emit(f"Сверка с шаблоном: {found if manifest is not None else 'шаблон не выбран'}", _BRAND_COMPARE_AT, step="compare", conflicts=[c.model_dump(mode="json") for c in conflicts])
            return {"brandbook_id": bid, "brand": spec.model_dump(mode="json"), "conflicts": [c.model_dump(mode="json") for c in conflicts]}
        except BaseException as e:
            gone = not marker.exists()
            store.delete_brandbook(bid)  # a brandbook that did not read leaves nothing behind (the card offers a retry)
            if gone and isinstance(e, Exception) and str(e) != _BRAND_REMOVED:
                # removed while it was read (its files went from under the reader): say that, not the reader's slip
                raise ValueError(_BRAND_REMOVED) from e
            raise

    try:
        job = runner.submit("brandbook", run)
    except BaseException:
        store.delete_brandbook(bid)
        raise
    if marker.exists():
        try:
            marker.write_text(job.id, encoding="utf-8")
        except OSError:
            pass
    return {"job_id": job.id, "brandbook_id": bid}


@app.get("/api/brandbooks/{bid}")
def get_brandbook(bid: str, template_id: Optional[str] = None) -> dict:
    """Разобранный брендбук и его расхождения с шаблоном `template_id` (другой шаблон — свои расхождения)."""
    spec = _brandbook_or_error(bid)
    _, conflicts = _conflicts_with(spec, template_id, store.brandbook_dir(bid))
    return {"brand": spec.model_dump(mode="json"), "conflicts": [c.model_dump(mode="json") for c in conflicts]}


@app.delete("/api/brandbooks/{bid}")
def delete_brandbook(bid: str) -> dict:
    if not SAFE_ID_RE.fullmatch(bid):
        raise HTTPException(404, "Брендбук не найден")
    return {"deleted": store.delete_brandbook(bid)}


@app.get("/api/brandbooks/{bid}/files/{path:path}")
def brandbook_file(bid: str, path: str):
    """Логотип брендбука по пути из `BrandLogo.file` (только логотипы: не исходник и не brand.json)."""
    spec = _brandbook_or_error(bid)
    bdir = store.brandbook_dir(bid)
    rel = PurePosixPath(path)
    if bdir is None or ".." in rel.parts or not (path in {lg.file for lg in spec.logos} or (len(rel.parts) > 1 and rel.parts[0] == "logos")):
        raise HTTPException(404, "Файл не найден")
    return _serve_file(bdir, path)


# ---------------------------------------------------------------------------- routes: examples (вторая ступень)

_EXAMPLES = _REPO_ROOT / "examples"
# пример брендбука — PDF-гайдлайн (его показывает холст: «Брендбук VK Cloud.pdf»); имя — как у файла, который приложил человек
_BRAND_EXAMPLE = ("brandbook-vk-cloud", "guideline.pdf", "Брендбук VK Cloud.pdf")
_EXAMPLE_SKIP = {"SCENARIO.md", "README.md"}
_DATA_EXTS = {".csv", ".tsv", ".tab", ".xlsx", ".xlsm", ".json", ".txt", ".md"}


def _example_url(name: str, file: str) -> str:
    from urllib.parse import quote

    return f"/api/examples/{name}/files/{quote(file, safe='')}"


def _example(name: str) -> Optional[dict]:
    """An example the «Создать» screen loads in one click: the text, the slide count, the data files (in the scenario's
    order) and the brandbook. `served` — the files GET /api/examples/{name}/files/… gives out (public name → path)."""
    brand_dir, brand_file, brand_name = _BRAND_EXAMPLE
    brandbook = {"name": brand_name, "url": _example_url(brand_dir, brand_file)} if (_EXAMPLES / brand_dir / brand_file).is_file() else None
    if name == brand_dir:
        if brandbook is None:
            return None
        return {"name": name, "title": "Брендбук VK Cloud", "brief": None, "slides": None, "files": [], "brandbook": brandbook,
                "served": {brand_file: _EXAMPLES / brand_dir / brand_file}}
    if name != "data-sales-2026":
        return None
    d = _EXAMPLES / name
    if not d.is_dir():
        return None
    try:
        scenario = (d / "SCENARIO.md").read_text(encoding="utf-8")
    except OSError:
        scenario = ""
    m = re.search(r"^Текст \(бриф.*?\):\s*«(.*)»\s*$", scenario, re.M)
    brief = m.group(1).strip() if m else None
    m = re.search(r"^## Колода «.*?(\d+)\s+слайд", scenario, re.M)
    slides = int(m.group(1)) if m else None
    data = {p.name: p for p in d.iterdir() if p.is_file() and not p.name.startswith(".") and p.name not in _EXAMPLE_SKIP and p.suffix.lower() in _DATA_EXTS}
    order = [n for n in re.findall(r"^\d+\.\s+`([^`]+)`", scenario, re.M) if n in data]
    names = list(dict.fromkeys(order + sorted(data)))
    return {"name": name, "title": "Данные продаж", "brief": brief, "slides": slides,
            "files": [{"name": n, "url": _example_url(name, n)} for n in names], "brandbook": brandbook, "served": data}


@app.get("/api/examples/{name}")
def get_example(name: str) -> dict:
    """Пример для «Создать»: текст, число слайдов, файлы с данными и брендбук — ссылками (файлы уходят на сервер тем же
    путём, что свои)."""
    ex = _example(name)
    if ex is None:
        raise HTTPException(404, "Пример не найден")
    return {k: v for k, v in ex.items() if k != "served"}


@app.get("/api/examples/{name}/files/{path:path}")
def example_file(name: str, path: str):
    ex = _example(name)
    target = (ex or {}).get("served", {}).get(path)
    if target is None:
        raise HTTPException(404, "Файл не найден")
    return _serve_file(target.parent, target.name)


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
    elif not _brief_from_request(req).text.strip() and not req.dataset_ids:
        raise HTTPException(422, "Текст презентации пуст")
    # вторая ступень: файлы с данными и брендбук должны быть на сервере (и брендбук — уже разобран)
    req.dataset_ids = list(dict.fromkeys(req.dataset_ids))
    try:
        data = _generation_data(req)
    except InputGone as e:
        raise HTTPException(e.status, str(e))
    gid, gdir = store.new_generation_dir()
    # the brandbook's logos go into the build's folder now, before the job: a DELETE of the brandbook from here on
    # cannot take them away from this deck
    data.brand_dir = _brand_files(data, gdir)
    store.write_generation_meta(gid, {"id": gid, "template_id": req.template_id, "strategies": req.strategies, "brief": req.brief, "audience": req.audience, "purpose": req.purpose, "slides": req.slides, **_request_options(req), "status": "running", "created_at": time.time()})
    job = runner.submit("generate", _generation_job(gid, gdir, req, data))
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


def download_name(title: Optional[str], variant: str, ext: str) -> str:
    """The deck's file name for people — «Название — Вариант.pptx», as the web's `fileBase`: the deck's title without the
    characters a file system refuses (at most 80 characters), else «Презентация»."""
    safe = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]', " ", title or "")).strip()
    safe = safe[:80].strip() or "Презентация"
    return f"{safe} — {variant}.{ext}"


def content_disposition(kind: str, name: str, fallback: str) -> str:
    """`Content-Disposition` with a non-ASCII name (RFC 6266 / RFC 5987): `filename*=UTF-8''…` for browsers that read it
    (all current ones), `filename="…"` — an ASCII fallback — for the rest."""
    from urllib.parse import quote

    if name.isascii() and '"' not in name:
        return f'{kind}; filename="{name}"'
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _deck_title(gid: str, vdir: Path) -> Optional[str]:
    """The title the result screen shows: the variant's plan, else the generation's own."""
    try:
        own = json.loads((vdir / "outline.json").read_text(encoding="utf-8")).get("title")
    except (OSError, ValueError, AttributeError):
        own = None
    if isinstance(own, str) and own.strip():
        return own.strip()
    meta = store.read_generation_meta(gid) or {}
    title = meta.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


@app.get("/api/generations/{gid}/{strategy}/files/{name}")
def generation_file(gid: str, strategy: str, name: str):
    vdir = _variant_dir(gid, strategy)
    if name not in ("deck.pptx", "deck.pdf", "deck.html", "outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json"):
        raise HTTPException(404, "Не найдено")
    ext = name.rsplit(".", 1)[-1]
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pdf": "application/pdf", "html": "text/html", "json": "application/json"}[ext]
    # the web version opens in the browser («Веб» → a new tab); the other files are downloads
    how = "inline" if name == "deck.html" else "attachment"
    if not name.startswith("deck."):
        return _serve_file(vdir, name, media_type=media, filename=name, content_disposition_type=how)
    # the deck itself saves as «Название — Вариант.pptx», not deck.pptx / deck (1).pptx (the header wins over the link's
    # `download`)
    spec = load_strategies().get(strategy)
    human = download_name(_deck_title(gid, vdir), spec.title if spec else strategy, ext)
    header = content_disposition(how, human, f"verstka-{strategy}.{ext}")
    return _serve_file(vdir, name, media_type=media, headers={"Content-Disposition": header})


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
    if not (vdir / "audit_report.json").exists():
        raise HTTPException(404, "Вариант не найден")
    if manifest is None:
        raise HTTPException(404, _TEMPLATE_GONE)
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
        if not (vdir / "outline.json").exists():
            raise ValueError("Вариант не найден")
        if manifest is None:
            raise ValueError(_TEMPLATE_GONE)
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
            target = outline.slides[i - 1] if 1 <= i <= total else None
            if target is not None and target.data is not None:
                from verstka.data.rebuild import option_for_request

                k = option_for_request(req.text or body.message, target.data)
                if k is not None:
                    # «на слайде 4 покажи таблицей» on a slide made from a data file: the analysis's own option, built
                    # from the file again («Пересобрать слайд так») — never the designer redrawing the figures
                    return _data_form_change(gid, strategy, vdir, meta, manifest, outline, i, k, body.message, job)
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
                return {"reply": _refused_reply(msg), "changed": False}
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


def _refused_reply(msg: str) -> str:
    """«Не получилось: …» — a refusal's own sentence once, with one period (qa4 E3: «512 строк не показать..»)."""
    m = " ".join((msg or "").split()).rstrip(" .")
    return f"Не получилось: {m[:1].lower() + m[1:]}."


def _data_form_change(gid: str, strategy: str, vdir: Path, meta: dict, manifest, outline: DeckOutline, n: int, option: int, message: str, job: Job) -> dict:
    """A chat request that names another form of a data slide, done as «Пересобрать слайд так» with that option."""
    from verstka.data.rebuild import RebuildRefused, load_rebuild, rebuild_data_slide

    d = outline.slides[n - 1].data
    if option == d.chosen:
        title = d.options[option].title or d.options[option].kind
        return {"reply": f"Слайд {n} уже показан так: {title.lower()}.", "changed": False, "slide": n, "strategy": strategy}
    try:
        rp = load_rebuild(vdir.parent, outline, n, option, store.read_dataset)
    except RebuildRefused as e:
        msg = str(e)
        return {"reply": _refused_reply(msg), "changed": False, "slide": n, "strategy": strategy}
    job.emit(f"Пересобираю слайд {n}: {rp.title.lower()}", 0.1)
    res = rebuild_data_slide(
        vdir, strategy, rp, manifest=manifest, ws=store.workspace(meta["template_id"]), template_source=store.workspace(meta["template_id"]).source,
        workspace_root=store.root, exports=list(meta.get("exports") or []), progress=job_progress(job), request=message,
    )
    store.merge_variant_summary(gid, strategy, {"n_slides": res.n_slides, "score": res.score_after, "errors": res.errors, "warnings": res.warnings})
    return {"reply": res.reply, "changed": res.applied, "slide": n, "strategy": strategy, "score": res.score_after, "kind": "rebuild",
            "option": rp.option, "viz": rp.kind, "version": res.version}


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
        if not (vdir / "outline.json").exists() or not (vdir / "audit_report.json").exists():
            raise ValueError("Вариант не найден")
        if manifest is None:
            raise ValueError(_TEMPLATE_GONE)
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
    if not all((vdir / f).exists() for f in ("deck.pptx", "outline.json", "audit_report.json", "layout_plan.json")):
        raise HTTPException(404, "Вариант не найден")
    if store.manifest(meta.get("template_id", "")) is None:
        raise HTTPException(404, _TEMPLATE_GONE)
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


@app.post("/api/generations/{gid}/{strategy}/slides/{n}/rebuild")
def rebuild_slide(gid: str, strategy: str, n: int, body: RebuildBody) -> dict:
    """«Пересобрать слайд так»: slide n's dataset shown with another visualization option (`body.option`, as «Почему
    так» lists `OutlineSlide.data.options`) — a job; the rest of the variant stays, «верни как было» undoes it. An option
    the data does not suit is refused at once (422 with its reason)."""
    from verstka.data.rebuild import RebuildRefused, load_rebuild

    try:
        vdir = _variant_dir(gid, strategy)
    except HTTPException:
        raise HTTPException(404, "Вариант не найден")
    meta = store.read_generation_meta(gid) or {}
    if not all((vdir / f).exists() for f in ("deck.pptx", "outline.json", "audit_report.json", "layout_plan.json")):
        raise HTTPException(404, "Вариант не найден")
    manifest = store.manifest(meta.get("template_id", ""))
    if manifest is None:
        raise HTTPException(404, _TEMPLATE_GONE)
    try:
        outline = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "Вариант не найден")
    try:
        rp = load_rebuild(vdir.parent, outline, n, body.option, store.read_dataset)
    except RebuildRefused as e:
        raise HTTPException(e.status, str(e))
    key = (gid, strategy)
    with _fix_lock:
        if key in _fix_active:
            raise HTTPException(409, _VARIANT_BUSY)
        _fix_active.add(key)

    def run(job: Job) -> dict:
        from verstka.data.rebuild import rebuild_data_slide

        try:
            res = rebuild_data_slide(
                vdir, strategy, rp, manifest=manifest, ws=store.workspace(meta["template_id"]),
                template_source=store.workspace(meta["template_id"]).source, workspace_root=store.root,
                exports=list(meta.get("exports") or []), progress=job_progress(job),
            )
            store.merge_variant_summary(gid, strategy, {"n_slides": res.n_slides, "score": res.score_after, "errors": res.errors, "warnings": res.warnings})
            return {
                "reply": res.reply, "changed": res.applied, "applied": res.applied, "kind": "rebuild", "strategy": strategy, "slide": n,
                "slides": res.slides, "option": rp.option, "viz": rp.kind, "title": rp.title, "score_before": res.score_before,
                "new_score": res.score_after, "errors": res.errors, "warnings": res.warnings, "version": res.version, "at": res.at,
            }
        finally:
            with _fix_lock:
                _fix_active.discard(key)

    try:
        job = runner.submit("rebuild", run)
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
                return {"reply": _refused_reply(msg), "changed": False, "applied": False, "kind": "picture", "action": body.action, "strategy": strategy, "slide": n}
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
    from verstka.api.edits import EDIT_RX, looks_like_edit

    if not looks_like_edit(message):
        return False
    if intent == "explain_slide":
        # «на слайде 7 добавь в заголовок, почему нет данных»: an order to change the slide that mentions «почему» —
        # the imperative comes first; «почему слайд 3 такой» has none
        verb = EDIT_RX.search(message)
        why = re.search(r"почему|объясни|why", message, re.I)
        return bool(verb and why and verb.start() < why.start())
    if intent in ("agent", "fix_all", "audit", "export"):
        return False
    return not (intent == "plan" and re.search(r"(покажи|какой|расскажи)\s+(мне\s+)?план", message, re.I))


def _edit_ack(req, data_slide: bool = False) -> str:
    """What the agent says at once, before the job: which change it is making."""
    if req.kind == "undo":
        return "Возвращаю предыдущую версию варианта…"
    if req.kind == "delete":
        return f"Убираю слайд {req.slides[0]} и пересобираю вариант…"
    if req.kind == "swap":
        return f"Меняю местами слайды {req.slides[0]} и {req.slides[1]}…"
    if req.kind == "move":
        return f"Переношу слайд {req.slides[0]} на место {req.target}…"
    # (a slide made from a data file takes its figures from the file, not from the person's text)
    where = "Цифры — только из файлов с данными…" if data_slide else "Цифры возьму только из вашего текста…"
    return f"Понял. Дизайнер переделывает слайд {req.slides[0]}: «{req.text[:120]}». {where}"


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
                    slides_ = (v.get("outline") or {}).get("slides") or []
                    n_ = parsed.slides[0] if parsed.slides else None
                    data_slide = bool(n_ and 1 <= n_ <= len(slides_) and (slides_[n_ - 1] or {}).get("data"))
                    reply = _edit_ack(parsed, data_slide=data_slide)
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
