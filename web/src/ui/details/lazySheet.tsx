// Ленивая загрузка содержимого листа «Подробнее» (SheetPanels: шесть вкладок, «Почему так» с данными и мини-графиками,
// слой «Слайд N шаблона»): к первой отрисовке оно не нужно и уходит из основного куска сборки. Кусок спрашивается один
// раз на страницу — в свободное время после первой отрисовки (`preloadSheet`) и при открытии листа, если ещё не пришёл
// (`loadSheet`). Пока его нет — Suspense без запасного содержимого: панели вкладок стоят в абсолютно поставленном слое
// листа, место не меняется, а пришедшее содержимое входит своей лесенкой p2-in. Не загрузился (нет связи, сервер успел
// обновиться) — спокойная строка с «Обновить страницу» на месте вкладок.
import { Component, lazy, Suspense, type ReactNode } from "react";
import { ErrorLine } from "../kit/ErrorLine";

type SheetModule = typeof import("./SheetPanels");
let chunk: Promise<SheetModule> | null = null;

/** Кусок листа: один запрос на страницу; неудача — следующий вызов спросит снова. */
export function loadSheet(): Promise<SheetModule> {
  chunk ??= import("./SheetPanels").catch((e: unknown) => {
    chunk = null;
    throw e;
  });
  return chunk;
}

export const LazyPanels = lazy(() => loadSheet().then((m) => ({ default: m.SheetPanels })));
export const LazyPattern = lazy(() => loadSheet().then((m) => ({ default: m.PatternLayer })));

/** Загрузить кусок листа в свободное время после первой отрисовки; возвращает отмену. */
export function preloadSheet(): () => void {
  const go = () => void loadSheet().catch(() => {});
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(go, { timeout: 2500 });
    return () => window.cancelIdleCallback(id);
  }
  const t = window.setTimeout(go, 1200);
  return () => window.clearTimeout(t);
}

/** Граница куска: пока он грузится — ничего (место держит слой листа), не загрузился — строка на месте вкладок
 *  (`quiet` — ничего: слой «Слайд N шаблона» закрыт, пока его не открыли из вкладки). */
export class SheetBoundary extends Component<{ children: ReactNode; quiet?: boolean }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return <Suspense fallback={null}>{this.props.children}</Suspense>;
    if (this.props.quiet) return null;
    return (
      <div className="dd-pw p2-in" style={{ position: "absolute", left: 48, right: 48, top: 104, pointerEvents: "auto" }}>
        <div className="dd-box" style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ display: "flex", flex: 1, minWidth: 0 }}><ErrorLine text="Подробности не загрузились — нет связи с сервером" lines={1} /></span>
          <button type="button" className="p2-gb" onClick={() => window.location.reload()}>Обновить страницу</button>
        </div>
      </div>
    );
  }
}
