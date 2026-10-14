// «Улучшить готовую» (C-improve): плита 01 свёрнута в полосу «01 Итоги квартала.pptx · 14 слайдов · оформление из
// презентации», плита 02 встаёт под неё (40 px), над полем — заметка об исходной презентации, поле уходит под неё.
// Разметка — boards/V2.dc.html, `.tx-strip` и `.tx-note`. Обе проявляются и гаснут перекрёстным затуханием
// (p2-on / p2-off) и, пока гаснут, держат последнюю презентацию. Помощник сужает колоду — текст заметки не переносится
// заново посреди хода: две копии в одном месте (стопка `c-note`, create.css), коробка растёт той же кривой до высоты
// узкой копии.
import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { useApp } from "../../store";
import type { ImproveSource } from "../../types";
import { useDeckWrap } from "../deck/useDeckFit";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { improveNoteParts, improveSlides, improveStripMeta, modelOnOf } from "./textRules";
import { useNarrow } from "./useNarrow";

/** Последнее непустое значение: уходящее содержимое гаснет со своими данными. */
export function useHeld<T>(value: T | null): T | null {
  const last = useRef<T | null>(value);
  if (value !== null) last.current = value;
  return last.current;
}

/** Режим виден: открыт шаг «Текст» на «Создать» и есть исходная презентация (V2 `txImpOn`). */
export function useImproveOn(): boolean {
  const { ui, improveSource } = useApp();
  return ui.screen === "create" && ui.open === "text" && !ui.more && ui.improve && !!improveSource;
}

/** Модель подключена: заметка обещает, что она посмотрит на каждый новый слайд. */
export function useModelOn(): boolean {
  const { health, modelStatus } = useApp();
  return modelOnOf(health, modelStatus);
}

/** Полоса «01 …» над плитой 02 (слой колоды, z 1). Клик — выход из режима к шагу «Шаблон», текст остаётся
 *  (V2 `txBack`: reducer `open tpl` снимает `improve`). */
export function ImproveStrip() {
  const { dispatch, improveSource } = useApp();
  const on = useImproveOn();
  const src = useHeld(improveSource);
  const meta = src ? improveStripMeta(src) : "";
  const count = src ? improveSlides(src) : null;
  return (
    <div className={cls("tx-strip", on ? "p2-on" : "p2-off")}
      style={{ position: "absolute", left: 0, right: 0, top: 0, height: 40, zIndex: 1, borderRadius: "40px 40px 0 0", background: "#FFFFFF" }}>
      {src && (
        <button type="button" className="ci-strip" onClick={() => dispatch({ type: "open", step: "tpl" })} tabIndex={on ? 0 : -1}
          aria-label={`Вернуться к шагу «Шаблон»: оформление из презентации «${src.name}»${count ? `, ${count}` : ""}`}>
          <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 13, lineHeight: "20px", color: "#5A6272" }}>01</span>
          <span className="ci-sname">{src.name}</span>
          <span style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{meta}</span>
        </button>
      )}
    </div>
  );
}

const NOTE: CSSProperties = {
  display: "flex", alignItems: "center", gap: 16, flex: "none", padding: "16px 24px", borderRadius: 24,
  boxShadow: "inset 0 0 0 1px rgba(37,99,235,.14)",
};

/** Высота заметки в широкой и узкой раскладке (0 — ещё не измерена). */
export interface NoteHeights { wide: number; narrow: number }

const NOTE_P: CSSProperties = { minWidth: 0, margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220" };
/** Поля заметки по вертикали (16 + 16) и значок (32): коробка не ниже его. */
const NOTE_PAD = 32;
const NOTE_ICON = 32;

/** Заметка над полем (`.tx-note`, absolute в `.tx-b2`). `onHeights` — её высота в обеих раскладках (замер двух копий
 *  текста: каждая на всём ходу своей ширины): TextBody сдвигает поле под неё, а create.css ведёт высоту коробки той же
 *  кривой, что колоду. */
export function ImproveNote({ on, onHeights }: { on: boolean; onHeights(h: NoteHeights): void }) {
  const { improveSource } = useApp();
  const modelOn = useModelOn();
  const narrow = useNarrow();
  const wrap = useDeckWrap();
  const src: ImproveSource | null = useHeld(improveSource);
  const parts = src ? improveNoteParts(src, modelOn) : [];
  const key = parts.map((p) => p.t).join("|");
  const wRef = useRef<HTMLParagraphElement>(null);
  const nRef = useRef<HTMLParagraphElement>(null);
  const [h, setH] = useState<NoteHeights>({ wide: 0, narrow: 0 });
  useLayoutEffect(() => {
    const w = wRef.current, n = nRef.current;
    if (!w || !n) return;
    // широкая копия всегда во весь рост; узкая в широкой раскладке — высотой 0, её строки — scrollHeight
    const measure = () => {
      const next = { wide: w.offsetHeight ? Math.max(NOTE_ICON, w.offsetHeight) + NOTE_PAD : 0, narrow: n.scrollHeight ? Math.max(NOTE_ICON, n.scrollHeight) + NOTE_PAD : 0 };
      setH((cur) => (cur.wide === next.wide && cur.narrow === next.narrow ? cur : next));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(w);
    window.addEventListener("resize", measure);
    void document.fonts?.ready.then(measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [key, wrap]);
  useLayoutEffect(() => onHeights(h), [h, onHeights]);
  const text = parts.map((p, i) => (p.b ? <b key={i} style={{ fontWeight: 700 }}>{p.t}</b> : <span key={i}>{p.t}</span>));
  return (
    <div className={cls("tx-note", on ? "p2-on" : "p2-off")} role="note" style={NOTE}>
      <span aria-hidden="true" style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: "none", width: 32, height: 32, borderRadius: 999, background: "#2563EB", color: "#FFFFFF" }}>
        <Icon name="wand" size={16} />
      </span>
      <div className="hp-tx hp-txf" data-tx="c-note">
        <p ref={wRef} className="hp-txw" style={NOTE_P} aria-hidden={narrow || undefined}>{text}</p>
        <p ref={nRef} className="hp-txn" style={NOTE_P} aria-hidden={!narrow || undefined}>{text}</p>
      </div>
    </div>
  );
}
