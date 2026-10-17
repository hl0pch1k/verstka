// Пункты шапки: «Мои презентации» и «Шаблоны» открывают слои-разделы (`ui.sect`), «Помощник» — плиту помощника
// (`ui.helper`); открытый пункт — белая таблетка p2-nav-on. Разметка — boards/V2.dc.html, `<nav class="p2-navs">`.
// Телефон (окно уже 768, stack.css): пункты — за кнопкой «Меню» (раскрытие, aria-expanded): белая плита под кнопкой,
// проявляется как меню «Из файла»; пункт, Esc или щелчок мимо закрывают её, Esc возвращает фокус на кнопку. На
// компьютере и планшете кнопки нет — пункты в ряд, как на холсте.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { useTier } from "./tier";

export function Nav() {
  const { ui, dispatch } = useApp();
  const hist = ui.sect === "hist";
  const tpls = ui.sect === "tpls";
  const phone = useTier() === "sm";
  const [menu, setMenu] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const nav = useRef<HTMLElement>(null);
  const open = menu && phone;
  // окно стало шире — меню нет
  useEffect(() => {
    if (!phone) setMenu(false);
  }, [phone]);
  // щелчок мимо меню и кнопки закрывает его
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!nav.current?.contains(t) && !btn.current?.contains(t)) setMenu(false);
    };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, [open]);
  // открылось — фокус на первый пункт
  useEffect(() => {
    if (open) nav.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
  }, [open]);
  const pick = (act: () => void) => {
    // пункт меню телефона после выбора скрыт — фокус на кнопку меню: слой или помощник вернут его туда, закрывшись
    if (open) btn.current?.focus({ preventScroll: true });
    setMenu(false);
    act();
  };
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Escape" || !open) return;
    e.preventDefault();
    e.stopPropagation();
    setMenu(false);
    btn.current?.focus({ preventScroll: true });
  };
  return (
    <>
      <button ref={btn} type="button" id="p2-navbtn" className="p2-navbtn" aria-expanded={open} aria-controls="p2-navmenu"
        aria-label={open ? "Закрыть меню" : "Меню: мои презентации, шаблоны, помощник"} onClick={() => setMenu(!open)}>
        <Icon name={open ? "x" : "list"} size={20} />
        <span>Меню</span>
      </button>
      <nav ref={nav} id="p2-navmenu" className={cls("p2-navs", open && "p2-navs-on")} aria-label="Разделы" onKeyDown={onKey}
        style={{ display: "flex", alignItems: "center", gap: 8, marginRight: -16 }}>
        <button type="button" className={cls("p2-nav", hist && "p2-nav-on")} aria-expanded={hist} aria-controls="p2-lay-h"
          onClick={() => pick(() => dispatch({ type: "sect", sect: hist ? null : "hist" }))}>Мои презентации</button>
        <button type="button" className={cls("p2-nav", tpls && "p2-nav-on")} aria-expanded={tpls} aria-controls="p2-lay-t"
          onClick={() => pick(() => dispatch({ type: "sect", sect: tpls ? null : "tpls" }))}>Шаблоны</button>
        <button type="button" id="hp-nav" className={cls("p2-nav", ui.helper && "p2-nav-on")} aria-expanded={ui.helper} aria-controls="hp-help"
          title={ui.helper ? "Закрыть помощника" : "Открыть помощника"}
          onClick={() => pick(() => dispatch({ type: "set", patch: { helper: !ui.helper } }))}>Помощник</button>
      </nav>
    </>
  );
}
