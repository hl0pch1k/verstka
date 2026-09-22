// Job tracking: Server-Sent Events from /api/jobs/{id}/events with a 2 s polling fallback on /api/jobs/{id}.
// Every `data:` line is a JSON JobEvent; the stream ends after status done/failed.
import { api } from "../api";
import type { Job, JobEvent, JobStatus } from "../types";

export interface JobHandlers {
  onEvent?: (ev: JobEvent) => void;
  onDone?: (job: Job) => void;
  onFailed?: (job: Job) => void;
}

const TERMINAL: JobStatus[] = ["done", "failed"];

/** Subscribe to a job. Returns an unsubscribe function. */
export function trackJob(jobId: string, handlers: JobHandlers, pollMs = 2000): () => void {
  let finished = false;
  let es: EventSource | null = null;
  let timer: number | null = null;
  let last: JobEvent | null = null;

  const cleanup = () => {
    if (es) {
      es.close();
      es = null;
    }
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  };

  const finish = async (status: JobStatus) => {
    if (finished) return;
    finished = true;
    cleanup();
    let job: Job | null = null;
    try {
      job = await api.job(jobId);
    } catch {
      job = null;
    }
    const fallback: Job = {
      id: jobId,
      kind: "",
      status,
      progress: last?.progress ?? (status === "done" ? 1 : 0),
      message: last?.message ?? "",
      error: status === "failed" ? last?.message ?? "failed" : null,
      created_at: 0,
      finished_at: null,
      result: null,
    };
    const final = job ?? fallback;
    if (final.status === "done") handlers.onDone?.(final);
    else handlers.onFailed?.(final);
  };

  const handle = (ev: JobEvent) => {
    if (finished) return;
    last = ev;
    handlers.onEvent?.(ev);
    if (TERMINAL.includes(ev.status)) void finish(ev.status);
  };

  try {
    es = new EventSource(api.jobEventsUrl(jobId));
    es.onmessage = (e) => {
      try {
        handle(JSON.parse(e.data) as JobEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
    es.onerror = () => {
      // Server closed the stream (or proxy hiccup): drop SSE, polling continues.
      if (es) {
        es.close();
        es = null;
      }
    };
  } catch {
    es = null;
  }

  timer = window.setInterval(async () => {
    if (finished) return;
    try {
      const job = await api.job(jobId);
      handle({ job_id: job.id, status: job.status, progress: job.progress, message: job.message, t: 0 });
    } catch {
      /* transient; keep polling */
    }
  }, pollMs);

  return cleanup;
}
