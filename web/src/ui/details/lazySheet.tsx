// Ленивая загрузка содержимого листа «Подробнее» (SheetPanels: шесть вкладок, «Почему так» с данными и мини-графиками,
// слой «Слайд N шаблона»): к первой отрисовке оно не нужно и уходит из основного куска сборки. Кусок спрашивается один
// раз на страницу — в свободное время после первой отрисовки (`preloadSheet`) и при открытии листа, если ещё не пришёл
// (`loadSheet`); неудача — следующий вызов спросит снова (`makeLoader`). Пока его нет, панели вкладок стоят в абсолютно
// поставленном слое листа, место не меняется; грузится дольше 600 мс — на месте вкладок спокойная строка «Загружаю
// подробности…» (проявляется), а когда кусок пришёл, она сперва гаснет (160 мс) и только потом входит содержимое своей
// лесенкой p2-in — ничего не наезжает и не выскакивает. Не загрузился (нет связи, сервер успел обновиться) — строка с
// «Обновить страницу» (браузер помнит неудачный import() того же адреса до перезагрузки — повторить на месте нельзя).
// Ошибка внутри вкладки — не сюда: её ловит граница самой вкладки (TabBoundary в SheetPanels), остальные вкладки
// работают; ошибка разметки вне вкладок — своя строка, не «нет связи».
import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { DsSpin } from "../create/dsKit";
import { ErrorLine } from "../kit/ErrorLine";
import { isChunkError, makeLoader } from "./sheetLoad";

type SheetModule = typeof import("./SheetPanels");

/** Кусок листа: один запрос на страницу; неудача — следующий вызов спросит снова. */
export const loadSheet: () => Promise<SheetModule> = makeLoader(() => import("./SheetPanels"));

// ── строка загрузки: проявляется через 600 мс; пришедший кусок ждёт, пока она погаснет
export const LOAD_LINE_AFTER = 600;
export const LOAD_LINE_OUT = 160;
let lineHide: (() => Promise<void>) | null = null;
/** Кусок пришёл: строка загрузки на виду — сперва погасить её. */
const afterLine = <T,>(v: T): Promise<T> => (lineHide ? lineHide().then(() => v) : Promise.resolve(v));

export const LazyPanels = lazy(() => loadSheet().then(afterLine).then((m) => ({ default: m.SheetPanels })));
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

const BOX = { position: "absolute", left: 48, right: 48, top: 104, pointerEvents: "auto" } as const;

/** «Загружаю подробности…» — на месте вкладок, пока кусок грузится дольше 600 мс. */
function LoadLine() {
  const [st, setSt] = useState<"wait" | "on" | "out">("wait");
  useEffect(() => {
    const t = window.setTimeout(() => setSt("on"), LOAD_LINE_AFTER);
    return () => window.clearTimeout(t);
  }, []);
  useEffect(() => {
    if (st !== "on") return;
    lineHide = () => {
      lineHide = null;
      setSt("out");
      return new Promise((r) => window.setTimeout(r, LOAD_LINE_OUT));
    };
    return () => {
      lineHide = null;
    };
  }, [st]);
  return (
    <div className={st === "on" ? "dd-load dd-load-on" : "dd-load"} style={BOX} aria-hidden={st !== "on" || undefined}>
      <p className="dd-box" role="status" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>
        <DsSpin size={16} /><span>Загружаю подробности…</span>
      </p>
    </div>
  );
}

/** Граница куска: пока он грузится — строка загрузки (через 600 мс); не загрузился — «нет связи»; ошибка разметки,
 *  которую не поймала вкладка, — «ошибка в интерфейсе»; обе — с «Обновить страницу». `quiet` — без строк (слой
 *  «Слайд N шаблона» закрыт, пока его не открыли из вкладки). */
export class SheetBoundary extends Component<{ children: ReactNode; quiet?: boolean }, { failed: "chunk" | "render" | null }> {
  state: { failed: "chunk" | "render" | null } = { failed: null };

  static getDerivedStateFromError(e: unknown): { failed: "chunk" | "render" } {
    return { failed: isChunkError(e) ? "chunk" : "render" };
  }

  render() {
    const { failed } = this.state;
    if (!failed) return <Suspense fallback={this.props.quiet ? null : <LoadLine />}>{this.props.children}</Suspense>;
    if (this.props.quiet) return null;
    return (
      <div className="dd-pw p2-in" style={BOX}>
        <div className="dd-box" style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ display: "flex", flex: 1, minWidth: 0 }}>
            <ErrorLine text={failed === "chunk" ? "Подробности не загрузились — нет связи с сервером" : "Подробности не открылись — ошибка в интерфейсе"} lines={1} />
          </span>
          <button type="button" className="p2-gb" onClick={() => window.location.reload()}>Обновить страницу</button>
        </div>
      </div>
    );
  }
}

/** Граница одной вкладки: ошибка разметки в ней — спокойная строка на её месте с «Открыть снова», остальные вкладки
 *  работают. Сменились данные вкладки (`reset`) — пробует снова сама. */
export class TabBoundary extends Component<{ children: ReactNode; reset?: unknown }, { failed: boolean; at: unknown }> {
  state = { failed: false, at: this.props.reset };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  static getDerivedStateFromProps(p: { reset?: unknown }, s: { failed: boolean; at: unknown }) {
    return p.reset !== s.at ? { failed: false, at: p.reset } : null;
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="dd-box p2-in" style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span style={{ display: "flex", flex: 1, minWidth: 0 }}><ErrorLine text="Эта вкладка не открылась — ошибка в интерфейсе" lines={1} /></span>
        <button type="button" className="p2-gb" onClick={() => this.setState({ failed: false })}>Открыть снова</button>
      </div>
    );
  }
}
