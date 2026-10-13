import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cls } from "./cls";
import { Icon } from "./Icon";

export interface MenuItem<T> {
  key: T;
  /** Номер слева (Unbounded 12, серый), как «1 2 3» у вариантов. */
  n?: ReactNode;
  name: ReactNode;
  /** Оценка справа (`p2-rsc`). */
  score?: ReactNode;
}

/** Меню выбора, как `df-menu` в D-files («Вариант оформления»): белая плита 256 px под кнопкой у правого края,
 *  появляется ходом `p2-pop`; пункты-радио с номером, названием, оценкой и галочкой у выбранного. Клик мимо меню
 *  (прозрачная подложка, как в V2, и нажатие где угодно на странице вне обёртки с кнопкой — подложка внутри слоя со
 *  сдвигом transform покрывает только слой) и Esc закрывают его, стрелки ходят по пунктам.
 *  Обёртку `position:relative` и кнопку (`p2-ob` со стрелкой `df-chev` / `df-chev-up`) даёт вызывающий. */
export function Menu<T extends string | number>({ label, items, value, onPick, onClose, className }: {
  label: string;
  items: MenuItem<T>[];
  value: T | null;
  onPick(k: T): void;
  onClose(): void;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // нажатие вне обёртки (кнопка меню и само меню) — где угодно на странице: шапка, помощник, другой слой
  useEffect(() => {
    const host = ref.current?.parentElement ?? null;
    const onDown = (e: PointerEvent) => {
      if (host && e.target instanceof Node && host.contains(e.target)) return;
      closeRef.current();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, []);
  const buttons = () => Array.from(ref.current?.querySelectorAll<HTMLButtonElement>(".df-mi") ?? []);
  // фокус — на выбранный пункт при открытии; при закрытии возвращается туда, откуда меню открыли
  useEffect(() => {
    const back = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const list = buttons();
    (list.find((b) => b.getAttribute("aria-checked") === "true") ?? list[0])?.focus();
    const menu = ref.current;
    return () => {
      const now = document.activeElement;
      if (!now || now === document.body || menu?.contains(now)) back?.focus();
    };
  }, []);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // Esc закрывает только меню, не слой под ним
      onClose();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const list = buttons();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus();
  };
  return (
    <>
      <button type="button" className="p2-scrim" tabIndex={-1} aria-label="Закрыть меню" onClick={onClose}
        style={{ position: "fixed", inset: 0, zIndex: 2, padding: 0, border: 0, background: "none", cursor: "default" }} />
      <div ref={ref} role="menu" aria-label={label} className={cls("df-menu p2-pop", className)} onKeyDown={onKey}>
        {items.map((it) => {
          const on = it.key === value;
          return (
            <button key={String(it.key)} type="button" role="menuitemradio" aria-checked={on} className="df-mi" onClick={() => onPick(it.key)}>
              {it.n != null && (
                <span style={{ width: 16, flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 12, lineHeight: "20px", color: "#5A6272" }}>{it.n}</span>
              )}
              <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220" }}>{it.name}</span>
              {it.score != null && <span className="p2-rsc">{it.score}</span>}
              <span className={cls("df-mchk", on && "df-mchk-on")} aria-hidden="true">
                <Icon name="check" size={16} />
              </span>
            </button>
          );
        })}
      </div>
    </>
  );
}
