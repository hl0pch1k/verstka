// Typed mirror of the Verstka FastAPI contract (verstka/api/app.py + verstka/schemas/*).

export type Severity = "error" | "warn" | "info";
export type IssueKind = "deterministic" | "model";
export type Family = "light" | "dark";
export type PatternKind =
  | "title" | "section" | "agenda" | "bullets" | "cards" | "two_column" | "big_number" | "stat_row"
  | "comparison" | "timeline" | "process" | "table" | "chart" | "image_text" | "team" | "quote"
  | "code" | "mockup" | "thanks" | "freeform";

/** Views of the app. The header shows five steps; «plan» lives inside «variants», «run» inside «export». */
export type TabKey = "template" | "brief" | "plan" | "variants" | "why" | "audit" | "export" | "run" | "agent";
/** The two screens a person sees; everything expert lives in the «Подробнее» drawer. */
export type Screen = "create" | "result";
export type DetailKey = "quality" | "why" | "agent" | "plan" | "template" | "tech";
export type JobKind = "analyze" | "generate" | "fix" | "edit" | "slide_fix" | "other";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface BboxFrac { x: number; y: number; w: number; h: number }

// ---- meta -------------------------------------------------------------------
export interface Health { ok: boolean; version: string; models_configured: boolean; workspace: string }

// ---- models (GET /api/models/status) ------------------------------------------------
/** A link of the model chain: the primary model first, then the backups.
 * ok — answered last time; unknown — not tried since the server started; congested — the host is overloaded (429
 * upstream / 5xx); rate — the account's per-minute cap (under 90 s); quota — the free daily quota of OpenRouter (until
 * 00:00 UTC); no_credits — 402; auth — the key is refused; missing — no such model; error — anything else; off — its
 * key is not set: skipped, never a failure. */
export type ModelLinkState = "ok" | "unknown" | "congested" | "rate" | "quota" | "no_credits" | "auth" | "missing" | "error" | "off";
export interface ModelLink {
  model: string | null;
  label: string;
  /** The label without «(бесплатно)» / «(OpenRouter)». */
  short_label?: string;
  /** Host name only («openrouter.ai»). */
  host?: string | null;
  state: ModelLinkState;
  /** False while the link pauses after a failure (see `until`). */
  available: boolean;
  last_ok: number | null;
  last_error: string | null;
  last_error_at?: number | null;
  /** Seconds until a congested / exhausted link is tried again. */
  until: number | null;
  free: boolean;
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
  /** Seconds until a paused link is tried again, and that link's state (quota: after 00:00 UTC). */
  retry_in: number | null;
  retry_state?: ModelLinkState | null;
  /** What the notice above a failed deck advises now («Соберите ещё раз через минуту.»), or null. */
  advice?: string | null;
  /** Building again can work now or once `retry_in` is over (false: a key, an account or a model id needs a fix). */
  retryable?: boolean;
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
  /** Plain Russian clause: «бесплатные модели OpenRouter сейчас перегружены». */
  reason: string | null;
  /** What helps, one sentence. */
  advice: string | null;
  /** The same deck built again can get past the reason (congestion, a cap, the time budget…); false: fix first. */
  retryable?: boolean;
  /** «Чтобы не зависеть от очереди бесплатных, пополните OpenRouter…» when a free model failed; added to the live advice. */
  steady?: string | null;
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
export interface RepeatGroup { id: string; member_shape_ids: string[][]; min_n: number; max_n: number; axis: string; rows: number; cols: number }
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
}
export interface StyleRule { text: string; source: string; confidence: number }
export interface TemplateManifest {
  template_id: string;
  source_file: string;
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
  summary?: Record<string, VariantSummary>;
  /** Did a model plan the decks; if none did — why (older servers do not send it). */
  planner?: PlannerInfo | null;
  /** The request's switches (newer runs): «Собрать ещё раз» repeats them. */
  audit_models?: boolean;
  autofix?: boolean;
  exports?: string[];
  language?: string;
  extra_instructions?: string | null;
  /** The plan came with the request (no model was asked to plan). */
  outline_supplied?: boolean;
  /** Writer mode (newer servers): the text was a topic, and the agent wrote the deck's text from it first. */
  writer?: WriterInfo | null;
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
  removed?: number;
  checked?: "reference" | "model" | null;
  model_label?: string | null;
  seconds?: number;
}
export interface VariantEdit {
  at: number; request: string; reply: string; kind: string; slides: number[]; score_before: number | null; score_after: number | null;
  /** A slide fix (kind "fix", newer servers): the remarks it fixed, how (model | rules | autofix) and the snapshot version. */
  fixed?: string[]; how?: string; version?: number | null;
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
}
export interface Generation extends GenerationMeta { variants: Variant[] }

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
