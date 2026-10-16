// «Почему так» слайда с данными (вторая ступень; V2 v105 `dlWD`, разметка `#dd-panel-why` с dA/dB): две колонки той же
// сетки, что у D-why (526 → 416 с помощником). Слева — «Данные» (профиль файла: файл, колонки с типом и ролью, ось
// времени, метрики, измерения, пропуски, выбросы, как подготовлены данные слайда) и «Задача» (какая, цель из текста,
// почему, все задачи с выбранной). Справа — «Варианты визуализации» (лучший по данным — первым: номер, мини-график из
// данных слайда, название, «Выбран», довод или почему не он, «Пересобрать слайд так») и «Заголовок-вывод» (слайд,
// ключевое число, как оно посчитано, каким был бы заголовок-описание). Данные и слова — lib/dataWhy.ts, эскизы —
// lib/miniChart.ts, пересборка — useRebuild (шаги — lib/rebuild.ts). Место действия варианта — одно, 40 px: кнопка, строка хода, причина отказа и
// «Вернуть как было» сменяют друг друга перекрёстным затуханием (useSwap), ничего ниже не сдвигается. Пересобрано —
// презентация перечиталась, и колонки проявляются заново лесенкой (ключ версии у Why.tsx), как после любой правки.
// Текст в несколько строк — стопки из двух копий (kit/Tx: x-l — левая колонка, x-r… — правая), подпись «лучший по
// данным — первым» в узкой раскладке сжимается и гаснет. Сайт: в тесной колоде (окно уже 1440) правой колонке с
// помощником 320 px — мини-графики и снимок слайда сжимаются и гаснут на месте, тексту остаётся место, заголовок
// «Варианты визуализации» мельчает transform'ом (details.css).
import { useRef, type ReactNode } from "react";
import type { OutlineSlide, SlideData, Variant } from "../../../types";
import { DsIcon, DsSpin, fileIcon } from "../../create/dsKit";
import { Arc } from "../../kit/Arc";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { Tx } from "../../kit/Tx";
import { useSwap } from "../../kit/useSwap";
import { slideSrc } from "../../result/resultView";
import { StaleLine, type Refresh } from "../../shell/StaleLine";
import { dataWhyView, type DxVar } from "../../../lib/dataWhy";
import type { MiniColors, MiniLayers } from "../../../lib/miniChart";
import { Shot } from "../parts";
import { busyText, rowAct, UNDO_TEXT, type RowAct } from "../../../lib/rebuild";
import type { Rebuild } from "../useRebuild";

/** Эскиз варианта (V2 `dx-mini`): рамка, слои по порядку. */
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

/** Ключ места действия: смена ключа — перекрёстное затухание; внутри одного (кнопка включилась, идёт возврат) — без. */
const actKey = (a: RowAct): string => (a.mode === "error" ? `error:${a.text}` : a.mode === "done" ? `done:${a.text ?? ""}` : a.mode);

/** Место действия варианта (40 px под доводом): «Пересобрать слайд так», ход, причина отказа, несвежий экран или
 *  «Вернуть как было» у выбранного пересборкой. */
function Slot({ act, slide, refresh, onBuild, onUndo }: { act: RowAct; slide: number; refresh: Refresh | null; onBuild(): void; onUndo(): void }) {
  const key = actKey(act);
  const held = useRef(new Map<string, RowAct>());
  held.current.set(key, act);
  const sw = useSwap(key);
  const a = held.current.get(sw.shown) ?? act;
  let body: ReactNode = null;
  switch (a.mode) {
    case "button":
      body = (
        <button type="button" className="p2-gb dx-act" disabled={a.off} title={a.why ?? `Пересобрать слайд ${slide} этим вариантом`} onClick={onBuild}>
          <Icon name="refresh" size={18} /><span>Пересобрать слайд так</span>
        </button>
      );
      break;
    case "busy":
      body = <p className="dx-busy" role="status"><DsSpin size={16} /><span>{busyText(slide)}</span></p>;
      break;
    case "error":
      body = <ErrorLine text={a.text} lines={2} />;
      break;
    case "stale":
      body = refresh ? <StaleLine r={refresh} lines={1} style={{ flex: 1 }} /> : null;
      break;
    case "done":
      body = a.text ? (
        <>
          <span style={{ display: "flex", flex: 1, minWidth: 0 }}><ErrorLine text={a.text} lines={2} /></span>
          <button type="button" className="p2-rbl dx-uri" aria-label="Вернуть как было" title={a.why ?? "Вернуть как было"} disabled={a.off} onClick={onUndo}><Icon name="undo" size={18} /></button>
        </>
      ) : (
        <button type="button" className="p2-gb dx-act" disabled={a.off} title={a.why ?? `Вернуть слайд ${slide} как было`} aria-busy={a.undoing || undefined} onClick={a.undoing ? undefined : onUndo}>
          {a.undoing ? <Arc size={18} /> : <Icon name="undo" size={18} />}<span>{a.undoing ? UNDO_TEXT : "Вернуть как было"}</span>
        </button>
      );
      break;
  }
  if (a.mode === "none" || body === null) return null;
  return <div className={cls("dx-slot", sw.cls)}>{body}</div>;
}

function Var({ x, c, act, slide, refresh, onBuild, onUndo }: {
  x: DxVar; c: MiniColors; act: RowAct; slide: number; refresh: Refresh | null; onBuild(): void; onUndo(): void;
}) {
  return (
    <li className={cls("dx-v", x.on && "dx-v-on")}>
      <span className="dx-rank" aria-hidden="true">{x.n}</span>
      <Mini m={x.mini} c={c} label={x.label} />
      <div className="dx-vt">
        <Tx tx="x-r" className="dx-vn">{x.name}{x.on && <span className="dd-tag dd-tag-b dx-on">Выбран</span>}</Tx>
        {x.why && <Tx tx="x-r" className="dx-vr">{x.why}</Tx>}
        {x.note && <Tx tx="x-rn" className="dx-note"><Icon name="info" size={16} /><span>{x.note}</span></Tx>}
        <Slot act={act} slide={slide} refresh={refresh} onBuild={onBuild} onUndo={onUndo} />
      </div>
    </li>
  );
}

/** Две колонки «Почему так» слайда `n` с данными `d` (обёртку сетки `dd-g dw-g` и строку проверки ставит Why.tsx). */
export function DataWhy({ v, n, slide, d, colors, rebuild, lock, refresh }: {
  v: Variant; n: number; slide: OutlineSlide; d: SlideData; colors: MiniColors; rebuild: Rebuild;
  /** Пересобрать нельзя: над вариантом идёт чужая задача или шаблона нет (`why` — почему). */
  lock: { off: boolean; why: string | null };
  /** Презентация несвежая: строка с «Обновить» для пересобранного, которого экран ещё не показал. */
  refresh: Refresh | null;
}) {
  const w = dataWhyView(v, n, slide, d);
  return (
    <>
      <div className="dx-col">
        <section className="dd-box p2-in" aria-labelledby="dx-h-data" style={{ animationDelay: "0ms" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <h3 id="dx-h-data" className="dd-h">Данные</h3>
            <span className="dd-cap">профиль файла</span>
          </div>
          <div className="dx-file">
            <span className="dx-fic" aria-hidden="true"><DsIcon name={fileIcon(w.kind)} size={20} /></span>
            <span className="dx-ft"><span className="dx-fn" title={w.file}>{w.file}</span><span className="dx-fm" title={w.meta}>{w.meta}</span></span>
          </div>
          <h4 className="dw-sub" style={{ marginTop: 16 }}>Колонки</h4>
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
          <dl className="dx-facts">
            {w.facts.map((f) => (
              <div key={f.k} className={cls("dx-fr", f.tone === "warn" && "dx-fw", f.tone === "info" && "dx-fb")}>
                <dt>{f.k}</dt>
                <dd>
                  {f.tone && <span style={{ display: "flex", flex: "none", marginTop: 2 }}><DsIcon name={f.tone === "warn" ? "warn" : "info"} size={16} /></span>}
                  <Tx tx="x-l" as="span" f>{f.v}</Tx>
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="dd-box p2-in" aria-labelledby="dx-h-task" style={{ marginTop: 24, animationDelay: "40ms" }}>
          <h3 id="dx-h-task" className="dd-h">Задача</h3>
          <p className="dx-tn">{w.task}</p>
          {w.goal && <p className="dx-goal"><span className="dd-tag dd-tag-b"><DsIcon name="target" size={14} />{w.goal}</span></p>}
          {w.taskWhy && <Tx tx="x-l" className="dx-tw">{w.taskWhy}</Tx>}
          <Tx tx="x-l" as="div" className="dx-ks">
            {w.kinds.map((k) => <span key={k.t} className={cls("dx-k", k.on && "dx-k-on")}>{k.t}</span>)}
          </Tx>
        </section>
      </div>

      <div className="dx-col">
        <section className="dd-box p2-in" aria-labelledby="dx-h-vars" style={{ animationDelay: "40ms" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <h3 id="dx-h-vars" className="dd-h dx-vh" style={{ whiteSpace: "nowrap" }}>Варианты визуализации</h3>
            <span className="hp-wo dx-capw"><span className="dd-cap">лучший по данным — первым</span></span>
          </div>
          <ol className="dx-vars">
            {w.vars.map((x) => (
              <Var key={x.k} x={x} c={colors} slide={n} refresh={refresh}
                act={rowAct(rebuild.run, n, x.k, d.chosen, w.undoable, lock)}
                onBuild={() => rebuild.start(n, x.k)} onUndo={() => rebuild.undo(n)} />
            ))}
          </ol>
        </section>

        <section className="dd-box p2-in" aria-labelledby="dx-h-hl" style={{ marginTop: 24, animationDelay: "80ms" }}>
          <h3 id="dx-h-hl" className="dd-h">Заголовок-вывод</h3>
          <div className="dx-hl">
            <span className="dx-hli"><Shot src={slideSrc(v, n)} alt={`Слайд ${n}: ${slide.headline}`} style={{ width: "100%", height: "100%", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} /></span>
            <div className="dx-hlt">
              {w.key && <span className="dx-key">{w.key}</span>}
              {w.from && <Tx tx="x-rh" className="dx-from">{w.from}</Tx>}
            </div>
          </div>
          {w.plain && (
            <Tx tx="x-r2" className="dx-not">
              <span className="dd-tag dd-tag-n">не описание</span>
              <span>«<s>{w.plain}</s>» — это тема; в заголовке — вывод из данных</span>
            </Tx>
          )}
        </section>
      </div>
    </>
  );
}
