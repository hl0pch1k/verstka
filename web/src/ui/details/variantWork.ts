// Работа над вариантом открытой презентации из листа «Подробнее» — без React: «Исправить отмеченные» / «Исправить всё
// автоматически» вкладки «Качество» (V2 `dlFix`) и «Вернуть как было» (V2 `dlq.undo`, «Ваши правки» вкладки «Агент»).
// Состояние живёт в хранилище по ключу «презентация|вариант» (`workKey`), а не во вкладке: закрыли лист во время
// исправления — задача идёт дальше, открыли снова — отмеченные приглушены, кнопки выключены, а потом «Исправлено N» и
// «Вернуть как было» держатся, пока вариант не изменится снова (ревизия `variantRev`). Сервер держит одну задачу на
// вариант (на вторую — 409): пока идёт исправление или возврат, новый запуск отклоняется (тот же объект состояния);
// чужую задачу над вариантом (исправление слайда, изображение) видно по `busyKeys` идущих задач хранилища. Номер запуска
// (`seq`) отсекает опоздавшие ответы прежней работы. Сеть, задачи и перечитывание — useVariantWork.
import { humanError } from "../../lib/errors";
import type { ActiveJob } from "../../lib/jobState";
import { fixedText } from "./quality";

export const workKey = (gid: string, strategy: string) => `${gid}|${strategy}`;

/** Варианты, над которыми идёт задача (ключи `workKey` по `target` задач), без повторов. */
export function busyKeys(jobs: Iterable<ActiveJob>): string[] {
  const out: string[] = [];
  for (const j of jobs) {
    if (!j.target) continue;
    const k = workKey(j.target.generation, j.target.strategy);
    if (!out.includes(k)) out.push(k);
  }
  return out;
}

/** Отказ без запроса: над вариантом уже идёт работа (те же слова, что у сервера на 409). */
export const VARIANT_BUSY = "Этот вариант уже меняется — дождитесь, пока агент закончит";

/** Итог задачи «верни как было»: null — вернулось; сервер ответил, что не вышло, — почему, его словами. */
export function undoRefusal(result: unknown): string | null {
  const r = result as { changed?: boolean; reply?: string } | null;
  return r && r.changed === false ? humanError(r.reply, "Вернуть не получилось. Попробуйте ещё раз.") : null;
}

/** Сколько запрошенных замечаний исправлено — по итогу задачи `fix` (`applied[].issue_id`; отменённые проверкой не
 *  считаются, повтор — один раз). Итог об этом не говорит (нет ни одного `issue_id`) — null: считают по новому отчёту. */
export function fixedFromJob(result: unknown, requested: string[]): number | null {
  const applied = (result as { applied?: unknown } | null)?.applied;
  if (!Array.isArray(applied)) return null;
  const rec = applied.filter((f): f is Record<string, unknown> => !!f && typeof f === "object" && typeof (f as { issue_id?: unknown }).issue_id === "string");
  if (!rec.length) return null;
  const done = new Set(rec.filter((f) => f.rolled_back !== true).map((f) => f.issue_id as string));
  return requested.filter((id) => done.has(id)).length;
}

// ---- состояние -------------------------------------------------------------------------------------------------------

export interface FixRun {
  seq: number;
  phase: "fix" | "done" | "idle";
  /** Что исправляется: отмеченные замечания или всё («all»). */
  ids: string[] | "all";
  /** Сколько исправлено (после итога). */
  fixed: number;
  /** Ревизия варианта, к которой относится итог или неудача; null — неизвестна (презентацию не перечитали). */
  rev: string | null;
  error: string | null;
}
/** Чья кнопка «Вернуть как было» запустила возврат: ход (дуга) и неудача показываются у неё. */
export type UndoBy = "quality" | "agent";
export interface UndoRun { seq: number; by: UndoBy; busy: boolean; error: string | null }
export interface VariantWork { fix?: FixRun; undo?: UndoRun }
export type WorkState = Record<string, VariantWork | undefined>;
export const WORK0: WorkState = {};

export type WorkAction =
  | { type: "fix"; key: string; ids: string[] | "all" }
  | { type: "fixed"; key: string; seq: number; fixed: number; rev: string | null }
  | { type: "fixFailed"; key: string; seq: number; error: string; rev: string | null }
  | { type: "undo"; key: string; by: UndoBy }
  /** «Верни как было» варианта удалось — своё (`seq` возврата) или с экрана результата (null): итога исправления нет. */
  | { type: "undone"; key: string; seq: number | null }
  | { type: "undoFailed"; key: string; seq: number; error: string };

let counter = 0;

/** Идёт исправление или возврат этого места: новый запуск не начинается. */
const working = (w: VariantWork | undefined) => w?.fix?.phase === "fix" || !!w?.undo?.busy;

export function workNext(s: WorkState, a: WorkAction): WorkState {
  const w = s[a.key] ?? {};
  const put = (next: VariantWork) => ({ ...s, [a.key]: next });
  const { fix, undo } = w;
  switch (a.type) {
    case "fix":
      if (working(w)) return s;
      // новое действие — прежние строки неудачи уходят
      return put({ fix: { seq: ++counter, phase: "fix", ids: a.ids, fixed: 0, rev: null, error: null }, undo: undo && { ...undo, error: null } });
    case "fixed":
      if (!fix || fix.seq !== a.seq || fix.phase !== "fix") return s;
      return put({
        ...w,
        fix: a.fixed > 0 ? { ...fix, phase: "done", fixed: a.fixed, rev: a.rev, error: null }
          : { ...fix, phase: "idle", fixed: 0, rev: a.rev, error: "Исправить не получилось — замечания остались." },
      });
    case "fixFailed":
      if (!fix || fix.seq !== a.seq || fix.phase !== "fix") return s;
      return put({ ...w, fix: { ...fix, phase: "idle", rev: a.rev, error: a.error } });
    case "undo":
      if (working(w)) return s;
      return put({ fix: fix && { ...fix, error: null }, undo: { seq: ++counter, by: a.by, busy: true, error: null } });
    case "undone": {
      const mine = !!undo && a.seq !== null && undo.seq === a.seq && undo.busy;
      const gone = fix?.phase === "done";
      if (!mine && !gone) return s;
      return put({
        fix: gone ? { ...fix!, phase: "idle", fixed: 0, error: null } : fix,
        undo: mine ? { ...undo!, busy: false, error: null } : undo,
      });
    }
    case "undoFailed":
      if (!undo || undo.seq !== a.seq || !undo.busy) return s;
      return put({ ...w, undo: { ...undo, busy: false, error: a.error } });
  }
}

// ---- что видно -------------------------------------------------------------------------------------------------------

export interface FixView {
  /** Замечания, над которыми идёт работа (приглушены), null — работы нет. */
  busy: string[] | "all" | null;
  /** Что идёт у «Качества»: исправление или его «Вернуть как было». */
  working: "fix" | "undo" | null;
  /** «Исправлено N замечаний» (строка итога), null — итога нет. */
  status: string | null;
  /** «Вернуть как было» на месте «Исправить всё автоматически». */
  undo: boolean;
  error: string | null;
  /** Над вариантом идёт работа (своя или чужая задача): кнопки и флажки выключены. */
  locked: boolean;
}

/** Вкладка «Качество»: `rev` — ревизия варианта на экране, `live` — над вариантом идёт задача хранилища. */
export function fixView(s: WorkState, key: string, rev: string, live: boolean): FixView {
  const w = s[key];
  const fix = w?.fix;
  const undo = w?.undo;
  const fresh = !!fix && (fix.rev === null || fix.rev === rev);
  const shown = !!fix && fix.phase === "done" && fresh;
  return {
    busy: fix?.phase === "fix" ? fix.ids : null,
    working: fix?.phase === "fix" ? "fix" : undo?.busy && undo.by === "quality" ? "undo" : null,
    status: shown ? fixedText(fix.fixed) : null,
    undo: shown,
    error: (fresh ? fix.error : null) ?? (undo?.by === "quality" ? undo.error : null),
    locked: live || working(w),
  };
}

export interface UndoView {
  /** Кнопка выключена: над вариантом идёт работа. */
  busy: boolean;
  /** Дуга в кнопке: возврат запустила она. */
  arc: boolean;
  error: string | null;
}

/** «Ваши правки» вкладки «Агент». */
export function undoView(s: WorkState, key: string, live: boolean): UndoView {
  const w = s[key];
  const undo = w?.undo;
  return { busy: live || working(w), arc: !!undo?.busy && undo.by === "agent", error: undo?.by === "agent" ? undo.error : null };
}
