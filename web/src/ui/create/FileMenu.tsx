// Меню «Из файла» шага «02 Текст»: белая плита 320 px под кнопкой, проявляется 240 мс и гаснет 160 мс (`tx-menu`,
// `tx-menu-on`). Разметка — boards/V2.dc.html, `#tx-menu`. Пункты открывают выбор файла: текст .txt/.md встаёт в поле,
// готовая презентация — «Улучшить готовую»; третий пункт — пример текста. Клик мимо (подложка `tx-scrim` на плите
// ставит TextHead) и Esc закрывают меню, стрелки ходят по пунктам.
import { useEffect, useRef, type KeyboardEvent } from "react";
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

export function FileMenu({ open, busy, onPick, onClose }: {
  open: boolean;
  /** Презентация уже читается: второй раз её не выбирают. */
  busy: boolean;
  onPick(k: FilePick): void;
  /** Закрыть меню; `back` — вернуть фокус на кнопку «Из файла» (Esc). */
  onClose(back?: boolean): void;
}) {
  const ref = useRef<HTMLDivElement>(null);
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
    <div ref={ref} id="tx-menu" role="menu" aria-label="Выберите файл" aria-hidden={!open || undefined} className={cls("tx-menu", open && "tx-menu-on")} onKeyDown={onKey}>
      <p className="tx-mcap">Выберите файл</p>
      {ITEMS.map((it) => {
        const off = it.key === "deck" && busy;
        return (
          <button key={it.key} type="button" role="menuitem" className="tx-mi" tabIndex={open ? 0 : -1} aria-disabled={off || undefined}
            title={off ? "Презентация уже читается" : undefined} onClick={() => !off && onPick(it.key)}>
            <span className="tx-mic" aria-hidden="true"><Icon name={it.icon} size={16} /></span>
            <span className="tx-mt"><span className="tx-mn">{it.name}</span><span className="tx-mm">{it.meta}</span></span>
          </button>
        );
      })}
    </div>
  );
}
