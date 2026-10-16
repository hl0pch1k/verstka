// Панель «Данные» справа от поля «О чём презентация» (boards/V2.dc.html версии 105, модуль ds, `.dt-pan`): карточки
// файлов, разбор по очереди — строка «в очереди» сменяется ходом («читаю таблицу…»), ход — профилем («Временной ряд ·
// 21 строка · 3 колонки»); не прочитан — причина красным. Дорожка панели 0 → 400 px (узкая колода — 320), содержимое
// не переносится, строки обрезаются многоточием. Убрать файл: карточка гаснет 240 мс, нижние подъезжают на её место
// (transform); последний — панель уезжает (её дорожка 400 → 0), коробка целей гаснет. Файлы, отпущенные на плиту 02, —
// зона «Отпустите файлы — разберу данные» (как C-upload).
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { cls } from "../kit/cls";
import { cardSize, cardTip, panelStatus, runWord, type DataCard } from "./dataRules";
import { DsIcon, DsSpin, fileIcon } from "./dsKit";
import { plural } from "../../lib/utils";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");
/** Карточка гаснет 240 мс; панель держит сетку `dt-on` ещё 560 мс после последней (V2 `dtRemove`, `dtKeep`); въезд
 *  панели — 520 мс (`dt-in`, V2 `dtAttach`). */
const OUT_MS = 240;
const KEEP_MS = 560;
const IN_MS = 560;

export interface PanelMotion {
  /** Классы сетки поля и панели: `dt-on` (есть вторая строка — цели), `dt-w` (панель 400), `dt-in` (въезд 520 мс). */
  grid: string;
  /** Коробка целей стоит (видна или гаснет). */
  goals: boolean;
  /** Карточка, которая гаснет. */
  out: string | null;
  /** Карточки, которые подъезжают на место убранной (класс `dt-upa` / `dt-upb` — новый ход на каждое удаление). */
  shift: Record<string, "a" | "b">;
  remove(key: string): void;
}

export function usePanelMotion(cards: DataCard[], removeCard: (key: string) => void): PanelMotion {
  const on = cards.length > 0;
  const [out, setOut] = useState<string | null>(null);
  const [shift, setShift] = useState<Record<string, "a" | "b">>({});
  const [keep, setKeep] = useState(false);
  const [enter, setEnter] = useState(false);
  const was = useRef(on);
  useEffect(() => {
    if (on === was.current) return;
    was.current = on;
    if (on) {
      setKeep(false);
      setEnter(true);
      const t = window.setTimeout(() => setEnter(false), IN_MS);
      return () => window.clearTimeout(t);
    }
    setEnter(false);
    setKeep(true);
    const t = window.setTimeout(() => setKeep(false), KEEP_MS);
    return () => window.clearTimeout(t);
  }, [on]);
  const cardsNow = useRef(cards);
  cardsNow.current = cards;
  const outNow = useRef(out);
  outNow.current = out;
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const remove = useCallback((key: string) => {
    if (outNow.current) return;
    setOut(key);
    outNow.current = key;
    timer.current = window.setTimeout(() => {
      const list = cardsNow.current;
      const k = list.findIndex((c) => c.key === key);
      if (k >= 0) {
        setShift((sh) => {
          const next = { ...sh };
          for (const c of list.slice(k + 1)) next[c.key] = next[c.key] === "a" ? "b" : "a";
          return next;
        });
        removeCard(key);
      }
      setOut(null);
      outNow.current = null;
    }, OUT_MS);
  }, [removeCard]);
  return { grid: cls((on || keep) && "dt-on", on && "dt-w", enter && "dt-in"), goals: on || keep, out, shift, remove };
}

function Card({ c, i, motion }: { c: DataCard; i: number; motion: PanelMotion }) {
  const s = c.summary;
  const size = s ? cardSize(s.rows, s.cols) : null;
  const sh = motion.shift[c.key];
  const bad = c.status === "fail";
  return (
    <li className={cls("dt-li p2-in", motion.out === c.key && "dt-out", sh && `dt-up${sh}`)} style={{ animationDelay: `${160 + i * 40}ms` }}>
      <div className={cls("dt-card", bad && "dt-card-bad")} title={cardTip(c)}>
        <span className="dt-ic" aria-hidden="true"><DsIcon name={bad ? "warn" : fileIcon(c.kind)} size={16} /></span>
        <span className="dt-tx">
          <span className="dt-nm">{c.file}</span>
          <span className="dt-sw">
            <span className={cls("dt-wait", show(c.status === "wait"))}>в очереди</span>
            <span className={cls("dt-run", show(c.status === "run"))}><DsSpin size={12} /><span>{runWord(c.kind)}</span></span>
            <span className={cls("dt-pf", show(c.status === "done"))}>
              {s && size && (
                <span className="hp-sw">
                  <span className="hp-wo"><b>{s.nature_label}</b> · {size.wide}</span>
                  <span className="hp-no"><b>{s.nature_label}</b> · {size.narrow}</span>
                </span>
              )}
            </span>
            <span className={cls("dt-bad", show(bad))}>{c.error}</span>
          </span>
        </span>
        <button type="button" className="dt-x" onClick={() => motion.remove(c.key)} aria-label={`Убрать файл «${c.file}»`} title="Убрать файл">
          <DsIcon name="x" size={14} />
        </button>
      </div>
    </li>
  );
}

/** Панель «Данные» (клетка `.dt-cell` — её ставит TextBody в сетку поля). */
export function DataPanel({ cards, motion }: { cards: DataCard[]; motion: PanelMotion }) {
  const st = panelStatus(cards);
  return (
    <section className="dt-pan" aria-labelledby="dt-h">
      <div className="dt-hd">
        <span id="dt-h" className="dt-lbl">Данные</span>
        <span className={cls("dt-st", st.busy && "dt-st-run")} aria-live="polite">{st.text}</span>
      </div>
      <ul className="dt-list">
        {cards.map((c, i) => <Card key={c.key} c={c} i={i} motion={motion} />)}
      </ul>
    </section>
  );
}

/** Файлы над плитой 02 (как C-upload): «Отпустите файлы — разберу данные», сколько файлов. */
export function DataZone({ on, count }: { on: boolean; count: number }) {
  return (
    <div className={cls("up-zone tp-zone dt-zone", on && "tp-zone-on")} role="status" aria-live="polite">
      <span className="up-veil" aria-hidden="true" />
      <span className="up-line" aria-hidden="true" />
      {on && <span className="p2-sr">Отпустите файлы — разберу данные</span>}
      <div className="up-msg" aria-hidden="true">
        <span className="p2-lic p2-lic-w p2-lic-up"><span className="p2-lic-b" /><span className="p2-lic-f"><DsIcon name="chart" size={22} /></span></span>
        <p style={{ margin: "24px 0 0", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 24, lineHeight: "32px", letterSpacing: "-0.03em", color: "#0B1220" }}>
          Отпустите файлы — разберу данные
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>
          CSV, XLSX, JSON или текст с таблицей{count > 0 ? ` · ${plural(count, "файл", "файла", "файлов")}` : ""}
        </p>
      </div>
    </div>
  );
}

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/** Перетаскивание файлов на плиту, внутри которой стоит `anchor` (несколько сразу): пока файлы над плитой — `over` и
 *  сколько их; отпущенные уходят в `onFiles`. Как `useFileDrop` шага 01, но со всеми файлами. */
export function useFilesDrop(anchor: RefObject<HTMLElement>, enabled: boolean, onFiles: (f: File[]) => void): { over: boolean; count: number } {
  const [over, setOver] = useState(false);
  const [count, setCount] = useState(0);
  const depth = useRef(0);
  const take = useRef(onFiles);
  take.current = onFiles;
  useEffect(() => {
    const plate = anchor.current?.closest("section");
    depth.current = 0;
    setOver(false);
    if (!plate || !enabled) return;
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setCount(Array.from(e.dataTransfer?.items ?? []).filter((it) => it.kind === "file").length);
      setOver(true);
    };
    const move = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length) take.current(files);
    };
    plate.addEventListener("dragenter", enter);
    plate.addEventListener("dragover", move);
    plate.addEventListener("dragleave", leave);
    plate.addEventListener("drop", drop);
    return () => {
      plate.removeEventListener("dragenter", enter);
      plate.removeEventListener("dragover", move);
      plate.removeEventListener("dragleave", leave);
      plate.removeEventListener("drop", drop);
    };
  }, [anchor, enabled]);
  return { over, count };
}
