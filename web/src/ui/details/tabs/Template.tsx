// Вкладка «Шаблон» листа «Подробнее» (boards/D-template, V2 `#dd-panel-template`, модуль details `dlT`): обзор
// шаблона презентации (имя, формат, слайды, типы, шрифт, палитра — клик копирует цвет, строка над лентой говорит
// «Цвет … скопирован»), макеты (шесть, «Все N» ↔ «Свернуть»; клик открывает слой «Слайд N шаблона»), правила
// оформления и «Шрифты и поля». Данные — templateTab.ts.
// Помощник сужает колоду (V2 версии 100): полоса плотнее, макеты у́же; в тесной колоде (окно меньше 1440) уходит третий
// факт, палитра у́же, «Правила» 416 → 336 (их строки — стопки t-rule), у подписи макета слово «слайд» уходит — остаётся
// номер.
import { useLayoutEffect, useRef, useState } from "react";
import { fontStack, useTemplateFont } from "../../../lib/fonts";
import { useApp } from "../../../store";
import type { TemplateManifest } from "../../../types";
import { cls } from "../../kit/cls";
import { Icon } from "../../kit/Icon";
import { Spinner } from "../../kit/Spinner";
import { Tx } from "../../kit/Tx";
import { Col, Empty, Shot } from "../parts";
import { bandOf, copyHint, fontRows, layoutsOf, paletteOf, rulesOf } from "../templateTab";
import type { DeckManifest } from "../useDeckManifest";

export function TemplateTab({ deck }: { deck: DeckManifest }) {
  const m = deck.manifest;
  useTemplateFont(m?.tokens.typography.families[0]?.family);
  return (
    <div id="dd-panel-template" className="dtp-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-template" tabIndex={0}>
      {m ? <TemplateBody m={m} />
        : deck.state === "loading" ? (
          <p style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, padding: 24, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}><Spinner size={16} />Загружаю разбор шаблона…</p>
        ) : deck.state === "gone" ? (
          <Empty title="Шаблона больше нет в библиотеке" text="Презентация открывается и скачивается как прежде; чтобы пересобрать её, загрузите шаблон снова." />
        ) : deck.state === "offline" ? (
          <Empty title="Разбор шаблона не загрузился" text="Нет связи с сервером — откройте вкладку ещё раз, когда связь вернётся." />
        ) : (
          <Empty title="Разбор шаблона не загрузился" text="Сервер не смог отдать разбор шаблона — откройте вкладку ещё раз, чтобы попросить снова." />
        )}
    </div>
  );
}

function TemplateBody({ m }: { m: TemplateManifest }) {
  const { dispatch } = useApp();
  const [all, setAll] = useState(false);
  const [fonts, setFonts] = useState(false);
  const [copied, setCopied] = useState<{ hex: string; ok: boolean; k: number } | null>(null);
  const band = bandOf(m);
  const pal = paletteOf(m);
  const rules = rulesOf(m);
  const rows = fontRows(m);
  const lays = layoutsOf(m, all);
  // ширина слова «слайд» в подписи макета (`--ctw`): в тесной колоде с помощником оно сжимается от неё до нуля
  const laysRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const box = laysRef.current;
    const w = box?.querySelector(".dtp-lsw");
    if (!box || !w) return;
    const set = () => {
      const r = document.createRange();
      r.selectNodeContents(w);
      box.style.setProperty("--ctw", `${Math.ceil(r.getBoundingClientRect().width)}px`);
    };
    set();
    void document.fonts?.ready.then(set);
  }, [lays.length]);
  const copy = (hex: string) => {
    const k = (copied?.k ?? 0) + 1;
    const done = (ok: boolean) => setCopied({ hex, ok, k });
    if (!navigator.clipboard?.writeText) return done(false);
    navigator.clipboard.writeText(hex).then(() => done(true), () => done(false));
  };

  return (
    <>
      <section className="dtp-box dtp-band p2-in" aria-label="Обзор шаблона" style={{ animationDelay: "120ms" }}>
        <h2 className="dtp-name" title={band.name}>{band.name}</h2>
        <dl style={{ display: "contents" }}>
          {band.facts.map((f, i) => <div key={f.l} className={cls("dtp-tile dtp-fact", i === 2 && "dtp-f3")}><dt>{f.l}</dt><dd>{f.v}</dd></div>)}
        </dl>
        <div className="dtp-tile dtp-font">
          <span className="dtp-aa" aria-hidden="true" style={{ fontFamily: fontStack(band.font) }}>Аа</span>
          <span style={{ minWidth: 0 }}><span className="dtp-fn" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{band.font ?? "не определён"}</span><span className="dtp-fl">основной шрифт</span></span>
        </div>
        <div className="dtp-tile dtp-pal">
          <div className="dtp-palh">
            <span className="dtp-pall" id="dtp-pal-l">Палитра</span>
            <span className="dtp-palhint" aria-live="polite">
              <span key={copied?.k ?? 0} className={cls(copied && "p2-in")} style={{ display: "block", color: copied && !copied.ok ? "#DC2626" : undefined }}>{copyHint(copied)}</span>
            </span>
          </div>
          <div className="dtp-rib" role="group" aria-labelledby="dtp-pal-l">
            {pal.map((c) => <button key={c.hex} type="button" className="dtp-sw" style={{ background: c.hex }} title={c.tip} aria-label={c.tip} onClick={() => copy(c.hex)} />)}
          </div>
        </div>
      </section>

      <div className="dtp-g" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gap: 24, alignItems: "start", marginTop: 16 }}>
        <section className="dtp-box p2-in" aria-labelledby="dtp-lay" style={{ animationDelay: "160ms" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 40 }}>
            <h2 id="dtp-lay" className="dtp-h2" style={{ whiteSpace: "nowrap" }}>Макеты <span style={{ color: "#5A6272" }}>{m.patterns.length}</span></h2>
            {m.patterns.length > 6 && (
              <button type="button" className="p2-gb" onClick={() => setAll(!all)} aria-expanded={all} style={{ marginRight: -16 }}>
                <span>{all ? "Свернуть" : `Все ${m.patterns.length}`}</span>
                <Icon name="chevron-down" size={18} className={cls("df-chev", all && "df-chev-up")} />
              </button>
            )}
          </div>
          <div ref={laysRef} className="dtp-lays">
            {lays.map((l) => (
              <div key={l.key} className="p2-in" style={{ animationDelay: l.delay }}>
                <button type="button" className="p2-card" onClick={() => dispatch({ type: "pattern", n: l.n })} aria-label={`Слайд ${l.n} шаблона: ${l.kind}`}>
                  <span className="p2-cover" style={{ height: "auto" }}>
                    <Shot src={l.img} alt="" style={{ width: "100%", aspectRatio: "16 / 9", borderRadius: 16, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} />
                  </span>
                  <span className="dtp-lr" style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, height: 20, marginTop: 8 }}>
                    <span className="dtp-lk" style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{l.kind}</span>
                    <span style={{ flex: "none", fontSize: 12, fontWeight: 600, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}><span className="dtp-lsw">слайд{"\u00A0"}</span>{l.n}</span>
                  </span>
                </button>
              </div>
            ))}
          </div>
        </section>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {rules.length > 0 && (
            <section className="dtp-box p2-in" aria-labelledby="dtp-rules" style={{ animationDelay: "200ms" }}>
              <h2 id="dtp-rules" className="dtp-h2">Правила оформления</h2>
              <ul className="dtp-rules">{rules.map((r) => <li key={r} className="dtp-rule"><Tx tx="t-rule" as="span" wrap="span" f>{r}</Tx></li>)}</ul>
            </section>
          )}
          {rows.length > 0 && (
            <Col prefix="dtp" label="Шрифты и поля" title="Шрифты и поля" hint="для дизайнера" open={fonts} onToggle={() => setFonts(!fonts)} delay={240} bodyTx="t-cb">
              <span className="dpl-tbl">{rows.map((r) => <span key={r.a} className="dpl-tr"><span>{r.a}</span><span>{r.b}</span></span>)}</span>
            </Col>
          )}
        </div>
      </div>
    </>
  );
}
