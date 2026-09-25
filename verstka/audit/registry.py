"""Check registry: every deterministic check registers itself with a CheckSpec and a run function."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import DeckIR
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest


@dataclass
class AuditContext:
    ir: DeckIR
    manifest: TemplateManifest
    outline: Optional[DeckOutline] = None
    ws: Optional[TemplateWorkspace] = None
    slide_images: dict[int, Path] = field(default_factory=dict)
    render_ok: Optional[bool] = None
    opens_ok: bool = True
    brief_text: Optional[str] = None  # the source text: the figures on the slides are compared with it (checks/facts.py)
    figure_stats: Optional[dict] = None  # what that comparison counted, for the report's summary
    _issue_counter: int = 0

    def new_issue(self, spec: CheckSpec, slide: int, message: str, **kw) -> Issue:
        self._issue_counter += 1
        outline_id = None
        if 1 <= slide <= len(self.ir.slides):
            outline_id = self.ir.slides[slide - 1].outline_id
        return Issue(id=f"{spec.id}-{slide}-{self._issue_counter}", slide=slide, check_id=spec.id, severity=kw.pop("severity", spec.severity), kind=spec.kind, message=message, outline_id=outline_id, **kw)


CheckFn = Callable[[AuditContext], list[Issue]]
_CHECKS: list[tuple[CheckSpec, CheckFn]] = []


def check(spec: CheckSpec):
    def deco(fn: CheckFn) -> CheckFn:
        _CHECKS.append((spec, fn))
        return fn

    return deco


_BUILTIN_LOADED = False


def load_builtin_checks() -> None:
    """Import every built-in check module once (idempotent; importing a subset elsewhere must not hide the rest)."""
    global _BUILTIN_LOADED
    if _BUILTIN_LOADED:
        return
    _BUILTIN_LOADED = True
    for mod in ("layout", "template", "density", "integrity", "facts"):
        importlib.import_module(f"verstka.audit.checks.{mod}")


def all_checks() -> list[tuple[CheckSpec, CheckFn]]:
    load_builtin_checks()
    return list(_CHECKS)


def run_checks(ctx: AuditContext, only: Optional[set[str]] = None, skip: Optional[set[str]] = None) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []
    ran: list[str] = []
    for spec, fn in all_checks():
        if only and spec.id not in only:
            continue
        if skip and spec.id in skip:
            continue
        try:
            issues.extend(fn(ctx))
        except Exception as e:  # noqa: BLE001
            issues.append(ctx.new_issue(spec, 0, f"проверка {spec.id} упала: {str(e)[:120]}", severity="info", details={"exception": str(e)[:300]}))
        ran.append(spec.id)
    return issues, ran
