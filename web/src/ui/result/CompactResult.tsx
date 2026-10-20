// Компактный вид «Результата» (boards/G-helper, G-helper-open; V2 `hp-in`): слой над плитой с той же сеткой, что у
// полного вида, — когда помощник сужает колоду, его шапка встаёт в строку уведомления (48 → 64): название, строка
// «шаблон · слайды · когда», действия-иконки («Скачать PDF», «Изменить текст», «Показать текст», «Новая презентация» —
// как на холсте; «Подробнее» открывают пункты итогов в узкой колонке) и «Скачать PowerPoint»; а в узкой колонке 184 px — варианты столбиком, оценка и итоги проверки (пункты о
// качестве открывают «Подробнее» на «Качестве»). Уведомления полного вида здесь нет: если оно есть, его действия — за
// значком «i» в начале ряда (меню как df-menu). Слайд, листание и лента миниатюр — общие с полным видом, их сетка
// перестраивается вместе с колодой (helper.css). Полный вид гаснет за 240 мс, компактный проявляется за 240 мс через
// 120 мс; закрытие — наоборот, быстрее. В режиме «Замечания» и с выбранным изображением колонка шире (320 px): панель
// замечаний стоит в ней, а карточка «Изображение» — здесь, вместо итогов; смена 184 ↔ 320 — перекрёстным затуханием
// (`snap`: сетка подменяется без хода, пока слайд и колонка не видны).
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Arc } from "../kit/Arc";
import { useSwap } from "../kit/useSwap";
import type { SheetTab } from "../deck/geometry";
import { useDeckWrap } from "../deck/useDeckFit";
import { HELPER_COL } from "../deck/layout";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { useHelperWant } from "../shell/helperMotion";
import { ctaShort, type CheckItem } from "./compact";
import type { NoteActions } from "./NotePill";
import type { NoteView } from "./resultView";

const UNB = "'Unbounded','Manrope',sans-serif";
const TONE: Record<CheckItem["tone"], string> = { ok: "#2563EB", warn: "#B45309", error: "#DC2626" };
const MI_T = { fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220" } as const;

export interface CompactData {
  title: string;
  line: string;
  /** Строка ряда результата (на месте строки под названием: уведомления и ряда в компактном виде нет) — с тем же
   *  действием, что в ряду: «Показать» у неудачи работы над слайдом, «Обновить» у несвежей презентации (дуга, пока она
   *  читается); целиком — в подсказке. null — строки нет. */
  error: { text: string; title: string; act: { label: string; title: string; busy?: boolean; icon?: "refresh"; onClick(): void } | null } | null;
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
      <button ref={btn} type="button" className="p2-rbl hp-nb hp-ib" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        aria-controls={open ? "hp-np" : undefined} aria-label={note.label}>
        <Icon name="info" size={18} />
        {!open && <Tip text={note.title} />}
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

/** Подпись значка: при наведении проявляется под кнопкой, в пустом зазоре между шапкой компактного вида и
 *  рабочей областью (только прозрачность и transform) — ничего не перекрывает и никого не сдвигает (замечание
 *  владельца 18.10). */
function Tip({ text }: { text: string }) {
  return <span className="hp-ibt" aria-hidden="true">{text}</span>;
}

/** Кегль названия компактного вида: 32 px, как на холсте; не помещается в строку — 28, 24; и тогда нет — две строки
 *  по 22 px (строка «шаблон · слайды · когда» уступает им место). Многоточия нет (замечание владельца 18.10). */
const TITLE_SIZES = [32, 28, 24];
function useTitleFit(title: string) {
  const ref = useRef<HTMLHeadingElement>(null);
  const [fit, setFit] = useState<{ size: number; two: boolean }>({ size: 32, two: false });
  useLayoutEffect(() => {
    const h = ref.current;
    const box = h?.parentElement;
    if (!h || !box) return;
    const measure = () => {
      if (!box.clientWidth) return;
      const was = { fs: h.style.fontSize, lh: h.style.lineHeight, ws: h.style.whiteSpace };
      h.style.whiteSpace = "nowrap";
      let next = { size: 22, two: true };
      for (const size of TITLE_SIZES) {
        h.style.fontSize = `${size}px`;
        if (h.scrollWidth <= box.clientWidth + 0.5) {
          next = { size, two: false };
          break;
        }
      }
      h.style.fontSize = was.fs;
      h.style.lineHeight = was.lh;
      h.style.whiteSpace = was.ws;
      setFit((f) => (f.size === next.size && f.two === next.two ? f : next));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    return () => ro.disconnect();
  }, [title]);
  return { ref, ...fit };
}

/** Строка под названием: строка ряда результата с её действием или «шаблон · слайды · когда»; смена — перекрёстным
 *  затуханием, уходящая гаснет со своим содержимым. */
function HeadLine({ d }: { d: CompactData }) {
  const key = d.error ? `e:${d.error.text}:${d.error.act?.label ?? ""}` : "line";
  const sw = useSwap(key);
  const held = useRef(new Map<string, CompactData["error"]>());
  held.current.set(key, d.error);
  for (const k of [...held.current.keys()]) if (k !== key && k !== sw.shown) held.current.delete(k);
  const e = sw.shown === key ? d.error : held.current.get(sw.shown) ?? null;
  const a = e?.act ?? null;
  return (
    <div className={sw.cls} style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, marginTop: 4 }}>
      {e ? (
        <>
          <ErrorLine text={e.text} title={e.title} lines={1} quiet style={{ display: "flex", flex: "0 1 auto" }} />
          {a && (
            <button type="button" className="gh-act hp-act" onClick={a.onClick} aria-busy={a.busy || undefined} title={a.busy ? "Перечитываю презентацию…" : a.title}>
              {a.icon && (a.busy ? <Arc size={16} /> : <Icon name="refresh" size={16} />)}
              {a.label}
            </button>
          )}
        </>
      ) : (
        <p title={d.line} style={{ margin: 0, fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.line}</p>
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
  // «Скачать PowerPoint» → «PowerPoint», когда рядом со значками названию мало места: компактный вид виден только в
  // узкой колоде — по её ширине (обёртка − место помощника), а не по состоянию помощника (подпись не меняется на глазах)
  const wrap = useDeckWrap();
  const short = ctaShort(wrap > 0 ? wrap - HELPER_COL : 0, (note ? 1 : 0) + 4);
  const tf = useTitleFit(d.title);
  // помощник закрыт — компактного вида нет и для клавиатуры, чтения с экрана и щелчка: он прозрачен, но его кнопки
  // («Новая презентация» и другие) лежали под заголовком полного вида и находились по имени (жюри, Playwright)
  const want = useHelperWant();
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    root.current?.toggleAttribute("inert", !want);
  }, [want]);
  return (
    <div ref={root} className={cls("hp-in", snap.wide && "hp-wide", snap.now && "hp-snap")}>
      <div className="hp-top hp-xf">
        <div className="gh-top p2-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64, animationDelay: "160ms" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 ref={tf.ref} title={d.title} style={{
              margin: 0, fontFamily: UNB, fontWeight: 600, fontSize: tf.size, lineHeight: tf.two ? "26px" : `${tf.size + 8}px`, letterSpacing: "-0.03em", color: "#0B1220",
              whiteSpace: tf.two ? "normal" : "nowrap", overflowWrap: "anywhere",
              ...(tf.two && { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }),
            }}>{d.title}</h1>
            {!tf.two && <HeadLine d={d} />}
          </div>
          <div className="hp-acts" data-hpr="" style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
            {note && <NoteMenu note={note} actions={noteActions} live={live} />}
            {d.pdf ? (
              <a className="p2-rbl hp-ib" href={d.pdf} download={`${d.fileBase}.pdf`} aria-label="Скачать PDF"><Icon name="file" size={18} /><Tip text="Скачать PDF" /></a>
            ) : (
              <button type="button" className="p2-rbl" disabled aria-label="Скачать PDF" title="PDF для этой презентации нет"><Icon name="file" size={18} /></button>
            )}
            <button type="button" className="p2-rbl hp-ib" onClick={onEditText} aria-label="Изменить текст"><Icon name="pen" size={18} /><Tip text="Изменить текст" /></button>
            <button type="button" className={cls("p2-rbl hp-ib", !d.hasText && "rt-nb-off")} onClick={onShowText} aria-haspopup="dialog" aria-label="Показать текст"
              aria-disabled={d.hasText ? undefined : true} title={d.hasText ? undefined : "Для этой презентации текст недоступен"}>
              <Icon name="list" size={18} />
              {d.hasText && <Tip text="Показать текст" />}
            </button>
            <button type="button" className="p2-rbl hp-ib" onClick={onNew} aria-label="Новая презентация"><Icon name="plus" size={18} /><Tip text="Новая презентация" /></button>
            {d.pptx && (
              <a className="p2-cta p2-cta-flat" href={d.pptx} download={`${d.fileBase}.pptx`} aria-label="Скачать PowerPoint" title={d.pptxTitle} style={{ marginLeft: 8 }}>
                <Icon name="download" size={20} />
                <span>{short ? "PowerPoint" : "Скачать PowerPoint"}</span>
              </a>
            )}
          </div>
        </div>
      </div>

      {/* узкая колонка едет с краем колоды, пока проявляется (ui/shell/helperMotion.ts, `data-hpr`) */}
      <div className={cls("hp-ncol hp-xf", wide && "hp-xf-off")} data-hpr="" aria-hidden={wide || undefined}>
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
