// Typed mirror of the Verstka FastAPI contract (verstka/api/app.py + verstka/schemas/*).

export type Severity = "error" | "warn" | "info";
export type IssueKind = "deterministic" | "model";
export type Family = "light" | "dark";
export type PatternKind =
  | "title" | "section" | "agenda" | "bullets" | "cards" | "two_column" | "big_number" | "stat_row"
  | "comparison" | "timeline" | "process" | "table" | "chart" | "image_text" | "team" | "quote"
  | "code" | "mockup" | "thanks" | "freeform";

/** Views of the app. The header shows five steps; «plan» lives inside «variants», «run» inside «export». */
export type TabKey = "template" | "brief" | "plan" | "variants" | "why" | "audit" | "export" | "run";
/** The two screens a person sees; everything expert lives in the «Подробнее» drawer. */
export type Screen = "create" | "result";
export type DetailKey = "quality" | "why" | "plan" | "template" | "tech";
export type JobKind = "analyze" | "generate" | "fix" | "other";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface BboxFrac { x: number; y: number; w: number; h: number }

// ---- meta -------------------------------------------------------------------
export interface Health { ok: boolean; version: string; models_configured: boolean; workspace: string }
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
}
export interface JobEvent { job_id: string; status: JobStatus; progress: number; message: string; t: number }

// ---- outline / plan ---------------------------------------------------------------
export interface Fact { id: string; value: string; unit: string | null; label: string; source_span: string | null }
export interface Series { id: string; name: string; categories: string[]; values: number[]; unit: string | null }
export interface TableData { columns: string[]; rows: string[][]; unit: string | null; caption: string | null }
export interface ChartSpec { type: string; series_ids: string[]; title: string | null; unit: string | null; highlight_index: number | null }
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
export interface AuditSummary { errors: number; warnings: number; infos: number; model_flags: number; score: number; checks_run: string[] }
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
}

// ---- generations ------------------------------------------------------------------
export interface VariantSummary { n_slides?: number; score?: number | null; errors?: number | null; warnings?: number | null; seconds?: number }
export interface GenerationMeta {
  id: string;
  template_id: string;
  template_file?: string;
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
}
export interface Variant {
  strategy: string;
  outline: DeckOutline | null;
  plan: LayoutPlan | null;
  audit: AuditReport | null;
  run_manifest: RunManifest | null;
  slides: string[];
  files: Record<string, string>;
}
export interface Generation extends GenerationMeta { variants: Variant[] }

export interface GenerateRequest {
  template_id: string;
  brief: string;
  audience?: string | null;
  purpose?: string | null;
  slides?: number | null;
  strategies: string[];
  use_models: boolean;
  audit_models: boolean;
  autofix: boolean;
  exports: string[];
}
export interface GenerateResponse { job_id: string; generation_id: string }
export interface FixRequest { issue_ids?: string[]; all_deterministic?: boolean }
export interface FixResult { score: number; errors: number; warnings: number; applied: Record<string, unknown>[] }
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
  | { type: "open_tab"; tab: string; slide?: number };
export interface ChatResponse { reply: string; intent: string; actions: ChatAction[]; template_id: string | null; generation_id: string | null }
export interface ChatMessage { id: string; role: "user" | "assistant"; text: string; ts: number; pending?: boolean }
