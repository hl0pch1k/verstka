// «Исправить отмеченные» / «Исправить всё автоматически» и «Вернуть как было» на вкладке «Качество» (V2 `dlFix`,
// `dlq.undo`) — шаги без React. У каждого варианта своя работа (сервер держит одну задачу на вариант и отвечает 409 на
// вторую): старт → ход (отмеченные замечания приглушены) → итог «Исправлено N» и «Вернуть как было», или строка
// неудачи. Номер запуска (`seq`) отсекает опоздавшие ответы прежней работы.
import { fixedText } from "./quality";

export interface FixRun {
  seq: number;
  phase: "fix" | "done" | "undo" | "idle";
  /** Что исправляется: отмеченные замечания или всё («all»). */
  ids: string[] | "all";
  /** Сколько исправлено (после итога). */
  fixed: number;
  error: string | null;
}
export type FixState = Record<string, FixRun | undefined>;
export const FIX0: FixState = {};

export type FixAction =
  | { type: "start"; strategy: string; ids: string[] | "all" }
  | { type: "done"; strategy: string; seq: number; fixed: number }
  | { type: "failed"; strategy: string; seq: number; error: string }
  | { type: "undo"; strategy: string }
  | { type: "undone"; strategy: string; seq: number };

let counter = 0;

export function fixNext(s: FixState, a: FixAction): FixState {
  const cur = s[a.strategy];
  const put = (run: FixRun) => ({ ...s, [a.strategy]: run });
  switch (a.type) {
    case "start":
      if (cur && (cur.phase === "fix" || cur.phase === "undo")) return s;
      return put({ seq: ++counter, phase: "fix", ids: a.ids, fixed: 0, error: null });
    case "done":
      if (!cur || cur.seq !== a.seq || cur.phase !== "fix") return s;
      return put(a.fixed > 0 ? { ...cur, phase: "done", fixed: a.fixed, error: null } : { ...cur, phase: "idle", fixed: 0, error: "Исправить не получилось — замечания остались." });
    case "failed":
      if (!cur || cur.seq !== a.seq) return s;
      // «Вернуть как было» не вышло — итог остаётся (его можно вернуть снова), рядом — почему
      if (cur.phase === "undo") return put({ ...cur, phase: "done", error: a.error });
      if (cur.phase !== "fix") return s;
      return put({ ...cur, phase: "idle", error: a.error });
    case "undo":
      if (!cur || cur.phase !== "done") return s;
      return put({ ...cur, phase: "undo", error: null });
    case "undone":
      if (!cur || cur.seq !== a.seq || cur.phase !== "undo") return s;
      return put({ ...cur, phase: "idle", fixed: 0, error: null });
  }
}

export interface FixView {
  /** Замечания, над которыми идёт работа (приглушены), null — работы нет. */
  busy: string[] | "all" | null;
  /** Что идёт: исправление или «Вернуть как было». */
  working: "fix" | "undo" | null;
  /** «Исправлено N замечаний» (строка итога), null — итога нет. */
  status: string | null;
  /** «Вернуть как было» на месте «Исправить всё автоматически». */
  undo: boolean;
  error: string | null;
}

export function fixView(s: FixState, strategy: string): FixView {
  const r = s[strategy];
  if (!r) return { busy: null, working: null, status: null, undo: false, error: null };
  const shown = r.phase === "done" || r.phase === "undo";
  return {
    busy: r.phase === "fix" ? r.ids : null,
    working: r.phase === "fix" ? "fix" : r.phase === "undo" ? "undo" : null,
    status: shown ? fixedText(r.fixed) : null,
    undo: shown,
    error: r.error,
  };
}
