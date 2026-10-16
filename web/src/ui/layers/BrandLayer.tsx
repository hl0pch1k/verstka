// Слой «Брендбук» (boards/V2.dc.html версии 105, модуль ds, `#bb-lay`): голубой слой поднимается из-под колоды, как
// «Слайды шаблона»; полоса над слоем закрывает его. Слева — что извлечено (палитра, шрифты, логотипы), справа —
// расхождения с шаблоном, что важнее (переключатель), правила; внизу «Убрать брендбук» и «Готово». Слой живёт, пока жив
// его контекст («Создать» без раздела и приложенный брендбук): ушёл контекст — уезжает и сам не возвращается.
// Помощник сужает колоду — правая колонка 416 → 376 той же кривой (layers.css `.bb-g`).
import { useEffect, useRef } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import type { BrandPriority } from "../../types";
import { cls } from "../kit/cls";
import { radioGroup } from "../kit/radios";
import { Icon } from "../kit/Icon";
import { LogoTile } from "../create/BrandAnalysis";
import { brandLayerMeta, brandName, conflictView, fontRoleLabel, roleLabel } from "../create/dataRules";
import { Layer, lsDelay, useLayerPresence } from "./Layer";
import { Scrim } from "./Scrim";

const SEG: [BrandPriority, string][] = [["brand", "Брендбук"], ["template", "Шаблон"]];

export function BrandLayer() {
  const { ui, dispatch, data, templates, templateId } = useApp();
  const live = data.brand;
  const ctx = ui.screen === "create" && !ui.sect && live.phase === "on" && !!live.spec;
  // «Убрать брендбук»: слой уезжает непрозрачным со своим содержимым — последний брендбук держится, пока он едет
  const held = useRef(live);
  if (live.spec) held.current = live;
  const b = held.current;
  // контекст ушёл (раздел, другой экран, брендбук убран) — слой закрывается и уезжает вместе со всем
  useEffect(() => {
    if (ui.brandLayer && !ctx) dispatch({ type: "set", patch: { brandLayer: false } });
  }, [ui.brandLayer, ctx, dispatch]);
  const open = ui.brandLayer && ctx;
  const p = useLayerPresence(open);
  const close = () => dispatch({ type: "set", patch: { brandLayer: false } });
  const spec = b.spec;
  const tpl = templates.find((t) => t.template_id === templateId);
  const tplName = tpl ? tplLabel(tpl) : null;
  const name = spec ? `Брендбук ${brandName(spec, b.file)}` : "";
  const seg = radioGroup(SEG.map(([k]) => k), data.priority, data.setPriority);
  // «Убрать брендбук»: карточки, открывшей слой, больше нет — фокус встаёт на кнопку «Брендбук», которая вернулась
  const remove = () => {
    close();
    data.removeBrand();
    window.setTimeout(() => document.querySelector<HTMLElement>(".bb-btn")?.focus({ preventScroll: true }), 60);
  };
  return (
    <>
      <Scrim open={open} onClose={close} label="Закрыть «Брендбук»" z={8} />
      <Layer id="bb-lay" presence={p} open={open} top={120} z={8} label={name} role="dialog" onClose={close}>
        {p.mounted && spec && (
          <>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64 }}>
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <h2 id="bb-ttl" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {name}
                </h2>
                <div style={{ display: "flex", alignItems: "center", gap: 16, height: 24, minWidth: 0 }}>
                  <span role="img" aria-label="Палитра брендбука" style={{ display: "flex", alignItems: "center", gap: 4, flex: "none" }}>
                    {spec.colors.slice(0, 6).map((c, i) => <span key={`${c.hex}-${i}`} className="pv-dot" title={c.hex} style={{ background: c.hex }} />)}
                  </span>
                  <span style={{ minWidth: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {brandLayerMeta(spec, b.file, tplName)}
                  </span>
                </div>
              </div>
              <button type="button" className="p2-rbl pv-rbw" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
            </div>

            <div className="pv-box">
              <div className="pv-scroll p2-fade">
                <div className="bb-g">
                  {/* что извлечено */}
                  <div style={{ minWidth: 0 }}>
                    <section className="p2-ls" aria-labelledby="bb-h-pal" style={lsDelay(160)}>
                      <h3 id="bb-h-pal" className="dd-h">Палитра</h3>
                      <ul className="bb-sws">
                        {spec.colors.map((c, i) => (
                          <li key={`${c.hex}-${i}`}>
                            <span className="bb-sw" style={{ background: c.hex }} />
                            <span className="bb-hex">{c.hex}</span>
                            <span className="bb-role" title={c.name ?? undefined}>{c.name ? `${roleLabel(c.role)} · ${c.name}` : roleLabel(c.role)}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                    {spec.fonts.length > 0 && (
                      <section className="p2-ls bb-sec" aria-labelledby="bb-h-font" style={lsDelay(200)}>
                        <h3 id="bb-h-font" className="dd-h">Шрифты</h3>
                        <ul className="bb-fonts">
                          {spec.fonts.map((f, i) => (
                            <li key={`${f.family}-${i}`} className="bb-font">
                              <span className="bb-fa" style={{ fontWeight: f.weight }} aria-hidden="true">Аа</span>
                              <span className="bb-ct">
                                <span className="bb-cn">{f.family}</span>
                                <span className="bb-cm">{fontRoleLabel(f.role)}{f.fallback ? ` · замена — ${f.fallback}` : ""}</span>
                              </span>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                    {spec.logos.length > 0 && (
                      <section className="p2-ls bb-sec" aria-labelledby="bb-h-logo" style={lsDelay(240)}>
                        <h3 id="bb-h-logo" className="dd-h">Логотипы</h3>
                        <ul className="bb-logos2">
                          {spec.logos.map((l, i) => (
                            <li key={`${l.file}-${i}`}>
                              <LogoTile logo={l} brandId={b.id} className="bb-lgt" />
                              <span className="bb-lgc">{l.name}</span>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                  </div>

                  {/* расхождения с шаблоном и правила */}
                  <div style={{ minWidth: 0 }}>
                    <section className="p2-ls" aria-labelledby="bb-h-cf" style={lsDelay(200)}>
                      <h3 id="bb-h-cf" className="dd-h">Расхождения с шаблоном</h3>
                      <p className="bb-sub">При расхождении важнее</p>
                      <div className="bb-seg" role="radiogroup" aria-label="При расхождении важнее" onKeyDown={seg.onKeyDown}>
                        {SEG.map(([k, label]) => (
                          <button key={k} type="button" role="radio" aria-checked={data.priority === k} tabIndex={seg.tabIndex(k)} className={cls("p2-rseg", data.priority === k && "p2-rseg-on")}
                            onClick={() => data.setPriority(k)}>
                            {label}
                          </button>
                        ))}
                      </div>
                      {b.conflicts.length > 0 ? (
                        <ul className="bb-cfs">
                          {b.conflicts.map((c, i) => {
                            const v = conflictView(c, data.priority);
                            return (
                              <li key={`${c.what}-${i}`} className="bb-cf">
                                <span className="bb-cfk">{v.k}</span>
                                <span className="bb-cfv">
                                  {v.sw && <span className="bb-dot" style={{ background: v.a }} />}<span>шаблон — {v.a}</span>
                                  <span aria-hidden="true">·</span>
                                  {v.sw && <span className="bb-dot" style={{ background: v.b }} />}<span>брендбук — {v.b}</span>
                                </span>
                                <span className="bb-win"><Icon name="check" size={16} /><span>В презентации: {v.res}</span></span>
                              </li>
                            );
                          })}
                        </ul>
                      ) : (
                        <p className="bb-none">{tplName ? `С шаблоном ${tplName} брендбук не расходится` : "Расхождений с шаблоном нет"}</p>
                      )}
                    </section>
                    {spec.rules.length > 0 && (
                      <section className="p2-ls bb-sec" aria-labelledby="bb-h-rl" style={lsDelay(240)}>
                        <h3 id="bb-h-rl" className="dd-h">Правила</h3>
                        <ul className="dtp-rules">
                          {spec.rules.map((r, i) => <li key={i} className="dtp-rule">{r.text}</li>)}
                        </ul>
                      </section>
                    )}
                  </div>
                </div>
              </div>
              <div className="pv-foot">
                <button type="button" className="p2-gb pv-del" onClick={remove}>
                  <Icon name="trash" size={18} />
                  <span>Убрать брендбук</span>
                </button>
                <button type="button" className="p2-cta pv-cta" onClick={close}><span>Готово</span></button>
              </div>
            </div>
          </>
        )}
      </Layer>
    </>
  );
}
