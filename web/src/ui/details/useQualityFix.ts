// «Исправить отмеченные» / «Исправить всё автоматически» (`api.fixes` → задача `fix`) и «Вернуть как было»
// (`api.editVariant` «верни как было» → задача `edit`) на вкладке «Качество». Задачи идут через `runJob` хранилища
// тихо (ход и неудача — строкой в сводке, без уведомлений); по готовности презентация перечитывается (`reloadIfOpen`),
// итог «Исправлено N» считается по новому отчёту проверки. Шаги — чистый fixNext (qualityFix.ts).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { useApp } from "../../store";
import type { Job } from "../../types";
import { fixedCount } from "./quality";
import { FIX0, fixNext, fixView, type FixAction, type FixState, type FixView } from "./qualityFix";

const startError = (e: unknown, what: string) => humanError(e instanceof ApiError || e instanceof Error ? e.message : String(e), `Не получилось ${what}. Попробуйте ещё раз.`);
const jobError = (job: Job, what: string) => humanError(job.error ?? job.message, `Не получилось ${what}. Попробуйте ещё раз.`);

export interface QualityFix extends FixView {
  /** `ids` — что исправить («all» — всё автоматически), `count` — какие замечания считать исправленными. */
  start(ids: string[] | "all", count: string[]): void;
  /** «Вернуть как было» итога исправления. */
  revert(): void;
}

export function useQualityFix(gid: string, strategy: string): QualityFix {
  const { runJob, reloadIfOpen } = useApp();
  const box = useRef<FixState>(FIX0);
  const [state, setState] = useState<FixState>(FIX0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const send = useCallback((a: FixAction) => {
    const next = fixNext(box.current, a);
    if (next !== box.current) {
      box.current = next;
      if (alive.current) setState(next);
    }
    return next;
  }, []);

  const start = useCallback((ids: string[] | "all", count: string[]) => {
    const before = box.current;
    const now = send({ type: "start", strategy, ids });
    if (now === before) return;
    const seq = now[strategy]!.seq;
    void (async () => {
      let jobId: string;
      try {
        jobId = (await api.fixes(gid, strategy, ids === "all" ? { all_deterministic: true } : { issue_ids: ids })).job_id;
      } catch (e) {
        return void send({ type: "failed", strategy, seq, error: startError(e, "исправить замечания") });
      }
      runJob(jobId, "Исправляю замечания", {
        kind: "fix", area: "result", quiet: true,
        onDone: async () => {
          const g = await reloadIfOpen(gid);
          const after = g?.variants.find((v) => v.strategy === strategy)?.audit ?? null;
          send({ type: "done", strategy, seq, fixed: after ? fixedCount(count, after) : count.length });
        },
        onFailed: (job) => void send({ type: "failed", strategy, seq, error: jobError(job, "исправить замечания") }),
      });
    })();
  }, [gid, strategy, runJob, reloadIfOpen, send]);

  const revert = useCallback(() => {
    const before = box.current;
    const now = send({ type: "undo", strategy });
    if (now === before) return;
    const seq = now[strategy]!.seq;
    void (async () => {
      let jobId: string;
      try {
        jobId = (await api.editVariant(gid, strategy, { message: "верни как было" })).job_id;
      } catch (e) {
        return void send({ type: "failed", strategy, seq, error: startError(e, "вернуть как было") });
      }
      runJob(jobId, "Возвращаю как было", {
        kind: "edit", area: "result", quiet: true,
        onDone: async (job) => {
          const r = job.result as { changed?: boolean; reply?: string } | null;
          if (r && r.changed === false) return void send({ type: "failed", strategy, seq, error: humanError(r.reply, "Вернуть не получилось. Попробуйте ещё раз.") });
          await reloadIfOpen(gid);
          send({ type: "undone", strategy, seq });
        },
        onFailed: (job) => void send({ type: "failed", strategy, seq, error: jobError(job, "вернуть как было") }),
      });
    })();
  }, [gid, strategy, runJob, reloadIfOpen, send]);

  return { ...fixView(state, strategy), start, revert };
}
