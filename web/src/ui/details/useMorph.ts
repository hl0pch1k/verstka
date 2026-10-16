// Обновление на месте (шаги — morph.ts): изменившиеся части (подписи `sigs`) гаснут 120 мс — на виду прежнее; потом
// подменяются невидимыми (`fx-hold`), и всё, что от этого сдвинулось, доезжает со старого места transform'ом (240 мс,
// FLIP через Web Animations: элементы с `data-mv`; белые подложки коробок `data-surf` растут или сжимаются scaleY от
// верхнего края — граница коробки идёт вместе с тем, что внутри, ничего не наезжает); снимки, которые меняются,
// догружаются (не дольше 1,2 с); потом части проявляются (240 мс). Без движения (системная настройка, до первого
// кадра) — сразу. Ширина обёртки сменилась посреди хода (помощник) — без сдвигов: раскладка перестраивается своим ходом.
import { useEffect, useLayoutEffect, useReducer, useRef, type RefObject } from "react";
import { decodeImage, prefersReducedMotion } from "../../lib/motion";
import { diffSigs, morph0, morphCls, morphNext, relMove, sigsKey, type MorphAction, type MorphPhase, type MorphState, type Moved, type Sigs } from "./morph";

export const MORPH_OUT = 120;
export const MORPH_MOVE = 240;
export const MORPH_IN = 240;
const EASE = "cubic-bezier(0.2, 0, 0, 1)";
/** Снимок, который меняется, ждём не дольше. */
const IMG_WAIT = 1200;

interface Snap { w: number; at: Map<Element, { x: number; y: number }>; surf: Map<Element, number> }

function snap(root: HTMLElement): Snap {
  const r = root.getBoundingClientRect();
  const at = new Map<Element, { x: number; y: number }>();
  root.querySelectorAll("[data-mv]").forEach((el) => {
    const b = el.getBoundingClientRect();
    at.set(el, { x: b.left - r.left, y: b.top - r.top });
  });
  const surf = new Map<Element, number>();
  root.querySelectorAll("[data-surf]").forEach((el) => surf.set(el, el.getBoundingClientRect().height));
  return { w: r.width, at, surf };
}

function play(el: Element, frames: Keyframe[]): void {
  const opts: KeyframeAnimationOptions = { duration: MORPH_MOVE, easing: EASE };
  try {
    el.animate(frames, { ...opts, composite: "add" });
  } catch {
    try {
      el.animate(frames, opts);
    } catch {
      /* без Web Animations — без хода */
    }
  }
}

/** Сдвинуть всё, что сместилось между `before` и тем, что сейчас, обратно на старое место и довести до нового. Что-то
 *  поехало — true. */
function flip(root: HTMLElement, before: Snap): boolean {
  const after = snap(root);
  if (Math.abs(after.w - before.w) > 0.5) return false;
  const moved = new Map<Element, Moved>();
  for (const [el, b] of after.at) {
    const a = before.at.get(el);
    if (a) moved.set(el, { dx: a.x - b.x, dy: a.y - b.y });
  }
  let any = false;
  for (const [el, m] of moved) {
    if (el.closest(".fx-hold")) continue; // невидимое не везём
    const up = el.parentElement?.closest("[data-mv]");
    const rel = relMove(m, up && root.contains(up) ? moved.get(up) ?? null : null);
    if (!rel) continue;
    play(el, [{ transform: `translate(${rel.dx}px, ${rel.dy}px)` }, { transform: "translate(0px, 0px)" }]);
    any = true;
  }
  for (const [el, h] of after.surf) {
    const h0 = before.surf.get(el);
    if (!h0 || !h || Math.abs(h0 - h) < 0.5) continue;
    play(el, [{ transform: `scaleY(${h0 / h})` }, { transform: "scaleY(1)" }]);
    any = true;
  }
  return any;
}

export interface Morph<V> {
  /** Что рисовать: во время хода — удержанное, в покое — то, что есть. */
  view: V;
  phase: MorphPhase;
  /** Класс части `id` (fx-out / fx-hold / fx-in) или ничего. */
  cls(id: string): string | undefined;
  /** На виду уже новое (подмена была или хода нет): фокус можно ставить. */
  fresh: boolean;
}

/** `view` — что показать, `sigs` — подписи его частей, `root` — обёртка частей (от неё меряются сдвиги), `images` —
 *  снимки в `view`, которые надо догрузить до проявления. */
export function useMorph<V>(view: V, sigs: Sigs, root: RefObject<HTMLElement | null>, images?: (v: V) => string[]): Morph<V> {
  const [s, dispatch] = useReducer(morphNext as (s: MorphState<V>, a: MorphAction<V>) => MorphState<V>, undefined, morph0<V>);
  const key = sigsKey(sigs);
  const rest = useRef({ view, sigs, key });
  const latest = useRef({ view, sigs });
  latest.current = { view, sigs };
  const st = useRef(s);
  st.current = s;
  const imgs = useRef(images);
  imgs.current = images;
  const painted = useRef(false);
  useEffect(() => {
    const raf = window.requestAnimationFrame(() => void (painted.current = true));
    return () => window.cancelAnimationFrame(raf);
  }, []);

  // новое в покое: в этом же кадре на виду ещё прежнее, изменившееся начинает гаснуть
  const starting = !s.phase && key !== rest.current.key && painted.current && !prefersReducedMotion();
  const cur = starting ? { phase: "out" as const, changed: diffSigs(rest.current.sigs, sigs) } : s;
  const shown = s.phase ? (s.held as V) : starting ? rest.current.view : view;

  useLayoutEffect(() => {
    if (s.phase === "out") return void dispatch({ type: "more", changed: diffSigs(s.heldSigs, sigs) });
    if (s.phase) return;
    if (starting) return void dispatch({ type: "start", held: rest.current.view, heldSigs: rest.current.sigs, changed: cur.changed });
    rest.current = { view, sigs, key };
  });

  const snapBefore = useRef<Snap | null>(null);
  const phase = s.phase;
  useEffect(() => {
    if (phase !== "out") return;
    const t = window.setTimeout(() => {
      snapBefore.current = root.current ? snap(root.current) : null;
      dispatch({ type: "swap", view: latest.current.view, sigs: latest.current.sigs });
    }, MORPH_OUT);
    return () => window.clearTimeout(t);
  }, [phase, root]);

  // подмена: всё сдвинувшееся доезжает, снимки догружаются, потом — проявление (не раньше следующего кадра: новое
  // должно успеть встать невидимым, иначе оно не проявится, а возникнет)
  useLayoutEffect(() => {
    if (phase !== "move") return;
    const el = root.current;
    const before = snapBefore.current;
    snapBefore.current = null;
    const moved = el && before ? flip(el, before) : false;
    let off = false;
    let t = 0;
    const held = st.current.held as V;
    const srcs = imgs.current ? imgs.current(held) : [];
    const loaded = Promise.race([
      Promise.allSettled(srcs.map(decodeImage)),
      new Promise((r) => window.setTimeout(r, IMG_WAIT)),
    ]);
    const timer = new Promise((r) => (t = window.setTimeout(r, moved ? MORPH_MOVE : 0)));
    void Promise.all([loaded, timer]).then(() => window.requestAnimationFrame(() => !off && dispatch({ type: "in" })));
    return () => {
      off = true;
      window.clearTimeout(t);
    };
  }, [phase, root]);

  useEffect(() => {
    if (phase !== "in") return;
    const t = window.setTimeout(() => {
      const cur = st.current;
      rest.current = { view: cur.held as V, sigs: cur.heldSigs, key: sigsKey(cur.heldSigs) };
      dispatch({ type: "end" });
    }, MORPH_IN);
    return () => window.clearTimeout(t);
  }, [phase]);

  return {
    view: shown,
    phase: cur.phase,
    cls: (id) => morphCls(cur, id),
    fresh: !starting && s.phase !== "out",
  };
}
