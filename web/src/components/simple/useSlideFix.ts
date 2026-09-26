// «Исправить слайд»: the one slide-fix run of a Deck. It starts the job (POST …/slides/{n}/fix), follows it through the
// store's runJob (quietly: the panel tells the story), reloads the deck when the fix was applied and offers the exact
// undo («верни как было»). The Deck is keyed by generation, so the run survives slide and variant switches and the
// same-generation reload.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { errText, firstLine } from "../../lib/narrate";
import { useApp } from "../../store";
import type { AgentEvent, Job, SlideFixRemaining, SlideFixResult } from "../../types";
import type { StageRemark } from "../VariantsHelpers";

export type FixPhase = "submitting" | "running" | "done" | "failed" | "undoing" | "undone";
export interface FixRun {
  strategy: string;
  slide: number;
  /** The remarks the fix was asked for, as they were numbered on the slide when it started. */
  requested: StageRemark[];
  wishes: string;
  jobId: string | null;
  startedAt: number;
  phase: FixPhase;
  result: SlideFixResult | null;
  error: string | null;
  /** The fixed slide's new image has been shown (or nothing had to be shown): the scan stops. */
  revealed: boolean;
  /** The person has seen the settled run on its slide (a banner elsewhere is no longer needed). */
  seen: boolean;
  /** The deck on screen is the one the run's outcome describes (the reload after an applied fix or an undo is in). */
  synced: boolean;
  /** The panel has played the «done» choreography (fixed rows turn into checks and fold): a panel mounted again later
   *  (the switch off and on) shows the settled list at once and never brings a removed remark back. */
  celebrated: boolean;
  /** When the run last changed phase (ms): keys the one-shot animations of that phase. */
  at: number;
}

export interface SlideFix {
  run: FixRun | null;
  events: AgentEvent[];
  progress: number;
  /** The job's latest plain line («Готовлю превью» while the previews render after the check). */
  message: string;
  /** Starts a fix; resolves true when the job has started (the draft of wishes can go). */
  start(strategy: string, slide: number, remarks: StageRemark[], wishes: string): Promise<boolean>;
  undo(): Promise<void>;
  reveal(): void;
  seen(): void;
  /** The «done» choreography has played (FixRun.celebrated). */
  celebrate(): void;
  dismiss(): void;
}

const hasCyrillic = (s: string) => /[а-яё]/i.test(s);
/** A job error as a person reads it: the first line, never a stack trace or an English server message. */
function reasonOf(job: Job): string {
  const line = firstLine(job.error ?? job.message, "");
  return line && hasCyrillic(line) ? line.replace(/\.\s*$/, "") : "Сервер не смог исправить слайд";
}

function asRemaining(v: unknown): SlideFixRemaining | null {
  if (!v || typeof v !== "object") return null;
  const r = v as Partial<SlideFixRemaining>;
  if (typeof r.id !== "string" || typeof r.check_id !== "string") return null;
  const severity = r.severity === "error" || r.severity === "warn" || r.severity === "info" ? r.severity : "warn";
  return { id: r.id, check_id: r.check_id, severity, message: String(r.message ?? ""), new: !!r.new };
}

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The job result arrives as `unknown`: accept it only when it really looks like a slide fix. */
export function asSlideFixResult(value: unknown): SlideFixResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Record<string, unknown>;
  if (typeof r.reply !== "string" || typeof r.slide !== "number") return null;
  const applied = typeof r.applied === "boolean" ? r.applied : !!r.changed;
  const how = r.how === "model" || r.how === "rules" || r.how === "autofix" ? r.how : "autofix";
  return {
    reply: r.reply,
    changed: !!r.changed,
    applied,
    kind: "fix",
    strategy: String(r.strategy ?? ""),
    slide: r.slide,
    requested: strings(r.requested),
    fixed: strings(r.fixed),
    remaining: (Array.isArray(r.remaining) ? r.remaining : []).map(asRemaining).filter((x): x is SlideFixRemaining => !!x),
    score_before: numOrNull(r.score_before),
    new_score: numOrNull(r.new_score),
    errors: numOrNull(r.errors) ?? undefined,
    warnings: numOrNull(r.warnings) ?? undefined,
    changed_other_slides: !!r.changed_other_slides,
    other_slides: Array.isArray(r.other_slides) ? r.other_slides.filter((x): x is number => typeof x === "number") : [],
    how,
    notes: strings(r.notes),
    why: typeof r.why === "string" && r.why ? r.why : null,
    version: numOrNull(r.version),
    at: numOrNull(r.at),
  };
}

/** `visible(run)`: the panel shows that run right now (the mode is on, the run's slide is on screen, no drawer over
 *  it). When it is not, the outcome is told in a toast. */
export function useSlideFix(gid: string, visible: (run: FixRun) => boolean): SlideFix {
  const { runJob, loadGeneration, activeJob, toast, generationId } = useApp();
  const [run, setRun] = useState<FixRun | null>(null);
  const live = useRef({ run, visible, runJob, loadGeneration, toast, generationId, mounted: true });
  live.current = { ...live.current, run, visible, runJob, loadGeneration, toast, generationId };
  /** Reloads the deck, unless the person has opened another one meanwhile (never yank them back). */
  const reload = async () => {
    if (live.current.generationId === gid) await live.current.loadGeneration(gid);
  };
  useEffect(() => {
    live.current.mounted = true;
    return () => {
      live.current.mounted = false;
    };
  }, []);

  const patch = useCallback((jobOrNull: string | null, p: Partial<FixRun>) => {
    setRun((cur) => (cur && (jobOrNull === null || cur.jobId === jobOrNull) ? { ...cur, ...p, at: p.phase && p.phase !== cur.phase ? Date.now() : cur.at } : cur));
  }, []);
  /** Shown to the person now? An unmounted deck (another screen) never is. */
  const shown = (r: FixRun | null) => !!r && live.current.mounted && live.current.visible(r);

  // the agent's lines of the running job; kept after the store lets the job go, so a finished timeline keeps them
  const kept = useRef<{ job: string | null; events: AgentEvent[]; progress: number; message: string }>({ job: null, events: [], progress: 0, message: "" });
  if (run?.jobId && activeJob?.id === run.jobId && run.phase === "running") {
    kept.current = { job: run.jobId, events: activeJob.agent ?? [], progress: activeJob.progress, message: activeJob.message };
  }

  const start = useCallback(async (strategy: string, slide: number, remarks: StageRemark[], wishes: string): Promise<boolean> => {
    const cur = live.current.run;
    if (cur && (cur.phase === "submitting" || cur.phase === "running" || cur.phase === "undoing")) return false;
    const now = Date.now();
    kept.current = { job: null, events: [], progress: 0, message: "" };
    setRun({ strategy, slide, requested: remarks, wishes: wishes.trim(), jobId: null, startedAt: now, phase: "submitting", result: null, error: null, revealed: false, seen: false, synced: true, celebrated: false, at: now });
    let jobId: string;
    try {
      const res = await api.fixSlide(gid, strategy, slide, { wishes: wishes.trim() || null, issue_ids: remarks.map((r) => r.issue.id) });
      jobId = res.job_id;
    } catch (e) {
      setRun(null);
      const busy = e instanceof ApiError && e.status === 409;
      live.current.toast("error", busy ? "Этот вариант уже меняется — дождитесь конца" : `Не получилось запустить исправление: ${errText(e)}`);
      return false;
    }
    setRun((r) => (r && r.startedAt === now ? { ...r, jobId, phase: "running", at: Date.now() } : r));
    live.current.runJob(jobId, `Исправляю слайд ${slide}`, {
      kind: "slide_fix",
      target: { generation: gid, strategy, slide },
      quiet: true,
      onDone: async (job) => {
        const res = asSlideFixResult(job.result);
        if (!res) {
          patch(jobId, { phase: "failed", error: "Сервер не смог исправить слайд", revealed: true });
          const r = live.current.run;
          if (!shown(r)) live.current.toast("error", `Не получилось исправить слайд ${slide}: сервер не смог исправить слайд`);
          return;
        }
        // the outcome at once (the scan runs on until the new slide is on screen), then the new deck: the reload keeps
        // the variant and the slide the person is on
        patch(jobId, { phase: "done", result: res, revealed: !res.applied, synced: !res.applied });
        if (res.applied) {
          await reload();
          patch(jobId, { synced: true });
        }
        const r = live.current.run;
        if (!shown(r ? { ...r, phase: "done" } : r)) {
          const before = res.score_before === null ? null : Math.round(res.score_before);
          const after = res.new_score === null ? null : Math.round(res.new_score);
          const score = before !== null && after !== null && before !== after ? ` · ${before} → ${after}` : "";
          const all = res.requested.length > 0 && res.fixed.length >= res.requested.length;
          if (!res.applied) live.current.toast("info", `Слайд ${slide} не исправлен: ${(res.why ?? "замечания остались").replace(/\.\s*$/, "")}`);
          else if (all || res.fixed.length === 0) live.current.toast("success", `Слайд ${slide} исправлен${score}`);
          else live.current.toast("success", `Слайд ${slide}: исправлено ${res.fixed.length} из ${res.requested.length}`);
        }
      },
      onFailed: (job) => {
        const reason = reasonOf(job);
        patch(jobId, { phase: "failed", error: reason, revealed: true });
        const r = live.current.run;
        if (!shown(r)) live.current.toast("error", `Не получилось исправить слайд ${slide}: ${reason}`);
      },
    });
    return true;
  }, [gid, patch]);

  const undo = useCallback(async () => {
    const cur = live.current.run;
    if (!cur || cur.phase !== "done" || !cur.result?.applied) return;
    const { strategy, slide } = cur;
    patch(null, { phase: "undoing", revealed: false, synced: false });
    let jobId: string;
    try {
      jobId = (await api.editVariant(gid, strategy, { message: "верни как было", slide })).job_id;
    } catch (e) {
      patch(null, { phase: "done", revealed: true, synced: true });
      const busy = e instanceof ApiError && e.status === 409;
      live.current.toast("error", busy ? "Этот вариант уже меняется — дождитесь конца" : `Не получилось вернуть: ${errText(e)}`);
      return;
    }
    const fixJob = cur.jobId;
    setRun((r) => (r && r.jobId === fixJob ? { ...r, jobId } : r));
    live.current.runJob(jobId, "Возвращаю как было", {
      kind: "edit",
      target: { generation: gid, strategy, slide },
      quiet: true,
      onDone: async () => {
        await reload();
        patch(jobId, { phase: "undone", revealed: false, synced: true });
        window.setTimeout(() => setRun((r) => (r && r.jobId === jobId && r.phase === "undone" ? null : r)), 4000);
      },
      onFailed: (job) => {
        patch(jobId, { phase: "done", revealed: true, synced: true });
        live.current.toast("error", `Не получилось вернуть: ${reasonOf(job)}`);
      },
    });
  }, [gid, patch]);

  const reveal = useCallback(() => setRun((r) => (r && !r.revealed && (r.phase === "done" || r.phase === "undone") ? { ...r, revealed: true } : r)), []);
  const seen = useCallback(() => setRun((r) => (r && !r.seen ? { ...r, seen: true } : r)), []);
  const celebrate = useCallback(() => setRun((r) => (r && !r.celebrated ? { ...r, celebrated: true } : r)), []);
  const dismiss = useCallback(() => setRun((r) => (r && (r.phase === "done" || r.phase === "failed" || r.phase === "undone") ? null : r)), []);

  const mine = !!run?.jobId && activeJob?.id === run.jobId && run.phase === "running";
  return {
    run,
    events: kept.current.events,
    progress: mine ? activeJob.progress : kept.current.progress,
    message: mine ? activeJob.message : kept.current.message,
    start,
    undo,
    reveal,
    seen,
    celebrate,
    dismiss,
  };
}
