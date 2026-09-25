"""Revising one variant of a finished generation — the chat agent's edits («на слайде 3 покажи расходы таблицей»,
«убери слайд 5», «поменяй местами 2 и 3», «верни как было»).

Every revision keeps the variant's previous version (versions/vN/: its plan, layout, audit, deck and run manifest), so
«верни как было» restores it exactly; the edited plan is rendered again with the template the variant was built on and
audited against the brief (the figures on the slides included), and the variant's edit log (edits.json) records what was
asked, what changed and the scores before and after — the versioning of the agent's work the ТЗ asks for."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from verstka.schemas.outline import Brief, DeckOutline

# what a version of a variant is: enough to show it again without re-rendering (the deck) and to rebuild it (the plan)
VERSION_FILES = ("outline.json", "layout_plan.json", "audit_report.json", "run_manifest.json", "deck.pptx")
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
    for name in VERSION_FILES:
        src = vdir / name
        if src.exists():
            shutil.copy2(src, dst / name)
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
        v.out_dir = vdir
        return v
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
