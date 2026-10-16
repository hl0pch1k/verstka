// Меню «Из файла» шага «02 Текст»: белая плита под кнопкой на две колонки (V2 версии 105, `.tx-menu2`): слева текст —
// .txt/.md встаёт в поле, готовая презентация — «Улучшить готовую», пример текста; справа «Данные для графиков» —
// файлы с данными (панель «Данные») и пример данных продаж, под ними подсказка «Или перетащите на поле». Высота прежняя —
// меню не заходит под плиту 03. Проявляется 240 мс и гаснет 160 мс (`tx-menu`, `tx-menu-on`). Клик мимо (подложка
// `tx-scrim` ставит TextHead) и Esc закрывают меню, стрелки ходят по пунктам.
// Сайт: меню шире места до края колоды (тесная колода с помощником) — у́же, до края колоды минус 24 (строки — многоточием).
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { DsIcon, DsSpin } from "./dsKit";
import { SAMPLE_BRIEF } from "../../lib/createForm";
import { cls } from "../kit/cls";
import { Icon, type IconName } from "../kit/Icon";

export type FilePick = "text" | "deck" | "sample";

/** «Текст Markdown · 3 КБ» — размер примера, как у файла. */
const sampleKb = Math.max(1, Math.round(new TextEncoder().encode(SAMPLE_BRIEF).length / 1024));

const ITEMS: { key: FilePick; icon: IconName; name: string; meta: string }[] = [
  { key: "text", icon: "file-text", name: "Текст из файла", meta: ".txt или .md" },
  { key: "deck", icon: "presentation", name: "Улучшить готовую", meta: "Презентация .pptx — новая вёрстка" },
  { key: "sample", icon: "file-text", name: "Пример: Умные сводки.md", meta: `Текст Markdown · ${sampleKb} КБ` },
];

/** Меню на две колонки — 608 px; у́же места до края колоды не бывает уже 440. */
const MENU_W = 608;
const MENU_MIN = 440;

export function FileMenu({ open, off: deckOff, onPick, onClose, onData, onExample, exampleBusy }: {
  open: boolean;
  /** «Улучшить готовую» не выбирается (презентация уже читается, разбирается свой шаблон): почему; null — выбирается. */
  off: string | null;
  onPick(k: FilePick): void;
  /** Закрыть меню; `back` — вернуть фокус на кнопку «Из файла» (Esc). */
  onClose(back?: boolean): void;
  /** «Файлы с данными» — окно выбора нескольких файлов. */
  onData(): void;
  /** «Пример: данные продаж» — текст, 7 файлов и брендбук. */
  onExample(): void;
  /** Пример скачивается. */
  exampleBusy: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const el = ref.current;
    const deck = el?.closest(".p2-deck");
    if (!el || !deck) return;
    const room = deck.getBoundingClientRect().right - 24 - el.getBoundingClientRect().left;
    setWidth(room < MENU_W ? Math.max(MENU_MIN, Math.floor(room)) : null);
  }, [open]);
  const items = () => Array.from(ref.current?.querySelectorAll<HTMLButtonElement>(".tx-mi:not([aria-disabled=true])") ?? []);
  // открылось — фокус на первый пункт (после кадра: плита только что стала видимой)
  useEffect(() => {
    if (!open) return;
    const r = requestAnimationFrame(() => items()[0]?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(r);
  }, [open]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose(true);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus({ preventScroll: true });
  };
  return (
    <div ref={ref} id="tx-menu" role="menu" aria-label="Выберите файл" aria-hidden={!open || undefined} className={cls("tx-menu tx-menu2", open && "tx-menu-on")} onKeyDown={onKey}
      style={width ? { width } : undefined}>
      <div className="tx-mcol" role="group" aria-labelledby="tx-mc1">
        <p id="tx-mc1" className="tx-mcap">Текст</p>
        {ITEMS.map((it) => {
          const off = it.key === "deck" ? deckOff : null;
          return (
            <button key={it.key} type="button" role="menuitem" className="tx-mi" tabIndex={open ? 0 : -1} aria-disabled={off ? true : undefined}
              title={off ?? undefined} onClick={() => !off && onPick(it.key)}>
              <span className="tx-mic" aria-hidden="true"><Icon name={it.icon} size={16} /></span>
              <span className="tx-mt"><span className="tx-mn">{it.name}</span><span className="tx-mm">{it.meta}</span></span>
            </button>
          );
        })}
      </div>
      <div className="tx-mcol" role="group" aria-labelledby="tx-mc2">
        <p id="tx-mc2" className="tx-mcap">Данные для графиков</p>
        <button type="button" role="menuitem" className="tx-mi" tabIndex={open ? 0 : -1} onClick={onData}>
          <span className="tx-mic" aria-hidden="true"><DsIcon name="tbl" size={16} /></span>
          <span className="tx-mt"><span className="tx-mn">Файлы с данными</span><span className="tx-mm">CSV, XLSX, JSON, таблица в тексте</span></span>
        </button>
        <button type="button" role="menuitem" className="tx-mi" tabIndex={open ? 0 : -1} onClick={onExample} aria-disabled={exampleBusy || undefined}
          title={exampleBusy ? "Пример загружается" : undefined}>
          <span className="tx-mic" aria-hidden="true">{exampleBusy ? <DsSpin /> : <DsIcon name="chart" size={16} />}</span>
          <span className="tx-mt"><span className="tx-mn">Пример: данные продаж</span><span className="tx-mm">7 файлов, бриф, брендбук</span></span>
        </button>
        <p className="tx-mdrop">
          <span className="tx-mic" aria-hidden="true"><DsIcon name="upload" size={16} /></span>
          <span className="tx-mt"><span className="tx-mn">Или перетащите на поле</span><span className="tx-mm">текст и данные вместе</span></span>
        </p>
      </div>
    </div>
  );
}
