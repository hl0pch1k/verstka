// «Заменить изображение»: the one picture run of a Deck. It starts the job (POST …/slides/{n}/image — a new picture on
// the person's wish, or the free place back), follows it through the store's runJob quietly (the card tells the
// story), reloads the deck when the slide changed and offers the exact undo («верни как было», like a slide fix). The
// Deck is keyed by generation, so the run survives slide and variant switches.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { errText, firstLine } from "../../lib/narrate";
import { useApp } from "../../store";
import { asPictureResult } from "../../lib/pictures";
import type { Job, PictureChangeResult } from "../../types";

export type PicturePhase = "submitting" | "running" | "done" | "failed" | "undoing" | "undone";
export type PictureAction = "generate" | "remove";
export interface PictureRun {
  strategy: string;
  slide: number;
  action: PictureAction;
  wish: string;
  jobId: string | null;
  phase: PicturePhase;
  result: PictureChangeResult | null;
  error: string | null;
  /** The deck on screen shows the run's outcome (the reload after an applied change or an undo is in). */
  synced: boolean;
  at: number;
}

export interface PictureChange {
  run: PictureRun | null;
  progress: number;
  message: string;
  /** Starts a change; resolves true when the job has started. */
  start(strategy: string, slide: number, action: PictureAction, wish: string): Promise<boolean>;
  undo(): Promise<void>;
  dismiss(): void;
}

const hasCyrillic = (s: string) => /[а-яё]/i.test(s);
function reasonOf(job: Job): string {
  const line = firstLine(job.error ?? job.message, "");
  return line && hasCyrillic(line) ? line.replace(/\.\s*$/, "") : "Сервер не смог поменять изображение";
}

export function usePictureChange(gid: string): PictureChange {
  const { runJob, loadGeneration, activeJob, toast, generationId } = useApp();
  const [run, setRun] = useState<PictureRun | null>(null);
  const live = useRef({ run, runJob, loadGeneration, toast, generationId });
  live.current = { run, runJob, loadGeneration, toast, generationId };
  /** Reloads the deck, unless the person has opened another one meanwhile (never yank them back). */
  const reload = async () => {
    if (live.current.generationId === gid) await live.current.loadGeneration(gid);
  };
  const patch = useCallback((jobOrNull: string | null, p: Partial<PictureRun>) => {
    setRun((cur) => (cur && (jobOrNull === null || cur.jobId === jobOrNull) ? { ...cur, ...p, at: p.phase && p.phase !== cur.phase ? Date.now() : cur.at } : cur));
  }, []);
  // the last progress of the running job, kept for the moment the store lets it go
  const kept = useRef({ job: null as string | null, progress: 0, message: "" });
  if (run?.jobId && activeJob?.id === run.jobId && run.phase === "running") kept.current = { job: run.jobId, progress: activeJob.progress, message: activeJob.message };

  const start = useCallback(async (strategy: string, slide: number, action: PictureAction, wish: string): Promise<boolean> => {
    const cur = live.current.run;
    if (cur && (cur.phase === "submitting" || cur.phase === "running" || cur.phase === "undoing")) return false;
    const now = Date.now();
    kept.current = { job: null, progress: 0, message: "" };
    setRun({ strategy, slide, action, wish: wish.trim(), jobId: null, phase: "submitting", result: null, error: null, synced: true, at: now });
    let jobId: string;
    try {
      jobId = (await api.changePicture(gid, strategy, slide, { wish: wish.trim() || null, action })).job_id;
    } catch (e) {
      setRun(null);
      const busy = e instanceof ApiError && e.status === 409;
      live.current.toast("error", busy ? "Этот вариант уже меняется — дождитесь конца" : `Не получилось: ${errText(e)}`);
      return false;
    }
    setRun((r) => (r && r.at === now ? { ...r, jobId, phase: "running", at: Date.now() } : r));
    live.current.runJob(jobId, action === "remove" ? `Убираю изображение со слайда ${slide}` : `Рисую изображение для слайда ${slide}`, {
      kind: "picture",
      target: { generation: gid, strategy, slide },
      quiet: true,
      onDone: async (job) => {
        const res = asPictureResult(job.result);
        if (!res) {
          patch(jobId, { phase: "failed", error: "Сервер не смог поменять изображение" });
          return;
        }
        if (!res.applied) {
          patch(jobId, { phase: "failed", result: res, error: res.reply.replace(/^Не получилось:\s*/, "").replace(/\.\s*$/, "") });
          return;
        }
        patch(jobId, { phase: "done", result: res, synced: false });
        await reload();
        patch(jobId, { synced: true });
      },
      onFailed: (job) => patch(jobId, { phase: "failed", error: reasonOf(job) }),
    });
    return true;
  }, [gid, patch]);

  const undo = useCallback(async () => {
    const cur = live.current.run;
    if (!cur || cur.phase !== "done" || !cur.result?.applied) return;
    const { strategy, slide } = cur;
    patch(null, { phase: "undoing", synced: false });
    let jobId: string;
    try {
      jobId = (await api.editVariant(gid, strategy, { message: "верни как было", slide })).job_id;
    } catch (e) {
      patch(null, { phase: "done", synced: true });
      const busy = e instanceof ApiError && e.status === 409;
      live.current.toast("error", busy ? "Этот вариант уже меняется — дождитесь конца" : `Не получилось вернуть: ${errText(e)}`);
      return;
    }
    const was = cur.jobId;
    setRun((r) => (r && r.jobId === was ? { ...r, jobId } : r));
    live.current.runJob(jobId, "Возвращаю как было", {
      kind: "edit",
      target: { generation: gid, strategy, slide },
      quiet: true,
      onDone: async () => {
        await reload();
        patch(jobId, { phase: "undone", synced: true });
        window.setTimeout(() => setRun((r) => (r && r.jobId === jobId && r.phase === "undone" ? null : r)), 4000);
      },
      onFailed: (job) => {
        patch(jobId, { phase: "done", synced: true });
        live.current.toast("error", `Не получилось вернуть: ${reasonOf(job)}`);
      },
    });
  }, [gid, patch]);

  const dismiss = useCallback(() => setRun((r) => (r && (r.phase === "done" || r.phase === "failed" || r.phase === "undone") ? null : r)), []);
  // a finished run is forgotten when the person opens another deck (the Deck is keyed by generation anyway)
  useEffect(() => () => void (kept.current = { job: null, progress: 0, message: "" }), []);

  const mine = !!run?.jobId && activeJob?.id === run.jobId && run.phase === "running";
  return { run, progress: mine ? activeJob.progress : kept.current.progress, message: mine ? activeJob.message : kept.current.message, start, undo, dismiss };
}
