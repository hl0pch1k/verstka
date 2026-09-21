# Verstka Phase 1: Foundation and Template Analysis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `verstka analyze <template.pptx>` that turns an arbitrary PPTX into `manifest.json` (design tokens, slide patterns with slots and repeat groups, components, assets, style rules) plus slide thumbnails and a pattern gallery, backed by pydantic schemas, a model-provider layer with a mock backend, and a versioned skills registry.

**Architecture:** Python package `verstka` with one module per pipeline concern. `ingest` unpacks and renders the PPTX; `analysis` extracts shape geometry and styles from OOXML (with theme/master inheritance resolved), derives tokens statistically, detects chrome and repeat groups, classifies roles/kinds with a heuristic + LLM + VLM ensemble, and assembles a `TemplateManifest`. `providers` wraps any OpenAI-compatible endpoint (OpenRouter now, VK inference later) with schema-validated JSON output; `skills_registry` loads versioned prompt+config bundles and hashes them for traceability.

**Tech Stack:** Python 3.11, python-pptx 1.0.2 (package access), lxml, Pillow, pydantic v2, openai SDK (OpenAI-compatible), httpx, typer, rich, PyYAML, Jinja2, numpy, pytest. LibreOffice (`soffice`) and poppler (`pdftoppm`) for rendering.

## Global Constraints

- Only open-weight models, Apache 2.0/MIT, ≤35B per model; default `qwen/qwen3.8-27b` via OpenRouter; no closed APIs anywhere in code or config.
- Prompts and skill configs live in `skills/<name>/` as files, never inline in Python.
- All geometry inside the package is EMU (int); pattern comparisons use fractions of slide size (float 0..1).
- Every pipeline artifact is JSON serializable through a pydantic schema in `verstka/schemas/`.
- Parser must never crash on a weird slide: per-slide try/except → `kind="freeform"`, warning collected in manifest.
- Template analysis is cached under `workspace/templates/<sha256>/`.
- Tests: unit tests use synthetic PPTX built with python-pptx in `tests/conftest.py`; integration tests use the three VK templates from `VERSTKA_FIXTURES_DIR` (default `../Датасет`) and skip when absent.
- Commit after each task (message prefix `feat:`, `test:`, `chore:`).

---

## File Structure

```
verstka/
  pyproject.toml
  verstka/__init__.py
  verstka/schemas/__init__.py
  verstka/schemas/common.py        # Bbox (EMU), BboxFrac, Color, enums
  verstka/schemas/template.py      # TemplateManifest, Tokens, Pattern, Slot, RepeatGroup, Component, Asset, StyleRule
  verstka/providers/__init__.py
  verstka/providers/base.py        # Provider protocol, ChatMessage, ImagePart, CompletionResult
  verstka/providers/openai_compat.py
  verstka/providers/mock.py
  verstka/providers/registry.py    # load configs/models.yaml → provider per role
  verstka/skills_registry/__init__.py
  verstka/skills_registry/models.py   # SkillSpec, AgentSpec
  verstka/skills_registry/registry.py # load skills/, hash, render prompts, run skill via provider
  verstka/ingest/__init__.py
  verstka/ingest/package.py        # PptxPackage: unzip, parts, rels, slide order, size, theme, fonts
  verstka/ingest/render.py         # render_slides(pptx, out_dir, dpi) via soffice + pdftoppm
  verstka/ingest/workspace.py      # TemplateWorkspace: sha256, dirs, cache
  verstka/analysis/__init__.py
  verstka/analysis/xmlns.py        # namespaces, helpers
  verstka/analysis/theme.py        # ThemeResolver: schemeClr → hex, lumMod/lumOff, fonts
  verstka/analysis/shapes.py       # extract_shapes(slide_xml, ctx) → list[ShapeInfo]; group transforms; text runs with resolved size/color/font
  verstka/analysis/colors.py       # cluster_colors, assign_color_roles
  verstka/analysis/typography.py   # build_type_scale, font_families
  verstka/analysis/spacing.py      # safe_area, column_grid
  verstka/analysis/chrome.py       # detect_chrome(shapes_per_slide)
  verstka/analysis/groups.py       # detect_repeat_groups(shapes)
  verstka/analysis/roles.py        # heuristic_roles(shapes, tokens, chrome) → role per shape
  verstka/analysis/kinds.py        # heuristic_kind(shapes, roles) → PatternKind
  verstka/analysis/classify.py     # ensemble: heuristics + slide_classifier skill + slide_vision_check skill
  verstka/analysis/patterns.py     # build_pattern(slide, shapes, roles, groups, kind) → Pattern; dedupe
  verstka/analysis/components.py   # derive_components(patterns, tokens)
  verstka/analysis/assets.py       # extract_assets(package, shapes) with heuristic tags (+ asset_tagger skill)
  verstka/analysis/rules.py        # harvest_rules(slide_texts, tokens) via rule_harvester skill + derived rules
  verstka/analysis/manifest.py     # analyze_template(pptx_path, providers, skills, workspace) → TemplateManifest
  verstka/analysis/gallery.py      # write pattern gallery HTML/JPG grid
  verstka/cli/__init__.py
  verstka/cli/main.py              # typer app: analyze
  skills/slide_classifier/skill.yaml, prompts/system.md, prompts/user.md
  skills/slide_vision_check/...
  skills/asset_tagger/...
  skills/rule_harvester/...
  configs/models.yaml
  configs/analysis.yaml            # thresholds (chrome share, ΔE tolerance, etc.)
  tests/conftest.py                # synthetic deck builders
  tests/unit/test_schemas.py
  tests/unit/test_providers.py
  tests/unit/test_skills_registry.py
  tests/unit/test_package.py
  tests/unit/test_render.py
  tests/unit/test_theme.py
  tests/unit/test_shapes.py
  tests/unit/test_colors.py
  tests/unit/test_typography.py
  tests/unit/test_spacing.py
  tests/unit/test_chrome.py
  tests/unit/test_groups.py
  tests/unit/test_roles_kinds.py
  tests/unit/test_patterns.py
  tests/unit/test_components.py
  tests/unit/test_assets.py
  tests/unit/test_rules.py
  tests/unit/test_manifest.py
  tests/integration/test_vk_templates.py
```

---

### Task 1: Project skeleton and schemas

**Files:**
- Create: `pyproject.toml`, `verstka/__init__.py`, `verstka/schemas/__init__.py`, `verstka/schemas/common.py`, `verstka/schemas/template.py`, `tests/conftest.py`, `tests/unit/test_schemas.py`, `.gitignore`, `README.md` (stub with setup)

**Interfaces:**
- Produces:
  - `Bbox(x:int, y:int, w:int, h:int)` EMU with `.to_frac(slide_w, slide_h) -> BboxFrac`, `.iou(other)`, `.contains_point(px, py)`, `.center`.
  - `BboxFrac(x:float,y:float,w:float,h:float)` with `.close_to(other, tol=0.01)`.
  - `Color(hex:str)` normalized uppercase 6-hex; `.to_lab()`, `Color.delta_e(a,b)`.
  - Enums `ShapeKind {sp, pic, graphic_frame, group, connector}`, `SlotRole {title, subtitle, body, bullet_list, card_title, card_body, number, number_label, caption, image, icon, decoration, chrome}`, `PatternKind {title, section, agenda, bullets, cards, two_column, big_number, stat_row, comparison, timeline, process, table, chart, image_text, team, quote, code, mockup, thanks, freeform}`, `Family {light, dark}`.
  - `TemplateManifest` with fields `template_id, source_file, slide_size{w,h}, tokens: Tokens, patterns: list[Pattern], components: Components, assets: list[Asset], style_rules: list[StyleRule], warnings: list[str], analysis_version`.
  - `Tokens{colors: list[ColorToken], typography: Typography, spacing: Spacing, shapes: ShapeStyleStats, chrome: list[ChromeElement], backgrounds: list[BackgroundFamily]}`; `ColorToken{hex, role: str|None, weight: float, contexts: dict[str,int]}`; `Typography{families: list[FontUsage], scale: list[TypeStep]}`; `TypeStep{role, size_pt, weight_bold_share, count}`; `Spacing{safe_area: BboxFrac, columns: list[float], gutter: float|None}`; `ChromeElement{signature, bbox: BboxFrac, share, kind, sample_slide}`.
  - `Pattern{id, source_slide: int, kind: PatternKind, family: Family, slots: list[Slot], repeat_groups: list[RepeatGroup], decor_assets: list[str], quality: float, thumbnail: str, classification: ClassificationTrace}`; `Slot{id, role: SlotRole, shape_id, bbox: BboxFrac, style: SlotStyle, capacity: Capacity, group_id: str|None}`; `RepeatGroup{id, member_shape_ids: list[list[str]], min_n:int, max_n:int, axis: str, gap: float, cell_bbox: BboxFrac}`; `Capacity{max_chars:int, max_lines:int}`; `SlotStyle{font_family, size_pt, bold, color_hex, align}`.
  - `Asset{id, path, kind, width, height, has_alpha, tags: list[str], used_on_slides: list[int]}`; `StyleRule{text, source: str, confidence: float}`.

- [ ] **Step 1: Write failing tests for Bbox/Color helpers and manifest round-trip**

```python
# tests/unit/test_schemas.py
from verstka.schemas.common import Bbox, BboxFrac, Color
from verstka.schemas.template import TemplateManifest, Tokens, Typography, Spacing, ShapeStyleStats

def test_bbox_to_frac_and_iou():
    a = Bbox(x=0, y=0, w=100, h=100)
    b = Bbox(x=50, y=50, w=100, h=100)
    assert a.iou(b) == 2500 / 17500
    f = a.to_frac(200, 400)
    assert (f.x, f.y, f.w, f.h) == (0.0, 0.0, 0.5, 0.25)

def test_bbox_frac_close_to():
    assert BboxFrac(x=0.1, y=0.1, w=0.2, h=0.2).close_to(BboxFrac(x=0.105, y=0.1, w=0.2, h=0.2))
    assert not BboxFrac(x=0.1, y=0.1, w=0.2, h=0.2).close_to(BboxFrac(x=0.2, y=0.1, w=0.2, h=0.2))

def test_color_normalization_and_delta_e():
    c = Color(hex="#0077ff")
    assert c.hex == "0077FF"
    assert Color.delta_e(Color(hex="0077FF"), Color(hex="0077FF")) == 0
    assert Color.delta_e(Color(hex="0077FF"), Color(hex="FF3885")) > 30

def test_manifest_roundtrip(tmp_path):
    m = TemplateManifest(template_id="abc", source_file="x.pptx", slide_size={"w": 9144000, "h": 5143500},
                         tokens=Tokens(typography=Typography(), spacing=Spacing(), shapes=ShapeStyleStats()))
    p = tmp_path / "m.json"
    p.write_text(m.model_dump_json())
    assert TemplateManifest.model_validate_json(p.read_text()).template_id == "abc"
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `cd verstka && python -m pytest tests/unit/test_schemas.py -v` → FAIL (module not found).

- [ ] **Step 3: Create pyproject.toml and schemas**

`pyproject.toml` with `[project] name="verstka" version="0.1.0" requires-python=">=3.11"`, dependencies: `python-pptx>=1.0.2, lxml, Pillow, pydantic>=2.7, openai>=1.40, httpx, typer, rich, PyYAML, Jinja2, numpy`; optional `dev`: `pytest, pytest-asyncio`; `[project.scripts] verstka = "verstka.cli.main:app"`; `[tool.pytest.ini_options] testpaths=["tests"]`.

`common.py`: implement Bbox/BboxFrac/Color per interface (Lab conversion via standard sRGB→XYZ→Lab formulas; ΔE = CIE76).

`template.py`: pydantic models per interface, all list fields default empty, `analysis_version="1"`.

- [ ] **Step 4: Install and run tests**

Run: `cd verstka && python -m pip install -e ".[dev]" && python -m pytest tests/unit/test_schemas.py -v` → 4 passed.

- [ ] **Step 5: Commit** `chore: project skeleton and template schemas`

---

### Task 2: Provider layer with mock and OpenAI-compatible backends

**Files:**
- Create: `verstka/providers/base.py`, `verstka/providers/openai_compat.py`, `verstka/providers/mock.py`, `verstka/providers/registry.py`, `configs/models.yaml`, `tests/unit/test_providers.py`

**Interfaces:**
- Produces:
  - `class ChatMessage(role: Literal["system","user","assistant"], content: str, images: list[bytes] = [])`.
  - `class Provider(Protocol): name: str; def complete(self, messages: list[ChatMessage], *, schema: type[BaseModel] | None, temperature: float = 0.2, max_tokens: int = 4096) -> CompletionResult`.
  - `CompletionResult(text: str, parsed: BaseModel | None, usage: Usage(prompt_tokens, completion_tokens, cost_usd: float|None), model: str, attempts: int)`.
  - `MockProvider(responses: dict[str, Any] | Callable[[list[ChatMessage]], str])` — keyed by substring found in the last user message, or callable.
  - `OpenAICompatProvider(model, base_url, api_key, price_in_per_m, price_out_per_m)`; images are sent as `image_url` data URIs; JSON extracted from ```json fences or first `{...}`; validation failure → one retry with the validation error appended; raises `ProviderError` after `max_attempts`.
  - `ProviderRegistry.from_yaml(path) -> ProviderRegistry`, `.get(role: str) -> Provider`; roles `llm`, `vlm`; backend `mock` allowed in YAML; env var expansion `${OPENROUTER_API_KEY}`.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_providers.py
from pydantic import BaseModel
from verstka.providers.base import ChatMessage
from verstka.providers.mock import MockProvider
from verstka.providers.openai_compat import extract_json
from verstka.providers.registry import ProviderRegistry

class Out(BaseModel):
    kind: str
    confidence: float

def test_mock_provider_parses_schema():
    p = MockProvider(responses={"classify": '{"kind": "cards", "confidence": 0.9}'})
    r = p.complete([ChatMessage(role="user", content="please classify this")], schema=Out)
    assert r.parsed.kind == "cards" and r.attempts == 1

def test_extract_json_from_fences_and_prose():
    assert extract_json('Sure:\n```json\n{"a": 1}\n```')["a"] == 1
    assert extract_json('text {"a": {"b": 2}} tail')["a"]["b"] == 2

def test_registry_loads_mock_backend(tmp_path):
    y = tmp_path / "models.yaml"
    y.write_text("roles:\n  llm: {backend: mock}\n  vlm: {backend: mock}\n")
    reg = ProviderRegistry.from_yaml(y)
    assert reg.get("llm").name == "mock"
```

- [ ] **Step 2: Run → FAIL (imports)**
- [ ] **Step 3: Implement** the four modules per interface. `configs/models.yaml`:

```yaml
roles:
  llm: {backend: openai_compat, model: qwen/qwen3.8-27b, base_url: https://openrouter.ai/api/v1, api_key: ${OPENROUTER_API_KEY}, price_in_per_m: 0.10, price_out_per_m: 1.80, temperature: 0.2}
  vlm: {backend: openai_compat, model: qwen/qwen3.8-27b, base_url: https://openrouter.ai/api/v1, api_key: ${OPENROUTER_API_KEY}, price_in_per_m: 0.10, price_out_per_m: 1.80, temperature: 0.1}
limits: {max_concurrency: 6, timeout_s: 120, max_attempts: 3}
```

- [ ] **Step 4: Run → 3 passed**
- [ ] **Step 5: Commit** `feat: provider layer with mock and OpenAI-compatible backends`

---

### Task 3: Skills registry

**Files:**
- Create: `verstka/skills_registry/models.py`, `verstka/skills_registry/registry.py`, `skills/slide_classifier/skill.yaml`, `skills/slide_classifier/prompts/system.md`, `skills/slide_classifier/prompts/user.md`, `tests/unit/test_skills_registry.py`

**Interfaces:**
- Produces:
  - `SkillSpec(name, version, role: Literal["llm","vlm"], prompt_files: dict[str,str] {"system": "prompts/system.md", "user": "prompts/user.md"}, output_schema: str (dotted path to pydantic class), params: dict, changelog: list[str], sha256: str)`.
  - `SkillsRegistry.load(root: Path) -> SkillsRegistry`; `.get(name) -> SkillSpec`; `.run(name, providers: ProviderRegistry, variables: dict, images: list[bytes] = []) -> CompletionResult` (renders Jinja2 templates with `variables`, picks provider by role, passes `schema` resolved by dotted path, applies `params.temperature`); `.versions() -> dict[name, {version, sha256}]`.
  - sha256 = hash of skill.yaml + all prompt files (sorted).

- [ ] **Step 1: Failing test** — load registry from `skills/`, assert `slide_classifier` exists with version `0.1.0`, sha256 length 64, `run` with MockProvider returns parsed `SlideClassification` (define schema in `verstka/analysis/classify.py` as `SlideClassification(kind: PatternKind, roles: dict[str, SlotRole], confidence: float, rationale: str)` — create the file now with only the schema).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**; write real prompts: system prompt explains the closed lists of `kind` and `role`, JSON-only output; user prompt renders `{{ slide_json }}` (compact shape list) and `{{ template_summary }}`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: versioned skills registry with slide_classifier skill`

---

### Task 4: PPTX package access and rendering

**Files:**
- Create: `verstka/ingest/package.py`, `verstka/ingest/render.py`, `verstka/ingest/workspace.py`, `tests/unit/test_package.py`, `tests/unit/test_render.py`

**Interfaces:**
- Produces:
  - `PptxPackage.open(path) -> PptxPackage` (zipfile-based, read-only): `.slide_size -> (w,h)`; `.slide_parts -> list[str]` in presentation order; `.rels(part) -> dict[rId, (type, target_part)]`; `.xml(part) -> lxml Element`; `.layout_of(slide_part) -> str`; `.master_of(layout_part) -> str`; `.theme_of(master_part) -> str`; `.media_bytes(part) -> bytes`; `.embedded_fonts -> list[str]`; `.notes_text(slide_part) -> str`.
  - `render_slides(pptx: Path, out_dir: Path, dpi: int = 110) -> list[Path]` (soffice → pdf → `pdftoppm -jpeg`), files `slide-NNN.jpg` 1-based; raises `RenderError` if soffice missing.
  - `TemplateWorkspace.create(pptx: Path, root: Path) -> TemplateWorkspace` with `.template_id` (sha256[:16]), `.dir`, `.slides_dir`, `.assets_dir`, `.manifest_path`, `.is_analyzed`.

- [ ] **Step 1: Tests** — conftest builds `simple_deck(tmp_path)` with python-pptx: 3 slides, 16:9 (12192000×6858000), slide 1 title+subtitle, slide 2 title + 3 rounded-rect "cards" each with a bold title textbox and body textbox aligned in a row, slide 3 title + picture (generated 200×100 PNG) + caption; also a footer textbox "ACME" at the same position on all slides. Tests: `slide_parts` length 3 in order; `layout_of` returns a layout part; `render_slides` yields 3 jpg files (skip if `shutil.which("soffice")` is None).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: pptx package reader, slide renderer, template workspace`

---

### Task 5: Theme resolution and shape extraction

**Files:**
- Create: `verstka/analysis/xmlns.py`, `verstka/analysis/theme.py`, `verstka/analysis/shapes.py`, `tests/unit/test_theme.py`, `tests/unit/test_shapes.py`

**Interfaces:**
- Produces:
  - `ThemeResolver(package, master_part)`: `.resolve_color(elem: lxml Element) -> str|None` handles `srgbClr`, `schemeClr` (via master `clrMap` + theme `clrScheme`), `sysClr`, `prstClr`, modifiers `lumMod`, `lumOff`, `tint`, `shade`, `alpha` ignored; `.major_font`, `.minor_font`; `.font_for(typeface_attr: str) -> str` maps `+mj-lt`/`+mn-lt` to theme fonts.
  - `ShapeInfo(id: str, name: str, kind: ShapeKind, bbox: Bbox, rotation: float, z: int, group_path: list[str], is_placeholder: bool, ph_type: str|None, ph_idx: str|None, geometry: str|None, fill_hex: str|None, line_hex: str|None, line_w_emu: int|None, corner_radius: float|None, has_shadow: bool, image_part: str|None, image_size: tuple|None, text: TextInfo|None, frame_kind: Literal["table","chart","diagram","ole"]|None, table_dims: tuple[int,int]|None)`.
  - `TextInfo(paragraphs: list[ParagraphInfo], autofit: str|None, anchor: str|None, wrap: bool, insets: tuple)`; `ParagraphInfo(text, level, has_bullet, align, runs: list[RunInfo], line_spacing)`; `RunInfo(text, font, size_pt, bold, italic, color_hex)`.
  - `extract_shapes(package, slide_part, resolver) -> list[ShapeInfo]`: walks spTree recursively; group children mapped through `chOff/chExt → off/ext`; placeholder inheritance for size/color/font: run `rPr` → paragraph `pPr/defRPr` → shape `lstStyle` → layout placeholder (match by idx then type) → master placeholder → master `txStyles` (`titleStyle` for title/ctrTitle, `bodyStyle` for body/subTitle, `otherStyle`) → default 18 pt, theme `dk1`, minor font. Also inherits bbox from layout/master placeholder when `xfrm` absent.
  - `slide_family(package, slide_part, resolver, shapes) -> Family` from background fill luminance (slide bg → layout bg → master bg; image bg → sample rendered JPG mean luminance if provided).

- [ ] **Step 1: Tests** on `simple_deck`: title shape extracted with `is_placeholder`, `ph_type == "ctrTitle"`, inherited size ≥ 40 pt; cards have `fill_hex` equal to the set color; picture shape has `image_part`; group transform test: build a deck with a group of two rects and verify child bbox offset by group position. Theme test: `schemeClr val="accent1"` resolves to theme accent1 hex; `lumMod 75000` darkens.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: theme resolver and shape extraction with inheritance`

---

### Task 6: Tokens — colors, typography, spacing, chrome, backgrounds

**Files:**
- Create: `verstka/analysis/colors.py`, `verstka/analysis/typography.py`, `verstka/analysis/spacing.py`, `verstka/analysis/chrome.py`, `configs/analysis.yaml`, tests for each.

**Interfaces:**
- Produces:
  - `collect_color_samples(shapes: list[ShapeInfo], slide_w, slide_h) -> list[ColorSample(hex, context: Literal["fill","text","line","background"], weight: float)]`; `cluster_colors(samples, delta_e_tol=8.0) -> list[ColorToken]` (representative = weighted mean in Lab, converted back); `assign_color_roles(tokens, families) -> list[ColorToken]`: background = dominant `background` context per family; `text.primary` = highest text weight with contrast ≥4.5 vs background; `text.secondary` = next text color; `surface` = fill color with low ΔE to background but distinct; `accent.N` = remaining fill/text colors ordered by weight, saturated first; also `positive/negative` if hue within green/red ranges and weight small.
  - `build_type_scale(shapes) -> Typography`: sizes weighted by char count, clustered ±0.75 pt; role assignment: sort clusters desc; `display` if ≥ 36 pt and used in ≤ 10% of runs; `h1` = the most common size among role-title placeholders or the largest cluster ≥ 24; `body` = highest weight cluster ≤ 20; `h2` = cluster between h1 and body; `small` and `caption` below body. `families` ordered by char weight, excluding symbol fonts.
  - `compute_spacing(shapes_per_slide, chrome_signatures, slide_w, slide_h) -> Spacing`: safe_area = 5th/95th percentile of content bbox edges (fractions); columns = cluster of left edges (tol 0.01) appearing on ≥ 25% of slides; gutter = median gap between adjacent repeat-group cells (filled later by groups).
  - `detect_chrome(shapes_per_slide: dict[int, list[ShapeInfo]], slide_w, slide_h, min_share=0.4) -> list[ChromeElement]`: signature = (kind, rounded bbox frac to 0.01, text[:20] or image hash); share = slides containing signature / slides total; returns elements with share ≥ min_share; `is_chrome(shape, chrome) -> bool`.

- [ ] **Step 1: Tests** with hand-built ShapeInfo lists (no PPTX needed): three near-identical blues cluster to one token; roles pick text.primary with sufficient contrast; type scale from sizes {44×2, 32×3, 18×40, 12×6} yields h1=44/32 ordering and body=18; chrome detects the "ACME" footer present on all slides of `simple_deck` and not the title.
- [ ] **Step 2: Run → FAIL**  - [ ] **Step 3: Implement**  - [ ] **Step 4: PASS**  - [ ] **Step 5: Commit** `feat: design tokens extraction (colors, typography, spacing, chrome)`

---

### Task 7: Repeat-group detection

**Files:**
- Create: `verstka/analysis/groups.py`, `tests/unit/test_groups.py`

**Interfaces:**
- Produces: `detect_repeat_groups(shapes: list[ShapeInfo], slide_w, slide_h, chrome) -> list[RepeatGroup]` and `Cell(anchor_id: str|None, member_ids: list[str], bbox: Bbox)`.
  - Algorithm: (1) candidates = non-chrome shapes; (2) anchors = shapes of kind `sp` with fill or line, or `pic`, sharing (geometry, w±5%, h±5%, fill_hex, line_hex) with ≥2 peers; (3) for each anchor set, cells = anchor bbox expanded to include shapes whose center lies inside anchor bbox; validate cells have equal composition (multiset of (kind, rounded size_pt)); (4) if no anchors: text shapes with equal (size_pt, bold, w±10%) aligned on same y (row) or same x (column) with ≥2 peers form single-shape cells; (5) axis: row if cells share y (±2% h), column if share x, grid otherwise (two rows/cols); gap = median distance between neighbours; `min_n = 1`, `max_n` = along axis: `floor((safe_len - start) / (cell_len + gap))` capped at 8, at least current n; grid: rows×cols. Overlapping groups: keep the larger.
- [ ] **Step 1: Tests**: `simple_deck` slide 2 yields one group with 3 cells, axis `row`, each cell 3 members (rect+2 textboxes), `max_n ≥ 3`; a synthetic column of 4 bullets-like textboxes yields a column group.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: repeat group detection`

---

### Task 8: Heuristic roles and kinds

**Files:**
- Create: `verstka/analysis/roles.py`, `verstka/analysis/kinds.py`, `tests/unit/test_roles_kinds.py`

**Interfaces:**
- Produces:
  - `heuristic_roles(shapes, groups, chrome, tokens, slide_w, slide_h) -> dict[shape_id, SlotRole]`. Rules in order: chrome → `chrome`; placeholder title/ctrTitle → `title`; text with largest size_pt on slide and y in top 35% → `title` (if none); text directly below title (gap < 5% h) with smaller size → `subtitle`; numeric-ish short text (`^[\d\s.,%+×x><≈~$€₽-]{1,8}$`) with size ≥ 1.6×body → `number`, and the nearest small text below/right → `number_label`; text with ≥2 paragraphs and (has_bullet or level>0) → `bullet_list`; inside a cell: bold or largest text → `card_title`, other text → `card_body`, pic small → `icon`; pic with min side < 8% of slide width → `icon`; pic with area ≥ 20% of slide and no text overlapping → `decoration` if it has alpha/illustration heuristics else `image`; text size ≤ caption step → `caption`; remaining text → `body`.
  - `heuristic_kind(shapes, roles, groups, slide_index, n_slides, text_all: str) -> tuple[PatternKind, float]` (with confidence): table frame → `table`; chart frame → `chart`; ≥3 `number` in a row group → `stat_row`; 1–2 `number` with size ≥ 48 → `big_number`; text matches `спасибо|thank|q&a|вопрос` and few shapes → `thanks`; slide_index==0 or (title + subtitle only + ≤4 shapes) → `title`; title only + decoration → `section`; group of pics with `card_title` name-like + `card_body` → `team`; agenda: ≥3 short numbered items (`^0?\d+$` numbers or `01..`) → `agenda`; group cells ≥2 with card_body → `cards`; two big text columns (two `body` shapes side by side ≥ 35% width each) → `two_column`; connector/line spanning ≥ 50% width plus ≥3 small items along it → `timeline`; numbered cells (1..n) → `process`; monospace font (`Consolas|Courier|Mono`) → `code`; big pic with aspect of phone/laptop + text → `mockup`; quote glyphs `«|"|“` starting a large text → `quote`; big image + body → `image_text`; ≥1 bullet_list → `bullets`; else `freeform` with 0.3.
- [ ] **Step 1: Tests**: `simple_deck` slide 1 → `title`, slide 2 → `cards`, slide 3 → `image_text`; synthetic stat row → `stat_row`; footer → `chrome`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: heuristic slot roles and pattern kinds`

---

### Task 9: LLM/VLM ensemble classification

**Files:**
- Create: `verstka/analysis/classify.py` (extend), `skills/slide_vision_check/{skill.yaml,prompts/system.md,prompts/user.md}`, `tests/unit/test_classify.py`

**Interfaces:**
- Produces:
  - `compact_slide_json(shapes, roles_hint, slide_w, slide_h) -> dict` (per shape: id, kind, bbox in % ints, size_pt, bold, n_paragraphs, text[:40], is_pic, in_group).
  - `SlideVisionCheck(kind: PatternKind, purpose: str, confidence: float)`.
  - `classify_slide(shapes, groups, chrome, tokens, slide_index, n_slides, image_path: Path|None, skills, providers, use_llm: bool, use_vlm: bool) -> ClassificationTrace(kind, roles, heuristic{kind,conf}, llm{kind,conf}|None, vlm{kind,conf}|None, agreement: float)`; vote weights heuristic 1.0, llm 1.5, vlm 1.0; roles from LLM override heuristics for shapes where LLM confidence ≥ 0.7; failures fall back to heuristics and add a warning.
- [ ] **Step 1: Tests** with MockProvider responses: agreement case returns llm kind; llm raising `ProviderError` returns heuristic kind with `llm=None`.
- [ ] **Steps 2–5:** FAIL → implement (write vision prompts) → PASS → commit `feat: ensemble slide classification with LLM and VLM skills`

---

### Task 10: Patterns, slots, capacity, dedupe

**Files:**
- Create: `verstka/analysis/patterns.py`, `tests/unit/test_patterns.py`

**Interfaces:**
- Produces:
  - `estimate_capacity(shape: ShapeInfo, size_pt: float, font: str) -> Capacity`: avg char width = 0.5×size_pt (0.55 for bold) in points → chars per line = usable width (bbox w − insets, in pt) / avg width; lines = usable height / (size_pt × line_spacing 1.2); `max_chars = chars_per_line × lines`.
  - `build_pattern(slide_index, shapes, roles, groups, trace, family, thumbnail, slide_w, slide_h) -> Pattern`: slots for every non-chrome, non-decoration text/image/icon shape; slot `group_id` set for group members; `decor_assets` from `decoration` shapes; `quality` = 1.0 − 0.4×(has lorem/placeholder text) − 0.3×(trace.agreement < 0.5) − 0.2×(kind == freeform).
  - `dedupe_patterns(patterns) -> list[Pattern]`: same kind, same family, same slot roles multiset, all slot bboxes close within 0.02 → keep the higher quality one.
  - `PLACEHOLDER_RE` shared regex: `lorem|ipsum|заголовок в (две|одну)|вставить (фото|qr)|имя фамилия|должность|xxx|текст описания|^текст$|^описание$|^пункт$|^заголовок$`.
- [ ] **Step 1: Tests**: capacity for a 10 in × 1 in box at 18 pt ≈ 80 chars/line × 4 lines; two identical card slides dedupe to one; placeholder detection.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: pattern assembly, capacity estimation, dedupe`

---

### Task 11: Components, assets, rules

**Files:**
- Create: `verstka/analysis/components.py`, `verstka/analysis/assets.py`, `verstka/analysis/rules.py`, `skills/asset_tagger/*`, `skills/rule_harvester/*`, tests.

**Interfaces:**
- Produces:
  - `derive_components(patterns, shapes_by_slide, tokens) -> Components{card: CardSpec|None, bullet_item: BulletSpec|None, number_callout: NumberSpec|None, icon_chip: IconChipSpec|None, table_style: TableStyleSpec, chart_style: ChartStyleSpec}` — each spec built from the most frequent group anchors/slots (fill, radius, insets, title/body sizes); `table_style` and `chart_style` derived from tokens + rules (header fill = accent.1, body font = body step, series colors = accents in order, gridlines off).
  - `extract_assets(package, shapes_by_slide, workspace.assets_dir) -> list[Asset]`: dedupe by media sha1; kind heuristics: `icon` (max side ≤ 96 px or used at ≤ 8% slide width, has alpha), `logo` (chrome pic), `mockup` (aspect in phone/laptop ranges), `illustration` (alpha + used as decoration), `photo` (jpg or no alpha, large), `pattern` (used as background); optional `asset_tagger` VLM pass on up to N largest assets → tags.
  - `harvest_rules(slide_texts: list[str], tokens, skills, providers, use_llm) -> list[StyleRule]`: derived rules always (left-align share, fonts allowed, heading color if title color consistent); LLM rules from text that looks like instructions (contains `используем|выравниваем|шрифт|цвет|не |можно`).
- [ ] **Step 1: Tests**: components from `simple_deck` produce a `card` spec with the rect fill; assets extraction writes one PNG and tags it; derived rule "text aligned left" when ≥80% paragraphs left-aligned; mock LLM returns two rules.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: components, assets and style rules extraction`

---

### Task 12: Manifest assembly, gallery, CLI, integration test

**Files:**
- Create: `verstka/analysis/manifest.py`, `verstka/analysis/gallery.py`, `verstka/cli/main.py`, `tests/unit/test_manifest.py`, `tests/integration/test_vk_templates.py`, update `README.md`

**Interfaces:**
- Produces:
  - `analyze_template(pptx: Path, *, workspace_root: Path, providers: ProviderRegistry|None, skills: SkillsRegistry|None, use_llm: bool, use_vlm: bool, render: bool = True, max_workers: int = 4) -> TemplateManifest`: runs ingest → per-slide extraction (parallel threads) → tokens → chrome → groups → classification → patterns → dedupe → components → assets → rules → manifest; writes `manifest.json`, `thumbs/`, `gallery.html`; skips analysis if cached and `--force` not set.
  - `write_gallery(manifest, workspace) -> Path`: HTML grid with thumbnail, kind, family, slots count, group sizes, quality, classification agreement.
  - CLI: `verstka analyze TEMPLATE [--workspace ./workspace] [--no-llm] [--no-vlm] [--force] [--models configs/models.yaml]`, prints summary table (slides, patterns by kind, colors with roles, fonts, scale, chrome, warnings) with rich.
- [ ] **Step 1: Tests**: `analyze_template(simple_deck, use_llm=False, use_vlm=False)` returns 3 patterns with kinds {title, cards, image_text}, a chrome element, ≥1 color role `accent.1`; manifest file exists; second call is cached (mtime unchanged). Integration (skipped if templates absent): each VK template analyzes without exception in < 120 s with heuristics only; VK Tech yields ≥ 15 patterns, families include `dark`; WorkSpace family majority `dark`; Education tokens include color `0077FF` with an accent or heading role and font family `Play` first.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: template analysis pipeline, gallery and analyze CLI`

---

## Self-review

- Spec coverage for §3.1–3.2: ingest (T4), tokens (T6), patterns/slots/groups (T7, T10), classification ensemble (T8, T9), components/assets/rules (T11), manifest+cache (T12), provider layer §5 (T2), skills registry §6 (T3). Planning, matching, rendering, audit, export, API, UI belong to later plans.
- Placeholder scan: none; every task has concrete tests and algorithms.
- Type consistency: `ShapeInfo`, `RepeatGroup`, `SlotRole`, `PatternKind`, `ClassificationTrace`, `Capacity` names match across tasks.
