// Слой «Слайд N шаблона» (boards/D-pattern, V2 `#dl-lay-x` и полоса `dpt-back`): белый слой поверх листа
// «Подробнее · Шаблон», на 40 px ниже его верха — над ним видна полоса «Подробнее Шаблон …», клик по ней (как ✕ и Esc)
// закрывает слой. Внутри: образец с рамками мест (по нажатию на место его рамка подсвечивается), качество образца,
// как определён тип слайда, декор, места для содержания и листание образцов (кнопки и ←/→). Въезжает снизу 520 мс и
// уезжает вниз непрозрачным со своим содержимым (Layer); новый образец проявляет содержимое заново (p2-in).
// Помощник сужает колоду — слой идёт за ней каждый кадр (V2 версии 100, details.css `.dpt-g`): образец чуть у́же, места
// для содержания — третья дорожка, сжимается до нуля и гаснет вместе с ней (`dpt-plw hp-wo`), не переносясь заново.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { plural } from "../../lib/utils";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Layer } from "../layers/Layer";
import { Shot } from "./parts";
import { patternView, PLACE_COLOR, type PatternView } from "./pattern";
import { headerLayerOpen } from "./sheetView";
import { bandOf } from "./templateTab";
import type { DeckManifest } from "./useDeckManifest";

const LEGEND: Array<[string, string]> = [[PLACE_COLOR.title, "заголовок"], [PLACE_COLOR.text, "текст"], [PLACE_COLOR.image, "изображение"], [PLACE_COLOR.data, "данные"]];

export function PatternLayer({ deck }: { deck: DeckManifest }) {
  const { ui, dispatch } = useApp();
  const m = deck.manifest;
  const view = m && ui.pattern !== null ? patternView(m, ui.pattern) : null;
  const open = !!view;
  // показанный образец держится, пока слой уезжает
  const last = useRef<PatternView | null>(null);
  if (view) last.current = view;
  const p = last.current;
  const [map, setMap] = useState(true);
  const [hov, setHov] = useState<string | null>(null);
  const [seen, setSeen] = useState<number | null>(null);
  if ((view?.n ?? null) !== seen) {
    setSeen(view?.n ?? null);
    setMap(true);
    setHov(null);
  }
  const close = () => dispatch({ type: "pattern", n: null });
  const go = (to: number | null) => to !== null && dispatch({ type: "pattern", n: to });
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    const t = e.target as HTMLElement;
    if (!p || e.altKey || e.ctrlKey || e.metaKey || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    if (e.key === "ArrowLeft" && p.prev !== null) go(p.prev);
    else if (e.key === "ArrowRight" && p.next !== null) go(p.next);
    else return;
    e.preventDefault();
    // новый образец заменяет содержимое: фокус остаётся в слое (Esc и стрелки работают дальше)
    e.currentTarget.focus({ preventScroll: true });
  };
  // фокус потерялся (на странице ничего не выбрано) — Esc всё равно закрывает слой, если поверх него ничего нет (раздел
  // шапки, просмотр или удаление шаблона)
  const covered = headerLayerOpen(ui);
  useEffect(() => {
    if (!open || covered) return;
    const onEsc = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || (document.activeElement && document.activeElement !== document.body)) return;
      e.preventDefault();
      dispatch({ type: "pattern", n: null });
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [open, covered, dispatch]);
  const band = m ? bandOf(m) : null;
  const aspect = m && m.slide_size.w && m.slide_size.h ? `${m.slide_size.w} / ${m.slide_size.h}` : "16 / 9";

  return (
    <>
      <div className={open ? "p2-on" : "p2-off"}>
        <button type="button" className="dpt-strip dpt-back" onClick={(e) => { e.currentTarget.blur(); close(); }} aria-label={`Вернуться к разбору шаблона ${band?.name ?? ""}`.trim()}>
          <span className="dpt-sw">Подробнее</span>
          <span className="dpt-sname">Шаблон</span>
          {band && <span className="dpt-smeta">{band.name} · {plural(m!.n_slides, "слайд", "слайда", "слайдов")} · {band.facts[2].v} {band.facts[2].l}</span>}
          <span className="dpt-ret">к шаблону<Icon name="chevron-up" size={16} /></span>
        </button>
      </div>
      <Layer id="dl-lay-x" open={open} top={40} z={2} bare label={p ? p.title : "Слайд шаблона"} onClose={close}>
        {p && (
          <section className="dpt-layer" role="dialog" aria-modal="true" aria-labelledby="dpt-title" aria-describedby="dpt-desc" tabIndex={-1} onKeyDown={onKey} style={{ outline: "none" }}>
            <div className="dpt-fx" style={{ display: "flex", flexDirection: "column", height: 532 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 24, height: 64, flex: "none" }}>
                <h2 key={`t${p.n}`} id="dpt-title" className="dpt-title p2-in" style={{ animationDelay: "120ms" }}>{p.title}</h2>
                <p key={`d${p.n}`} id="dpt-desc" className="p2-in" title={p.desc} style={{ minWidth: 0, margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", animationDelay: "160ms" }}>{p.desc}</p>
                <span style={{ flex: 1, minWidth: 0 }} />
                <button type="button" className="p2-rbl p2-in" onClick={close} aria-label="Закрыть" title="Закрыть (Esc)" style={{ flex: "none", animationDelay: "200ms" }}><Icon name="x" size={18} /></button>
              </div>

              <div key={p.n} className="dpt-g" style={{ display: "grid", gridTemplateColumns: "576px 296px minmax(0, 1fr)", gap: 32, height: 388, marginTop: 24 }}>
                <div style={{ minWidth: 0 }}>
                  <figure className="dpt-map p2-in" style={{ animationDelay: "160ms" }}>
                    <Shot src={p.img} fallback={p.fallback} alt={p.alt} loading="eager" style={{ width: "100%", aspectRatio: aspect }} />
                    {map && p.frames.length > 0 && (
                      <span className="dpt-frames p2-pop" aria-hidden="true">
                        {p.frames.map((f) => (
                          <span key={f.key} className={cls("dpt-fr", f.dash && "dpt-dash", hov === f.id && "dpt-fr-on")} style={{ left: f.x, top: f.y, width: f.w, height: f.h, borderColor: f.c }}>
                            <span className="dpt-pill" style={{ background: f.c }}>{f.n}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </figure>
                  <div className="p2-in" style={{ display: "flex", alignItems: "center", gap: 16, height: 40, marginTop: 16, animationDelay: "200ms" }}>
                    {p.frames.length > 0 && (
                      <button type="button" className="p2-gb" onClick={() => setMap(!map)} aria-pressed={map} style={{ marginLeft: -16 }}>
                        <Icon name={map ? "eye-off" : "eye"} size={18} /><span>{map ? "Скрыть разметку" : "Показать разметку"}</span>
                      </button>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
                  <section className="dpt-box p2-in" title="Насколько чистая структура у образца и насколько он пригоден для новых слайдов" style={{ animationDelay: "200ms" }}>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16 }}>
                      <h3 className="dpt-bt">Качество образца</h3>
                      <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#2563EB" }}>{p.q}&#160;%</span>
                    </div>
                    <div role="progressbar" aria-label="Качество образца" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p.q} style={{ position: "relative", height: 4, marginTop: 12, borderRadius: 999, background: "rgba(11,18,32,.08)", overflow: "hidden" }}>
                      <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: "#2563EB", transformOrigin: "left center", transform: `scaleX(${p.q / 100})` }} />
                    </div>
                  </section>
                  {p.votes.length > 0 && (
                    <section className="dpt-box p2-in" style={{ animationDelay: "240ms" }}>
                      <h3 className="dpt-bt">Как определён тип слайда · {p.agree}</h3>
                      <ul className="dpt-votes">
                        {p.votes.map((v) => (
                          <li key={v.src} className="dpt-vote">
                            <span className="dpt-src">{v.src}</span>
                            <span className="dpt-badge" style={v.agree ? undefined : { background: "#F3F4F1", color: "#5A6272" }}>{v.agree && <Icon name="check" size={12} />}{v.kind}</span>
                            <span className="dpt-pc">{v.p}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  <section className="dpt-box p2-in" style={{ animationDelay: "280ms" }}>
                    <h3 className="dpt-bt">Декор</h3>
                    <p style={{ margin: "4px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{p.decor}</p>
                  </section>
                </div>

                <section className="p2-in dpt-plw hp-wo" aria-labelledby="dpt-pl" style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, animationDelay: "240ms" }}>
                  <h3 id="dpt-pl" className="dpt-h3">{p.placesH}</h3>
                  <p className="dpt-legend">{LEGEND.map(([c, t]) => <span key={t}><span className="dpt-dot" style={{ background: c }} />{t}</span>)}</p>
                  <ul className="dpt-places" style={{ minHeight: 0, overflowY: "auto", scrollbarWidth: "none" }}>
                    {p.places.map((x) => {
                      const on = hov === x.id;
                      return (
                        <li key={x.id}>
                          <button type="button" className={cls("dpt-pl", on && "dpt-pl-on")} aria-pressed={on} onClick={() => setHov(on ? null : x.id)}>
                            <span className="dpt-pl1">{x.num && <span className="dpt-num" style={{ background: x.c }}>{x.num}</span>}{!x.num && <span className="dpt-dot" style={{ background: x.c, margin: "0 6px" }} />}<span className="dpt-role">{x.role}</span>{x.extra && <span className="dpt-extra">{x.extra}</span>}</span>
                            {x.sample && <span className="dpt-sample" title={x.sample}>{x.sample}</span>}
                            {x.note && <span className="dpt-note">{x.note}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              </div>

              <div className="p2-in" style={{ display: "flex", alignItems: "center", gap: 8, height: 40, marginTop: 16, animationDelay: "280ms" }}>
                <p style={{ margin: "0 auto 0 0", fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", color: "#0B1220" }}>
                  {p.n} <span style={{ color: "#5A6272" }}>/ {m?.n_slides ?? ""}</span>
                </p>
                <button type="button" className="p2-rbl" onClick={() => go(p.prev)} disabled={p.prev === null} aria-label="Предыдущий образец"><Icon name="chevron-left" size={18} /></button>
                <button type="button" className="p2-rbl" onClick={() => go(p.next)} disabled={p.next === null} aria-label="Следующий образец"><Icon name="chevron-right" size={18} /></button>
              </div>
            </div>
          </section>
        )}
      </Layer>
    </>
  );
}
