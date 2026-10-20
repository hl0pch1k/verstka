// Прогрев слоёв-разделов («Мои презентации», «Шаблоны»): наведение или фокус на пункте шапки монтирует слой закрытым
// (под колодой, его не видно) — к нажатию он уже нарисован, и подъём начинается в кадре нажатия, а не после того, как
// тяжёлое содержимое смонтировалось (холст: слои стоят в DOM всегда). Ушёл указатель — слой держится ещё COOL_MS и
// размонтируется (если не открыт).
import { useEffect, useState } from "react";

export type Sect = "hist" | "tpls";

/** Сколько прогретый слой держится после ухода указателя. */
const COOL_MS = 4000;

const warm = new Set<Sect>();
const timers = new Map<Sect, number>();
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

/** Указатель или фокус на пункте шапки: слой — смонтировать закрытым. */
export function warmSect(s: Sect) {
  window.clearTimeout(timers.get(s));
  timers.delete(s);
  if (warm.has(s)) return;
  warm.add(s);
  emit();
}

/** Указатель или фокус ушёл: прогрев снимается через COOL_MS. */
export function coolSect(s: Sect) {
  window.clearTimeout(timers.get(s));
  timers.set(s, window.setTimeout(() => {
    timers.delete(s);
    if (warm.delete(s)) emit();
  }, COOL_MS));
}

/** Прогрет ли слой. */
export function useWarm(s: Sect): boolean {
  const [on, setOn] = useState(() => warm.has(s));
  useEffect(() => {
    const f = () => setOn(warm.has(s));
    subs.add(f);
    f();
    return () => void subs.delete(f);
  }, [s]);
  return on;
}
