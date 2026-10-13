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
  /** `stale` — исправления применены, а презентация на экране не перечиталась: итог ждёт её перечитывания (`fresh`). */
  phase: "fix" | "done" | "idle" | "stale";
  /** Что исправляется: отмеченные замечания или всё («all»). */
  ids: string[] | "all";
  /** Сколько исправлено (после итога). */
  fixed: number;
  /** Ревизия варианта, к которой относится итог или неудача; null — неизвестна (презентацию не перечитали). */
  rev: string | null;
  error: string | null;
  /** Несвежий итог (`stale`): сколько исправлено по итогу задачи (null — не сказано, считают по новому отчёту) и какие
   *  замечания просили. */
  wait?: { fixed: number | null; count: string[] };
}
/** Чья кнопка «Вернуть как было» запустила возврат: ход (дуга) и неудача показываются у неё. */
export type UndoBy = "quality" | "agent";
/** `stale` — вернулось, а презентация на экране не перечиталась (строка с «Обновить» у той же кнопки). */
export interface UndoRun { seq: number; by: UndoBy; busy: boolean; error: string | null; stale?: boolean }
export interface VariantWork { fix?: FixRun; undo?: UndoRun }
export type WorkState = Record<string, VariantWork | undefined>;
export const WORK0: WorkState = {};

export type WorkAction =
  | { type: "fix"; key: string; ids: string[] | "all" }
  | { type: "fixed"; key: string; seq: number; fixed: number; rev: string | null }
  | { type: "fixFailed"; key: string; seq: number; error: string; rev: string | null }
  /** Исправление кончилось, но вариант не прочитался ни открытым, ни тихо: сколько исправлено и к какой ревизии это
   *  относится, неизвестно — итога «Исправлено N» нет (он был бы «свежим» навсегда). */
  | { type: "fixLost"; key: string; seq: number }
  | { type: "undo"; key: string; by: UndoBy }
  /** «Верни как было» варианта удалось — своё (`seq` возврата) или с экрана результата (null): итога исправления нет. */
  | { type: "undone"; key: string; seq: number | null }
  | { type: "undoFailed"; key: string; seq: number; error: string }
  /** Исправления применены, а презентация не перечиталась: итог ждёт перечитывания. */
  | { type: "fixStale"; key: string; seq: number; fixed: number | null; count: string[] }
  /** Вернулось, а презентация не перечиталась (`seq` — возврат этого места; null — с экрана результата). */
  | { type: "undoStale"; key: string; seq: number | null }
  /** Презентация перечиталась: несвежий итог исправления становится итогом (`fixed` по новому отчёту, `rev` — ревизия
   *  перечитанного варианта), строка у «Вернуть как было» уходит. */
  | { type: "fresh"; key: string; fixed: number; rev: string };

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
      return put({ fix: { seq: ++counter, phase: "fix", ids: a.ids, fixed: 0, rev: null, error: null }, undo: undo && { ...undo, error: null, stale: false } });
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
    case "fixLost":
      if (!fix || fix.seq !== a.seq || fix.phase !== "fix") return s;
      return put({ ...w, fix: { ...fix, phase: "idle", fixed: 0, rev: null, error: null } });
    case "undo":
      if (working(w)) return s;
      return put({ fix: fix && { ...fix, error: null }, undo: { seq: ++counter, by: a.by, busy: true, error: null, stale: false } });
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
    case "fixStale":
      if (!fix || fix.seq !== a.seq || fix.phase !== "fix") return s;
      return put({ ...w, fix: { ...fix, phase: "stale", fixed: 0, rev: null, error: null, wait: { fixed: a.fixed, count: a.count } } });
    case "undoStale": {
      // как «undone» (итога исправления больше нет), но экран ещё прежний: строка с «Обновить» у кнопки этого места
      const mine = !!undo && a.seq !== null && undo.seq === a.seq && undo.busy;
      const gone = fix?.phase === "done";
      if (!mine && !gone) return s;
      return put({
        fix: gone ? { ...fix!, phase: "idle", fixed: 0, error: null } : fix,
        undo: mine ? { ...undo!, busy: false, error: null, stale: true } : undo,
      });
    }
    case "fresh": {
      const wasFix = fix?.phase === "stale";
      if (!wasFix && !undo?.stale) return s;
      return put({
        fix: wasFix ? (a.fixed > 0 ? { ...fix!, phase: "done", fixed: a.fixed, rev: a.rev, error: null, wait: undefined }
          : { ...fix!, phase: "idle", fixed: 0, rev: a.rev, error: "Исправить не получилось — замечания остались.", wait: undefined }) : fix,
        undo: undo?.stale ? { ...undo, stale: false } : undo,
      });
    }
  }
}

/** Места, которые ждут перечитывания презентации `gid` (несвежий итог исправления или возврата): ключи `workKey`. */
export function staleKeys(s: WorkState, gid: string): string[] {
  return Object.keys(s).filter((k) => k.startsWith(`${gid}|`) && (s[k]?.fix?.phase === "stale" || !!s[k]?.undo?.stale));
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
  /** Исправление или его возврат сохранены, а презентация на экране не перечиталась: строка с «Обновить» вместо `error`. */
  stale: boolean;
  /** Над вариантом идёт работа (своя или чужая задача): кнопки и флажки выключены. */
  locked: boolean;
}

/** Вкладка «Качество»: `rev` — ревизия варианта на экране, `live` — над вариантом идёт задача хранилища, `staleNow` —
 *  хранилище держит открытую презентацию несвежей. */
export function fixView(s: WorkState, key: string, rev: string, live: boolean, staleNow = false): FixView {
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
    stale: staleNow && (fix?.phase === "stale" || (undo?.by === "quality" && !!undo.stale)),
    locked: live || working(w),
  };
}

export interface UndoView {
  /** Кнопка выключена: над вариантом идёт работа. */
  busy: boolean;
  /** Дуга в кнопке: возврат запустила она. */
  arc: boolean;
  error: string | null;
  /** Вернулось, а презентация на экране не перечиталась: строка с «Обновить» вместо `error`. */
  stale: boolean;
}

/** «Ваши правки» вкладки «Агент». */
export function undoView(s: WorkState, key: string, live: boolean, staleNow = false): UndoView {
  const w = s[key];
  const undo = w?.undo;
  return {
    busy: live || working(w), arc: !!undo?.busy && undo.by === "agent", error: undo?.by === "agent" ? undo.error : null,
    stale: staleNow && undo?.by === "agent" && !!undo.stale,
  };
}
