// The planning agent's work (Agent v2) as a timeline of plain steps: Аналитик → Архитектор (when the text did not
// describe the slides) → Дизайнер (a line per slide with its form) → Критик → Правка → Вёрстка → Проверка.
// The agent's own steps come as events {step, message, slide, variant}; «Вёрстка» and «Проверка» follow the
// pipeline's plain progress messages («visual: rendered slide 3/10», «export: …»). Pure functions, no React.
import type { AgentEvent, DeckOutline, JobEvent, Variant } from "../types";
import { plural } from "./utils";

export type PhaseKey = "analyst" | "architect" | "designer" | "critic" | "revise" | "layout" | "check";
export type PhaseStatus = "done" | "active" | "pending" | "skipped";

export interface PhaseDef { key: PhaseKey; title: string; hint: string; optional?: boolean }

export const PHASES: PhaseDef[] = [
  { key: "analyst", title: "Аналитик", hint: "читает текст: какие слайды, цифры и диаграммы нужны" },
  { key: "architect", title: "Архитектор", hint: "выстраивает сюжет: разделы и слайды", optional: true },
  { key: "designer", title: "Дизайнер", hint: "придумывает форму каждого слайда" },
  { key: "critic", title: "Критик", hint: "сверяет план с текстом и правилами" },
  { key: "revise", title: "Правка", hint: "переделывает слайды с замечаниями" },
  { key: "layout", title: "Вёрстка", hint: "раскладывает слайды по макетам шаблона" },
  { key: "check", title: "Проверка", hint: "шрифты, цвета, отступы — и исправления" },
];

const ORDER: Record<PhaseKey, number> = Object.fromEntries(PHASES.map((p, i) => [p.key, i])) as Record<PhaseKey, number>;
export const phaseOrder = (k: PhaseKey) => ORDER[k];
export const laterPhase = (a: PhaseKey | null | undefined, b: PhaseKey | null | undefined): PhaseKey | null =>
  !a ? b ?? null : !b ? a : ORDER[b] > ORDER[a] ? b : a;

/** The agent's step (contract names) → the phase of the timeline; null for a step this UI does not know. */
export function phaseOfStep(step: string | null | undefined): PhaseKey | null {
  switch ((step ?? "").toLowerCase()) {
    case "analyst": return "analyst";
    case "architect": return "architect";
    case "designer": return "designer";
    case "critic": return "critic";
    case "revise": return "revise";
    case "compile": return "layout";
    default: return null;
  }
}

/** Where a plain progress message of the pipeline is («analyze: …», «plan: 3 variants», «visual: rendered slide 3/10»). */
export function phaseOfMessage(message: string): PhaseKey | null {
  const m = message.trim();
  if (/^(analyze|plan): /.test(m)) return "analyst";
  if (/^export: /.test(m)) return "check";
  const r = m.match(/^([a-z_]+): (.+)$/);
  if (!r) return null;
  const what = r[2];
  if (/^planned \d+ slides/.test(what) || /^rendered slide/.test(what)) return "layout";
  if (what === "audit" || /^autofix/.test(what) || /^done in /.test(what)) return "check";
  return null;
}

export function phaseOfEvent(ev: JobEvent): PhaseKey | null {
  return ev.type === "agent" ? phaseOfStep(ev.step) : ev.message ? phaseOfMessage(ev.message) : null;
}

export function toAgentEvent(ev: JobEvent): AgentEvent {
  return { step: ev.step ?? "", message: ev.message, slide: ev.slide ?? null, variant: ev.variant ?? null, t: ev.t, seq: ev.seq };
}

const sameEvent = (a: AgentEvent, b: AgentEvent) =>
  a.seq !== undefined && b.seq !== undefined ? a.seq === b.seq : a.step === b.step && a.message === b.message && a.slide === b.slide && a.variant === b.variant;

/** Appends an event unless the list has it (the stream and the polled job record both deliver it). */
export function addAgentEvent(list: AgentEvent[] | undefined, ev: AgentEvent): AgentEvent[] {
  const cur = list ?? [];
  return cur.some((x) => sameEvent(x, ev)) ? cur : [...cur, ev];
}

/** The phase of every event; a step unknown to this UI joins the phase before it. */
export function withPhases(events: AgentEvent[]): Array<AgentEvent & { phase: PhaseKey }> {
  let last: PhaseKey = "analyst";
  return events.map((e) => {
    const phase = phaseOfStep(e.step) ?? last;
    last = phase;
    return { ...e, phase };
  });
}

/** «Слайд 3 — круговая диаграмма расходов» with the slide shown as a badge: the text after the number. */
export function eventText(e: AgentEvent): string {
  const text = e.slide !== null && e.slide !== undefined ? e.message.replace(/^слайд[ыа]?\s*\d+\s*[—–:.-]\s*/i, "") : e.message;
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : e.message;
}

export interface TimelineRow {
  key: PhaseKey;
  title: string;
  hint: string;
  status: PhaseStatus;
  /** A line under the title when the phase has no events of its own (the layout progress, why it was skipped). */
  note: string | null;
  events: Array<AgentEvent & { phase: PhaseKey }>;
}

export interface TimelineInput {
  events: AgentEvent[];
  /** The latest phase reached (from every event of the job); null before the first one. */
  phase: PhaseKey | null;
  /** The job is still running (false: everything reached is done). */
  running: boolean;
  notes?: Partial<Record<PhaseKey, string | null>>;
}

export function buildTimeline({ events, phase, running, notes }: TimelineInput): TimelineRow[] {
  const evs = withPhases(events);
  let cur = phase;
  for (const e of evs) cur = laterPhase(cur, e.phase);
  const curIdx = cur ? ORDER[cur] : 0;
  const criticSaid = evs.some((e) => e.phase === "critic");
  const rows: TimelineRow[] = [];
  for (const def of PHASES) {
    const own = evs.filter((e) => e.phase === def.key);
    if (def.optional && own.length === 0) continue;
    const idx = ORDER[def.key];
    const passed = running ? idx < curIdx : idx <= curIdx || !cur;
    let status: PhaseStatus = passed ? "done" : running && idx === curIdx ? "active" : "pending";
    let note = notes?.[def.key] ?? null;
    // the critic and the revision leave no trace when the plan came without the model, ran out of time or needed no fixes
    if ((def.key === "critic" || def.key === "revise") && own.length === 0 && passed) {
      status = "skipped";
      note = def.key === "critic" ? "в этой сборке не запускался" : criticSaid ? "правки не понадобились" : "не понадобилась";
    }
    rows.push({ key: def.key, title: def.title, hint: def.hint, status, note, events: own });
  }
  return rows;
}

// ---------------------------------------------------------------------------- a finished variant

const count = (n: number, one: string, few: string, many: string) => plural(n, one, few, many);

/** What the deck shows, counted: «4 диаграммы, 1 таблица, 1 формула». */
export function formsSummary(outline: DeckOutline | null | undefined): string | null {
  if (!outline) return null;
  let charts = 0;
  let tables = 0;
  let formulas = 0;
  for (const s of outline.slides) {
    charts += (s.content.chart ? 1 : 0) + (s.content.chart2 ? 1 : 0);
    tables += s.content.table ? 1 : 0;
    formulas += s.content.formula ? 1 : 0;
  }
  const parts = [charts && count(charts, "диаграмма", "диаграммы", "диаграмм"), tables && count(tables, "таблица", "таблицы", "таблиц"), formulas && count(formulas, "формула", "формулы", "формул")].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

export interface AgentSummaryLine { step: string; text: string }

/** Three lines for the result screen: what the analyst found, what the designer made, what the critic said. */
export function agentSummary(v: Variant | null | undefined): AgentSummaryLine[] {
  const a = v?.agent;
  if (!a) return [];
  const evs = withPhases(a.events ?? []);
  const lines: AgentSummaryLine[] = [];
  if (evs.length) {
    const analyst = evs.find((e) => e.phase === "analyst");
    if (analyst) lines.push({ step: "Аналитик", text: analyst.message });
    const designed = evs.filter((e) => e.phase === "designer");
    const forms = formsSummary(v?.outline);
    if (designed.length) lines.push({ step: "Дизайнер", text: `продумал ${count(designed.length, "слайд", "слайда", "слайдов")}${forms ? `: ${forms}` : ""}` });
    const critic = evs.filter((e) => e.phase === "critic" && e.variant === v?.strategy);
    const fixed = [...new Set(evs.filter((e) => e.phase === "revise" && e.slide !== null).map((e) => e.slide as number))].sort((x, y) => x - y);
    if (critic.length || fixed.length) {
      const said = critic.filter((e) => e.slide !== null).length;
      const head = said ? count(said, "замечание", "замечания", "замечаний") : critic[0]?.message ?? "";
      lines.push({ step: "Критик", text: fixed.length ? `${head}${head ? " — " : ""}${fixed.length === 1 ? "исправлен слайд" : "исправлены слайды"} ${fixed.join(", ")}` : head });
    }
    // the variants are nearly one deck when the brief dictated the forms: said plainly, not offered as alternatives
    const same = [...evs.map((e) => e.message), ...(a.log ?? [])].find((m) => /отличаются подачей/.test(m));
    if (same) lines.push({ step: "Варианты", text: same.replace(/^Сборка:\s*/, "") });
    return lines;
  }
  return (a.log ?? []).slice(0, 3).map((line) => {
    const m = line.match(/^([А-ЯЁ][а-яё]+):\s*(.+)$/);
    return m ? { step: m[1], text: m[2] } : { step: "", text: line };
  });
}

export const hasAgentWork = (v: Variant | null | undefined) => !!v?.agent && ((v.agent.events?.length ?? 0) > 0 || (v.agent.log?.length ?? 0) > 0);
