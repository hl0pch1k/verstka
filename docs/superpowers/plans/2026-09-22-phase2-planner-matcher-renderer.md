# Verstka Phase 2: Planner, Matcher, Renderer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `verstka generate --template T.pptx --brief brief.md --strategy structured --out out/` produces `outline.json`, `layout_plan.json` and a native `deck.pptx` built on the template package: sample slides cloned and rewritten, repeat groups resized to the content, native charts and tables styled from tokens, leftover placeholders removed.

**Architecture:** `planning` turns a brief into a `DeckOutline` (facts registry, series, per-slide content) with LLM skills and deterministic post-validation; `matching` scores every template pattern for every outline slide (kind compatibility, capacity, family, diversity, strategy weights) and emits a `LayoutPlan` with human-readable reasons; `rendering` clones the chosen sample slides inside a copy of the template package with python-pptx, rewrites text preserving run styles, adjusts repeat groups, swaps images, adds native charts/tables, and falls back to a basic synthesized slide when no pattern fits.

**Tech Stack:** python-pptx (package + chart/table API), lxml, Pillow (text metrics with bundled Play TTF), pydantic, Jinja2 skills, typer.

## Global Constraints

- Same as Phase 1 (open weights only, prompts as files, EMU geometry, never crash the run per slide, commits per task).
- Every generated slide must be built from the template package (masters/layouts/theme/fonts preserved) and consist of native editable objects; no rasterized slides.
- Density limits enforced before rendering: ≤6 bullets, ≤15 words per bullet, tables ≤7×5, ≤5 chart series (from the ТЗ audit list).
- Text fitting only shrinks within the template's type scale; if it still overflows, text is condensed, never clipped.
- Deterministic path (mock providers / provided outline.json) must produce a deck without any model call so tests and demos never depend on an API key.

---

## File Structure

```
verstka/schemas/outline.py     # Brief, Fact, Series, TableData, ChartSpec, SlideItem, NumberCallout, SlideContent, OutlineSlide, DeckOutline
verstka/schemas/layout.py      # LayoutSlide, LayoutPlan, Composition
verstka/planning/__init__.py
verstka/planning/brief.py      # load_brief(path|text) with optional YAML front matter
verstka/planning/strategies.py # load configs/strategies.yaml → Strategy(name, planner_instructions, kind_weights, slide_ratio, synth_threshold)
verstka/planning/facts.py      # extract_facts(brief, skills, providers) via data_extractor; deterministic fallback (regex numbers)
verstka/planning/outline.py    # plan_outline(brief, manifest, strategy, facts, skills, providers) → DeckOutline; validate_outline(outline, manifest) enforces count/density/kinds
verstka/planning/condense.py   # condense_text(text, max_chars, skills, providers) via text_condenser; deterministic fallback (sentence trimming)
verstka/matching/__init__.py
verstka/matching/compat.py     # KIND_FALLBACKS, needed_items(slide), needed_chars(slide)
verstka/matching/scorer.py     # score_pattern(slide, pattern, manifest, strategy, context) → (score, reasons, fit)
verstka/matching/matcher.py    # match_outline(outline, manifest, strategy) → LayoutPlan
verstka/rendering/__init__.py
verstka/rendering/fonts.py     # font_path(family, bold) → bundled Play / DejaVu; measure_text_lines(text, family, size_pt, bold, width_pt)
verstka/rendering/fit.py       # fit_size(text, bbox_emu, style, scale, insets) → (size_pt, fits)
verstka/rendering/deck.py      # DeckBuilder: open template copy, clone_slide(source_index) → Slide, delete_original_slides(), save(); id/rels bookkeeping
verstka/rendering/textfill.py  # fill_text(shape_el, paragraphs, size_pt=None) keeping rPr/pPr; clear_text(shape_el); ParagraphSpec(text, bullet, level, bold)
verstka/rendering/groups.py    # adjust_group(slide_el, group, n_needed, slide_w, slide_h) → cell element lists
verstka/rendering/images.py    # replace_picture(slide, pic_el, asset_path); insert_picture(slide, bbox, asset_path)
verstka/rendering/charts.py    # add_chart(slide, bbox, chart_spec, outline, chart_style, typography) → GraphicFrame
verstka/rendering/tables.py    # add_table(slide, bbox, table_data, table_style, typography) → GraphicFrame
verstka/rendering/clone.py     # render_clone(builder, plan_slide, outline_slide, pattern, manifest, ws) → RenderedSlide
verstka/rendering/synth.py     # render_synth(builder, plan_slide, outline_slide, manifest, ws) — basic compositions
verstka/rendering/renderer.py  # render_deck(outline, plan, manifest, ws, out_pptx) → RenderResult
verstka/fonts/Play-Regular.ttf, Play-Bold.ttf, OFL.txt
skills/data_extractor/, skills/outline_planner/, skills/text_condenser/, skills/fact_checker/
configs/strategies.yaml
verstka/cli/main.py            # + generate, plan commands
tests/unit/test_outline_schema.py, test_strategies_brief.py, test_planner_validate.py, test_matcher.py, test_fonts_fit.py, test_textfill_groups.py, test_charts_tables.py, test_render_e2e.py
tests/fixtures/outline_demo.json  # a 12-slide outline used by tests and the deterministic demo
examples/briefs/vk_workspace_feature.md, examples/briefs/edu_program.md, examples/briefs/cloud_initiative.md
```

---

### Task 1: Outline and layout schemas, strategies, brief loader

**Interfaces (produces):**
- `Brief(text, title_hint, audience, purpose: Literal[feature, product, project, initiative]|None, slide_count: int|None, language="ru", tone, extra_instructions)`; `load_brief(src: Path|str) -> Brief` — markdown with optional front matter (`---\naudience: ...\nslides: 12\n---`).
- `Fact(id, value, unit, label, source_span)`, `Series(id, name, categories: list[str], values: list[float], unit)`, `TableData(columns, rows, unit, caption)`, `ChartSpec(type: Literal[bar, column, line, area, pie, doughnut], series_ids, categories: list[str]|None, unit, highlight_index)`, `SlideItem(title, text="", icon_hint=None, number=None)`, `NumberCallout(value, label, fact_id=None)`.
- `SlideContent(bullets: list[str], paragraphs: list[str], items: list[SlideItem], numbers: list[NumberCallout], table: TableData|None, chart: ChartSpec|None, quote, quote_author, image_hint, columns: list[SlideItem])`; `OutlineSlide(id, kind: PatternKind, section, headline, subtitle, content: SlideContent, notes="", fact_refs: list[str])`; `DeckOutline(title, subtitle, audience, purpose, strategy, language, slides, facts, series, tables)` with `.needed_items(slide)` helper moved to matching.
- `LayoutSlide(outline_id, mode: Literal[clone, synth], pattern_id: str|None, composition: str|None, fit: dict, score: float, reasons: list[str])`; `LayoutPlan(strategy, template_id, slides: list[LayoutSlide])`.
- `Strategy(name, title, planner_instructions: str, kind_weights: dict[str, float], slide_ratio: float, synth_threshold: float, prefer_clone: float)`; `load_strategies(path) -> dict[str, Strategy]`.
- `configs/strategies.yaml` with `structured`, `visual`, `compact` as designed in the spec §4.
- Tests: schema round-trip of `tests/fixtures/outline_demo.json` (12 slides: title, agenda, bullets, cards×4, stat_row×3, chart, table, two_column, process×4, quote, thanks; facts and one series); brief front matter parsing; strategies load with three names.
- Commit `feat: outline/layout schemas, strategies, brief loader`.

### Task 2: Matcher

**Interfaces:**
- `KIND_FALLBACKS: dict[PatternKind, list[tuple[PatternKind, float]]]` e.g. `stat_row → [(stat_row,1.0),(big_number,0.7),(cards,0.6)]`, `bullets → [(bullets,1.0),(two_column,0.5),(cards,0.5)]`, `process → [(process,1),(timeline,0.8),(cards,0.6)]`, `chart → [(chart,1),(image_text,0.6),(freeform,0.5)]`, `table → [(table,1),(freeform,0.5)]`, `title → [(title,1)]`, `section → [(section,1),(title,0.5)]`, `thanks → [(thanks,1),(section,0.4)]`, `quote → [(quote,1),(section,0.5),(bullets,0.3)]`, `comparison → [(comparison,1),(two_column,0.8),(cards,0.6)]`, `team → [(team,1),(cards,0.5)]`, `image_text → [(image_text,1),(mockup,0.6),(bullets,0.4)]`, `agenda → [(agenda,1),(bullets,0.6),(process,0.5)]`.
- `needed_items(slide) -> int` (items/numbers/columns/bullets-as-cards), `needed_chars(slide) -> dict[role, int]`.
- `score_pattern(slide, pattern, manifest, strategy, prev_family, recent_ids) -> ScoreResult(score, reasons, fit)`; components: kind (0–1 from fallbacks) × 0.4; capacity (items within [min_n,max_n] → 1, else 0.3 penalty per missing/extra beyond max, no group when items ≥2 → 0.2) × 0.25; text fit (chars needed / capacity ≤ 1 → 1, ≤1.3 → 0.7 shrinkable, else 0.3) × 0.15; family continuity × 0.05; diversity (pattern in last 3 → −0.15); quality × 0.1; strategy kind weight multiplier (0.7–1.3).
- `match_outline(outline, manifest, strategy) -> LayoutPlan`: best pattern per slide; `mode=synth` with `composition` when `best.score < strategy.synth_threshold` or no pattern of a compatible kind exists; compositions: `title, section, bullets, cards(n), stat_row(n), two_column, chart_text, table, process(n), quote, thanks`.
- Tests on the demo outline against the analyzed `simple_deck` manifest (cards slide → pattern p2 clone; stat_row → synth) and on VK Tech manifest fixture (integration): every slide gets a plan, title → title pattern, reasons non-empty.
- Commit `feat: layout matcher with explainable scoring`.

### Task 3: Fonts and text fitting

- Bundle Play TTF (OFL) in `verstka/fonts/`; `font_path(family, bold)` returns Play for Play/VK Sans/unknown-sans, DejaVuSans (Pillow's bundled) otherwise; `measure_text_lines(text, family, size_pt, bold, width_pt) -> int` greedy word wrap with Pillow `ImageFont.getlength`.
- `fit_size(paragraphs, bbox, style, scale_sizes, insets, line_spacing) -> FitResult(size_pt, fits, lines)`: try the slot size then smaller scale steps (≥ 0.6 × original) until lines × size × spacing ≤ height.
- Tests: 200-char text in a 3in×0.5in box at 18pt does not fit; fit_size returns a smaller scale step; short text keeps its size.
- Commit `feat: bundled fonts and text fitting`.

### Task 4: DeckBuilder — clone slides inside the template package

- `DeckBuilder(template_pptx: Path)`: opens with python-pptx; `clone_slide(source_index: int) -> pptx.slide.Slide`: adds a slide with the same layout, deep-copies every child of the source `p:spTree` (except the empty placeholder nodes python-pptx added), copies relationships used by `r:embed`/`r:link`/`r:id` attributes (images, hyperlinks) by `part.relate_to(target_part, reltype)` and rewrites rIds; also copies `p:bg`; `delete_original_slides()` removes the template's original slides from `sldIdLst` and drops their parts; `save(path)`; `ensure_unique_ids(slide)`.
- Tests: clone slide 2 of `simple_deck` twice → deck with 2 slides opens in python-pptx, both have 3 cards + picture rels resolve; original slides removed; LibreOffice renders (skip w/o soffice); `validate.py`-style check: all `r:embed` rIds exist in slide rels.
- Commit `feat: DeckBuilder cloning sample slides with relationships`.

### Task 5: Text fill and repeat-group adjustment

- `ParagraphSpec(text, bullet: bool|None=None, level=0, bold: bool|None=None)`; `fill_text(sp_el, paragraphs: list[ParagraphSpec], size_pt: float|None=None, keep_bullets=True)`: keeps `a:bodyPr` and `a:lstStyle`; uses the first existing `a:p`'s `pPr` and the first run's `rPr` as templates (bullet paragraphs use the first paragraph that had a bullet); writes one `a:p` per spec; sets `sz` when size_pt given; sets `b` when bold given; `xml:space="preserve"`; removes `a:endParaRPr` duplicates; `clear_text` empties all paragraphs but keeps one empty `a:p`.
- `adjust_group(slide, group, n_needed, slide_w, slide_h) -> list[list[etree._Element]]`: locates cell elements by shape ids (cNvPr id), deletes cells beyond n (keeping the first n in reading order), duplicates the last cell to reach n (≤ max_n) shifting by (cell_w + gap) along the axis with fresh ids, then re-distributes cells evenly across the original span when n < original (row/column only); returns cells in order.
- Tests: fill 3 bullets into the card body → 3 `a:p` with copied rPr size/colour; `adjust_group` 3→2 leaves 2 cells with even spacing; 3→5 (max 5) creates 2 new cells with unique ids and increasing x; 3→7 with max 5 clamps to 5.
- Commit `feat: text fill preserving styles and repeat-group resizing`.

### Task 6: Charts, tables, images

- `add_chart(slide, bbox_emu, chart_spec, outline, style, typography)`: python-pptx `CategoryChartData`; type map to `XL_CHART_TYPE`; series colours from `style.series_colors`; `value_axis.has_major_gridlines = style.gridlines`; data labels on with number format from unit (%, ₽, plain); legend bottom only when >1 series; fonts (family/size) on chart; `highlight_index` colours one point with accent.1 and others with neutral/surface (bar/column).
- `add_table(slide, bbox_emu, table_data, style, typography)`: python-pptx table; header fill/text colours, body font size, numbers right-aligned (regex), zebra band via `band_fill_hex` when rows > 4, remove default table style banding (`tbl.first_row`, `tblPr` `bandRow=0`) and set thin borders by `border_hex`.
- `replace_picture(pic_el, slide, asset_path)`: new image part via `slide.part.get_or_add_image_part`, set `r:embed`, set `a:srcRect` to crop to the frame's aspect; `insert_picture(slide, bbox, asset_path)`.
- Tests: chart and table XML load back through python-pptx; series count; header text; LibreOffice renders a slide with both without error (skip w/o soffice).
- Commit `feat: native charts, tables and picture replacement`.

### Task 7: Clone renderer, basic synth renderer, render_deck

- `render_clone(...)`: mapping rules per slot role: `title ← headline`, `subtitle ← subtitle|section`, `bullet_list ← bullets` (fill_text with bullets), `body ← paragraphs|bullets joined`, `card_title/card_body ← items[i]` per cell after `adjust_group`, `number/number_label ← numbers[i]`, `caption ← notes/unit`, `image ← asset by image_hint tag match else keep`, quote roles → `body`; chart/table: if outline has chart/table and pattern has an `image` slot or is `chart|table|freeform` → insert native object into that bbox (replacing the image); unfilled text slots (roles in _TEXT_ROLES not mapped) → `clear_text` then if the shape is an empty text box → delete; decoration left as is; size fitting via `fit_size` per slot.
- `render_synth(...)`: uses the first layout with only title placeholder (or blank), copies `p:bg` from the pattern family's sample slide, writes: title (h1 size, text.primary/accent colour from title slot stats), then composition: `bullets` (one text box with bullet paragraphs), `cards(n)` (rounded rects per `CardSpec` in a row/grid + title/body text boxes), `stat_row(n)` (number + label), `two_column`, `chart_text`, `table`, `process(n)` (numbered circles + text), `quote`, `section`, `thanks`.
- `render_deck(outline, plan, manifest, ws, out_pptx, progress=None) -> RenderResult(pptx_path, slides: list[RenderedSlide(outline_id, index, mode, pattern_id, warnings)])`: clones in outline order, deletes originals, saves; per-slide try/except → synth fallback → bullets fallback.
- Tests (unit, `simple_deck` + demo outline via mock plan): deck has len(outline.slides) slides; no placeholder regex hits in the deck text; the cards slide has exactly the number of cards the outline item count demands; a chart slide contains a `c:chart` part; LibreOffice renders (skip w/o soffice). Integration: VK Tech, WorkSpace, Education with the demo outline and each strategy → 9 decks render without exception in < 60 s each.
- Commit `feat: clone and synth renderers, render_deck`.

### Task 8: Planner skills and CLI `generate`

- Skills: `data_extractor` (llm → `FactsExtraction(facts, series, tables)`), `outline_planner` (llm → `DeckOutline` minus facts; receives brief, facts JSON, list of available kinds with max items, strategy instructions, slide target, language), `text_condenser` (llm → `{"text": ...}`), `fact_checker` (llm → `{"issues": [{slide_id, text, severity}]}`).
- `plan_outline(...)`: run extractor → planner → validate (count, density: trim to 6 bullets/15 words via condenser or deterministic cut, ensure title first / thanks last if the template has those kinds, unique headlines, kinds ∈ PatternKind) → fact_checker → one repair pass (planner with `issues`) → outline; deterministic fallback when providers are absent: `outline_from_brief_basic` (split by headings/paragraphs into bullets slides) so the CLI still works offline.
- CLI: `verstka plan --brief b.md --template T.pptx --strategy structured --out out/` (writes outline.json), `verstka generate --template T.pptx (--brief b.md | --outline outline.json) [--strategy structured|visual|compact|all] [--slides N] [--out out/] [--models ...] [--no-llm] [--render]` → per strategy: `out/<strategy>/outline.json, layout_plan.json, deck.pptx, slides/*.jpg` and a summary table (slide → pattern/mode/score).
- Tests: planner validation trims density on a synthetic over-dense outline; mock-provider run of `plan_outline` returns 12 slides; CLI smoke via `typer.testing.CliRunner` with `--outline fixture --no-llm` on `simple_deck`.
- Commit `feat: planner skills, plan/generate CLI`.

## Self-review

- Spec coverage §3.3 (planner, facts, condenser, fact checker) → Task 1, 8; §3.4 matcher → Task 2; §3.5 rendering (clone, synth basic, charts, tables, icons partially — icon provider from assets only, Tabler set is Phase 3) → Tasks 3–7; three strategies config → Task 1 (weights) and Task 8 (planner instructions); CLI reproducible run → Task 8.
- Placeholder scan: none.
- Type consistency: `DeckOutline`, `OutlineSlide`, `SlideContent`, `LayoutPlan`, `LayoutSlide`, `Strategy`, `DeckBuilder`, `ParagraphSpec`, `RenderResult` used consistently.
