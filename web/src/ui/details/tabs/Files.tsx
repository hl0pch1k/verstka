// Вкладка «Файлы» листа «Подробнее» (boards/D-files, V2 `#dd-panel-files`, модуль details `dlF`): файлы каждого
// варианта (PowerPoint, PDF, Веб), паспорт запуска, время по этапам, итог проверки, автоисправления и свёрнутое «Для
// разработчиков» (FilesDev). Данные — files.ts.
// Помощник сужает колоду (V2 версии 100): те же две колонки, правая 50 % → 44 %, кнопки файлов плотнее, «на экране» и
// бейдж «Паспорта» сжимаются и гаснут, у плиток итога значки сжимаются и гаснут, длинная подпись — многоточием.
import { useContext, useState } from "react";
import { plural } from "../../../lib/utils";
import { useApp } from "../../../store";
import type { Generation, Variant } from "../../../types";
import { cls } from "../../kit/cls";
import { Icon } from "../../kit/Icon";
import { checkTiles, fileRows, fixRowsOf, passport, stagesOf } from "../files";
import { slideTag } from "../quality";
import { FilesDev } from "./FilesDev";
import { Tx } from "../../kit/Tx";
import { SheetCtx } from "../sheetMorph";
import type { DeckManifest } from "../useDeckManifest";

const H = { margin: 0 } as const;

export function FilesTab({ g, v, deck }: { g: Generation; v: Variant; deck: DeckManifest }) {
  const { strategyTitle, templateLabel } = useApp();
  const [dev, setDev] = useState(false);
  const files = fileRows(g, v.strategy, strategyTitle);
  const pass = passport(g, v, templateLabel(g.template_id, v.run_manifest?.template.file ?? g.template_file), strategyTitle);
  const m = v.run_manifest;
  const stages = m ? stagesOf(m) : null;
  const check = checkTiles(g, v);
  const fixes = fixRowsOf(v, deck.manifest);
  const n = files.length;
  const fact = useContext(SheetCtx).fact;

  return (
    <div id="dd-panel-files" className="df-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-files" tabIndex={0} style={{ flex: 1, minHeight: 0, padding: "24px 0", overflowY: "auto", borderRadius: 24 }}>
      <div className="df-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
        <section className="df-card p2-in" aria-labelledby="df-h1" style={{ animationDelay: "280ms" }}>
          <div className="df-hd"><h2 id="df-h1" className="df-h">Файлы</h2><span className="df-badge">{plural(n, "вариант", "варианта", "вариантов")}</span></div>
          <ul style={{ display: "flex", flexDirection: "column", gap: 16, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
            {files.map((f) => (
              <li key={f.key} className={cls("df-row", f.cur && "df-row-on")} aria-current={f.cur || undefined} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 64, padding: "0 12px 0 16px", borderRadius: 16 }}>
                <div style={{ minWidth: 0 }}>
                  <p style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap" }}>
                    <span className="df-t" title={f.title}>{f.title}</span>{f.score !== null && <span className="df-score" title={f.tip}>{f.score}</span>}{f.cur && <span className="df-now hp-wo">на экране</span>}
                  </p>
                  <p title={f.file} style={{ margin: 0, fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.file}</p>
                </div>
                <div style={{ display: "flex", gap: 8, flex: "none" }}>
                  {f.pptx && <a className="p2-ob" href={f.pptx} download={`${f.base}.pptx`} aria-label={f.aPpt} style={{ height: 40, padding: "0 16px" }}>PowerPoint</a>}
                  {f.pdf && <a className="p2-ob" href={f.pdf} download={`${f.base}.pdf`} aria-label={f.aPdf} style={{ height: 40, padding: "0 16px" }}>PDF</a>}
                  {f.html && <a className="p2-ob" href={f.html} target="_blank" rel="noopener noreferrer" aria-label={f.aWeb} title="Откроется в новой вкладке" style={{ height: 40, padding: "0 16px" }}><span>Веб</span><Icon name="external" size={16} /></a>}
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="df-card p2-in" aria-labelledby="df-h2" style={{ animationDelay: "320ms" }}>
          <div className="df-hd"><h2 id="df-h2" className="df-h">Паспорт запуска</h2><span className="df-badge df-pb hp-wo">{pass.badge}</span></div>
          {pass.facts.length ? (
            <dl style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "16px 24px", margin: "16px 0 0" }}>
              {pass.facts.map((x) => (
                <Tx key={x.k} tx="f-fact" as="div" hpd={fact} title={x.title}>
                  <dt className="df-fk">{x.k}</dt>
                  <dd className={cls("df-fv", x.dim && "df-dim")} style={H}>{x.v}</dd>
                </Tx>
              ))}
            </dl>
          ) : <p className="df-fk" style={{ marginTop: 16 }}>У этого варианта нет паспорта — соберите презентацию заново.</p>}
        </section>

        {stages && (
          <section className="df-card p2-in" aria-labelledby="df-h3" style={{ animationDelay: "360ms" }}>
            <div className="df-hd"><h2 id="df-h3" className="df-h">Время по этапам</h2><span className="df-badge" title={stages.title}>{stages.total}</span></div>
            <ul style={{ display: "flex", flexDirection: "column", gap: 12, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
              {stages.rows.map((s) => (
                <li key={s.name} title={s.tip} style={{ display: "grid", gridTemplateColumns: "216px minmax(0, 1fr) 48px", alignItems: "center", gap: 16, height: 24 }}>
                  <span style={{ minWidth: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.name}</span>
                  <span className="df-track" aria-hidden="true"><span className="df-fill" style={{ width: s.w }} /></span>
                  <span style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{s.v}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="df-card p2-in" aria-labelledby="df-h4" style={{ animationDelay: "400ms" }}>
          <div className="df-hd">
            <h2 id="df-h4" className="df-h">Итог проверки</h2>
            <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}>
              {check.head && <span className="df-chk">{check.head}{check.score !== null ? " ·" : ""}</span>}{check.score !== null && <span className="df-score" title={`Оценка качества ${check.score} из 100`}>{check.score}</span>}
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 12, marginTop: 16 }}>
            {check.tiles.map((t) => (
              <div key={t.label} className={cls("df-tile", t.cls)} style={{ gridColumn: `span ${t.span}` }}>
                <p className="df-tl"><Icon name={t.icon} size={16} className="hq-ico" /><span>{t.label}</span></p>
                <p className="df-tv"><span>{t.v}</span>{t.sub && <span className="df-tsub">{t.sub}</span>}</p>
              </div>
            ))}
          </div>
        </section>

        {fixes.length > 0 && (
          <section className="df-card p2-in" aria-labelledby="df-h5" style={{ gridColumn: "1 / -1", animationDelay: "440ms" }}>
            <div className="df-hd"><h2 id="df-h5" className="df-h">Автоисправления</h2><span className="df-badge">{fixes.reduce((k, r) => k + r.n, 0)}</span></div>
            <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none" }}>
              {fixes.map((x, i) => (
                <li key={i} className="df-fx" style={{ display: "grid", gridTemplateColumns: "120px minmax(0, 1fr) auto", alignItems: "center", gap: 24, height: 48 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>{x.slide ? slideTag(x.slide) : "Все слайды"}</span>
                  <span style={{ minWidth: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {x.title}{x.extra ? `: ${x.extra}` : ""}{x.n > 1 ? ` ×${x.n}` : ""}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>{x.pass ?? ""}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="p2-in" style={{ gridColumn: "1 / -1", borderRadius: 24, background: "#FFFFFF", animationDelay: "480ms" }}>
          <button type="button" className="df-coll" aria-expanded={dev} aria-controls="df-dev" onClick={() => setDev(!dev)}>
            <span style={{ flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", color: "#0B1220" }}>Для разработчиков</span>
            <span style={{ minWidth: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>JSON плана и проверки · навыки и агенты · журнал агента · сравнение запусков</span>
            <span style={{ flex: 1, minWidth: 0 }} />
            <span className="df-cc" aria-hidden="true"><Icon name="chevron-down" size={18} className={cls("df-chev", dev && "df-chev-up")} /></span>
          </button>
          {dev && <FilesDev g={g} v={v} />}
        </section>
      </div>
    </div>
  );
}
