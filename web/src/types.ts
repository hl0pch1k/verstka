// Typed mirror of the Verstka FastAPI contract (verstka/api/app.py + verstka/schemas/*).

export type Severity = "error" | "warn" | "info";
export type IssueKind = "deterministic" | "model";
export type Family = "light" | "dark";
export type PatternKind =
  | "title" | "section" | "agenda" | "bullets" | "cards" | "two_column" | "big_number" | "stat_row"
  | "comparison" | "timeline" | "process" | "table" | "chart" | "image_text" | "team" | "quote"
  | "code" | "mockup" | "thanks" | "freeform";

/** Where a status line stands (no pop-ups in «Слои»): the template step, the text step, the build (its launch and the
 *  build screen), the result, or the page as a whole. Screens and sheets: `ui/deck/geometry.ts`. */
export type NoticeArea = "template" | "text" | "build" | "result" | "global";
/** A status line: an error, a done action or a remark, and when it came (ms; the same text again restarts its fade). */
export interface Notice { kind: "error" | "success" | "info"; text: string; at: number }
export type JobKind = "analyze" | "generate" | "fix" | "edit" | "slide_fix" | "picture" | "other";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface BboxFrac { x: number; y: number; w: number; h: number }

// ---- meta -------------------------------------------------------------------
export interface Health {
  ok: boolean; version: string; models_configured: boolean; workspace: string;
  /** writer mode is on (configs/writer.yaml): a topic-only text is written by the agent */ writer?: boolean;
  /** pictures inside slides (the t2i role): configured — a text-to-image model has a key; the models in order */
  images?: { configured: boolean; enabled: boolean; models: { label: string; state: string }[] };
}

// ---- models (GET /api/models/status) ------------------------------------------------
/** A link of the model chain: the main model first (Qwen3.8-27B on Polza), then the backup (Qwen3.6-27B).
 * ok — answered last time; unknown — not tried since the server started; congested — the model's hosts are overloaded
 * (their 429 / a 5xx); rate — Polza's per-minute cap on the model (under 90 s); quota — Polza's daily cap on the model
 * (until midnight by Moscow time); no_credits — 402: no money on the balance or the key's limit is spent; auth — the
 * key is refused; missing — no such model; error — anything else; off — its key is not set: skipped, never a failure. */
export type ModelLinkState = "ok" | "unknown" | "congested" | "rate" | "quota" | "no_credits" | "auth" | "missing" | "error" | "off";
export interface ModelLink {
  model: string | null;
  label: string;
  /** The label without a host tag («Qwen3.8-27B (VK)» → «Qwen3.8-27B»). */
  short_label?: string;
  /** Host name only («polza.ai»). */
  host?: string | null;
  state: ModelLinkState;
  /** False while the link pauses after a failure (see `until`). */
  available: boolean;
  last_ok: number | null;
  last_error: string | null;
  last_error_at?: number | null;
  /** Seconds until a congested / exhausted link is tried again. */
  until: number | null;
  roles?: string[];
}
/** ok — the primary answers; unknown — not called yet; retry — failed lately, will be tried again; fallback — a
 * backup works; down — the built-in planner; off — no model configured. */
export type ModelsOverall = "ok" | "unknown" | "retry" | "fallback" | "down" | "off";
export interface ModelsStatus {
  configured: boolean;
  config: string | null;
  active_model: string | null;
  active_model_label: string | null;
  host: string | null;
  links: ModelLink[];
  source: string;
  state: ModelsOverall;
  /** The indicator line as is: «Модель: Qwen3.8-27B — доступна». */
  summary: string;
  /** What helps when the model is not available (the detailed hint) or null. */
  hint: string | null;
  working_label: string | null;
  /** Seconds until a paused link is tried again, and that link's state (quota: after midnight by Moscow time). */
  retry_in: number | null;
  retry_state?: ModelLinkState | null;
  /** What the notice above a failed deck advises now («Соберите ещё раз через минуту.»), or null. */
  advice?: string | null;
  /** Building again can work now or once `retry_in` is over (false: a key, an account or a model id needs a fix). */
  retryable?: boolean;
  /** What the server's owner has to fix for the failed model (the Polza balance, the key, a model id), or null. */
  owner?: string | null;
}
/** Who wrote the plan of a variant (or of the whole generation) and, when the built-in planner did, why. */
export interface PlannerInfo {
  /** model | shared:<strategy> | rules | skeleton | supplied (the outline came with the request) | null (not recorded) */
  planned_by?: string | null;
  /** null: an older deck that does not say who planned it (no notice is shown). */
  by_model: boolean | null;
  model: string | null;
  model_label: string | null;
  tried_model?: string | null;
  tried_label?: string | null;
  /** congested | rate | quota | no_credits | auth | missing | timeout | unreachable | rejected | error | off */
  reason_code: string | null;
  /** Plain Russian clause: «сервер модели перегружен». */
  reason: string | null;
  /** What helps, one sentence. */
  advice: string | null;
  /** The same deck built again can get past the reason (congestion, a cap, the time budget…); false: fix first. */
  retryable?: boolean;
  /** Always null (kept for older payloads). */
  steady?: string | null;
  /** What the server's owner has to fix (the balance, the key — «На балансе Polza нет средств…»), or null. */
  owner?: string | null;
}
export interface StrategyInfo { name: string; title: string; description: string }
export interface SkillInfo { name: string; version: string; role: string; sha256: string; description: string; changelog: unknown }
export interface AgentInfo { name: string; version: string; sha256: string }
export interface SkillsResponse { skills: SkillInfo[]; agents: AgentInfo[] }
export interface CheckSpec { id: string; title: string; severity: Severity; kind: IssueKind; category: string; description: string }

// ---- templates ------------------------------------------------------------------
export interface TemplateListItem {
  template_id: string;
  source_file: string | null;
  /** The name a person gave the template (PATCH /api/templates/{id}); null: the file's name stands. */
  title?: string | null;
  n_slides: number | null;
  n_patterns: number;
  analyzed_at: number;
  /** Card data (optional: older servers do not send it). */
  cover_url?: string | null;
  palette?: string[];
  font?: string | null;
  aspect?: number | null;
}

export interface ColorToken {
  hex: string;
  role: string | null;
  roles: string[];
  semantic: string | null;
  is_brand: boolean;
  weight: number;
  contexts: Record<string, number>;
}
export interface FontUsage { family: string; weight: number; bold_share: number }
export interface TypeStep { role: string; size_pt: number; weight_bold_share: number; count: number }
export interface Typography { families: FontUsage[]; scale: TypeStep[]; sizes_used: number[]; left_align_share: number; line_spacing: number }
export interface Tokens {
  colors: ColorToken[];
  typography: Typography;
  spacing?: { safe_area: BboxFrac; columns: number[]; gutter: number | null };
  backgrounds?: { family: Family; fill_kind: string; hex: string | null; slides: number[] }[];
}
export interface Slot { id: string; role: string; shape_id: string; bbox: BboxFrac; group_id: string | null; sample_text: string | null }
export interface RepeatGroup { id: string; member_shape_ids: string[][]; min_n: number; max_n: number; axis: string; rows: number; cols: number; fixed?: boolean; cell_boxes?: BboxFrac[] }
export interface SignalVote { kind: PatternKind; confidence: number; rationale: string | null }
export interface ClassificationTrace { kind: PatternKind; heuristic: SignalVote; llm: SignalVote | null; vlm: SignalVote | null; agreement: number; purpose: string | null }
export interface Pattern {
  id: string;
  source_slide: number;
  kind: PatternKind;
  family: Family;
  slots: Slot[];
  repeat_groups: RepeatGroup[];
  decor_assets: string[];
  quality: number;
  thumbnail: string | null;
  thumbnail_url?: string;
  classification: ClassificationTrace | null;
  layout_part: string | null;
  /** a table drawn with text boxes or a chart drawn with shapes: its area takes the deck's native table or chart */
  data_box?: BboxFrac | null;
  /** the sample's design is one picture of its own layout */
  art_layout?: boolean;
  /** rows of the drawn table (its header included) */
  data_rows?: number | null;
  /** what the sample draws in that area: a table or a chart (columns, bars, a Gantt) */
  data_kind?: "table" | "chart" | null;
  /** how a drawn chart reads */
  chart_hint?: { direction?: "col" | "bar" | "gantt"; bars?: number; series?: number; label_pt?: number | null; value_pt?: number | null } | null;
  /** the note field at the sample's foot («Примечание» over «Текст»): the slide's conclusion goes there */
  note_slot?: string | null;
  note_label?: string | null;
}
export interface StyleRule { text: string; source: string; confidence: number }
export interface TemplateManifest {
  template_id: string;
  source_file: string;
  title?: string | null;
  slide_size: { w: number; h: number };
  tokens: Tokens;
  patterns: Pattern[];
  assets: { id: string; kind: string; width: number; height: number; tags: string[] }[];
  style_rules: StyleRule[];
  warnings: string[];
  n_slides: number;
  analysis_version: string;
  embedded_fonts: string[];
  gallery_url: string;
  narration: string;
}
export interface UploadResponse { job_id: string; filename: string; use_models: boolean }
/** «Улучшить готовую презентацию» (Verstka 3.0): the uploaded deck read back as the author's text («Слайд N. …»), what
 *  it holds, and its own audit — the «было» of «было → стало» (verstka/ingest/deck_text.py). */
export interface ImproveSource {
  brief: string;
  name: string;
  /** The uploaded deck as a template (its pictures go to the new deck in any template). */
  template_id?: string;
  title?: string;
  /** Absent when the deck was reopened from a build that did not keep the count («Изменить текст»). */
  slides?: number;
  tables: number;
  charts: number;
  pictures: number;
  audit?: { score: number; errors: number; warnings: number } | null;
  /** What «Взгляд дизайнера» saw wrong on the original (its serious problems), when a vision model is connected. */
  problems?: { slide: number; code: string; text: string; where?: string }[];
}
/** What a generation was made from in «Улучшить» (generation.json `improved_from`). */
export interface ImprovedFrom { name: string; slides?: number; template_id?: string; audit?: { score: number; errors: number; warnings: number } | null }

// ---- jobs ---------------------------------------------------------------------
export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  result: unknown;
  /** The planning agent's steps so far (a polling client gets the timeline from here). */
  agent?: JobEvent[];
}
/** A progress event of a job. `type: "agent"` marks a step of the planning agent (Agent v2): who did it (`step`), on
 * which slide and for which variant (null: shared by all variants); `message` is a plain Russian sentence. `seq` is
 * the event's number within the job (the stream and the polled record may both deliver it). */
export interface JobEvent {
  job_id: string; status: JobStatus; progress: number; message: string; t: number;
  type?: "agent"; step?: string; slide?: number | null; variant?: string | null; seq?: number;
  /** The critic's «what to do» of an agent event, apart from the problem (newer servers). */
  fix?: string | null;
}

// ---- the planning agent (Agent v2) ------------------------------------------------------
/** analyst | architect | designer | critic | revise | compile (other values may come from newer servers). */
export interface AgentEvent { step: string; message: string; slide: number | null; variant: string | null; t?: number; seq?: number; fix?: string | null }
/** What the agent did for a variant: its log (outline.agent_log), the timeline the build screen showed (shared steps
 * and this variant's own) and the critic's notes with the revisions. Empty for runs made before Agent v2. */
export interface VariantAgent { log: string[]; events: AgentEvent[]; critic: AgentEvent[] }
/** Another form the designer proposed for a slide; `used_in`: the variants that show the slide in that form. */
export interface SlideAlternativeInfo { kind: string | null; label: string | null; text: string | null; used_in?: string[] }
/** Per slide of a variant: why the designer chose this form, the other forms, the conclusion and footnote on it and
 * the number of the slide in the user's text. */
export interface SlideDesign {
  index: number; kind?: string | null; rationale: string | null; alternatives: SlideAlternativeInfo[];
  takeaway: string | null; footnote: string | null; spec_ref: number | null;
}

// ---- outline / plan ---------------------------------------------------------------
export interface Fact { id: string; value: string; unit: string | null; label: string; source_span: string | null }
export interface Series { id: string; name: string; categories: string[]; values: number[]; unit: string | null }
export interface TableData { columns: string[]; rows: string[][]; unit: string | null; caption: string | null }
export interface ChartSpec {
  type: string; series_ids: string[]; title: string | null; unit: string | null; highlight_index: number | null;
  /** Agent v2: the chart's data written by the designer. */
  categories?: string[]; series?: { name: string; values: number[] }[];
}
export interface SlideItem { title: string; text: string; icon_hint: string | null; number: string | null; bullets: string[] }
export interface NumberCallout { value: string; label: string; fact_id: string | null }
export interface SlideContent {
  bullets: string[];
  paragraphs: string[];
  items: SlideItem[];
  numbers: NumberCallout[];
  table: TableData | null;
  chart: ChartSpec | null;
  quote: string | null;
  quote_author: string | null;
  image_hint: string | null;
  columns: SlideItem[];
  /** Agent v2: a second chart beside the first, a formula shown large. */
  chart2?: ChartSpec | null;
  formula?: string | null;
}
export interface OutlineSlide {
  id: string;
  kind: PatternKind;
  section: string | null;
  headline: string;
  subtitle: string | null;
  content: SlideContent;
  notes: string;
  fact_refs: string[];
  /** Agent v2 (absent in older runs): the conclusion and the footnote on the slide, why the designer chose its form,
   * the slide of the user's text it answers, the other forms the designer proposed. */
  takeaway?: string | null;
  footnote?: string | null;
  rationale?: string | null;
  spec_ref?: number | null;
  alternatives?: { kind: string; change: string }[];
}
export interface DeckOutline {
  title: string;
  subtitle: string | null;
  audience: string | null;
  purpose: string | null;
  strategy: string;
  language: string;
  /** "rules" | "model" | "skeleton" (a topic without theses) | "shared:<strategy>" (another variant's model plan). */
  planned_by?: string;
  slides: OutlineSlide[];
  facts: Fact[];
  series: Series[];
  tables: TableData[];
  /** Agent v2: what the agent did, step by step, in plain Russian. */
  agent_log?: string[];
}
export interface LayoutSlide {
  outline_id: string;
  mode: "clone" | "synth";
  pattern_id: string | null;
  composition: string | null;
  fit: Record<string, unknown>;
  score: number;
  reasons: string[];
  alternatives: [string, number][];
}
export interface LayoutPlan { strategy: string; template_id: string; slides: LayoutSlide[] }

// ---- audit --------------------------------------------------------------------
export interface FixAction { action: string; params: Record<string, unknown>; description: string }
export interface Issue {
  id: string;
  slide: number; // 1-based, 0 = deck level
  check_id: string;
  severity: Severity;
  kind: IssueKind;
  message: string;
  bboxes: BboxFrac[];
  element_ids: string[];
  suggestion: string | null;
  autofix: FixAction | null;
  details: Record<string, unknown>;
  outline_id: string | null;
}
// figures: every number on the slides compared with the source text (audit/checks/facts.py); null without a brief
export interface FigureStats { checked: number; derived: number; unverified: number }
export interface AuditSummary { errors: number; warnings: number; infos: number; model_flags: number; score: number; checks_run: string[]; figures?: FigureStats | null }
export interface AuditReport {
  deck: string;
  template_id: string;
  strategy: string | null;
  issues: Issue[];
  summary: AuditSummary;
  per_slide: Record<string, string[]>;
  iterations: number;
  applied_fixes: Record<string, unknown>[];
  seconds: number;
}

// ---- run manifest ---------------------------------------------------------------
export interface ProviderDesc { backend: string; model?: string }
export interface RunManifest {
  verstka_version: string;
  git_commit: string | null;
  created_at: string;
  platform: string;
  template: { id: string; file: string };
  strategy: string;
  inputs: { brief_sha256: string | null; outline_sha256: string };
  skills: Record<string, { version: string; sha256: string }>;
  providers: Record<string, ProviderDesc>;
  timings_s: Record<string, number>;
  usage: Record<string, unknown>;
  applied_fixes: Record<string, unknown>[];
  audit: Partial<AuditSummary> & Record<string, unknown>;
  slides: unknown[];
  /** Who wrote the plan (newer runs): planned_by and the model that answered. */
  planner?: { planned_by?: string; model?: string | null; supplied?: boolean };
}

// ---- generations ------------------------------------------------------------------
export interface VariantSummary {
  n_slides?: number; score?: number | null; errors?: number | null; warnings?: number | null; seconds?: number;
  planned_by?: string; model?: string | null; model_label?: string | null; reason_code?: string | null; reason?: string | null;
}
export interface GenerationMeta {
  id: string;
  template_id: string;
  template_file?: string;
  /** The deck's title (the first variant's outline; newer servers). */
  title?: string | null;
  strategies: string[];
  brief?: string | null;
  audience?: string | null;
  purpose?: string | null;
  slides?: number | null;
  use_models?: boolean;
  seconds?: number;
  created_at?: number;
  status?: string;
  /** Why the build failed (status «failed»): its reason's first lines, or that the server restarted under it. */
  error?: string | null;
  /** The job that builds (built) the deck: a page reloaded mid-build follows it again (status «running»). */
  job_id?: string;
  summary?: Record<string, VariantSummary>;
  /** Did a model plan the decks; if none did — why (older servers do not send it). */
  planner?: PlannerInfo | null;
  /** The request's switches (newer runs): «Собрать ещё раз» repeats them. */
  audit_models?: boolean;
  autofix?: boolean;
  /** «Генерировать изображения» as the request asked (null: the server's default). */
  pictures?: boolean | null;
  exports?: string[];
  language?: string;
  extra_instructions?: string | null;
  /** The plan came with the request (no model was asked to plan). */
  outline_supplied?: boolean;
  /** Writer mode (newer servers): the text was a topic, and the agent wrote the deck's text from it first. */
  writer?: WriterInfo | null;
  /** «Взгляд дизайнера» as the request asked. */
  eyes?: boolean | null;
  /** «Улучшить готовую презентацию»: the original deck (its name, slides and audit). */
  improved_from?: ImprovedFrom | null;
}
/** What the agent wrote from a topic (generation.json `writer`, planning/writer.py `WriterResult.meta`). */
export interface WriterInfo {
  mode: "topic" | "expand";
  status: "written" | "private" | "refused" | "failed" | "skipped";
  kind?: string;
  /** The written text as the agent read it («Слайд 1. Титульный…»); empty unless written. */
  text?: string;
  /** The person's topic, as they wrote it. */
  topic?: string;
  /** Slides of the written deck, the cover included (0 unless written). */
  slides?: number;
  /** The slide count the person chose. */
  asked?: number;
  /** The encyclopedia article the text was written from; null: from the model's own knowledge. */
  source?: { title: string; url: string } | null;
  /** All the articles the text was written from (newer servers; `source` is the first). */
  pages?: { title: string; url: string }[];
  /** Every statement's source (source-anchored writing): the statement as the text shows it, the article and its
   *  sentence. Empty when the text was not anchored. */
  sources?: { text: string; page: string; url: string; sentence: string }[];
  removed?: number;
  checked?: "reference" | "model" | null;
  model_label?: string | null;
  seconds?: number;
  /** Content slides fewer than asked after the checks and the refill (0: as asked). */
  short_by?: number;
}
export interface VariantEdit {
  at: number; request: string; reply: string; kind: string; slides: number[]; score_before: number | null; score_after: number | null;
  /** A slide fix (kind "fix", newer servers): the remarks it fixed, how (model | rules | autofix) and the snapshot version. */
  fixed?: string[]; how?: string; version?: number | null;
  /** «верни как было» (newer servers): the version this entry undid; null — a change of its own. */
  undo_of?: number | null;
}
export interface Variant {
  strategy: string;
  planner?: PlannerInfo;
  edits?: VariantEdit[]; // the chat agent's edits of this variant, oldest first
  outline: DeckOutline | null;
  plan: LayoutPlan | null;
  audit: AuditReport | null;
  run_manifest: RunManifest | null;
  slides: string[];
  files: Record<string, string>;
  /** Agent v2 (newer servers; empty lists for older runs). */
  agent?: VariantAgent;
  design?: SlideDesign[];
  /** The pictures inside the slides and the places kept for them (newer servers). */
  pictures?: SlidePicture[];
  /** «Взгляд дизайнера» (Verstka 3.0): what the vision model saw and what it laid out again; null when it did not run. */
  eyes?: DesignEye | null;
}
export interface Generation extends GenerationMeta { variants: Variant[] }

/** A problem the vision model named on a slide (closed list of codes; `label` is its Russian name). */
export interface DesignProblem { code: string; label: string; severity: "major" | "minor" | string; where: string; evidence: string }
/** One slide the model had something to say about: laid out again (`fixed`, with the slide before and after), tried
 *  again but kept (`kept`, with why) or only noted (`seen`, minor polish). Numbers are the slides' current ones. */
export interface DesignEyeSlide {
  outline_id: string;
  slide: number;
  status: "fixed" | "kept" | "seen";
  problems: DesignProblem[];
  reason: string;
  before: string | null;
  after: string | null;
  /** Redesigned since the build: the pictures of the review are not this slide's any more. */
  redone?: boolean;
}
/** `skipped` — why the review did not look (English, for the log); `skipped_code` — the same as a code the interface
 *  says in words (lib/designEye `EYES_SKIP`): off · no_model · no_time · no_images · no_answer · failed. */
export interface DesignEye { looked: number; seconds?: number | null; skipped?: string | null; skipped_code?: string | null; slides: DesignEyeSlide[] }

/** A picture inside a slide, or the place kept for one: generated — a text-to-image model made it; free — the place
 *  waits (why: the author's own photo, generation off, the model did not answer); removed — the person took it out. */
export interface SlidePicture {
  id: string;
  slide: number;
  status: "generated" | "free" | "removed";
  /** The author's own photo goes there: never generated by itself. */
  own?: boolean;
  why?: string | null;
  /** What the picture shows, in the author's words; the person's wish for the current one. */
  hint?: string | null;
  label?: string | null;
  headline?: string | null;
  wish?: string | null;
  prompt?: string | null;
  style?: string | null;
  model?: string | null;
  model_label?: string | null;
  palette_match?: number | null;
  at?: number | null;
  /** Where the place is on the slide, in slide fractions (newer servers): the result screen frames it and takes a click. */
  bbox?: BboxFrac | null;
}
/** «Заменить изображение»: POST /api/generations/{gid}/{strategy}/slides/{n}/image */
export interface PictureChangeRequest { wish?: string | null; action?: "generate" | "remove" }
export interface PictureChangeResult {
  reply: string; changed: boolean; applied: boolean; kind: "picture"; action: "generate" | "remove"; strategy: string; slide: number;
  picture?: SlidePicture | null; version?: number | null; at?: number | null; score_before?: number | null; new_score?: number | null;
}

export interface GenerateRequest {
  template_id: string;
  brief: string;
  audience?: string | null;
  purpose?: string | null;
  slides?: number | null;
  language?: string;
  extra_instructions?: string | null;
  strategies: string[];
  use_models: boolean;
  audit_models: boolean;
  autofix: boolean;
  exports: string[];
  /** «Генерировать изображения»: null — the server's default (on when a text-to-image model has a key). */
  pictures?: boolean | null;
  /** «Взгляд дизайнера»: null — with the text model; true — on its own too (an improved deck keeps its text). */
  eyes?: boolean | null;
  /** «Улучшить готовую презентацию»: the original deck, for «было → стало». */
  improved_from?: ImprovedFrom | null;
}
export interface GenerateResponse { job_id: string; generation_id: string }
export interface FixRequest { issue_ids?: string[]; all_deterministic?: boolean }
export interface FixResult { score: number; errors: number; warnings: number; applied: Record<string, unknown>[] }
/** «Исправить слайд»: POST /api/generations/{gid}/{strategy}/slides/{n}/fix — the remarks of one slide, the person's
 *  wishes; only that slide of the deck changes. */
export interface SlideFixRequest { wishes?: string | null; issue_ids?: string[] }
/** A stage remark of the fixed slide after the fix; `new`: its check was not among the slide's remarks before. */
export interface SlideFixRemaining { id: string; check_id: string; severity: Severity; message: string; new: boolean }
export interface SlideFixResult {
  reply: string; changed: boolean; applied: boolean; kind: "fix"; strategy: string; slide: number;
  requested: string[]; fixed: string[]; remaining: SlideFixRemaining[];
  score_before: number | null; new_score: number | null; errors?: number; warnings?: number;
  changed_other_slides: boolean; other_slides: number[];
  how: "model" | "rules" | "autofix"; notes: string[]; why: string | null; version: number | null; at: number | null;
}
export interface ExplainResponse { index: number; text: string }

export interface DiffChange<T = unknown> { from: T; to: T }
export interface DiffResponse {
  a: { generation: string; strategy: string; score: number | null };
  b: { generation: string; strategy: string; score: number | null };
  diff: {
    skills: Record<string, DiffChange<{ version: string; sha256: string } | null>>;
    providers: Record<string, DiffChange<ProviderDesc | null>>;
    strategy: DiffChange<string> | null;
    audit_score: DiffChange<number | null> | null;
  };
}

// ---- chat -----------------------------------------------------------------------
export type ChatAction =
  | { type: "generation_started"; job_id: string; generation_id: string }
  | { type: "jobs"; jobs: { strategy: string; job_id: string }[] }
  | { type: "open_tab"; tab: string; slide?: number }
  | { type: "edit"; job_id: string; strategy: string; generation_id: string; slide?: number | null };
// what an edit job answers (verstka/api/app.py _edit_job): the agent's reply and the slide to show
export interface EditResult { reply: string; changed: boolean; slide?: number | null; strategy?: string; score?: number | null; kind?: string }
export interface ChatResponse { reply: string; intent: string; actions: ChatAction[]; template_id: string | null; generation_id: string | null }
export interface ChatMessage { id: string; role: "user" | "assistant"; text: string; ts: number; pending?: boolean }
