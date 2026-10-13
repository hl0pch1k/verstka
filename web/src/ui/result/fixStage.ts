// Фазы эскиза исправления на сцене без React (R-fixing, V2 `rm-fx`) — чистый редьюсер, как presenceNext:
//   pre  — запуск виден, сцена ещё развёрнута (со следующего кадра — mini, чтобы переход стартовал из развёрнутого);
//   mini — сцена сжата до scale(.5) в эскиз, пока агент работает;
//   post — новое превью декодировано, эскиз разворачивается (520 мс) — потом снимается, и панель показывает итог.
// Исправление, которое кончилось там, где его не видели (другой слайд, режим выключен) или до первого кадра, не
// играется; сыгранное не играется снова. Таймеры и кадры — useFixStage (FixSketch.tsx).

export type FxPhase = "pre" | "mini" | "post";

export interface FxState {
  /** Запуск, который играет эскиз; `at` — когда сцена начала сжиматься (мс). */
  cur: { seq: number; phase: FxPhase; at: number } | null;
  /** Сыгранные (или кончившиеся без показа) запуски. */
  played: readonly number[];
}
export const FX0: FxState = { cur: null, played: [] };

export type FxAction =
  /** Что видно на сцене сейчас: `seq` — запуск исправления на этом слайде (null — его здесь нет), `done` — его
   *  задача кончилась и презентация перечитана. */
  | { type: "sync"; seq: number | null; done: boolean }
  | { type: "mini"; seq: number; at: number }
  | { type: "post"; seq: number }
  | { type: "end"; seq: number };

/** Эскиз держится хотя бы столько, сколько сцена сжимается, и ещё немного — короткая задача не дёргает сцену. */
export const MIN_MINI = 900;

const played = (s: FxState, seq: number) => (s.played.includes(seq) ? s.played : [...s.played, seq]);

export function fixStageNext(s: FxState, a: FxAction): FxState {
  switch (a.type) {
    case "sync": {
      if (a.seq === null || s.played.includes(a.seq)) return s.cur ? { ...s, cur: null } : s;
      if (s.cur?.seq === a.seq) return s;
      if (a.done) return { cur: null, played: played(s, a.seq) };
      return { ...s, cur: { seq: a.seq, phase: "pre", at: 0 } };
    }
    case "mini":
      return s.cur?.seq === a.seq && s.cur.phase === "pre" ? { ...s, cur: { seq: a.seq, phase: "mini", at: a.at } } : s;
    case "post":
      return s.cur?.seq === a.seq && s.cur.phase !== "post" ? { ...s, cur: { ...s.cur, phase: "post" } } : s;
    case "end":
      return { cur: s.cur?.seq === a.seq ? null : s.cur, played: played(s, a.seq) };
  }
}

/** Фаза эскиза запуска `seq` на этой сцене; null — эскиза нет. */
export const fxPhase = (s: FxState, seq: number | null): FxPhase | null => (seq !== null && s.cur?.seq === seq ? s.cur.phase : null);

/** Сколько эскиз ещё держится, прежде чем развернуться (мс): ещё не сжат — весь минимум, сжат — остаток от `at`. */
export const holdLeft = (phase: FxPhase, at: number, now: number): number => (phase === "pre" ? MIN_MINI : Math.max(0, at + MIN_MINI - now));
