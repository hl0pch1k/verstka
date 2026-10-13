// Вкладка «План» листа «Подробнее» (boards/D-plan, V2 `#dd-panel-plan`, модуль details `dlP`): слева — слайды плана
// строками (выбор строки — тот же слайд в результате), справа — заголовок колоды, «Текст агента» с «Изменить»,
// «Цифры из текста» и «Данные для диаграмм» (раскрываются ходом p2-in, сворачиваются сразу). Данные — plan.ts.
import { useEffect, useRef, useState } from "react";
import { figuresLine } from "../../../lib/narrate";
import { plural } from "../../../lib/utils";
import { useApp } from "../../../store";
import type { Generation, Variant } from "../../../types";
import { cls } from "../../kit/cls";
import { Icon } from "../../kit/Icon";
import { writtenText } from "../../layers/writerText";
import { deckPreset } from "../../result/resultView";
import { Col, Empty, Shot } from "../parts";
import { chartData, deckHead, factChips, planRows, writerHead, writerTexts } from "../plan";

export function PlanTab({ g, v, active }: { g: Generation; v: Variant; active: boolean }) {
  const { selectedSlide, setSelectedSlide, editText } = useApp();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const list = useRef<HTMLDivElement>(null);
  const o = v.outline;
  const rows = planRows(v);

  // вкладка открылась — текущий слайд виден в списке
  useEffect(() => {
    if (!active) return;
    const box = list.current;
    const row = box?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!box || !row) return;
    const top = row.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top + row.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = Math.max(0, top - 8);
  }, [active, v.strategy]);

  if (!o) {
    return (
      <div id="dd-panel-plan" role="tabpanel" aria-labelledby="dd-tab-plan" style={{ marginTop: 24 }}>
        <Empty title="Плана нет" text="У этого варианта план не сохранился — соберите презентацию заново." />
      </div>
    );
  }
  const head = deckHead(o);
  const text = writtenText(g.writer);
  const facts = factChips(o.facts);
  const fig = figuresLine(v.audit?.summary.figures);
  const data = chartData(o);
  const edit = () => {
    if (!text) return;
    editText(text, deckPreset(g));
  };

  return (
    <div id="dd-panel-plan" className="dpl-g" role="tabpanel" aria-labelledby="dd-tab-plan" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gap: 24, height: 484, marginTop: 24 }}>
      <div className="dpl-listw p2-in" style={{ animationDelay: "120ms" }}>
        <div ref={list} className="dpl-list p2-fade">
          <ol key={v.strategy} aria-label="Слайды плана" style={{ display: "flex", flexDirection: "column", margin: 0, padding: 0, listStyle: "none" }}>
            {rows.map((r, i) => {
              const on = r.n === selectedSlide;
              return (
                <li key={r.id} className="p2-in" style={{ animationDelay: `${160 + Math.min(i, 7) * 40}ms` }}>
                  <button type="button" className={cls("dpl-row", on && "dpl-row-on")} aria-current={on} aria-label={`Слайд ${r.n}: ${r.title}`} title={`Открыть слайд ${r.n}`} onClick={() => setSelectedSlide(r.n)}>
                    <span className="dpl-th"><Shot src={r.img} alt="" style={{ width: "100%", height: "100%", aspectRatio: "16 / 9" }} /><span className="dpl-n" aria-hidden="true">{r.n}</span></span>
                    <span className="dpl-hd">
                      <span className="dpl-kind">{r.kind}</span>
                      <span className="dpl-h">{r.title}</span>
                      {r.sub && <span className="dpl-sub2">{r.sub}</span>}
                    </span>
                    <span className="dpl-body">
                      {r.par && <span className="dpl-par">{r.par}</span>}
                      {r.bul.length > 0 && <span className="dpl-ul">{r.bul.map((b, k) => <span key={k} className="dpl-li dpl-li-cl">{b}</span>)}</span>}
                      {r.chips.length > 0 && <span className="dpl-chips">{r.chips.map((c, k) => <span key={k} className="dpl-chip"><b>{c.v}</b>{c.l}</span>)}</span>}
                      {r.fx.map((f, k) => <span key={k} className="dpl-fx" title={f} style={{ maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis" }}>{f}</span>)}
                      {r.items.length > 0 && (
                        <span className={cls("dpl-items", r.itemsCls)}>
                          {r.items.map((it, k) => <span key={k} className="dpl-item"><span className="dpl-it">{it.t}</span><span className="dpl-ix">{it.x}</span></span>)}
                        </span>
                      )}
                      {r.tbl && (
                        <span className="dpl-tbl">
                          <span className="dpl-tr dpl-thd"><span>{r.tbl.c1}</span><span>{r.tbl.c2}</span></span>
                          {r.tbl.rows.map((t, k) => <span key={k} className="dpl-tr"><span>{t.a}</span><span>{t.b}</span></span>)}
                        </span>
                      )}
                      {r.charts.map((c, k) => <span key={k} className="dpl-line"><Icon name="chart" size={16} /><span><b>{c.type}</b>{c.rest}</span></span>)}
                      {r.image && <span className="dpl-line"><Icon name="image" size={16} /><span>Изображение: {r.image}</span></span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      <aside className="dlp-aside p2-fade" aria-label="О плане" style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
        <section className="p2-in" style={{ padding: 24, borderRadius: 24, background: "#FFFFFF", animationDelay: "160ms" }}>
          <h2 style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", overflowWrap: "anywhere" }}>{head.title}</h2>
          {head.sub && <p style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>{head.sub}</p>}
          <p style={{ margin: "8px 0 0", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#0B1220" }}>{head.meta}</p>
        </section>

        {text && g.writer && (
          <Col prefix="dpl" label="Текст агента" title="Текст агента" hint={writerHead(g.writer)} tall open={!!open.text} onToggle={() => toggle("text")} delay={200}
            action={(
              <button type="button" className="p2-ob" onClick={edit} title="Изменить текст презентации" style={{ height: 40, padding: "0 20px" }}>
                <Icon name="pen" size={18} /><span>Изменить</span>
              </button>
            )}>
            <ol className="dlp-tx">
              {writerTexts(text).map((x) => <li key={x.n}><span className="dlp-tn">Слайд {x.n}{x.title ? ` · ${x.title}` : ""}</span><span className="dlp-tt">{x.t}</span></li>)}
            </ol>
          </Col>
        )}

        {facts.length > 0 && (
          <Col prefix="dpl" label="Цифры из текста" title="Цифры из текста" hint={plural(facts.length, "цифра", "цифры", "цифр")} open={!!open.nums} onToggle={() => toggle("nums")} delay={240}>
            <p className="dl-sub">Аналитик выписал их для сверки{fig ? ` · ${fig.text}` : ""}</p>
            <span className="dpl-chips" style={{ marginTop: 8 }}>{facts.map((f, k) => <span key={k} className="dpl-chip"><b>{f.v}</b>{f.l}</span>)}</span>
          </Col>
        )}

        {data.charts.length > 0 && (
          <Col prefix="dpl" label="Данные для диаграмм" title="Данные для диаграмм" hint={data.count} open={!!open.data} onToggle={() => toggle("data")} delay={280}>
            {data.charts.map((c, k) => (
              <div key={c.key} style={{ marginTop: k ? 16 : 0 }}>
                <span className="dpl-line"><Icon name="chart" size={16} /><span><b>{c.type}</b>{c.rest}</span></span>
                <span className="dpl-tbl" style={{ marginTop: 8 }}>
                  <span className="dpl-tr dpl-thd"><span>{c.head[0]}</span><span>{c.head[1]}</span></span>
                  {c.rows.map((t, j) => <span key={j} className="dpl-tr"><span>{t.a}</span><span>{t.b}</span></span>)}
                </span>
              </div>
            ))}
          </Col>
        )}
      </aside>
    </div>
  );
}
