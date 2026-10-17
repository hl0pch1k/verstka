// Вкладка «Файлы» листа «Подробнее» (boards/D-files, V2 `#dd-panel-files`, модуль details `dlF`): файлы каждого
// варианта (PowerPoint, PDF, Веб), паспорт запуска, время по этапам, итог проверки, автоисправления и свёрнутое «Для
// разработчиков» (FilesDev). Данные — files.ts.
// Помощник сужает колоду (V2 версии 100): те же две колонки, правая 50 % → 44 %, кнопки файлов плотнее, «на экране» и
// бейдж «Паспорта» сжимаются и гаснут, у плиток итога значки сжимаются и гаснут, длинная подпись — многоточием.
// Тесная колода (окно у́же 1440): дорожки плиток итога — по замеру подписей (tileLayout), подписи — целиком.
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { plural } from "../../../lib/utils";
import { useApp } from "../../../store";
import type { Generation, Variant } from "../../../types";
import { cls } from "../../kit/cls";
import { Icon } from "../../kit/Icon";
import { checkTiles, fileRows, fixRowsOf, passport, stagesOf, type Fact, type Tile } from "../files";
import { slideTag } from "../quality";
import { FilesDev } from "./FilesDev";
import { Tx } from "../../kit/Tx";
import { SHEET_PAD } from "../../deck/layout";
import { filesCols, filesVars, SheetCtx, type FilesCols, type SheetMorph } from "../sheetMorph";
import type { DeckManifest } from "../useDeckManifest";

const H = { margin: 0 } as const;
/** Группа факта — клетка сетки «Паспорта»: встаёт по верху своей клетки (высота стопки на ходу — своя). */
const FACT = { alignSelf: "start", minWidth: 0 } as const;

/** То, что нужно замеру полосы прокрутки (часть HTMLElement). */
export type Scroller = Pick<HTMLElement, "offsetWidth" | "clientWidth"> & { checkVisibility?(): boolean };

/** Ширина полосы прокрутки вкладки (обычная — 15 px, накладная — 0) или `null`, когда замер неверен: содержимое вкладки
 *  не рисуется — невыбранная вкладка, догаснув, пропускает его (content-visibility: hidden у `#dd-panel-files`,
 *  layers.css), и полосы у неё нет, хотя содержимое длиннее, — или у неё нет рамки (display: none, предок с
 *  content-visibility: hidden). Иначе каждое скрытие и показ «Файлов» меняли бы полосу 15 → 0 → 15, а с ней дорожки
 *  сетки (--dfw, --dfn) и замер стопок «Паспорта». Смонтированная скрытой, пока лист ещё рисует все вкладки
 *  (DetailsSheet: в свободное время), меряется сразу — её содержимое рисуется. */
export function scrollbarOf(el: Scroller, contentVisibility: string): number | null {
  if (contentVisibility === "hidden" || el.checkVisibility?.() === false) return null;
  return Math.max(0, el.offsetWidth - el.clientWidth);
}

/** Факты «Паспорта запуска» (`dl`: группы `div` из `dt` и `dd`). Факт — стопка из двух копий (kit/Tx, `f-fact`): в
 *  каждой и название, и значение (на ходу помощника ни то ни другое не переносится заново, копия проявляется целиком).
 *  Стопка — внутри `dd`; название в копиях скрыто от чтения с экрана, читается `dt` (p2-sr) — каждое по разу. */
export function PassportFacts({ facts, hpd }: { facts: Fact[]; hpd: number }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "16px 24px", margin: "16px 0 0" }}>
      {facts.map((x) => (
        <div key={x.k} style={FACT}>
          <dt className="p2-sr">{x.k}</dt>
          <dd style={H}>
            <Tx tx="f-fact" as="div" hpd={hpd} title={x.title}>
              <div className="df-fk" aria-hidden="true">{x.k}</div>
              <div className={cls("df-fv", x.dim && "df-dim")}>{x.v}</div>
            </Tx>
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ── «Итог проверки» в тесной колоде: дорожки плиток по замеру подписей ───────────────────────────────────────────────
// V2 делит сетку плиток поровну (шесть дорожек: три плитки по две, две по три) и в узкой раскладке сокращает длинную
// подпись многоточием («Предупр…» при 1440). В тесной колоде так обрезались бы и «Ошибки», «Заметки», «По картинке»,
// «Автоисправления» (при 1280 в узкой — по 37 и 78 px), а при 1280 без помощника — «Предупреждения». Здесь дорожки —
// по естественной ширине подписей: каждой плитке — сколько нужно её подписи и числу, остаток — «Предупреждениям» (им
// целиком не хватает места и у V2). Где обе подписи второго ряда в строку не встают, переносится та, что переносится
// («Авто-/исправления»: стопка f-tl, узкая копия в две строки). Дорожки — доли (fr) из px покоя: сетка в обеих раскладках
// заполняет свою карточку, а доли идут вместе с колонкой (details.css, --dtw / --dtn).

/** Поля плиток, зазор сетки и место значка подписи (16 + зазор 8): в широкой раскладке — как у V2, в узкой тесной —
 *  плотнее (details.css: поля 16 → 12, зазор 12 → 8, значок сжимается и гаснет). */
export const TILE_WIDE = { pad: 16, gap: 12, ico: 24 } as const;
export const TILE_NARROW = { pad: 12, gap: 8, ico: 0 } as const;
type TileBox = { readonly pad: number; readonly gap: number; readonly ico: number };

/** Естественные ширины плитки, px: подпись в строку; её самый широкий кусок в две строки (по пробелу и мягкому переносу,
 *  `null` — не переносится); число с подписью («— выключена», широкая раскладка) и без неё (в узкой она гаснет). */
export interface TileNat { label: number; piece: number | null; value: number; valueN: number }

/** Дорожки сетки плиток (шесть, px покоя) и какие подписи в этой раскладке — в две строки. */
export interface TileTrack { cols: number[]; wrap: boolean[] }

/** Запас к замеру: подпись встаёт без многоточия и при долях пикселя. */
const SAFE = 1;
/** Плитки итога (files.ts, checkTiles): с какой дорожки и на сколько. */
const AT = [0, 2, 4, 0, 3];
const SPANS = [2, 2, 2, 3, 3];
/** Мягкий перенос в длинной подписи: узкая копия переносит по нему, в строку его не видно. */
const HY: Record<string, string> = { Автоисправления: "Авто­исправления" };
export const hyphenated = (label: string): string => HY[label] ?? label;

/** Куски подписи в две строки: по пробелам и мягким переносам (кусок перед мягким переносом — с дефисом). */
export function labelPieces(label: string): string[] {
  return hyphenated(label).split(" ").flatMap((w) => {
    const p = w.split("­");
    return p.map((x, i) => (i < p.length - 1 ? `${x}-` : x));
  });
}

/** Ширина плитки `i` по дорожкам. */
export function tileWidth(cols: number[], gap: number, i: number): number {
  return cols.slice(AT[i], AT[i] + SPANS[i]).reduce((s, c) => s + c, 0) + (SPANS[i] - 1) * gap;
}

/** Дорожки сетки плиток шириной `width` (px): поровну, если так встают все подписи; иначе — по их ширине. Первый ряд:
 *  «Ошибки» и «Заметки» — поровну и целиком, «Предупреждения» — остаток (не больше, чем им нужно целиком). Второй:
 *  «По картинке» и «Автоисправления» — поровну, если обе в строку; иначе одной — сколько нужно, другой — остаток; в
 *  строку не встают обе — в две строки та, что переносится. `null` — не помещается и так (окно у́же 1280). */
export function tileTrack(width: number, nat: TileNat[], box: TileBox, narrow: boolean): TileTrack | null {
  if (nat.length !== SPANS.length || !(width > 0)) return null;
  const { pad, gap, ico } = box;
  const val = (i: number) => (narrow ? nat[i].valueN : nat[i].value);
  const one = (i: number) => Math.max(nat[i].label + ico, val(i)) + 2 * pad + SAFE;
  const two = (i: number) => {
    const p = nat[i].piece;
    return p === null ? Infinity : Math.max(p + ico, val(i)) + 2 * pad + SAFE;
  };
  const free1 = width - 2 * gap;
  let a = free1 / 3;
  if (a < one(0) || a < one(1) || a < one(2)) a = Math.max(one(0), one(2), (free1 - one(1)) / 2);
  if (free1 - 2 * a < val(1) + 2 * pad) return null;
  const free2 = width - gap;
  let d = free2 / 2;
  const wrap = SPANS.map(() => false);
  if (d < one(3) || d < one(4)) {
    if (one(3) + one(4) <= free2) d = d < one(3) ? one(3) : free2 - one(4);
    else if (one(3) + two(4) <= free2) [d, wrap[4]] = [one(3), true];
    else if (two(3) + one(4) <= free2) [d, wrap[3]] = [free2 - one(4), true];
    else if (two(3) + two(4) <= free2) [d, wrap[3], wrap[4]] = [(free2 + two(3) - two(4)) / 2, true, true];
    else return null;
  }
  const t3 = d - a - gap;
  const t4 = free2 - d - a - gap;
  if (t3 < 0 || t4 < 0) return null;
  const h = (a - gap) / 2;
  return { cols: [h, h, t3, t4, h, h], wrap };
}

const equalTrack = (width: number, gap: number): TileTrack => ({ cols: Array.from({ length: 6 }, () => (width - 5 * gap) / 6), wrap: SPANS.map(() => false) });
const r3 = (x: number) => Math.round(x * 1000) / 1000;

export interface TileLayout {
  /** grid-template-columns в широкой и узкой раскладке (доли из px покоя). */
  dtw: string;
  dtn: string;
  /** Подпись в две строки в узкой раскладке — стопка: на сколько её клетка у́же в узкой (`--hpd`); `null` — в строку. */
  hpd: (number | null)[];
}

/** Дорожки плиток в обеих раскладках тесной колоды по ширине сетки (`grid`, px) и замеру. Широкая раскладка подписи не
 *  переносит: не встают в строку — поровну, как у V2. */
export function tileLayout(grid: { wide: number; narrow: number }, nat: TileNat[]): TileLayout | null {
  const w0 = tileTrack(grid.wide, nat, TILE_WIDE, false);
  const wide = w0 && !w0.wrap.some(Boolean) ? w0 : equalTrack(grid.wide, TILE_WIDE.gap);
  const nar = tileTrack(grid.narrow, nat, TILE_NARROW, true) ?? equalTrack(grid.narrow, TILE_NARROW.gap);
  if ([...wide.cols, ...nar.cols].some((c) => !(c >= 0))) return null;
  const fr = (t: TileTrack) => t.cols.map((c) => `minmax(0, ${r3(c)}fr)`).join(" ");
  // клетка подписи: плитка без полей и (в широкой) без значка с зазором
  const cell = (t: TileTrack, b: TileBox, i: number) => tileWidth(t.cols, b.gap, i) - 2 * b.pad - b.ico;
  const hpd = nar.wrap.map((on, i) => (on ? r3(cell(wide, TILE_WIDE, i) - cell(nar, TILE_NARROW, i)) : null));
  return { dtw: fr(wide), dtn: fr(nar), hpd };
}

/** Ширина сетки плиток в обеих раскладках: карточка «Итог проверки» справа (с «Временем по этапам» она четвёртая) или
 *  слева (третья), без полей карточки (24 + 24). */
export function tilesGrid(m: SheetMorph, cols: FilesCols, bar: number, right: boolean): { wide: number; narrow: number } | null {
  if (!(cols.wide > 0) || !(m.inner > 0)) return null;
  const col = right ? cols : { wide: m.wrap - SHEET_PAD - bar - 16 - cols.wide, narrow: m.inner - bar - 16 - cols.narrow };
  return { wide: col.wide - 48, narrow: col.narrow - 48 };
}

// Замер — по шрифтам плиток (details.css: .df-tl, .df-tv, .df-tsub) на холсте: не читает раскладку, поэтому идёт при
// отрисовке, и первая же отрисовка — с дорожками (без хода от «поровну»); после загрузки шрифтов — заново.
const FONT_LABEL = "600 13px Manrope, system-ui, sans-serif";
const FONT_VALUE = "600 32px Unbounded, Manrope, sans-serif";
/** letter-spacing числа: −0.03em от 32 px. */
const VALUE_LS = "-0.96px";
let canvas: CanvasRenderingContext2D | null | undefined;
function textWidth(s: string, font: string, ls = "0px"): number {
  canvas ??= typeof document === "undefined" ? null : document.createElement("canvas").getContext("2d");
  if (!canvas) return 0;
  canvas.font = font;
  canvas.letterSpacing = ls;
  return canvas.measureText(s).width;
}

/** Естественные ширины плитки (`measure` — ширина строки шрифтом: подпись, число, подпись числа). */
export function tileNat(t: Pick<Tile, "label" | "v" | "sub">, measure: (s: string, kind: "label" | "value" | "sub") => number): TileNat {
  const pieces = labelPieces(t.label);
  const v = measure(t.v, "value");
  return {
    label: measure(t.label, "label"),
    piece: pieces.length > 1 ? Math.max(...pieces.map((p) => measure(p, "label"))) : null,
    value: t.sub ? v + 8 + measure(t.sub, "sub") : v,
    valueN: v,
  };
}

const measureCanvas = (s: string, kind: "label" | "value" | "sub") => (kind === "value" ? textWidth(s, FONT_VALUE, VALUE_LS) : textWidth(s, FONT_LABEL));

/** Шрифты догрузились — замер плиток заново. */
function useFontsTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (typeof document === "undefined" || !document.fonts || document.fonts.status === "loaded") return;
    let off = false;
    void document.fonts.ready.then(() => !off && setTick((x) => x + 1));
    return () => {
      off = true;
    };
  }, []);
  return tick;
}

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
  // дорожки в px — от ширины сетки: лист без полосы прокрутки вкладки (обычная полоса — 15 px, накладная — 0); пока
  // вкладка скрыта и не рисуется, замер неверен — остаётся последний настоящий (scrollbarOf)
  const scroller = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState(0);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => {
      const b = scrollbarOf(el, getComputedStyle(el).contentVisibility);
      if (b !== null) setBar(b);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const sheet = useContext(SheetCtx);
  const cols = filesCols(sheet, bar);
  const fact = cols.fact;
  // тесная колода: дорожки плиток итога по замеру подписей
  const fonts = useFontsTick();
  const tilesKey = check.tiles.map((t) => `${t.label}|${t.v}|${t.sub}`).join("\n");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- плитки — по их тексту (tilesKey), шрифты — по fonts
  const nat = useMemo(() => (sheet.tight ? check.tiles.map((t) => tileNat(t, measureCanvas)) : null), [tilesKey, sheet.tight, fonts]);
  const tilesW = sheet.tight ? tilesGrid(sheet, cols, bar, !!stages) : null;
  const lay = nat && tilesW ? tileLayout(tilesW, nat) : null;

  return (
    <div ref={scroller} id="dd-panel-files" className="df-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-files" tabIndex={0} style={{ flex: 1, minHeight: 0, padding: "24px 0", overflowY: "auto", borderRadius: 24 }}>
      <div className="df-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16, ...filesVars(cols) } as CSSProperties}>
        <section className="df-card p2-in" aria-labelledby="df-h1" style={{ animationDelay: "280ms" }}>
          <div className="df-hd"><h2 id="df-h1" className="df-h">Файлы</h2><span className="df-badge">{plural(n, "вариант", "варианта", "вариантов")}</span></div>
          <ul style={{ display: "flex", flexDirection: "column", gap: 16, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
            {files.map((f) => (
              <li key={f.key} className={cls("df-row", f.cur && "df-row-on")} aria-current={f.cur || undefined} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 64, padding: "0 12px 0 16px", borderRadius: 16 }}>
                <div className="df-ft" style={{ minWidth: 0 }}>
                  <p style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap" }}>
                    <span className="df-t" title={f.title}>{f.title}</span>{f.score !== null && <span className="df-score" title={f.tip}>{f.score}</span>}{f.cur && <span className="df-now hp-wo">на экране</span>}
                  </p>
                  <p className="df-fn" title={f.file} style={{ margin: 0, fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.file}</p>
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
          {pass.facts.length ? <PassportFacts facts={pass.facts} hpd={fact} />
            : <p className="df-fk" style={{ marginTop: 16 }}>У этого варианта нет паспорта — соберите презентацию заново.</p>}
        </section>

        {stages && (
          <section className="df-card p2-in" aria-labelledby="df-h3" style={{ animationDelay: "360ms" }}>
            <div className="df-hd"><h2 id="df-h3" className="df-h">Время по этапам</h2><span className="df-badge" title={stages.title}>{stages.total}</span></div>
            <ul style={{ display: "flex", flexDirection: "column", gap: 12, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
              {stages.rows.map((s) => (
                <li key={s.name} className="df-st" title={s.tip} style={{ display: "grid", gridTemplateColumns: "216px minmax(0, 1fr) 48px", alignItems: "center", gap: 16, height: 24 }}>
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
          <div className="df-tiles" style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 12, marginTop: 16, ...(lay && { "--dtw": lay.dtw, "--dtn": lay.dtn }) } as CSSProperties}>
            {check.tiles.map((t, i) => (
              <div key={t.label} className={cls("df-tile", t.cls)} style={{ gridColumn: `span ${t.span}` }}>
                <p className="df-tl">
                  <Icon name={t.icon} size={16} className="hq-ico" />
                  {lay?.hpd[i] != null ? <Tx tx="f-tl" as="span" wrap="span" f hpd={lay.hpd[i]!}>{hyphenated(t.label)}</Tx> : <span>{t.label}</span>}
                </p>
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
            <span className="df-ct" style={{ flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", color: "#0B1220" }}>Для разработчиков</span>
            <span className="df-cd" style={{ minWidth: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>JSON плана и проверки · навыки и агенты · журнал агента · сравнение запусков</span>
            <span className="df-csp" style={{ flex: 1, minWidth: 0 }} />
            <span className="df-cc" aria-hidden="true"><Icon name="chevron-down" size={18} className={cls("df-chev", dev && "df-chev-up")} /></span>
          </button>
          {dev && <FilesDev g={g} v={v} />}
        </section>
      </div>
    </div>
  );
}
