// Меню у кнопки (раскрытие, aria-expanded): меню разделов в шапке телефона, «Ещё» у «Скачать PowerPoint» на телефоне.
// Открылось — фокус на первый пункт; пункт, Esc, щелчок мимо меню и кнопки или фокус, ушедший из меню не на кнопку (Tab
// за последний пункт), закрывают его. Esc и пункт возвращают фокус на кнопку: то, что пункт откроет (слой, помощник),
// вернёт его туда же, закрывшись.
import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

/** Фокус ушёл туда, куда меню не дотягивается (`to` — не в меню и не кнопка): меню закрывается. Ушёл никуда (окно
 *  потеряло фокус) — меню остаётся. */
export function blurCloses<T>(to: T | null, inMenu: (n: T) => boolean, onButton: (n: T) => boolean): boolean {
  return to !== null && !inMenu(to) && !onButton(to);
}

export interface Pop<B extends HTMLElement, M extends HTMLElement> {
  open: boolean;
  toggle(): void;
  btn: React.RefObject<B>;
  box: React.RefObject<M>;
  onKey(e: KeyboardEvent<HTMLElement>): void;
  onBlur(e: FocusEvent<HTMLElement>): void;
  /** Пункт меню: меню закрывается, фокус — на кнопку, потом действие. */
  pick(act: () => void): void;
}

/** `on` — меню возможно здесь (например, только на телефоне); стало невозможно — закрывается. */
export function usePop<B extends HTMLElement = HTMLButtonElement, M extends HTMLElement = HTMLElement>(on = true): Pop<B, M> {
  const [want, setWant] = useState(false);
  const open = want && on;
  const btn = useRef<B>(null);
  const box = useRef<M>(null);
  useEffect(() => {
    if (!on) setWant(false);
  }, [on]);
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !btn.current?.contains(t)) setWant(false);
    };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, [open]);
  useEffect(() => {
    if (open) box.current?.querySelector<HTMLElement>("button, a[href]")?.focus({ preventScroll: true });
  }, [open]);
  const back = () => btn.current?.focus({ preventScroll: true });
  return {
    open,
    toggle: () => setWant(!open),
    btn,
    box,
    onKey: (e) => {
      if (e.key !== "Escape" || !open) return;
      e.preventDefault();
      e.stopPropagation();
      setWant(false);
      back();
    },
    onBlur: (e) => {
      const inside = (n: Node) => !!box.current?.contains(n);
      const onBtn = (n: Node) => !!btn.current?.contains(n);
      if (open && blurCloses(e.relatedTarget as Node | null, inside, onBtn)) setWant(false);
    },
    pick: (act) => {
      if (open) back();
      setWant(false);
      act();
    },
  };
}
