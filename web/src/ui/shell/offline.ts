// «Нет связи с сервером» — модуль offline из boards/V2.dc.html (`ofSync`/`ofLater`) как чистые шаги. Режим полосок
// логотипа: idle — на месте, run — бегут (анимация G-toasts), land — связь вернулась: бег на паузе в текущей позе,
// за 360 мс (of-home) полоски сходятся домой, через 440 мс анимации снимаются. Связь пропала во время возврата —
// сначала дом, потом кадр покоя (34 мс) и бег с начала цикла: иначе анимация продолжилась бы с паузы.
import { cls } from "../kit/cls";

export type OfMode = "idle" | "run" | "land";
/** `rest` — идёт кадр покоя после возврата (в V2 — ждущий таймер `ofT`): бег не начинается. */
export interface OfState { mode: OfMode; rest: boolean }

export const OF0: OfState = { mode: "idle", rest: false };
/** Возврат домой: of-home 360 мс + запас, как `ofLater(440, …)` в V2. */
export const OF_LAND_MS = 440;
/** Кадр покоя перед новым бегом, как `ofLater(34, …)` в V2. */
export const OF_REST_MS = 34;

/** Шаг к состоянию связи `off` (V2 `ofSync`); в цели — тот же объект. */
export function ofStep(s: OfState, off: boolean): OfState {
  if (off && s.mode === "idle" && !s.rest) return { mode: "run", rest: false };
  if (!off && s.mode === "run") return { mode: "land", rest: s.rest };
  return s;
}

/** Таймер доиграл: возврат → покой с кадром отдыха; отдых → обычный покой. */
export function ofTimer(s: OfState): OfState {
  return s.mode === "land" ? { mode: "idle", rest: true } : { ...s, rest: false };
}

/** Классы логотипа и строки статуса (V2 renderVals: `ofBrand`, `ofMv`, `ofTr`, `ofB1..3`, `ofLine`). */
export function ofClasses(off: boolean, mode: OfMode) {
  const run = mode !== "idle";
  return {
    brand: cls("p2-brand of-brand", off && "p2-offline", mode === "land" && "of-land"),
    mv: cls("of-mv", run && "p2-lmove"),
    tr: cls("of-tr", run && "p2-ltrain"),
    lb: [1, 2, 3].map((i) => cls("p2-lb", run && `p2-lb${i}`)),
    line: off ? "p2-in" : "of-gone p2-off",
  };
}
