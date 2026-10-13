// The state of a running job as the interface sees it, and the one fold of a job event into it: the store folds the
// stream (and the polled record) with it, the dev replay folds a recorded build the same way.
import type { AgentEvent, JobEvent, JobKind, JobStatus } from "../types";
import { addAgentEvent, eventParts, laterPhase, phaseOfEvent, phaseOfMessage, toAgentEvent, type PhaseKey } from "./agent";
import { humanizeJobMessage, variantProgress, type VariantProgress } from "./jobText";

/** What the build stage says now: the agent's newest line or the pipeline's newest step. `n` counts the changes (a
 *  repeat of the same words is no change, so the stage never types a line twice). */
export interface StageLine { text: string; slide: number | null; variant: string | null; n: number }

export interface ActiveJob {
  id: string; label: string; progress: number; message: string; status: JobStatus; kind: JobKind; startedAt: number; items?: string[]; variants?: Record<string, VariantProgress>;
  /** When the job ended (ms; done or failed): the build's clock stops there. null — it ended, when is not known (a build
   *  that stopped while the page was closed, its job forgotten by the server): the clock shows a dash. */
  endedAt?: number | null;
  /** The planning agent's steps so far (Agent v2) and the latest phase of the timeline the job has reached. */
  agent?: AgentEvent[]; phase?: PhaseKey | null;
  /** The template a generation is built from (the build screen names it under its title). */
  template?: string | null;
  /** The slide a job works on (a slide fix): the stage and the thumbnails mark it. */
  target?: { generation: string; strategy: string; slide: number };
  /** The generation being built (the build's rail shows its slide previews once they are rendered) and the slide count
   *  the person asked for (the rail's first tiles). */
  generation?: string | null; slides?: number | null;
  line?: StageLine | null;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));

/** A variant's new status over its last: the planned count stays; checking and fixing mean every slide is laid out. */
function mergeVariant(prev: VariantProgress | undefined, next: VariantProgress): VariantProgress {
  const of = next.of ?? prev?.of;
  const laid = next.laid ?? (next.done || /^(проверка|исправляю)/.test(next.text) ? of : prev?.laid);
  return { ...next, of, laid };
}

function nextLine(cur: StageLine | null | undefined, text: string, slide: number | null, variant: string | null): StageLine | null | undefined {
  if (!text || (cur && cur.text === text && cur.slide === slide && cur.variant === variant)) return cur;
  return { text, slide, variant, n: (cur?.n ?? 0) + 1 };
}

/** One event of a job (not the terminal one: the store settles that from the full job record). */
export function foldJobEvent(cur: ActiveJob, ev: JobEvent, titleOf: (name: string) => string): ActiveJob {
  const isAgent = ev.type === "agent";
  // the agent speaks plain Russian already; the pipeline's own messages are for logs and get translated
  const message = isAgent ? ev.message : ev.message ? humanizeJobMessage(ev.message, titleOf) : "";
  // every event is folded in (renders may coalesce several): the per-variant states and the agent's timeline never
  // miss a step
  const step = !isAgent && ev.message ? variantProgress(ev.message) : null;
  const agent = isAgent ? addAgentEvent(cur.agent, toAgentEvent(ev)) : cur.agent;
  let line = cur.line;
  if (isAgent && agent !== cur.agent) line = nextLine(line, eventParts(toAgentEvent(ev)).text, ev.slide ?? null, ev.variant ?? null);
  // only the pipeline's own steps speak on the stage (a polled record repeats the agent's last words as its message)
  else if (!isAgent && ev.message && phaseOfMessage(ev.message)) line = nextLine(line, message, step?.state.laid || null, step?.name ?? null);
  return {
    ...cur,
    status: ev.status,
    progress: Math.max(cur.progress, clamp01(ev.progress)),
    message: message || cur.message,
    variants: step ? { ...cur.variants, [step.name]: mergeVariant(cur.variants?.[step.name], step.state) } : cur.variants,
    agent,
    phase: laterPhase(cur.phase, phaseOfEvent(ev)),
    line,
  };
}
