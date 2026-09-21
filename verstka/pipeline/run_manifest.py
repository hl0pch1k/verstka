"""run_manifest.json: what produced a generation (skills, models, template, timings, fixes) — the traceability artefact."""

from __future__ import annotations

import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from verstka import __version__
from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.registry import SkillsRegistry


def git_commit(repo: Optional[Path] = None) -> Optional[str]:
    try:
        root = repo or Path(__file__).resolve().parents[2]
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def build_run_manifest(
    *,
    template_id: str,
    template_file: str,
    strategy: str,
    brief_hash: Optional[str],
    outline_hash: str,
    skills: Optional[SkillsRegistry],
    providers: Optional[ProviderRegistry],
    timings: dict[str, float],
    applied_fixes: list[dict],
    audit_summary: dict[str, Any],
    slides: list[dict],
    usage: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    return {
        "verstka_version": __version__,
        "git_commit": git_commit(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "template": {"id": template_id, "file": template_file},
        "strategy": strategy,
        "inputs": {"brief_sha256": brief_hash, "outline_sha256": outline_hash},
        "skills": skills.versions() if skills else {},
        "providers": providers.describe() if providers else {"llm": {"backend": "none"}, "vlm": {"backend": "none"}},
        "timings_s": timings,
        "usage": usage or {},
        "applied_fixes": applied_fixes,
        "audit": audit_summary,
        "slides": slides,
        **(extra or {}),
    }


def write_run_manifest(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def diff_manifests(a: dict, b: dict) -> dict:
    """What changed between two runs: skills, providers, strategy, audit score."""
    out: dict[str, Any] = {"skills": {}, "providers": {}, "strategy": None, "audit_score": None}
    for name in sorted(set(a.get("skills", {})) | set(b.get("skills", {}))):
        sa, sb = a.get("skills", {}).get(name), b.get("skills", {}).get(name)
        if sa != sb:
            out["skills"][name] = {"from": sa, "to": sb}
    for role in sorted(set(a.get("providers", {})) | set(b.get("providers", {}))):
        pa, pb = a.get("providers", {}).get(role), b.get("providers", {}).get(role)
        if pa != pb:
            out["providers"][role] = {"from": pa, "to": pb}
    if a.get("strategy") != b.get("strategy"):
        out["strategy"] = {"from": a.get("strategy"), "to": b.get("strategy")}
    sa, sb = a.get("audit", {}).get("score"), b.get("audit", {}).get("score")
    if sa != sb:
        out["audit_score"] = {"from": sa, "to": sb}
    return out
