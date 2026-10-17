// Колода стопкой (окно уже 1280): затемнение под слоем или помощником — только прозрачность (stack.css `.p2-dim`), щелчок
// закрывает верхнюю плиту (sheets.ts). Поверх колоды — одна плита: открылся помощник — слои закрываются, открылся слой —
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
  if (!stack) return null;
  const close = dimClose(ui);
  return (
    <button type="button" className={cls("p2-dim", close && "p2-dim-on")} tabIndex={-1} aria-hidden="true"
      onClick={() => close && dispatch(close)} />
  );
}
