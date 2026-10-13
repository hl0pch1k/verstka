// Компактный вид «Результата» (boards/G-helper, G-helper-open; V2 `hp-in`): слой над плитой с той же сеткой, что у
// полного вида, — когда помощник сужает колоду, его шапка встаёт в строку уведомления (48 → 64): название, строка
// «шаблон · слайды · когда», действия-иконки («Скачать PDF», «Изменить текст», «Показать текст», «Подробнее», «Новая
// презентация») и «Скачать PowerPoint»; а в узкой колонке 184 px — варианты столбиком, оценка и итоги проверки (пункты о
// качестве открывают «Подробнее» на «Качестве»). Уведомления полного вида здесь нет: если оно есть, его действия — за
// значком «i» в начале ряда (меню как df-menu). Слайд, листание и лента миниатюр — общие с полным видом, их сетка
// перестраивается вместе с колодой (helper.css). Полный вид гаснет за 240 мс, компактный проявляется за 240 мс через
// 120 мс; закрытие — наоборот, быстрее. В режиме «Замечания» и с выбранным изображением колонка шире (320 px): панель
// замечаний стоит в ней, а карточка «Изображение» — здесь, вместо итогов; смена 184 ↔ 320 — перекрёстным затуханием
// (`snap`: сетка подменяется без хода, пока слайд и колонка не видны).
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { SheetTab } from "../deck/geometry";
import { useDeckWidth } from "../deck/useDeckFit";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { ctaShort, type CheckItem } from "./compact";
import type { NoteActions } from "./NotePill";
import type { NoteView } from "./resultView";

const UNB = "'Unbounded','Manrope',sans-serif";
const TONE: Record<CheckItem["tone"], string> = { ok: "#2563EB", warn: "#B45309", error: "#DC2626" };
const MI_T = { fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220" } as const;

export interface CompactData {
  title: string;
  line: string;
  /** Строка неудачи результата (на месте строки под названием: уведомления в компактном виде нет). */
  error: string | null;
  score: number | null;
  variants: { key: string; label: string; score: number | null; title?: string }[];
  variant: string;
  pptx: string | null;
  pdf: string | null;
  fileBase: string;
  pptxTitle: string;
  checks: CheckItem[];
  /** У презентации есть написанный агентом текст («Показать текст»). */
  hasText: boolean;
}

/** Уведомление результата в компактном виде: значок «i» и меню с его текстом и действиями (те же, что у таблетки). */
function NoteMenu({ note, actions, live }: { note: NoteView; actions: NoteActions; live: boolean }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  // помощник закрылся — меню гаснет вместе с компактным видом (160 мс) и закрывается, когда его уже не видно
  useEffect(() => {
    if (live || !open) return;
    const t = window.setTimeout(() => setOpen(false), 160);
    return () => window.clearTimeout(t);
  }, [live, open]);
  // фокус — на первое действие (или на меню); при закрытии — обратно на значок
  useEffect(() => {
    if (!open) return;
    const first = pop.current?.querySelector<HTMLElement>(".df-mi:not([aria-disabled])");
    (first ?? pop.current)?.focus({ preventScroll: true });
  }, [open]);
  const close = (back = true) => {
    setOpen(false);
    if (back) btn.current?.focus({ preventScroll: true });
  };
  const run = (fn: () => void) => () => {
    close(false);
    fn();
  };
  const off = actions.rebuildOff;
  const busy = !!actions.rebuildBusy;
  return (
    <div style={{ position: "relative", flex: "none" }}>
      <button ref={btn} type="button" className="p2-rbl hp-nb" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        aria-controls={open ? "hp-np" : undefined} aria-label={note.label} title={note.title}>
        <Icon name="info" size={18} />
      </button>
      {open && (
        <>
          <button type="button" className="p2-scrim" tabIndex={-1} aria-label="Закрыть уведомление" onClick={() => close()}
            style={{ position: "fixed", inset: 0, zIndex: 2, cursor: "default" }} />
          <div ref={pop} id="hp-np" role="dialog" aria-label={note.label} tabIndex={-1} className="df-menu p2-pop hp-np"
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.preventDefault();
              e.stopPropagation(); // Esc закрывает только меню, не помощника
              close();
            }}>
            <p className="hp-npt">{note.title}</p>
            <p className="hp-npb" title={note.full}>{note.body}</p>
            {note.showText && (
              <button type="button" className={cls("df-mi", actions.textOff && "rt-nb-off")} aria-disabled={actions.textOff ? true : undefined}
                title={actions.textOff ?? undefined} onClick={actions.textOff ? undefined : run(actions.onShowText)}>
                <Icon name="file-text" size={18} /><span style={MI_T}>Показать текст</span>
              </button>
            )}
            {note.retry && (
              <button type="button" className={cls("df-mi", off && "rt-nb-off")} aria-disabled={off || busy ? true : undefined} aria-busy={busy || undefined}
                title={off ?? (busy ? "Отправляю запрос на сборку…" : "Собрать ту же презентацию заново")} onClick={off || busy ? undefined : run(actions.onRebuild)}>
                {busy ? <span style={{ display: "flex", color: "#2563EB" }}><Spinner size={18} /></span> : <Icon name="retry" size={18} />}
                <span style={MI_T}>Собрать ещё раз</span>
              </button>
            )}
            {note.rewrite && (
              <button type="button" className="df-mi" onClick={run(actions.onRewrite)}>
                <Icon name="pen" size={18} /><span style={MI_T}>Дописать текст</span>
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function CompactResult({ d, live, wide, snap, note, noteActions, onVariant, onEditText, onShowText, onDetails, onNew, card }: {
  d: CompactData;
  /** Компактный вид на месте (помощник открыт). */
  live: boolean;
  /** Колонка шире: режим «Замечания» или карточка «Изображение» (итоги гаснут сразу). */
  wide: boolean;
  /** Сетка уже в новом виде (184 ↔ 320 — после затухания) и встаёт без хода. */
  snap: { wide: boolean; now: boolean };
  /** Уведомление результата (таблетка полного вида); null — его нет. */
  note: NoteView | null;
  noteActions: NoteActions;
  onVariant(key: string): void;
  onEditText(): void;
  onShowText(): void;
  /** Лист «Подробнее» на вкладке. */
  onDetails(tab: SheetTab): void;
  onNew(): void;
  /** Карточка «Изображение» на месте итогов (выбрано изображение на слайде); `node` — null, пока карточка стоит в
   *  колонке полного вида (смена вида). null — изображение не выбрано. */
  card: { shown: boolean; node: ReactNode } | null;
}) {
  // «Скачать PowerPoint» → «PowerPoint», когда рядом со значками названию мало места (по целевой ширине колоды)
  const short = ctaShort(useDeckWidth(), (note ? 1 : 0) + 5);
  return (
    <div className={cls("hp-in", snap.wide && "hp-wide", snap.now && "hp-snap")}>
      <div className="hp-top hp-xf">
        <div className="gh-top p2-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64, animationDelay: "160ms" }}>
          <div style={{ minWidth: 0 }}>
            <h1 title={d.title} style={{ margin: 0, fontFamily: UNB, fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.title}</h1>
            {d.error
              ? <ErrorLine text={d.error} lines={1} quiet style={{ display: "flex", marginTop: 4 }} />
              : <p title={d.line} style={{ margin: "4px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.line}</p>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
            {note && <NoteMenu note={note} actions={noteActions} live={live} />}
            {d.pdf ? (
              <a className="p2-rbl" href={d.pdf} download={`${d.fileBase}.pdf`} aria-label="Скачать PDF" title="Скачать PDF"><Icon name="file" size={18} /></a>
            ) : (
              <button type="button" className="p2-rbl" disabled aria-label="Скачать PDF" title="PDF для этой презентации нет"><Icon name="file" size={18} /></button>
            )}
            <button type="button" className="p2-rbl" onClick={onEditText} aria-label="Изменить текст" title="Изменить текст или шаблон"><Icon name="pen" size={18} /></button>
            <button type="button" className={cls("p2-rbl", !d.hasText && "rt-nb-off")} onClick={onShowText} aria-haspopup="dialog" aria-label="Показать текст"
              aria-disabled={d.hasText ? undefined : true} title={d.hasText ? "Показать текст презентации" : "Для этой презентации текст недоступен"}>
              <Icon name="list" size={18} />
            </button>
            <button type="button" className="p2-rbl" onClick={() => onDetails("quality")} aria-haspopup="dialog" aria-label="Подробнее"
              title="Подробнее: качество, почему так, агент, план, шаблон, файлы">
              <Icon name="chart" size={18} />
            </button>
            <button type="button" className="p2-rbl" onClick={onNew} aria-label="Новая презентация" title="Новая презентация"><Icon name="plus" size={18} /></button>
            {d.pptx && (
              <a className="p2-cta" href={d.pptx} download={`${d.fileBase}.pptx`} aria-label="Скачать PowerPoint" title={d.pptxTitle} style={{ marginLeft: 8 }}>
                <Icon name="download" size={20} />
                <span>{short ? "PowerPoint" : "Скачать PowerPoint"}</span>
              </a>
            )}
          </div>
        </div>
      </div>

      <div className={cls("hp-ncol hp-xf", wide && "hp-xf-off")} aria-hidden={wide || undefined}>
        <div className="p2-in" style={{ display: "flex", flexDirection: "column", minHeight: 0, animationDelay: "200ms" }}>
          <div role="group" aria-label="Вариант оформления" style={{ display: "flex", flexDirection: "column", gap: 4, padding: 4, borderRadius: 24, background: "#F3F4F1" }}>
            {d.variants.map((v) => {
              const on = v.key === d.variant;
              return (
                <button key={v.key} type="button" className={cls("p2-rseg", on && "p2-rseg-on")} aria-pressed={on} onClick={() => onVariant(v.key)} title={v.title}
                  style={{ justifyContent: "space-between", width: "100%", padding: "0 16px" }}>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{v.label}</span>
                  {v.score !== null && <span className="p2-rsc">{v.score}</span>}
                </button>
              );
            })}
          </div>
          {d.score !== null && (
            <div style={{ display: "flex", flexDirection: "column", marginTop: 24 }}>
              <span key={d.variant} className="ra-xf" style={{ fontFamily: UNB, fontWeight: 700, fontSize: 88, lineHeight: "72px", letterSpacing: "-0.04em", color: "#0B1220" }}>{d.score}</span>
              <span style={{ marginTop: 8, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220" }}>из 100</span>
              <span style={{ fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>оценка качества</span>
            </div>
          )}
          <div style={{ height: 1, marginTop: 24, background: "rgba(11,18,32,.08)" }} />
          <ul style={{ display: "flex", flexDirection: "column", gap: 12, margin: "24px 0 0", padding: 0, listStyle: "none" }}>
            {d.checks.map((c, i) => {
              const body = (
                <>
                  <span style={{ display: "flex", flex: "none", color: TONE[c.tone] }}><Icon name={c.icon} size={20} /></span>
                  <span className="hp-chk">{c.lead && <b style={{ fontWeight: 700, color: c.tone === "ok" ? undefined : TONE[c.tone] }}>{c.lead}</b>}{c.rest}</span>
                </>
              );
              return (
                <li key={i} title={c.title}>
                  {c.sheet
                    ? <button type="button" className="hp-chkb" onClick={() => onDetails(c.sheet!)} aria-haspopup="dialog">{body}</button>
                    : <span className="hp-chkr">{body}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {card && <div className={cls("hp-pcol hp-xf", !card.shown && "hp-xf-off")} aria-hidden={card.shown ? undefined : true}>{card.node}</div>}
    </div>
  );
}
