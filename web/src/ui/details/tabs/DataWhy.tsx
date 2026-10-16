// «Почему так» слайда с данными (вторая ступень; V2 v105 `dlWD`, разметка `#dd-panel-why` с dA/dB): две колонки той же
// сетки, что у D-why (526 → 416 с помощником), и строка «Проверка слайда» под ними. Слева — «Данные» (профиль файла:
// файл, колонки с типом и ролью, ось времени, метрики, измерения, пропуски, выбросы, как подготовлены данные слайда) и
// «Задача» (какая, цель из текста, почему, все задачи с выбранной). Справа — «Варианты визуализации» (лучший по данным —
// первым: номер, мини-график из данных набора, название, «Выбран», довод или почему не он, «Пересобрать слайд так») и
// «Заголовок-вывод» (слайд, ключевое число, как оно посчитано, каким был бы заголовок-описание). Данные и слова —
// dataWhy.ts, эскизы — miniChart.ts, пересборка — useRebuild (шаги — rebuild.ts).
// Обновление на месте (V2 `dwRebuild`; useMorph): пересобрано или вернулось как было — вкладка та же, гаснет и
// проявляется только изменившееся («Выбран», довод, пометка, место действия, снимок, ключевое число, строки профиля),
// то, что от этого сдвинулось, доезжает transform'ом, белые подложки коробок растут вместе с содержимым; «Данные» и
// «Задача» не мигают. Место действия варианта — одно, 40 px: кнопка, строка хода (на ней фокус), спокойный отказ анализа,
// красная неудача и «Вернуть как было» (фокус на ней после пересборки) сменяют друг друга в нём. Выключенная кнопка
// говорит почему — и подсказкой, и текстом для экранного диктора (aria-describedby).
// Текст в несколько строк — стопки из двух копий (kit/Tx: x-l — левая колонка, x-r… — правая), подпись «лучший по
// данным — первым» в узкой раскладке сжимается и гаснет. Сайт: в тесной колоде (окно уже 1440) правой колонке с
// помощником 320 px — мини-графики и снимок слайда сжимаются и гаснут на месте, тексту остаётся место, заголовок
// «Варианты визуализации» мельчает transform'ом (details.css).
import { useEffect, useMemo, useRef, type CSSProperties, type ReactNode } from "react";
import { smoothScroll } from "../../../lib/motion";
import type { OutlineSlide, SlideData, Variant } from "../../../types";
import { DsIcon, DsSpin, fileIcon } from "../../create/dsKit";
import { Arc } from "../../kit/Arc";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { Tx } from "../../kit/Tx";
import { slideSrc } from "../../result/resultView";
import { StaleLine, type Refresh } from "../../shell/StaleLine";
import { dataWhyView, type DataWhyView, type DxVar } from "../dataWhy";
import type { Sigs } from "../morph";
import type { MiniColors, MiniLayers } from "../miniChart";
import { Shot } from "../parts";
import type { QTone } from "../quality";
import { busyText, REFUSED_SAME, rowAct, STALE_TEXT, takeFocus, UNDO_TEXT, type RowAct } from "../rebuild";
import type { Rebuild } from "../useRebuild";
import { MORPH_MOVE, useMorph, type Morph } from "../useMorph";
import { CheckRow } from "./CheckRow";

/** Эскиз варианта (V2 `dx-mini`): рамка, слои по порядку; `label` — что он рисует, с числами (для экранного диктора). */
export function Mini({ m, c, label }: { m: MiniLayers; c: MiniColors; label: string }) {
  return (
    <svg className="dx-mini" viewBox="0 0 160 90" role="img" aria-label={label}>
      <rect x="0.5" y="0.5" width="159" height="89" rx="10" fill="#FAFCFF" stroke="rgba(11,18,32,.08)" />
      {m.grid && <path d={m.grid} fill="none" stroke="rgba(32,32,32,.14)" strokeWidth="1" strokeLinecap="round" />}
      {m.light && <path d={m.light} fill={c.light} />}
      {m.txt && <path d={m.txt} fill="none" stroke="rgba(32,32,32,.22)" strokeWidth="3" strokeLinecap="round" />}
      {m.ringL && <path d={m.ringL} fill="none" stroke={c.light} strokeWidth="12" />}
      {m.ring2 && <path d={m.ring2} fill="none" stroke={c.main} strokeOpacity=".55" strokeWidth="12" />}
      {m.ring && <path d={m.ring} fill="none" stroke={c.main} strokeWidth="12" />}
      {m.half && <path d={m.half} fill={c.main} fillOpacity=".55" />}
      {m.main && <path d={m.main} fill={c.main} />}
      {m.sep && <path d={m.sep} fill="none" stroke="#FAFCFF" strokeWidth="1.5" strokeLinecap="round" />}
      {m.line && <path d={m.line} fill="none" stroke={c.main} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />}
      {m.acc && <path d={m.acc} fill={c.acc} />}
      {m.dash && <path d={m.dash} fill="none" stroke="rgba(32,32,32,.4)" strokeWidth="1.5" strokeDasharray="3 3" strokeLinecap="round" />}
    </svg>
  );
}

/** Подпись места действия: смена — перекрёстное затухание; внутри одной (кнопка включилась, идёт возврат) — на месте. */
export const actKey = (a: RowAct): string =>
  a.mode === "error" || a.mode === "refused" ? `${a.mode}:${a.text}` : a.mode === "done" ? `done:${a.text ?? ""}` : a.mode;

/** Что на виду во вкладке: слова и эскизы, места действия вариантов, снимок слайда, строка проверки. */
interface Shown { w: DataWhyView; acts: RowAct[]; shot: string; check: { text: string; tone: QTone | null } | null }

/** Подписи частей (обновление на месте): что изменилось — гаснет и проявляется, остальное стоит. */
function shownSigs(x: Shown): Sigs {
  const { w } = x;
  const s: Sigs = { file: `${w.file}|${w.kind}|${w.meta}`, cols: JSON.stringify([w.cols, w.more]), "t.name": w.task, "t.kinds": JSON.stringify(w.kinds), "h.shot": x.shot, "h.key": `${w.key}|${w.from}` };
  if (w.goal) s["t.goal"] = w.goal;
  if (w.taskWhy) s["t.why"] = w.taskWhy;
  if (w.plain) s["h.plain"] = w.plain;
  for (const f of w.facts) s[`f:${f.k}`] = `${f.v}|${f.tone}`;
  w.vars.forEach((v, i) => {
    const p = `v${v.k}`;
    s[`${p}.rank`] = `${v.n}|${v.on}`;
    s[`${p}.mini`] = `${v.label}|${JSON.stringify(v.mini)}`;
    s[`${p}.name`] = v.name;
    if (v.on) s[`${p}.tag`] = "on";
    if (v.why) s[`${p}.why`] = v.why;
    if (v.note) s[`${p}.note`] = v.note;
    const a = x.acts[i];
    if (a && a.mode !== "none") s[`${p}.slot`] = actKey(a);
  });
  if (x.check) s.check = `${x.check.text}|${x.check.tone}`;
  return s;
}

const shotsOf = (x: Shown) => (x.shot ? [x.shot] : []);

/** Часть, которая меняется на месте: гаснет и проявляется по своему `id`, двигается со всем (data-mv). */
function P({ m, id, as: El = "div", className, style, children }: { m: Morph<Shown>; id: string; as?: "div" | "span" | "p" | "li"; className?: string; style?: CSSProperties; children: ReactNode }) {
  return <El data-mv="" className={cls(className, m.cls(id))} style={style}>{children}</El>;
}

/** Спокойная строка у варианта: анализ этот вариант не строит или сервер сейчас занят (не неудача — без красного). */
function NoteLine({ text, title }: { text: string; title?: string }) {
  return (
    <p role="status" data-fx="note" tabIndex={-1} title={title ?? text} className="dx-nl">
      <span style={{ display: "flex", flex: "none", paddingTop: 2 }}><Icon name="info" size={16} /></span>
      <span className="dx-nlt">{text}</span>
    </p>
  );
}

/** Место действия варианта (40 px под доводом): «Пересобрать слайд так», ход, отказ, неудача, несвежий экран или
 *  «Вернуть как было» у выбранного пересборкой. Выключено — `aria-disabled` и причина текстом (aria-describedby). */
function Slot({ a, id, slide, refresh, onBuild, onUndo }: { a: RowAct; id: string; slide: number; refresh: Refresh | null; onBuild(): void; onUndo(): void }) {
  const why = (on: boolean, text: string | null) => (on && text ? <span id={id} className="p2-sr">{text}</span> : null);
  switch (a.mode) {
    case "button":
      return (
        <>
          <button type="button" className="p2-gb dx-act" aria-disabled={a.off || undefined} aria-describedby={a.off && a.why ? id : undefined}
            title={a.why ?? `Пересобрать слайд ${slide} этим вариантом`} onClick={a.off ? undefined : onBuild}>
            <Icon name="refresh" size={18} /><span>Пересобрать слайд так</span>
          </button>
          {why(a.off, a.why)}
        </>
      );
    case "busy":
      return <p className="dx-busy" role="status" data-fx="busy" tabIndex={-1}><DsSpin size={16} /><span>{busyText(slide)}</span></p>;
    case "refused":
      return <NoteLine text={a.same ? REFUSED_SAME : a.text} title={a.text} />;
    case "error":
      return <div data-fx="note" tabIndex={-1} className="dx-fl"><ErrorLine text={a.text} lines={2} /></div>;
    case "stale":
      return refresh ? <div data-fx="note" tabIndex={-1} className="dx-fl"><StaleLine r={refresh} lines={1} style={{ flex: 1 }} /></div>
        : <NoteLine text={STALE_TEXT} />;
    case "done":
      return a.text ? (
        <>
          <span data-fx="note" tabIndex={-1} className="dx-fl" style={{ flex: 1 }}><ErrorLine text={a.text} lines={2} /></span>
          <button type="button" className="p2-rbl dx-uri" aria-label="Вернуть как было" title={a.why ?? "Вернуть как было"}
            aria-disabled={a.off || undefined} aria-describedby={a.off && a.why ? id : undefined} onClick={a.off ? undefined : onUndo}><Icon name="undo" size={18} /></button>
          {why(a.off, a.why)}
        </>
      ) : (
        <>
          <button type="button" className="p2-gb dx-act" data-fx="undo" title={a.why ?? `Вернуть слайд ${slide} как было`}
            aria-disabled={a.off || a.undoing || undefined} aria-describedby={a.off && a.why ? id : undefined} aria-busy={a.undoing || undefined}
            onClick={a.off || a.undoing ? undefined : onUndo}>
            {a.undoing ? <Arc size={18} /> : <Icon name="undo" size={18} />}<span>{a.undoing ? UNDO_TEXT : "Вернуть как было"}</span>
          </button>
          {why(a.off, a.why)}
        </>
      );
  }
  return null;
}

function Var({ m, x, c, act, slide, refresh, onBuild, onUndo }: {
  m: Morph<Shown>; x: DxVar; c: MiniColors; act: RowAct; slide: number; refresh: Refresh | null; onBuild(): void; onUndo(): void;
}) {
  const p = `v${x.k}`;
  return (
    <li data-mv="" className={cls("dx-v", x.on && "dx-v-on")} data-fx={x.on ? "row" : undefined} tabIndex={x.on ? -1 : undefined} aria-current={x.on || undefined}>
      <P m={m} id={`${p}.rank`} as="span" className="dx-rank"><span aria-hidden="true">{x.n}</span></P>
      <P m={m} id={`${p}.mini`} className="dx-miw"><Mini m={x.mini} c={c} label={x.label} /></P>
      <div className="dx-vt">
        <Tx tx="x-r" className="dx-vn">{x.name}{x.on && <span className={cls("dd-tag dd-tag-b dx-on", m.cls(`${p}.tag`))}>Выбран</span>}</Tx>
        {x.why && <P m={m} id={`${p}.why`}><Tx tx="x-r" className="dx-vr">{x.why}</Tx></P>}
        {x.note && <P m={m} id={`${p}.note`}><Tx tx="x-rn" className="dx-note"><Icon name="info" size={16} /><span>{x.note}</span></Tx></P>}
        {act.mode !== "none" && (
          <P m={m} id={`${p}.slot`} className="dx-slot">
            <Slot a={act} id={`dx-why-${slide}-${x.k}`} slide={slide} refresh={refresh} onBuild={onBuild} onUndo={onUndo} />
          </P>
        )}
      </div>
    </li>
  );
}

/** Место фокуса ушло за край листа — лист (только он, не страница) доезжает до него плавно, ровно насколько нужно. */
function reveal(el: HTMLElement): void {
  const box = el.closest<HTMLElement>(".dd-scroll");
  if (!box || !el.isConnected || document.activeElement !== el) return;
  const a = el.getBoundingClientRect();
  const b = box.getBoundingClientRect();
  const pad = 24;
  const dy = a.bottom > b.bottom - pad ? a.bottom - (b.bottom - pad) : a.top < b.top + pad ? a.top - (b.top + pad) : 0;
  if (Math.abs(dy) >= 1) box.scrollBy({ top: dy, behavior: smoothScroll() });
}

/** Две колонки «Почему так» слайда `n` с данными `d` и строка проверки (обёртку сетки `dd-g dw-g` ставит Why.tsx). */
export function DataWhy({ v, n, slide, d, colors, rebuild, lock, refresh, check, onCheck }: {
  v: Variant; n: number; slide: OutlineSlide; d: SlideData; colors: MiniColors; rebuild: Rebuild;
  /** Пересобрать нельзя: над вариантом идёт чужая задача или шаблона нет (`why` — почему). */
  lock: { off: boolean; why: string | null };
  /** Презентация несвежая: строка с «Обновить» для пересобранного, которого экран ещё не показал. */
  refresh: Refresh | null;
  check: { text: string; tone: QTone | null } | null;
  onCheck(): void;
}) {
  const run = rebuild.run;
  const latest = useMemo<Shown>(() => {
    const w = dataWhyView(v, n, slide, d);
    const whyNot = (k: number) => d.options[k]?.why_not ?? null;
    return { w, acts: w.vars.map((x) => rowAct(run, n, x.k, d.chosen, w.undoable, lock, whyNot(x.k))), shot: slideSrc(v, n) ?? "", check };
  }, [v, n, slide, d, run, lock.off, lock.why, check?.text, check?.tone]); // eslint-disable-line react-hooks/exhaustive-deps
  const sigs = useMemo(() => shownSigs(latest), [latest]);
  // обёртка сетки (колонки и строка проверки — в ней): от неё меряются сдвиги
  const root = useRef<HTMLElement | null>(null);
  const m = useMorph(latest, sigs, root, shotsOf);
  const { w, acts, shot } = m.view;
  const first = latest.w.first;

  // фокус — туда, где теперь работа (строка хода, «Вернуть как было», выбранный вариант, строка отказа): один раз, когда
  // место встало на экран, и только если фокус не ушёл в другое место страницы
  useEffect(() => {
    const what = run?.focus;
    if (!what || !m.fresh || !root.current) return;
    const el = root.current.querySelector<HTMLElement>(`[data-fx="${what}"]`);
    if (!el) return;
    const panel = root.current.closest('[role="tabpanel"]');
    const now = document.activeElement;
    if (now && now !== document.body && !panel?.contains(now)) return;
    if (!takeFocus(run, n, what)) return;
    // без прыжка прокрутки: фокус — на месте, а если место ушло за край листа, лист доезжает до него плавно и ровно
    // настолько, насколько нужно (после того как ряды доехали)
    el.focus({ preventScroll: true });
    window.setTimeout(() => reveal(el), MORPH_MOVE);
  });

  const surf = <span className="dx-surf" data-surf="" aria-hidden="true" />;
  return (
    <>
      <div className="dx-col" ref={(el) => void (root.current = el?.parentElement ?? null)}>
        <section data-mv="" className="dd-box dx-box p2-in" aria-labelledby="dx-h-data" style={{ animationDelay: "0ms" }}>
          {surf}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <h3 id="dx-h-data" className="dd-h">Данные</h3>
            <span className="dd-cap">профиль файла</span>
          </div>
          <P m={m} id="file" className="dx-file">
            <span className="dx-fic" aria-hidden="true"><DsIcon name={fileIcon(w.kind)} size={20} /></span>
            <span className="dx-ft"><span className="dx-fn" title={w.file}>{w.file}</span><span className="dx-fm" title={w.meta}>{w.meta}</span></span>
          </P>
          <h4 data-mv="" className="dw-sub" style={{ marginTop: 16 }}>Колонки</h4>
          <P m={m} id="cols">
            <ul className="dx-cols" aria-label="Колонки и их типы">
              {w.cols.map((c, i) => (
                <li key={i} className="dx-cr">
                  <span className="dx-cn" title={c.name}>{c.name}</span>
                  <span className={cls("dd-tag dx-ty", c.tcls)}>{c.type}</span>
                  <span className="dx-role">{c.role}</span>
                </li>
              ))}
              {w.more > 0 && <li className="dx-cr dx-more"><span className="dx-cn">и ещё {w.more}</span></li>}
            </ul>
          </P>
          <dl data-mv="" className="dx-facts">
            {w.facts.map((f) => (
              <div key={f.k} data-mv="" className={cls("dx-fr", f.tone === "warn" && "dx-fw", f.tone === "info" && "dx-fb", m.cls(`f:${f.k}`))}>
                <dt>{f.k}</dt>
                <dd>
                  {f.tone && <span style={{ display: "flex", flex: "none", marginTop: 2 }}><DsIcon name={f.tone === "warn" ? "warn" : "info"} size={16} /></span>}
                  <Tx tx="x-l" as="span" f>{f.v}</Tx>
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section data-mv="" className="dd-box dx-box p2-in" aria-labelledby="dx-h-task" style={{ marginTop: 24, animationDelay: "40ms" }}>
          {surf}
          <h3 id="dx-h-task" className="dd-h">Задача</h3>
          <P m={m} id="t.name" as="p" className="dx-tn">{w.task}</P>
          {w.goal && <P m={m} id="t.goal" as="p" className="dx-goal"><span className="dd-tag dd-tag-b"><DsIcon name="target" size={14} />{w.goal}</span></P>}
          {w.taskWhy && <P m={m} id="t.why"><Tx tx="x-l" className="dx-tw">{w.taskWhy}</Tx></P>}
          <P m={m} id="t.kinds">
            <Tx tx="x-l" as="div" className="dx-ks">
              {w.kinds.map((k) => <span key={k.t} className={cls("dx-k", k.on && "dx-k-on")}>{k.t}</span>)}
            </Tx>
          </P>
        </section>
      </div>

      <div className="dx-col">
        <section data-mv="" className="dd-box dx-box p2-in" aria-labelledby="dx-h-vars" style={{ animationDelay: "40ms" }}>
          {surf}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <h3 id="dx-h-vars" className="dd-h dx-vh" style={{ whiteSpace: "nowrap" }}>Варианты визуализации</h3>
            <span className="hp-wo dx-capw"><span className="dd-cap">лучший по данным — первым</span></span>
          </div>
          <ol className="dx-vars">
            {w.vars.map((x, i) => (
              <Var key={x.k} m={m} x={x} c={colors} slide={n} refresh={refresh} act={acts[i] ?? { mode: "none" }}
                onBuild={() => rebuild.start(n, x.k)} onUndo={() => rebuild.undo(n, first)} />
            ))}
          </ol>
        </section>

        <section data-mv="" className="dd-box dx-box p2-in" aria-labelledby="dx-h-hl" style={{ marginTop: 24, animationDelay: "80ms" }}>
          {surf}
          <h3 id="dx-h-hl" className="dd-h">Заголовок-вывод</h3>
          <div className="dx-hl">
            <P m={m} id="h.shot" as="span" className="dx-hli">
              <Shot src={shot} alt={`Слайд ${n}: ${slide.headline}`} style={{ width: "100%", height: "100%", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} />
            </P>
            <P m={m} id="h.key" className="dx-hlt">
              {w.key && <span className="dx-key">{w.key}</span>}
              {w.from && <Tx tx="x-rh" className="dx-from">{w.from}</Tx>}
            </P>
          </div>
          {w.plain && (
            <P m={m} id="h.plain">
              <Tx tx="x-r2" className="dx-not">
                <span className="dd-tag dd-tag-n">не описание</span>
                <span>«<s>{w.plain}</s>» — это тема; в заголовке — вывод из данных</span>
              </Tx>
            </P>
          )}
        </section>
      </div>

      {m.view.check && <CheckRow check={m.view.check} onOpen={onCheck} data-mv="" fx={m.cls("check")} className="p2-in" style={{ animationDelay: "120ms" }} />}
    </>
  );
}
