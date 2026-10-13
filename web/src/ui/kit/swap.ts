// Перекрёстное затухание без React (useSwap): что показано (`shown`) и фаза (`out` — гаснет 120 мс, `in` — проявляется
// 240 мс). Начатое затухание всегда доигрывает: содержимое не возвращается к непрозрачности скачком — ни когда оно
// посреди хода стало невидимым (`live` снялся: плита гаснет, слой закрылся), ни когда значение сменилось ещё раз.

export type SwapPhase = "out" | "in" | null;
export interface SwapState<T> { shown: T; phase: SwapPhase }

/** `set` — новое значение (`live`: содержимое на виду; `ready`: был первый кадр и движение не отключено); `swap` —
 *  затухание кончилось (`value` — значение на этот момент); `end` — проявление кончилось. */
export type SwapEvent<T> =
  | { type: "set"; value: T; live: boolean; ready: boolean }
  | { type: "swap"; value: T }
  | { type: "end" };

/** Один шаг. Без перемен — тот же объект (без лишней перерисовки).
 *  - Вернулось показанное, пока оно гасло, — проявляется обратно (и невидимым: прозрачность 0 → 1 ходом, не скачком).
 *  - Новое значение, пока идёт затухание или проявление, — гаснет (дальше или снова) и подменяется в конце, даже если
 *    стало невидимым: снять `fx-out` на полпути — значит вернуть непрозрачность скачком.
 *  - В покое: на виду — гаснет; невидимое (или до первого кадра, или без движения) — сразу.
 *  - Конец затухания — подмена при нулевой прозрачности и проявление; конец проявления — покой. */
export function swapNext<T>(s: SwapState<T>, e: SwapEvent<T>): SwapState<T> {
  if (e.type === "swap") return s.phase === "out" ? { shown: e.value, phase: "in" } : s;
  if (e.type === "end") return s.phase === "in" ? { shown: s.shown, phase: null } : s;
  if (e.value === s.shown) return s.phase === "out" ? { shown: s.shown, phase: "in" } : s;
  if (s.phase === "out") return s;
  if (s.phase === "in" || (e.live && e.ready)) return { shown: s.shown, phase: "out" };
  return { shown: e.value, phase: null };
}
