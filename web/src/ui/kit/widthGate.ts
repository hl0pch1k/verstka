// Наблюдение за шириной без лишних срабатываний. Копии стопок текста (hp-tx) держат ширину на ходу помощника только с
// точностью до долей пикселя (клетка + --hpd·--hpp): ResizeObserver на них срабатывал бы каждый кадр хода и каждый раз
// вызывал бы замер с раскладкой. Здесь срабатывание доходит до замера, только когда ширина ушла от последней принятой
// хотя бы на 1 px (окно, шрифты) — дрожь посреди хода отсеивается.

/** Пропускает ширину, только если она отличается от последней пропущенной хотя бы на `step` px (первая — всегда). */
export function widthGate(step = 1): (w: number) => boolean {
  let last = Number.NaN;
  return (w) => {
    if (Math.abs(w - last) < step) return false;
    last = w;
    return true;
  };
}

/** ResizeObserver на `els`, который зовёт `cb`, только когда ширина какого-то из них ушла на 1 px и больше. */
export function observeWidth(els: Iterable<Element>, cb: () => void): () => void {
  const gates = new Map<Element, (w: number) => boolean>();
  const ro = new ResizeObserver((entries) => {
    let hit = false;
    for (const e of entries) if (gates.get(e.target)?.(e.contentRect.width)) hit = true;
    if (hit) cb();
  });
  for (const el of els) {
    gates.set(el, widthGate());
    ro.observe(el);
  }
  return () => ro.disconnect();
}
