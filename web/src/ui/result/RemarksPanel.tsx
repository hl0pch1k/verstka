// Панель режима «Замечания» (R-remarks, R-fixing, R-fixed; V2 `rm-col`): встаёт на место правой колонки (колонка
// гаснет 240 мс, панель проявляется), выключение — наоборот. Шапка «Слайд 3 · 3 замечания»; ниже — один из видов:
//  · rem  — список замечаний слайда (выбранное — в обводке своего цвета), «Ваши правки» и «Исправить слайд» (пока
//           сервер не ответил на запуск — кнопка занята, вид ещё не меняется: отказ не мигает карточкой хода);
//  · fix  — приглушённые ряды и карточка хода «Агент исправляет слайд»: часы, полоса, шаги Критик → Дизайнер → Вёрстка
//           → Проверка по событиям задачи, «Готовлю превью слайда», пожелание;
//  · done — ряды «Исправлено» и итог: «N из M», оценка было → стало, какие слайды ещё изменились, «Вернуть как было»;
//  · none — «Замечаний нет».
// В rem и none — ещё «Вернуть как было», если последнее изменение варианта — исправление этого слайда, а итога на
// странице нет (перезагрузка, возврат на экран).
// Содержимое вида входит лесенкой p2-in по 40 мс; панель, которая только что появилась, сдвигает лесенку на 200 мс
// (V2 `rmD`) и не ведёт свои поля отдельно (V2 `rmRide`).
// Ширина панели — колонки того вида, что на месте (416 полного, 320 компактного при открытом помощнике): при открытии и
// закрытии помощника содержимое панели гаснет 120 мс, панель меняет ширину (`data-fit`) невидимой и содержимое
// проявляется 240 мс (useSwap) — размер не меняется на глазах, пока колонка сетки едет.
import { useState, type ReactNode } from "react";
import { Arc } from "../kit/Arc";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { cls } from "../kit/cls";
import { useSwap } from "../kit/useSwap";
import { StaleLine, type Refresh } from "../shell/StaleLine";
import type { FixStep, FixSummary, StepState } from "./fix";
import { panelFit } from "./compact";
import { countText, type Remark } from "./marks";

export type PanelView = "rem" | "fix" | "done" | "none";
export type PanelRow = Remark & { done?: boolean };

/** Строка у кнопки. `refresh` — исправление сохранено, а презентация на экране не перечиталась: строка с «Обновить». */
export interface PanelLine { tone: "error" | "info"; text: string; refresh?: Refresh | null }

export interface RemarksPanelProps {
  /** Режим включён (панель видна) или гаснет. */
  shown: boolean;
  /** Когда панель появилась (мс): содержимое, вошедшее вместе с ней, не ведёт лесенку отдельно. */
  since: number;
  /** Помощник открыт: панель стоит в узкой колонке компактного вида (320), а не полного (416). */
  helper: boolean;
  n: number;
  view: PanelView;
  rows: PanelRow[];
  sel: number;
  onSel(i: number): void;
  wish: string;
  onWish(text: string): void;
  onFix(): void;
  /** «Исправить слайд» нажато, сервер ещё не ответил: кнопка занята (вид сменится, только когда задача принята). */
  fixBusy: boolean;
  /** Почему «Исправить слайд» и «Вернуть как было» сейчас не начнутся (идёт работа над вариантом); null — начнутся. */
  fixOff: string | null;
  /** «Вернуть как было» без итога на странице: последнее изменение варианта — исправление этого слайда. `refresh` —
   *  вернулось, а презентация на экране не перечиталась (строка с «Обновить» вместо `error`). */
  revert: { onRevert(): void; busy: boolean; error: string | null; refresh?: Refresh | null } | null;
  /** Строка у кнопки: неудача или почему слайд остался прежним. */
  line: PanelLine | null;
  /** На других слайдах замечания есть (вид «Замечаний нет» говорит про числа на миниатюрах). */
  elsewhere: boolean;
  progress: { clock: string; value: number; steps: FixStep[]; preview: StepState; wish: string } | null;
  done: {
    summary: FixSummary;
    onShow(): void;
    onUndo(): void;
    /** «Вернуть как было» есть, только пока исправление — последнее изменение варианта. */
    canUndo: boolean;
    undoBusy: boolean;
    undoError: string | null;
    /** Вернули как было, а презентация на экране не перечиталась: строка с «Обновить» на месте кнопки. */
    refresh?: Refresh | null;
  } | null;
}

const H2 = { margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#0B1220", whiteSpace: "nowrap" } as const;
const LIST = { display: "flex", flexDirection: "column", gap: 8, flex: 1, minHeight: 0, margin: "16px -4px 0", padding: "4px 4px 24px", listStyle: "none", overflowY: "auto" } as const;

export function RemarksPanel(p: RemarksPanelProps) {
  const open = p.rows.filter((r) => !r.done).length;
  // раскладка (ширина) панели меняется в подмене: содержимое в обёртке `.rm-body` гаснет, панель встаёт в новую ширину
  const fit = useSwap(panelFit(p.helper));
  return (
    <aside className={cls("rm-col p2-in", p.shown ? "rm-col-on" : "rm-out")} data-fit={fit.shown} aria-labelledby="rk-h" aria-hidden={p.shown ? undefined : true}
      style={{ animationDelay: "200ms" }}>
      <div className={cls("rm-body", fit.cls)}>
        <div style={{ display: "flex", alignItems: "center", height: 40, flex: "none" }}>
          <h2 id="rk-h" style={H2}>
            Слайд {p.n}{" "}
            <span style={{ marginLeft: 4, fontFamily: "'Manrope',sans-serif", fontSize: 15, fontWeight: 600, lineHeight: "24px", letterSpacing: 0, color: "#5A6272" }}>
              · {p.view === "fix" ? countText(p.rows.length) : countText(open)}
            </span>
          </h2>
        </div>
        <Body key={`${p.n}:${p.view}`} {...p} />
      </div>
    </aside>
  );
}

/** Содержимое вида; новое (другой слайд, другой вид) входит заново. */
function Body(p: RemarksPanelProps) {
  // вошло вместе с панелью — лесенка ждёт панель (+200 мс), поля не ведутся отдельно
  const [fresh] = useState(() => Date.now() - p.since < 300);
  const d = (ms: number) => `${(fresh ? 200 : 0) + ms}ms`;
  const ride = fresh ? undefined : "p2-in";
  if (p.view === "fix") return <Fixing p={p} d={d} ride={ride} />;
  if (p.view === "done" && p.done) return <Done p={p} d={d} />;
  if (p.view === "none" || !p.rows.length) {
    return (
      <>
        <div className={ride} role="status" style={{ marginTop: 16, flex: "none" }}>
          <div className="rd-row">
            <span className="rd-dot rd-ok" aria-hidden="true"><Icon name="check" size={12} /></span>
            <span style={{ display: "block", minWidth: 0 }}>
              <span className="rd-rt">Замечаний нет</span>
              <span className="rd-rx">{p.elsewhere ? "Числа на миниатюрах показывают, на каких слайдах они есть." : "На слайдах этого варианта замечаний не осталось."}</span>
            </span>
          </div>
        </div>
        {p.revert && <Revert p={p} ride={ride} />}
      </>
    );
  }
  return <Remarks p={p} d={d} ride={ride} />;
}

function Line({ line }: { line: PanelLine }) {
  if (line.refresh) return <StaleLine r={line.refresh} style={{ marginTop: 16, flex: "none" }} />;
  if (line.tone === "error") return <ErrorLine text={line.text} lines={2} style={{ marginTop: 16, flex: "none" }} />;
  return (
    <p role="status" title={line.text}
      style={{ display: "flex", alignItems: "flex-start", gap: 8, margin: "16px 0 0", flex: "none", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>
      <span style={{ display: "flex", flex: "none", paddingTop: 2, color: "#2563EB" }}><Icon name="info" size={16} /></span>
      <span style={{ minWidth: 0, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{line.text}</span>
    </p>
  );
}

function Remarks({ p, d, ride }: { p: RemarksPanelProps; d(ms: number): string; ride?: string }) {
  return (
    <>
      <ol className="rk-list p2-fade" aria-label={`Замечания к слайду ${p.n}`} style={LIST}>
        {p.rows.map((r, j) => {
          const on = j === p.sel;
          return (
            <li key={r.id} className="p2-in" style={{ flex: "none", animationDelay: d(40 + Math.min(j, 6) * 40) }}>
              <button type="button" className={cls("rk-row", on && `rk-on-${r.tone}`)} aria-pressed={on} onClick={() => p.onSel(j)}>
                <span className={`rk-dot rk-${r.tone}`} aria-hidden="true">{r.n}</span>
                <span style={{ display: "block", minWidth: 0 }}>
                  <span className="rk-rt">{r.title}</span>
                  {r.text && <span className="rk-rx" title={r.text}>{r.text}</span>}
                  <span className={`rk-rl rk-c-${r.tone}`}><Icon name={r.icon} size={16} />{r.label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {p.line && <Line line={p.line} />}
      <label className={ride} style={{ display: "block", marginTop: 16, flex: "none" }}>
        <span className="p2-sr">Ваши правки к слайду {p.n}</span>
        <input type="text" className="p2-inp rk-inp" maxLength={500} value={p.wish} placeholder="Ваши правки, например: покажи этапами"
          onChange={(e) => p.onWish(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (!p.fixOff) p.onFix();
            }
          }} />
      </label>
      <button type="button" className={cls("p2-cta rm-cta", ride)} onClick={p.onFix} disabled={!p.fixBusy && !!p.fixOff} title={p.fixBusy ? "Отправляю слайд агенту…" : p.fixOff ?? undefined}
        aria-busy={p.fixBusy || undefined} aria-disabled={p.fixBusy || undefined} style={{ width: "100%", marginTop: 8, flex: "none" }}>
        {p.fixBusy ? <Spinner size={20} /> : <Icon name="wand" size={20} />}
        <span>Исправить слайд</span>
      </button>
      {p.revert && <Revert p={p} ride={ride} />}
    </>
  );
}

/** «Вернуть как было» исправления, сделанного раньше (итога на странице нет): тот же «верни как было», что в итоге. */
function Revert({ p, ride }: { p: RemarksPanelProps; ride?: string }) {
  const r = p.revert!;
  const off = r.busy ? null : p.fixOff;
  return (
    <>
      <button type="button" className={cls("p2-ob", ride)} onClick={r.onRevert} disabled={!!off} aria-busy={r.busy || undefined} aria-disabled={r.busy || undefined}
        title={r.busy ? "Возвращаю слайд, каким он был до исправления…" : off ?? "Вернуть слайд, каким он был до последнего исправления"}
        style={{ width: "100%", marginTop: 8, flex: "none", cursor: r.busy ? "progress" : undefined }}>
        {r.busy ? <Arc size={18} /> : <Icon name="undo" size={18} />}
        <span>Вернуть как было</span>
      </button>
      {r.refresh ? <StaleLine r={r.refresh} style={{ marginTop: 8, flex: "none" }} />
        : r.error && <ErrorLine text={r.error} lines={2} style={{ marginTop: 8, flex: "none" }} />}
    </>
  );
}

const STEP_SR: Record<StepState, string> = { done: "готово: ", act: "сейчас: ", wait: "ждёт: " };

function Fixing({ p, d, ride }: { p: RemarksPanelProps; d(ms: number): string; ride?: string }) {
  const g = p.progress;
  return (
    <>
      <ol className="rf-list p2-fade" aria-label={`Замечания к слайду ${p.n} — агент их исправляет`} style={LIST}>
        {p.rows.map((r) => (
          <li key={r.id} className={ride} style={{ flex: "none" }}>
            <div className="rf-row">
              <span className={`rf-dot rf-${r.tone}`} aria-hidden="true">{r.n}</span>
              <span style={{ display: "block", minWidth: 0 }}>
                <span className="rf-rt">{r.title}</span>
                <span className={`rf-rl rf-c-${r.tone}`}><Icon name={r.icon} size={16} />{r.label}</span>
              </span>
            </div>
          </li>
        ))}
      </ol>
      {g && (
        <div className="p2-in" role="group" aria-label={`Исправление слайда ${p.n}`} aria-busy="true"
          style={{ marginTop: 16, padding: "16px 24px", borderRadius: 24, background: "#F3F4F1", flex: "none", animationDelay: d(80) }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 24 }}>
            <p style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap" }}>
              <Arc />
              <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, letterSpacing: "-0.02em" }}>Агент исправляет слайд</span>
            </p>
            <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", color: "#0B1220", fontVariantNumeric: "tabular-nums" }}>
              <span className="p2-sr">Прошло </span>{g.clock}
            </span>
          </div>
          <div role="progressbar" aria-label="Ход исправления" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(g.value * 100)}
            style={{ position: "relative", height: 4, marginTop: 8, borderRadius: 999, background: "rgba(11,18,32,.08)", overflow: "hidden" }}>
            <span className="p2-bar" style={{ position: "absolute", inset: 0, borderRadius: 999, background: "#2563EB", transformOrigin: "left center", transform: `scaleX(${g.value.toFixed(4)})` }} />
          </div>
          <ol aria-label="Шаги исправления" style={{ display: "flex", flexDirection: "column", gap: 8, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
            {g.steps.map((s) => (
              <li key={s.name} className={`rf-step rf-${s.state}`}>
                <span className="rf-sd" aria-hidden="true"><Icon name="check" size={10} /></span>
                <span className="rf-sn">{s.name}</span>
                <span className="rf-sl" title={s.line}><span className="p2-sr">{STEP_SR[s.state]}</span>{s.line}</span>
              </li>
            ))}
          </ol>
          <p className={g.preview === "wait" ? undefined : `rf-${g.preview}`}
            style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0 0", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>
            <span className="rf-sd" aria-hidden="true"><Icon name="check" size={10} /></span>
            <span>Готовлю превью слайда</span>
          </p>
          {g.wish && (
            <p title={g.wish} style={{ margin: "8px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              Пожелание: <b style={{ fontWeight: 700, color: "#0B1220" }}>«{g.wish}»</b>
            </p>
          )}
        </div>
      )}
    </>
  );
}

function Stat({ children, cap, title, delay }: { children: ReactNode; cap: string; title?: string; delay: string }) {
  return (
    <p className="rd-stat p2-in" title={title} style={{ animationDelay: delay }}>
      <span className="rd-num">{children}</span>
      <span className="rd-cap">{cap}</span>
    </p>
  );
}

function Done({ p, d }: { p: RemarksPanelProps; d(ms: number): string }) {
  const x = p.done!;
  const s = x.summary;
  const score = s.was !== null && s.now !== null;
  return (
    <>
      <ol className="rd-list p2-fade" aria-label={`Замечания к слайду ${p.n}`} style={LIST}>
        {p.rows.map((r, j) => {
          const on = j === p.sel && !r.done;
          return (
            <li key={r.id} className="p2-in" style={{ flex: "none", animationDelay: d(40 + Math.min(j, 6) * 40) }}>
              {r.done ? (
                <div className="rd-row">
                  <span className="rd-dot rd-ok" aria-hidden="true"><Icon name="check" size={12} /></span>
                  <span style={{ display: "block", minWidth: 0 }}>
                    <span className="rd-rt rd-rt-done"><span className="p2-sr">Замечание {r.n}: </span>{r.title}</span>
                    <span className="rd-rl rd-c-ok"><Icon name="check-circle" size={16} />Исправлено</span>
                  </span>
                </div>
              ) : (
                <button type="button" className={cls("rd-row rd-btn", on && `rk-on-${r.tone}`)} aria-pressed={on} onClick={() => p.onSel(j)}>
                  <span className={`rd-dot rd-${r.tone}`} aria-hidden="true">{r.n}</span>
                  <span style={{ display: "block", minWidth: 0 }}>
                    <span className="rd-rt">{r.title}</span>
                    {r.text && <span className="rd-rx" title={r.text}>{r.text}</span>}
                    <span className={`rd-rl rd-c-${r.tone}`}><Icon name={r.icon} size={16} />{r.label}</span>
                  </span>
                </button>
              )}
            </li>
          );
        })}
      </ol>
      {/* итог: два крупных числа · следствие · одно действие */}
      <section className="rd-sum p2-in" role="status" aria-label={`Итог исправления слайда ${p.n}`} style={{ flex: "none", animationDelay: d(80) }}>
        <div className="rd-stats" style={score ? undefined : { gridTemplateColumns: "minmax(0, 1fr)" }}>
          <Stat cap={s.cap} delay={d(120)}>
            <span className="rd-acc">{s.fixedN}</span>
            <span className="rd-mut">из {s.of}</span>
          </Stat>
          {score && (
            <Stat cap="оценка качества" title={`Оценка качества: было ${s.was}, стало ${s.now}`} delay={d(160)}>
              <span className="p2-sr">было </span>
              <span className="rd-mut">{s.was}</span>
              <svg className="rd-arr" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#2563EB" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14 M13.5 6.5L19 12l-5.5 5.5" />
              </svg>
              <span className="p2-sr">, стало </span>
              <span className="rd-acc">{s.now}</span>
            </Stat>
          )}
        </div>
        <div className="rd-line p2-in" style={{ animationDelay: d(200) }}>
          <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="copy" size={20} /></span>
          <p style={{ flex: 1, minWidth: 0, margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.line}</p>
          {s.show !== null && (
            <button type="button" className="p2-gb" onClick={x.onShow} title={s.showTip} style={{ flex: "none", marginRight: -16 }}>Показать</button>
          )}
        </div>
        {x.canUndo && (
          <button type="button" className="p2-ob p2-in" onClick={x.onUndo} aria-busy={x.undoBusy || undefined} aria-disabled={x.undoBusy || undefined}
            title={x.undoBusy ? "Возвращаю слайд, каким он был до исправления…" : "Вернуть слайд, каким он был до исправления"}
            style={{ width: "100%", marginTop: 8, animationDelay: d(240), cursor: x.undoBusy ? "progress" : undefined }}>
            {x.undoBusy ? <Arc size={18} /> : <Icon name="undo" size={18} />}
            <span>Вернуть как было</span>
          </button>
        )}
        {x.refresh ? <StaleLine r={x.refresh} style={{ marginTop: 16 }} />
          : x.undoError && <ErrorLine text={x.undoError} lines={2} style={{ marginTop: 8 }} />}
      </section>
    </>
  );
}
