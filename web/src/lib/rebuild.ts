// «Пересобрать слайд так» (вторая ступень; V2 v105 `dwRebuild`) без React: слайд с данными собирается заново другим
// вариантом визуализации — настоящая задача сервера (POST …/slides/{n}/rebuild), её ход — строкой у самого варианта
// («Пересобираю слайд 4…»), отказ — его причиной там же (422 — вариант не подходит к данным, 409 — файла с данными нет
// или вариант уже меняется), итог — новый слайд и «Выбран» у этого варианта, а у него «Вернуть как было» («верни как
// было» — как у других правок слайда, store `revertVariant`). Работа — одна на вариант презентации (сервер держит одну
// задачу на вариант), живёт вне вкладки (`rebuildStore`): лист закрыли посреди пересборки — она идёт, открыли снова —
// строка хода на месте. Шаги — чистый rebuildNext; сеть и задачи — useRebuild.
import { humanError } from "./errors";
import type { Job, RebuildResult } from "../types";

export interface RebuildRun {
  /** Номер запуска: шаги прежнего (поздний ответ, конец его задачи) новый не трогают. */
  seq: number;
  slide: number;
  /** Вариант, которым пересобирают (номер в `data.options`, с 0). */
  option: number;
  /** work — запрос ушёл или задача идёт (и презентация перечитывается после неё); done — пересобрано; failed — нет. */
  phase: "work" | "done" | "failed";
  jobId: string | null;
  /** Почему не пересобралось — словами сервера (по-русски), у этого варианта. */
  error: string | null;
  /** Пересобрано, а презентация на экране не перечиталась: у варианта строка с «Обновить». */
  stale: boolean;
  /** «Вернуть как было»: идёт или не вышло (`undoError`). */
  undo: "work" | "failed" | null;
  undoError: string | null;
}
/** Работа каждого варианта презентации (ключ — `workKey(gid, strategy)`). */
export type RebuildState = Record<string, RebuildRun | undefined>;
export const REBUILD0: RebuildState = {};

export type RebuildAction =
  | { type: "start"; key: string; slide: number; option: number }
  | { type: "accepted"; key: string; seq: number; jobId: string }
  | { type: "done"; key: string; seq: number; stale: boolean }
  | { type: "failed"; key: string; seq: number; error: string }
  /** «Вернуть как было» пересборки слайда `slide` (и тогда, когда её запуска на странице нет: перезагрузка). */
  | { type: "undo"; key: string; slide: number }
  /** Вернулось; `stale` — а презентация на экране не перечиталась (на экране ещё пересобранный слайд). */
  | { type: "undone"; key: string; seq: number; stale: boolean }
  | { type: "undoFailed"; key: string; seq: number; error: string };

/** Идёт пересборка или её возврат: новая не начинается. */
export const rebuildBusy = (r: RebuildRun | null | undefined): boolean => !!r && (r.phase === "work" || r.undo === "work");

let counter = 0;

export function rebuildNext(s: RebuildState, a: RebuildAction): RebuildState {
  const r = s[a.key];
  const put = (run: RebuildRun | null): RebuildState => {
    const next = { ...s };
    if (run) next[a.key] = run;
    else delete next[a.key];
    return next;
  };
  const mine = (seq: number) => !!r && r.seq === seq;
  switch (a.type) {
    case "start":
      if (rebuildBusy(r)) return s;
      return put({ seq: ++counter, slide: a.slide, option: a.option, phase: "work", jobId: null, error: null, stale: false, undo: null, undoError: null });
    case "accepted":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, jobId: a.jobId }) : s;
    case "done":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, phase: "done", stale: a.stale }) : s;
    case "failed":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, phase: "failed", error: a.error }) : s;
    case "undo":
      if (rebuildBusy(r)) return s;
      if (r && r.slide === a.slide && r.phase === "done") return put({ ...r, undo: "work", undoError: null, stale: false });
      return put({ seq: ++counter, slide: a.slide, option: -1, phase: "done", jobId: null, error: null, stale: false, undo: "work", undoError: null });
    case "undone":
      // вернулось — работы больше нет: вид снова по презентации; экран не перечитался — строка с «Обновить» у выбранного
      // (второе «Вернуть как было» по несвежему экрану вернуло бы уже сам возврат)
      if (!mine(a.seq) || r!.undo !== "work") return s;
      return put(a.stale ? { ...r!, phase: "done", option: -1, undo: null, undoError: null, stale: true } : null);
    case "undoFailed":
      return mine(a.seq) && r!.undo === "work" ? put({ ...r!, undo: "failed", undoError: a.error }) : s;
  }
}

/** Что стоит в месте действия варианта (под его доводом, 44 px — кнопка, ход, причина отказа, итог с «Вернуть как
 *  было» сменяют друг друга в одном месте, ничего ниже не сдвигается):
 *  - `button` — «Пересобрать слайд так» (`off` — выключена, `why` — почему);
 *  - `busy` — «Пересобираю слайд N…»;
 *  - `error` — почему не пересобралось (`text`);
 *  - `stale` — пересобрано, а экран не обновился (строка с «Обновить»);
 *  - `done` — выбранный пересборкой: «Пересобран» и «Вернуть как было» (`undoing` — идёт, `text` — не вышло);
 *  - `none` — ничего (выбранный анализом). */
export type RowAct =
  | { mode: "button"; off: boolean; why: string | null }
  | { mode: "busy" }
  | { mode: "error"; text: string }
  | { mode: "stale" }
  | { mode: "done"; undoing: boolean; text: string | null; off: boolean; why: string | null }
  | { mode: "none" };

/** Место действия варианта `k` слайда `slide`: `chosen` — выбранный вариант на экране, `undoable` — последнее изменение
 *  варианта — пересборка этого слайда (rebuiltLast), `lock` — над вариантом идёт чужая задача или шаблона нет. */
export function rowAct(run: RebuildRun | null | undefined, slide: number, k: number, chosen: number, undoable: boolean, lock: { off: boolean; why: string | null }): RowAct {
  const here = !!run && run.slide === slide;
  const busy = rebuildBusy(run);
  const why = lock.why ?? (busy && run ? (run.undo === "work" ? UNDO_BUSY : `Пересобираю слайд ${run.slide} — дождитесь конца`) : null);
  if (k === chosen) {
    if (!undoable) return { mode: "none" };
    if (here && run!.stale && run!.option === -1) return { mode: "stale" };
    const undoing = here && run!.undo === "work";
    return { mode: "done", undoing, text: here && run!.undo === "failed" ? run!.undoError : null, off: !undoing && (lock.off || busy), why: undoing ? null : why };
  }
  if (here && run!.option === k) {
    if (run!.phase === "work") return { mode: "busy" };
    if (run!.phase === "failed" && run!.error) return { mode: "error", text: run!.error };
    if (run!.phase === "done" && run!.stale) return { mode: "stale" };
  }
  return { mode: "button", off: lock.off || busy, why };
}

const UNDO_BUSY = "Возвращаю как было — дождитесь конца";
/** Строка хода у варианта. */
export const busyText = (slide: number) => `Пересобираю слайд ${slide}…`;
export const UNDO_TEXT = "Возвращаю как было…";
export const DONE_TEXT = "Пересобран";
export const STALE_TEXT = "Слайд пересобран, а экран не обновился";

/** Итог задачи пересборки (null — не он). */
export function asRebuildResult(x: unknown): RebuildResult | null {
  const r = x as Partial<RebuildResult> | null;
  return r && typeof r === "object" && r.kind === "rebuild" && typeof r.changed === "boolean" ? (r as RebuildResult) : null;
}

/** Отказ сервера при запуске (422 — вариант не подходит, слайд не из файла, уже показан так; 409 — файла нет, вариант
 *  уже меняется; 404 — нет презентации или шаблона) — его словами, по-русски. */
export const refusalText = (message: string): string => humanError(message, "Не получилось пересобрать слайд. Попробуйте ещё раз.");

/** Задача кончилась неудачей или сервер ответил, что слайд не изменился. */
export function jobFailText(job: Pick<Job, "error" | "message">): string {
  return humanError(job.error ?? job.message, "Не получилось пересобрать слайд. Попробуйте ещё раз.");
}
export function notChangedText(r: RebuildResult): string {
  return humanError(r.reply, "Слайд остался прежним. Попробуйте другой вариант.");
}

// ── общее состояние: одно на страницу (вкладку листа монтируют и снимают, работа идёт дальше)
let state: RebuildState = REBUILD0;
const listeners = new Set<() => void>();
export const rebuildStore = {
  get: (): RebuildState => state,
  send(a: RebuildAction): RebuildState {
    const next = rebuildNext(state, a);
    if (next !== state) {
      state = next;
      listeners.forEach((f) => f());
    }
    return next;
  },
  subscribe(f: () => void): () => void {
    listeners.add(f);
    return () => void listeners.delete(f);
  },
};
