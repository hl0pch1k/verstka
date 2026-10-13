// «Все параметры» (`#p2-b3m`, boards/V2.dc.html и C-params): плита 03 поднялась на 80, меню проявляется лесенкой —
// тип презентации (`PURPOSES` и «Свой вариант…»), аудитория и слайды (40 мс), «Варианты оформления» (120 мс) и
// варианты с миниатюрами (160/200/240 мс), три переключателя (280 мс). Лесенка — `.p2-stag` внутри `p2-on`/`p2-off`.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useApp } from "../../store";
import { PURPOSES } from "../../lib/createForm";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Switch } from "../kit/Switch";
import { OWN, SLIDES_LOCKED, type SwitchView } from "./params";
import type { ParamsPlate } from "./ParamsPlate";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");
const GRID3 = { display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 } as const;

/** Миниатюры вариантов (V2 `isS`, `isV`, `isC`): схема слайда в рамке 156×88. */
const THUMBS: Record<"s" | "v" | "c", ReactNode> = {
  s: (
    <>
      <path d="M20 24h64" stroke="rgba(255,255,255,.72)" strokeWidth="6" strokeLinecap="round" />
      <circle cx="22" cy="46" r="4" fill="#38BDF8" />
      <path d="M34 46h96" stroke="rgba(255,255,255,.48)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="22" cy="60" r="4" fill="rgba(255,255,255,.32)" />
      <path d="M34 60h80" stroke="rgba(255,255,255,.32)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="22" cy="74" r="4" fill="rgba(255,255,255,.32)" />
      <path d="M34 74h88" stroke="rgba(255,255,255,.32)" strokeWidth="4" strokeLinecap="round" />
    </>
  ),
  v: (
    <>
      <path d="M22 32h32" stroke="#38BDF8" strokeWidth="12" strokeLinecap="round" />
      <path d="M20 54h48" stroke="rgba(255,255,255,.48)" strokeWidth="4" strokeLinecap="round" />
      <path d="M20 66h32" stroke="rgba(255,255,255,.32)" strokeWidth="4" strokeLinecap="round" />
      <path d="M88 76h64" stroke="rgba(255,255,255,.24)" strokeWidth="2" strokeLinecap="round" />
      <rect x="92" y="56" width="8" height="16" rx="4" fill="rgba(255,255,255,.32)" />
      <rect x="108" y="46" width="8" height="26" rx="4" fill="rgba(255,255,255,.32)" />
      <rect x="124" y="50" width="8" height="22" rx="4" fill="rgba(255,255,255,.32)" />
      <rect x="140" y="28" width="8" height="44" rx="4" fill="#38BDF8" />
    </>
  ),
  c: (
    <>
      <path d="M20 22h56" stroke="rgba(255,255,255,.72)" strokeWidth="6" strokeLinecap="round" />
      <path d="M20 38h48M20 48h40M20 58h48M20 68h36M20 78h44" stroke="rgba(255,255,255,.32)" strokeWidth="3" strokeLinecap="round" />
      <rect x="84.5" y="32.5" width="67" height="47" rx="4.5" stroke="rgba(255,255,255,.24)" />
      <path d="M85 44h66" stroke="#38BDF8" strokeWidth="2" />
      <path d="M85 56.5h66M85 68.5h66M107.5 33v46M129.5 33v46" stroke="rgba(255,255,255,.16)" />
    </>
  ),
};

function Thumb({ kind }: { kind: "s" | "v" | "c" }) {
  return (
    <svg width="156" height="88" viewBox="0 0 172 96" fill="none" aria-hidden="true" style={{ display: "block" }}>
      <rect x="0.5" y="0.5" width="171" height="95" rx="11.5" fill="rgba(255,255,255,.04)" stroke="rgba(255,255,255,.16)" />
      {THUMBS[kind]}
    </svg>
  );
}

/** Переключатель с названием и подсказкой под ним (ряд 3). */
function SwitchBox({ id, name, hint, sw, onToggle }: { id: string; name: string; hint: string; sw: SwitchView; onToggle(): void }) {
  return (
    <div className="p2-box pp-swb">
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <span id={id} className="cp-nm" style={{ paddingTop: 2, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#FFFFFF" }}>{name}</span>
        <Switch on={sw.on} disabled={sw.disabled} title={sw.title} labelledBy={id} describedBy={`${id}d`} onToggle={onToggle} />
      </div>
      <p id={`${id}d`} style={{ margin: "4px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{hint}</p>
    </div>
  );
}

export function ParamsAll({ pp, on }: { pp: ParamsPlate; on: boolean }) {
  const { params, setParams } = useApp();
  const own = params.purpose === OWN;
  // «Вернуться к списку» ставит тип, который был выбран в списке до «Свой вариант…» (V2: `own: false`)
  const listed = useRef(own ? "product" : params.purpose);
  if (!own) listed.current = params.purpose;
  // смена списка на своё поле и обратно переносит фокус в то, что встало (только по действию человека)
  const ownRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLSelectElement>(null);
  const [focusTo, setFocusTo] = useState<"own" | "list" | null>(null);
  useEffect(() => {
    if (!focusTo) return;
    (focusTo === "own" ? ownRef.current : listRef.current)?.focus({ preventScroll: true });
    setFocusTo(null);
  }, [focusTo, own]);
  const s = pp.slides;
  return (
    <div id="p2-b3m" className={cls("p2-body p2-more-body", show(on))} style={{ position: "absolute", left: 240, right: 48, top: 128, display: "flex", flexDirection: "column" }}>
      {/* ряд 1: тип · аудитория · слайдов */}
      <div className="p2-params p2-stag" style={{ ...GRID3, transitionDelay: "40ms" }}>
        {own ? (
          <div className="p2-box cp-fbox">
            <span id="cp-tl" className="cp-lbl">Тип презентации</span>
            <input ref={ownRef} type="text" className="cp-ctl cp-own p2-in" aria-labelledby="cp-tl" value={params.ownPurpose}
              onChange={(e) => setParams({ ownPurpose: e.target.value })} placeholder="Например: лекция для студентов" />
            <button type="button" className="p2-rb cp-x p2-in" aria-label="Вернуться к списку типов" title="Вернуться к списку" style={{ animationDelay: "40ms" }}
              onClick={() => {
                setParams({ purpose: listed.current });
                setFocusTo("list");
              }}>
              <Icon name="x" size={16} />
            </button>
          </div>
        ) : (
          <label className="p2-box cp-fbox">
            <span className="cp-lbl">Тип презентации</span>
            <select ref={listRef} className="cp-ctl" value={params.purpose}
              onChange={(e) => {
                const v = e.target.value;
                setParams({ purpose: v });
                if (v === OWN) setFocusTo("own");
              }}>
              {PURPOSES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              <option value={OWN}>Свой вариант…</option>
            </select>
            <Icon name="chevron-down" size={16} className="cp-chev" />
          </label>
        )}
        <label className="p2-box cp-fbox">
          <span className="cp-lbl">Аудитория</span>
          <input type="text" className="cp-ctl" value={params.audience} onChange={(e) => setParams({ audience: e.target.value })} placeholder="Руководство, инвесторы, команда…" />
        </label>
        <div className="p2-box cp-fbox" role="group" aria-labelledby="cp-cnt" title={s.locked ? SLIDES_LOCKED : undefined}>
          <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <span id="cp-cnt" className="cp-lbl">Слайдов</span>
            {/* C-params: метка появляется, когда число слайдов задано в тексте, — тогда степпер заблокирован */}
            <span className={show(s.locked)} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.48)", whiteSpace: "nowrap" }}>
              <Icon name="lock" size={12} />
              <span>задано в тексте</span>
            </span>
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 16, height: 40 }}>
            <button type="button" className="p2-rb" onClick={() => pp.step(-1)} disabled={!s.dec} aria-label="Меньше слайдов"><Icon name="minus" size={18} /></button>
            <span aria-live="polite" style={{ minWidth: 48, textAlign: "center", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#FFFFFF" }}>{s.count}</span>
            <button type="button" className="p2-rb" onClick={() => pp.step(1)} disabled={!s.inc} aria-label="Больше слайдов"><Icon name="plus" size={18} /></button>
          </span>
        </div>
      </div>

      {/* ряд 2: варианты оформления */}
      <p id="cp-vl" className="p2-stag" style={{ margin: "32px 0 0", fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#FFFFFF", transitionDelay: "120ms" }}>Варианты оформления</p>
      <div className="p2-params" role="group" aria-labelledby="cp-vl" style={{ ...GRID3, gridTemplateColumns: `repeat(${pp.cards.length}, minmax(0, 1fr))`, marginTop: 16 }}>
        {pp.cards.map((v, i) => (
          <div key={v.name} className="p2-stag" style={{ transitionDelay: `${160 + i * 40}ms` }}>
            <button type="button" role="checkbox" aria-checked={v.on} className={cls("p2-vc cp-vc", v.on && "p2-vc-on")} onClick={() => pp.toggle(v.name)} title={v.full}>
              <span className="pp-th" aria-hidden="true"><Thumb kind={v.thumb} /></span>
              <span style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 0 }}>
                <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <span className="pp-vt" style={{ fontSize: 16, fontWeight: 700, lineHeight: "24px", color: "#FFFFFF" }}>{v.title}</span>
                  <span className="p2-vbox" aria-hidden="true"><Icon name="check" size={12} /></span>
                </span>
                <span style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{v.hint}</span>
              </span>
            </button>
          </div>
        ))}
      </div>

      {/* ряд 3: модель и изображения */}
      <div className="p2-params p2-stag" style={{ ...GRID3, marginTop: 32, transitionDelay: "280ms" }}>
        <SwitchBox id="cp-sw1" name="Модель пишет тексты слайдов" hint={pp.writesHint} sw={pp.writes} onToggle={pp.toggleWrites} />
        <SwitchBox id="cp-sw2" name="Модель проверяет слайды по картинке" hint="Посмотрит на каждый новый слайд" sw={pp.eyes} onToggle={pp.toggleEyes} />
        <SwitchBox id="cp-sw3" name="Генерировать изображения" hint={pp.imagesHint} sw={pp.pictures} onToggle={pp.togglePictures} />
      </div>
    </div>
  );
}
