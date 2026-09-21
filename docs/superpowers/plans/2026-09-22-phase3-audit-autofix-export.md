# Verstka Phase 3: Audit, Autofix, Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every generated deck is parsed back into a `DeckIR`, checked by deterministic audits (layout, template compliance, density, integrity) and optional VLM/LLM content audits, auto-fixed within two iterations (re-render a failing slide with the next-best pattern or a synthesized composition, shrink or condense text), and exported to PPTX, PDF and HTML. The CLI `generate` runs audit + autofix + export by default and writes `audit_report.json`.

**Architecture:** `audit/ir.py` reuses the Phase 1 shape extractor on the generated deck to build a `DeckIR`; `audit/checks/*.py` are pure functions `(DeckIR, TemplateManifest, DeckOutline) → list[Issue]`; `audit/model_checks.py` runs the VLM/LLM skills; `audit/autofix.py` maps issue classes to fix actions and drives the re-render loop through the existing planner/matcher/renderer; `export/` produces PDF (LibreOffice) and HTML (own renderer from `DeckIR`).

**Tech Stack:** python-pptx, lxml, Pillow (metrics), LibreOffice + poppler, Jinja2 (HTML template), pydantic.

## Global Constraints

- Deterministic checks must be pure and reproducible (same deck → same issues, same order).
- Each check lives in its own module with an `id`, `severity`, `kind="deterministic"` and a `run(ctx) -> list[Issue]`; the AUDIT.md list is generated from the registry.
- Autofix never edits text semantics: it re-renders, shrinks within the type scale, or condenses via the `text_condenser` skill (deterministic trim offline).
- Exports: PPTX native (already), PDF via LibreOffice, HTML as markup (not screenshots): one file, fonts embedded, tables as `<table>`, charts as inline SVG.

---

## File Structure

```
verstka/schemas/deck_ir.py      # DeckIR, IRSlide, IRElement (type, bbox, text runs, style refs, native kind)
verstka/schemas/audit.py        # Issue, AuditReport, AuditSummary, FixAction
verstka/audit/__init__.py
verstka/audit/ir.py             # build_deck_ir(pptx_path, manifest) → DeckIR (uses analysis.shapes on the generated deck)
verstka/audit/registry.py       # CheckRegistry: discover checks, run all, filter by ids
verstka/audit/checks/__init__.py
verstka/audit/checks/layout.py  # out_of_bounds, overlap, text_overflow, text_clipped, margin_violation, image_stretched
verstka/audit/checks/template.py# font_not_in_template, size_not_in_scale, color_not_in_palette, layout_not_from_template, chrome_moved, contrast_low
verstka/audit/checks/density.py # too_many_bullets, bullet_too_long, table_too_big, too_many_series, fill_ratio
verstka/audit/checks/integrity.py # file_opens, placeholder_text, empty_slide, slide_is_picture, chart_missing_labels, duplicate_slides
verstka/audit/model_checks.py   # slide_content_audit (VLM, 11 questions), deck_coherence_audit (LLM)
verstka/audit/runner.py         # run_audit(pptx, manifest, outline, ws, providers, skills, use_vlm) → AuditReport (+ per-slide PNG paths)
verstka/audit/autofix.py        # plan_fixes(report) → actions; apply_fixes(...) → re-render loop (≤2 iterations)
verstka/export/__init__.py
verstka/export/pdf.py           # export_pdf(pptx) via LibreOffice
verstka/export/html.py          # export_html(deck_ir, manifest, out_path, assets) → single-file HTML
verstka/export/svg_charts.py    # chart series → inline SVG (bar/column/line/pie/doughnut)
skills/slide_content_audit/, skills/deck_coherence_audit/
verstka/pipeline/generate.py    # + audit, autofix, export steps; audit_report.json; run_manifest.json (skills versions, timings, cost)
verstka/cli/main.py             # + audit, export commands; generate flags --no-audit --no-autofix --export
AUDIT.md                        # generated list of checks
tests/unit/test_deck_ir.py, test_checks.py (fixtures with deliberate defects), test_autofix.py, test_export.py
```

---

### Task 1: DeckIR and audit schemas

- `IRRun(text, font, size_pt, bold, color_hex)`, `IRParagraph(text, runs, bullet, level)`, `IRElement(id, type: text|picture|shape|chart|table|group|connector, bbox: Bbox, bbox_frac: BboxFrac, paragraphs, fill_hex, line_hex, image_part, native_kind, is_placeholder, name, z)`, `IRSlide(index, layout_part, family, elements, notes, outline_id)`, `DeckIR(source, slide_size, slides)`.
- `Issue(id, slide, check_id, severity: error|warn|info, kind: deterministic|model, message, bboxes: list[BboxFrac], element_ids, suggestion, autofix: FixAction|None, details: dict)`; `FixAction(action: rematch|synth|shrink_text|condense_text|recolor|refont|move_inside|drop_element, params: dict)`; `AuditReport(deck, template_id, strategy, issues, summary{errors, warnings, infos, model_flags, score}, per_slide: dict[int, list[str]], iterations: int)`.
- `build_deck_ir(pptx, manifest)`: reuse `PptxPackage` + `SlideContext` + `extract_shapes`; map ShapeInfo → IRElement; family via `slide_family`; outline_id from slide notes marker (renderer writes `[verstka:outline_id]` line into notes) — add that marker in `render_deck`.
- Tests: IR of a generated demo deck has 12 slides, elements with text, at least one chart/table element; every element has a bbox.

### Task 2: Deterministic checks

Each check: `CHECK = CheckSpec(id, title_ru, severity, description)`; `run(ir, manifest, outline, ws) -> list[Issue]`.
- layout: `out_of_bounds` (bbox exceeds slide by > 1%), `overlap` (two text elements IoU > 0.15, or text over picture/shape not its background: text bbox intersects a *different* text bbox), `text_overflow` (measured lines × size × spacing > box height by > 8%), `text_clipped` (element partially outside), `margin_violation` (text starts outside safe area by > 3% and not chrome), `image_stretched` (picture aspect vs native image aspect differs > 12% without crop).
- template: `font_not_in_template` (run font not in manifest families with weight ≥ 1% ∪ embedded fonts), `size_not_in_scale` (size not within ±0.75 pt of any template size list — use `all_sizes` stored in manifest tokens (add `typography.sizes_used`)), `color_not_in_palette` (text/fill hex ΔE > 4 from every palette hex), `layout_not_from_template` (slide layout part not in manifest layouts), `chrome_moved` (slide-level chrome signature missing/moved — only for slide-sourced chrome), `contrast_low` (text colour vs background (slide bg or enclosing filled shape) < 4.5 for body text, < 3.0 for ≥ 24 pt).
- density: `too_many_bullets` (> 6 paragraphs with bullets in one element), `bullet_too_long` (> 15 words), `table_too_big` (> 7 rows or > 5 cols), `too_many_series` (> 5), `fill_ratio` (union of content bboxes < 25% or > 75% of safe area).
- integrity: `file_opens` (python-pptx opens + LibreOffice render succeeded), `placeholder_text` (PLACEHOLDER_RE), `empty_slide` (no text besides title / no content), `slide_is_picture` (one picture ≥ 90% area and no text), `chart_missing_labels` (chart without data labels and axis or legend), `duplicate_slides` (text similarity > 0.9 between two slides).
- Tests: build small decks with deliberate defects via python-pptx (overflowing text box, overlapping boxes, off-slide shape, 8 bullets, 20-word bullet, foreign font, placeholder text, empty slide) and assert each check fires exactly on the defective slide and not on a clean one.

### Task 3: Model checks and runner

- Skills `slide_content_audit` (VLM: PNG + headline + outline content → 11 yes/no answers with evidence) and `deck_coherence_audit` (LLM: sequence of headlines/notes → issues).
- `run_audit(...)`: build IR, run registry, render PNGs (reuse `render_slides`), optionally run model checks with concurrency, aggregate summary and score (100 − 10·errors − 3·warnings − 2·model_flags, floored at 0), write `audit_report.json` next to the deck.
- Tests: mock providers → model issues present; deterministic-only path works without providers.

### Task 4: Autofix loop

- `plan_fixes(report, plan)`: per slide, choose one action by priority: `overlap|out_of_bounds|text_overflow(severe)|fill_ratio(low with clone)` → `rematch` to the next alternative pattern (from `LayoutSlide.alternatives`) or `synth` when none; `text_overflow(mild)` → `shrink_text`; `bullet_too_long` → `condense_text`; `color_not_in_palette` → `recolor` nearest palette; `font_not_in_template` → `refont`; `placeholder_text` → `drop_element`.
- `apply_fixes(...)`: for `rematch/synth` update `LayoutPlan` entries and re-render the whole deck (fast, < 10 s); for text/colour fixes edit the deck XML in place via textfill/set_text_size and colour replacement; loop ≤ 2 iterations while error count decreases; record applied actions.
- Tests: a deck with an overflowing clone slide gets rematched/synthesized and the overflow disappears; loop stops after 2 iterations.

### Task 5: Export PDF + HTML

- `export_pdf(pptx, out)` via `pptx_to_pdf`.
- `export_html(ir, manifest, out, assets_root)`: page with one `<section class="slide">` per slide sized to the slide aspect (CSS `aspect-ratio`, scaled to viewport), absolutely positioned `<div>`s in percent units, text with font-family/size (vw-relative scaling via CSS `calc`), fills/lines/radius, pictures as base64 `<img>` (copied from the package media), native tables as `<table>`, charts as inline SVG from `svg_charts.py` (series + colours from IR chart part XML: parse `c:ser` categories/values), embedded Play font as base64 `@font-face`, keyboard navigation (← →), print CSS.
- Tests: HTML contains 12 sections, `<table>` for the table slide, `<svg` for the chart slide, no `<img` for slide screenshots; PDF has 12 pages (pypdf or `pdfinfo`).

### Task 6: Pipeline, CLI, run manifest, AUDIT.md

- `generate_variants`: after render → audit → autofix (if enabled) → re-audit → exports (pptx already; pdf/html when `--export`) → `audit_report.json`, `run_manifest.json` (skills versions/hashes from `SkillsRegistry.versions()`, providers describe, timings per stage, model usage/cost, applied fixes, git commit hash).
- CLI: `verstka audit deck.pptx --template T.pptx [--outline outline.json] [--no-vlm]`, `verstka export deck.pptx --format html|pdf|all`, `generate --no-audit --no-autofix --export all`.
- `scripts/gen_audit_md.py` writes AUDIT.md from the registry (id, severity, kind, description, test file).

## Self-review

- Spec §3.6 audit (all listed checks, model checks, autofix ≤2 iterations, user-selectable fixes come with the API in Phase 4) → Tasks 2–4; §3.7 export → Task 5; §6 run manifest → Task 6.
- Placeholder scan: none. Type names consistent: `DeckIR`, `IRElement`, `Issue`, `FixAction`, `AuditReport`, `run_audit`, `apply_fixes`, `export_html`, `export_pdf`.
