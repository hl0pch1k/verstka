"""Build the submission set: 3 templates × 3 strategies = 9 decks (PPTX + PDF + HTML + JSON artefacts).

Usage:
    python scripts/make_demo_decks.py                 # with models when OPENROUTER_API_KEY is set, else offline
    python scripts/make_demo_decks.py --offline       # force the deterministic mode
    python scripts/make_demo_decks.py --dataset DIR --out examples/outputs --only workspace
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verstka.pipeline.generate import generate_variants  # noqa: E402
from verstka.planning.brief import load_brief  # noqa: E402
from verstka.providers.registry import ProviderRegistry  # noqa: E402
from verstka.skills_registry.registry import SkillsRegistry  # noqa: E402

# name → (template file name inside the dataset, brief)
DEMOS = {
    "workspace": ("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx", "examples/briefs/vk_workspace_feature.md"),
    "education": ("Шаблон презентации VK Education.pptx", "examples/briefs/edu_program.md"),
    "vktech": ("VK Tech шаблон.pptx", "examples/briefs/cloud_initiative.md"),
}


def models_ready(path: Path) -> ProviderRegistry | None:
    try:
        reg = ProviderRegistry.from_yaml(path)
        llm = reg.get("llm")
        return reg if getattr(llm, "api_key", "") else None
    except Exception as e:  # noqa: BLE001
        print(f"models unavailable: {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT.parent / "Датасет")
    ap.add_argument("--out", type=Path, default=ROOT / "examples" / "outputs")
    ap.add_argument("--models", type=Path, default=ROOT / "configs" / "models.yaml")
    ap.add_argument("--only", choices=sorted(DEMOS), action="append")
    ap.add_argument("--offline", action="store_true", help="no model calls at all")
    ap.add_argument("--audit-models", action="store_true", help="also run VLM/LLM content checks")
    ap.add_argument("--keep-slides", action="store_true", help="keep slides/*.jpg renders next to the decks")
    args = ap.parse_args()

    providers = None if args.offline else models_ready(args.models)
    skills = SkillsRegistry.load() if providers else None
    mode = "models" if providers else "offline"
    print(f"mode: {mode}")
    summary: dict[str, dict] = {}
    for name in args.only or list(DEMOS):
        template_name, brief_path = DEMOS[name]
        template = args.dataset / template_name
        if not template.exists():
            print(f"skip {name}: {template} not found")
            continue
        brief = load_brief(ROOT / brief_path)
        out = args.out / name
        if out.exists():
            shutil.rmtree(out)
        t0 = time.time()
        res = generate_variants(
            template, brief=brief, out_dir=out, providers=providers, skills=skills,
            use_llm=bool(providers), use_vlm=bool(providers), audit=True, autofix=True,
            audit_models=bool(providers) and args.audit_models, exports=["pdf", "html"],
            progress=lambda msg, frac, n=name: print(f"  [{n} {frac:4.0%}] {msg}"),
        )
        summary[name] = {"template": template_name, "brief": brief_path, "mode": mode, "seconds": round(time.time() - t0, 1), "variants": {}}
        for v in res.variants:
            a = v.audit.summary if v.audit else None
            summary[name]["variants"][v.strategy] = {
                "slides": len(v.outline.slides), "seconds": round(v.seconds, 1),
                "score": a.score if a else None, "errors": a.errors if a else None, "warnings": a.warnings if a else None,
            }
            if not args.keep_slides:
                shutil.rmtree(v.out_dir / "slides", ignore_errors=True)
        print(f"{name}: {summary[name]['seconds']} s → {out}")
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
