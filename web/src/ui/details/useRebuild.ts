// «Пересобрать слайд так» и его «Вернуть как было» для вкладки «Почему так»: ход с сервером — rebuild.ts (startRebuild,
// followRebuild, undoRebuild, resumeRebuild), здесь — настоящие зависимости. Задача сервера идёт через `runJob`
// хранилища тихо (ход и отказ показывает сам вариант визуализации, не строка уведомления) с целью `target` — пока она
// идёт, вариант презентации занят и для других мест действия (исправление слайда, «Качество», помощник); по готовности
// презентация перечитывается (`reloadIfOpen`) — и новый слайд, и «Выбран» у нового варианта встают по ней; слайдов
// стало больше или меньше — выбран первый новый. «Вернуть как было» — общее для всех правок (store `revertVariant`).
// Идущая задача записана в localStorage (`verstka.rebuild`): страница, открытая заново посреди пересборки, снова следит
// за ней (useRebuildResume — с экрана результата), кончившаяся — перечитывает презентацию.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { storage } from "../../lib/utils";
import { useApp } from "../../store";
import type { GenerationMeta } from "../../types";
import {
  LS_REBUILD, parsePending, rebuildStore, resumeRebuild, startRebuild, undoRebuild, withoutPending, withPending, type RebuildDeps, type RebuildRun,
} from "./rebuild";
import { workKey } from "./variantWork";

export interface Rebuild {
  run: RebuildRun | null;
  /** Над вариантом идёт чужая задача (исправление, изображение, правка помощника, «Качество»). */
  taken: boolean;
  start(slide: number, option: number): void;
  /** `first` — какой слайд выбрать, когда вернулось (первый слайд пересборки). */
  undo(slide: number, first: number): void;
}

type App = ReturnType<typeof useApp>;
/** Где человек сейчас: открытая презентация и вариант (выбор слайда — только если это они). */
type Where = { current: { gid: string | null; strategy: string | null } };

const remember = (gid: string, strategy: string) => (jobId: string, slide: number, option: number) =>
  storage.set(LS_REBUILD, JSON.stringify(withPending(parsePending(storage.get(LS_REBUILD)), { gid, strategy, slide, option, jobId, at: Date.now() })));
const forget = (jobId: string) => {
  const list = parsePending(storage.get(LS_REBUILD));
  const next = withoutPending(list, jobId);
  if (next.length !== list.length) storage.set(LS_REBUILD, next.length ? JSON.stringify(next) : null);
};

/** Настоящие зависимости хода пересборки варианта `strategy` презентации `gid`. */
function depsOf(app: Pick<App, "runJob" | "reloadIfOpen" | "revertVariant" | "setSelectedSlide">, where: Where, busy: () => boolean, gid: string, strategy: string): RebuildDeps {
  return {
    request: (slide, option) => api.rebuildSlide(gid, strategy, slide, option),
    watch: (jobId, slide, done, failed) => app.runJob(jobId, `Пересобираю слайд ${slide}`, {
      kind: "rebuild", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy, slide }, onDone: done, onFailed: failed,
    }),
    async reload() {
      let lost = false;
      await app.reloadIfOpen(gid, () => {
        lost = true;
      });
      return !lost;
    },
    select(n) {
      if (where.current.gid === gid && where.current.strategy === strategy) app.setSelectedSlide(n);
    },
    remember: remember(gid, strategy),
    forget,
    taken: busy,
    revert: (slide) => app.revertVariant(gid, strategy, { slide }),
  };
}

/** Работа варианта `key` из общего состояния. Подписка — обычным обновлением состояния, не синхронным
 *  (useSyncExternalStore): итог пересборки приходит сразу за перечитанной презентацией и должен встать с ней в одну
 *  отрисовку — иначе фокус («Вернуть как было», выбранный вариант) искал бы место по прежней презентации. */
function useRebuildRun(key: string): RebuildRun | null {
  const [run, setRun] = useState<RebuildRun | null>(() => rebuildStore.get()[key] ?? null);
  useEffect(() => {
    const sync = () => setRun(rebuildStore.get()[key] ?? null);
    sync();
    return rebuildStore.subscribe(sync);
  }, [key]);
  return run;
}

export function useRebuild(gid: string, strategy: string): Rebuild {
  const app = useApp();
  const { busyVariants, generationId, activeStrategy } = app;
  const key = workKey(gid, strategy);
  const run = useRebuildRun(key);
  const own = !!run?.jobId && run.phase === "work";
  // своя задача тоже в busyVariants — чужая занятость только тогда, когда своей нет
  const taken = busyVariants.includes(key) && !own && run?.undo !== "work";
  const where = useRef({ gid: generationId, strategy: activeStrategy });
  where.current = { gid: generationId, strategy: activeStrategy };
  const appRef = useRef(app);
  appRef.current = app;
  const busyRef = useRef(busyVariants);
  busyRef.current = busyVariants;

  const deps = useCallback(() => depsOf(appRef.current, where, () => busyRef.current.includes(key), gid, strategy), [gid, strategy, key]);
  const start = useCallback((slide: number, option: number) => void startRebuild(rebuildStore, key, slide, option, deps()), [key, deps]);
  const undo = useCallback((slide: number, first: number) => void undoRebuild(rebuildStore, key, slide, first, deps()), [key, deps]);
  return { run, taken, start, undo };
}

/** Задачи, уже подхваченные этой страницей (одна и та же — один раз). */
const resumed = new Set<string>();

/** Страница открыта заново посреди пересборки слайда презентации `g`: её задача (записанная) — снова своя работа. */
export function useRebuildResume(g: Pick<GenerationMeta, "id">): void {
  const app = useApp();
  const appRef = useRef(app);
  appRef.current = app;
  const where = useRef({ gid: app.generationId, strategy: app.activeStrategy });
  where.current = { gid: app.generationId, strategy: app.activeStrategy };
  useEffect(() => {
    for (const p of parsePending(storage.get(LS_REBUILD))) {
      if (p.gid !== g.id || resumed.has(p.jobId)) continue;
      resumed.add(p.jobId);
      const key = workKey(p.gid, p.strategy);
      const deps = depsOf(appRef.current, where, () => false, p.gid, p.strategy);
      // сервер не знает задачу (404) — её нет; не ответил — запись остаётся до следующего открытия
      const job = (id: string) => api.job(id).catch((e: unknown) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e)));
      void resumeRebuild(rebuildStore, key, p, job, deps).then((ok) => void (ok || resumed.delete(p.jobId)));
    }
  }, [g.id]);
}
