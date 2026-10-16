// «Пересобрать слайд так» и его «Вернуть как было» для вкладки «Почему так»: задача сервера идёт через `runJob`
// хранилища тихо (ход и отказ показывает сам вариант визуализации, не строка уведомления) с целью `target` — пока она
// идёт, вариант презентации занят и для других мест действия (исправление слайда, «Качество», помощник); по готовности
// презентация перечитывается (`reloadIfOpen`) — и новый слайд, и «Выбран» у нового варианта встают по ней. «Вернуть как
// было» — общее для всех правок (store `revertVariant`, «верни как было» сервера). Состояние — lib/rebuild.ts (`rebuildStore`,
// одно на страницу: лист закрыли — работа идёт дальше).
import { useCallback, useSyncExternalStore } from "react";
import { api, ApiError } from "../../api";
import { useApp } from "../../store";
import { asRebuildResult, jobFailText, notChangedText, rebuildStore, refusalText, type RebuildRun } from "../../lib/rebuild";
import { VARIANT_BUSY, workKey } from "./variantWork";

export interface Rebuild {
  run: RebuildRun | null;
  /** Над вариантом идёт чужая задача (исправление, изображение, правка помощника, «Качество»). */
  taken: boolean;
  start(slide: number, option: number): void;
  undo(slide: number): void;
}

export function useRebuild(gid: string, strategy: string): Rebuild {
  const { runJob, reloadIfOpen, revertVariant, busyVariants } = useApp();
  const key = workKey(gid, strategy);
  const all = useSyncExternalStore(rebuildStore.subscribe, rebuildStore.get, rebuildStore.get);
  const run = all[key] ?? null;
  const own = !!run?.jobId && (run.phase === "work");
  // своя задача тоже в busyVariants — чужая занятость только тогда, когда своей нет
  const taken = busyVariants.includes(key) && !own && run?.undo !== "work";

  const start = useCallback((slide: number, option: number) => {
    const before = rebuildStore.get();
    const now = rebuildStore.send({ type: "start", key, slide, option });
    if (now === before) return;
    const seq = now[key]!.seq;
    const fail = (error: string) => void rebuildStore.send({ type: "failed", key, seq, error });
    if (busyVariants.includes(key)) return fail(VARIANT_BUSY);
    void (async () => {
      let jobId: string;
      try {
        jobId = (await api.rebuildSlide(gid, strategy, slide, option)).job_id;
      } catch (e) {
        return fail(refusalText(e instanceof ApiError || e instanceof Error ? e.message : String(e)));
      }
      rebuildStore.send({ type: "accepted", key, seq, jobId });
      runJob(jobId, `Пересобираю слайд ${slide}`, {
        kind: "rebuild", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy, slide },
        onDone: async (job) => {
          const r = asRebuildResult(job.result);
          if (!r) return fail(jobFailText(job));
          if (!r.changed) return fail(notChangedText(r));
          // новый слайд — новая версия презентации: сперва она, потом итог (строка хода держится, пока она читается);
          // не перечиталась — у варианта строка с «Обновить»
          let lost = false;
          await reloadIfOpen(gid, () => {
            lost = true;
          });
          rebuildStore.send({ type: "done", key, seq, stale: lost });
        },
        onFailed: (job) => fail(jobFailText(job)),
      });
    })();
  }, [gid, strategy, key, busyVariants, runJob, reloadIfOpen]);

  const undo = useCallback((slide: number) => {
    const before = rebuildStore.get();
    const now = rebuildStore.send({ type: "undo", key, slide });
    if (now === before) return;
    const seq = now[key]!.seq;
    void revertVariant(gid, strategy, { slide }).then(({ why, stale }) => {
      rebuildStore.send(why === null ? { type: "undone", key, seq, stale } : { type: "undoFailed", key, seq, error: why });
    });
  }, [gid, strategy, key, revertVariant]);

  return { run, taken, start, undo };
}
