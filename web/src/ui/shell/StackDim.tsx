// Колода стопкой (окно уже 1280): затемнение под слоем или помощником — только прозрачность (stack.css `.p2-dim`), щелчок
// закрывает верхнюю плиту (sheets.ts), Esc — тоже. Поверх колоды — одна плита: открылся помощник — слои закрываются, открылся слой —
// закрывается помощник (`oneSheet`). На компьютере затемнения нет: слои ложатся в колоду, помощник — рядом с ней.
import { useEffect, useRef } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { closeSheet, dimClose, layerOpen, oneSheet } from "./sheets";
import { useStack } from "./tier";

export function StackDim() {
  const { ui, dispatch } = useApp();
  const stack = useStack();
  const was = useRef(ui);
  const wasStack = useRef(stack);
  useEffect(() => {
    const prev = was.current;
    const fromWide = stack && !wasStack.current;
    was.current = ui;
    wasStack.current = stack;
    if (!stack) return;
    // окно сузилось при открытых помощнике (рядом с колодой) и слое — поверх колоды остаётся слой
    if (fromWide && ui.helper && layerOpen(ui)) return void dispatch(closeSheet("helper"));
    for (const a of oneSheet(prev, ui)) dispatch(a);
  }, [ui, stack, dispatch]);
  const close = stack ? dimClose(ui) : null;
  // Esc где угодно (фокус на странице, в шапке) закрывает верхнюю плиту, как щелчок по затемнению; Esc внутри плиты она
  // обрабатывает сама (и гасит событие). «Удалить шаблон?» закрывается своим Esc
  const top = useRef(close);
  top.current = ui.tplDelete ? null : close;
  const on = !!close;
  useEffect(() => {
    if (!on) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || !top.current) return;
      e.preventDefault();
      dispatch(top.current);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [on, dispatch]);
  if (!stack) return null;
  // щелчок по затемнению фокус не берёт: он остаётся в плите и возвращается туда, откуда её открыли
  return (
    <button type="button" className={cls("p2-dim", close && "p2-dim-on")} tabIndex={-1} aria-hidden="true"
      onMouseDown={(e) => e.preventDefault()} onClick={() => close && dispatch(close)} />
  );
}
