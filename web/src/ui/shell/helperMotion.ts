// Помощник: открытие и закрытие — заново, по холсту V2 («Создать (Play: весь путь)», блок «Помощник (модуль helper)»), и
// только transform и opacity (замечание владельца 18.10: «лагают тени, элементы, цвета»). Холст сужает колоду ходом
// сетки (ширина колонок каждый кадр) — здесь тот же вид движения собран из слоёв постоянного размера:
//
//   • колода во время хода — широкая, её раскладка не меняется ни в одном кадре хода; край колоды — «рельс» (`hp-rail`)
//     справа от неё: полоса края (`hp-band`, 48 px — копии фонов, теней и углов плит, без содержимого), под ней занавес
//     (`hp-cur`, цвет страницы, обрезает свою ширину) с плитой помощника внутри (`hp-ctr` — встречный ход: плита стоит на
//     своём месте) и тень края на плите помощника (`hp-shd`). Рельс едет translateX 0 → −416 (открытие 520 мс) и обратно
//     (закрытие 340 мс): край колоды, её углы и тени плит идут одним слоем, плита помощника открывается из-под края;
//   • то, что есть в обеих раскладках и стоит в них по-разному (помечено `data-hpm` — сдвиг, `data-hps` — сдвиг и масштаб
//     сцены), едет transform'ом к месту другой раскладки; места обеих раскладок замерены заранее (при наведении на
//     «Помощник» и ✕ — `prepareHelper`), в кадре нажатия — только сверка с замером. Лента миниатюр (`data-hpe`) у́же в
//     узкой раскладке — её правый край закрывает «ластик» цвета плиты, он едет вместе с краем ленты;
//   • то, что есть только в одной раскладке, гаснет и проявляется на месте (класс `hp-v` — «помощник открыт» для глаза,
//     helper.css: полный вид гаснет 240 мс, компактный проявляется 240 мс с 120; закрытие — 160 и 160 с 80), названия
//     шагов мельчают transform'ом;
//   • раскладка колоды меняется один раз, когда на экране уже всё стоит на её местах: в конце открытия и в начале
//     закрытия (`hp-nar`; переходы, которые запустила бы смена раскладки, снимаются — `settle`).
// Состояние React (`ui.helper`) догоняет ход в его конце, переходом React (startTransition): кадр нажатия — только
// классы и transform'ы, без перерисовки приложения. Пункт шапки «Помощник» читает намерение отсюда (`useHelperWant`).
import { startTransition, useSyncExternalStore } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { HELPER_COL } from "../deck/layout";
import { layoutRect } from "./stage";

/** Открытие, мс (холст: сетка 520). */
export const OPEN_MS = 520;
/** Закрытие, мс (холст: сетка 340 — 2/3 открытия). */
export const CLOSE_MS = 340;
/** Кривая холста. */
export const EASE = "cubic-bezier(0.2, 0, 0, 1)";
/** На сколько сужается колода: плита помощника 400 + зазор 16. */
export const CUT = HELPER_COL;
/** Запас таймера смены раскладки после конца хода (CSS-ход начинается с отрисовкой кадра, а не в обработчике). */
const TAIL_MS = 40;

export interface Box { x: number; y: number; w: number; h: number }

const r2 = (v: number) => Math.round(v * 100) / 100;

/** Сдвиг из места `a` в место `b` за вычетом сдвига помеченного предка `base`. */
export function shiftOf(a: Box, b: Box, base: { dx: number; dy: number } = { dx: 0, dy: 0 }): { dx: number; dy: number } {
  return { dx: r2(b.x - a.x - base.dx), dy: r2(b.y - a.y - base.dy) };
}

/** transform сдвига; null — на месте. */
export function moveCss(d: { dx: number; dy: number }): string | null {
  return Math.abs(d.dx) < 0.5 && Math.abs(d.dy) < 0.5 ? null : `translate(${d.dx}px, ${d.dy}px)`;
}

/** Сцена: из места `a` в место `b` сдвигом и масштабом по ширине; transform ставится обёртке `wrap` (её место в той же
 *  раскладке, что `a`), начало масштаба — левый верхний угол сцены в обёртке. */
export function scaleCss(a: Box, b: Box, wrap: Box): { transform: string; origin: string } | null {
  const s = a.w > 0 ? b.w / a.w : 1;
  const d = shiftOf(a, b);
  if (Math.abs(s - 1) < 0.002 && !moveCss(d)) return null;
  return { transform: `translate(${d.dx}px, ${d.dy}px) scale(${Math.round(s * 10000) / 10000})`, origin: `${r2(a.x - wrap.x)}px ${r2(a.y - wrap.y)}px` };
}

/** Ластик ленты: левый край — у правого края ленты (широкая раскладка `a`, узкая `b`), ширина — на сколько лента у́же (и
 *  запас под обводку миниатюр). `x`, `y` — место в широкой раскладке относительно плиты `plate`; `dx`, `dy` — ход к узкой. */
export function eraserOf(a: Box, b: Box, plate: Box): { x: number; y: number; w: number; h: number; dx: number; dy: number } | null {
  const cut = a.w - b.w;
  if (cut < 0.5) return null;
  return {
    x: r2(a.x + a.w - plate.x), y: r2(a.y - plate.y - 4), w: r2(cut + 16), h: r2(a.h + 8),
    dx: r2(b.x + b.w - (a.x + a.w)), dy: r2(b.y - a.y),
  };
}

/** «Растяжка» коробки шириной `wide` → `narrow` со скруглением `radius`: края по `r` (не больше половины узкой), середина
 *  от `r` шириной wide − 2r (+1 px нахлёста на правый край — без просвета) сжимается до narrow − 2r, правый край (`right`
 *  — его место в широкой) едет на `cut`. null — ширина та же. */
export function stretchOf(wide: number, narrow: number, radius: number): { r: number; mid: number; scale: number; right: number; cut: number } | null {
  const cut = wide - narrow;
  if (Math.abs(cut) < 0.5 || narrow <= 0) return null;
  const r = Math.max(0, Math.min(radius, narrow / 2, wide / 2));
  const mid = wide - 2 * r + 1;
  return { r: r2(r), mid: r2(mid), scale: Math.round(((narrow - 2 * r + 1) / mid) * 10000) / 10000, right: r2(wide - r), cut: r2(cut) };
}

/** Цвет обводки «inset 0 0 0 1px …» из computed box-shadow (обводка карточек и коробок); null — её нет. */
export function insetLine(shadow: string): string | null {
  if (!shadow || shadow === "none" || !/inset/.test(shadow)) return null;
  const m = shadow.match(/(rgba?\([^)]*\)|#[0-9a-f]{3,8})\s+0px\s+0px\s+0px\s+1px\s+inset|inset\s+0px\s+0px\s+0px\s+1px\s+(rgba?\([^)]*\)|#[0-9a-f]{3,8})/i);
  return m ? (m[1] ?? m[2]) : null;
}

/** Одинаковы ли места (замер ещё верен). */
export function sameBoxes(a: Box[], b: Box[]): boolean {
  return a.length === b.length && a.every((x, i) => Math.abs(x.x - b[i].x) < 0.5 && Math.abs(x.y - b[i].y) < 0.5 && Math.abs(x.w - b[i].w) < 0.5 && Math.abs(x.h - b[i].h) < 0.5);
}

// ── намерение (для пункта шапки)

let want = false;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const sub = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

/** Помощник открыт для глаза — меняется в кадре нажатия (состояние React — в конце хода). */
export function useHelperWant(): boolean {
  return useSyncExternalStore(sub, () => want, () => want);
}

// ── ход

interface Dom { root: HTMLElement; wrap: HTMLElement; band: HTMLElement }
interface Item { el: HTMLElement; scale: boolean; erase: boolean; stretch: boolean }
/** Стиль, нужный ходу (замерен заранее): фон, скругление и обводка коробки, стоит ли она в потоке, фон её плиты. */
interface Look { fill: string; radius: number; line: string | null; flow: boolean; plate: string }
interface Geo { items: Item[]; wide: Box[]; narrow: Box[]; wrapW: Box[]; plate: Box[]; look: Look[]; legacy: boolean }

let dom: Dom | null = null;
let commit: ((open: boolean) => void) | null = null;
/** Состояние React (`ui.helper`), как его видел ход. */
let state = false;
let running: { dir: "open" | "close"; timer: number; step2: number } | null = null;
let pending: boolean | null = null;
let geo: Geo | null = null;
/** Замер устарел: помеченное поменяло размер (ResizeObserver) или окно — другое. */
let stale = true;
/** До какого времени перемены размеров — от своей смены раскладки (замер их уже знает). */
let ownSwitch = 0;
let geoObs: ResizeObserver | null = null;
const sizes = new Map<Element, string>();
let prepared = 0;
let moves: Animation[] = [];
let erasers: HTMLElement[] = [];
let stretched: Array<{ el: HTMLElement; pos: string }> = [];

/** Множитель длительностей (только для проверки кадров: `--hp-k` в стиле страницы) — без пересчёта стилей. */
function speed(): number {
  const v = Number(dom?.root.style.getPropertyValue("--hp-k").trim());
  return v > 0 ? v : 1;
}

const visible = (el: Element) => el.getClientRects().length > 0;

/** Помеченное в шагах и слоях, что сейчас на экране (скрытое — `p2-off` — не едет); без чтения раскладки. */
function marked(wrap: HTMLElement): HTMLElement[] {
  return Array.from(wrap.querySelectorAll<HTMLElement>("[data-hpm],[data-hps],[data-hpk]")).filter((el) => !el.closest(".p2-off"));
}

function items(wrap: HTMLElement): Item[] {
  return marked(wrap).filter(visible)
    .map((el) => ({ el, scale: el.hasAttribute("data-hps"), erase: el.hasAttribute("data-hpe"), stretch: el.hasAttribute("data-hpk") }));
}

function boxOf(el: Element, o: { left: number; top: number }): Box {
  const r = layoutRect(el);
  return { x: r2(r.left - o.left), y: r2(r.top - o.top), w: r2(r.width), h: r2(r.height) };
}

/** Места помеченного в этой раскладке: сам элемент (у сцены — её первый ребёнок), обёртка сцены, плита. */
function read(wrap: HTMLElement, its: Item[]): { at: Box[]; wrapAt: Box[]; plate: Box[] } {
  const o = layoutRect(wrap);
  return {
    at: its.map((it) => boxOf(it.scale ? (it.el.firstElementChild ?? it.el) : it.el, o)),
    wrapAt: its.map((it) => boxOf(it.el, o)),
    plate: its.map((it) => boxOf(it.el.closest(".p2-plate") ?? wrap, o)),
  };
}

/** Переходы, которые запустила смена раскладки (ширины, дорожки сеток, кегли прежнего «перестроения каждый кадр» на
 *  экранах, где оно ещё осталось), снимаются: раскладка встаёт разом. getAnimations сам пересчитывает стили — переходы
 *  уже заведены; снятый переход оставляет конечное значение. Только внутри колоды. Ответ — сколько снято. */
function settle(): number {
  const deck = dom?.wrap.querySelector(".p2-deck");
  if (!deck) return 0;
  let n = 0;
  for (const a of document.getAnimations()) {
    if (!("transitionProperty" in a)) continue;
    const t = (a.effect as KeyframeEffect | null)?.target;
    if (t && deck.contains(t)) {
      a.cancel();
      n++;
    }
  }
  return n;
}

function lookOf(it: Item): Look {
  const cs = getComputedStyle(it.el);
  const plateEl = it.el.closest(".p2-plate");
  return {
    fill: cs.backgroundColor, radius: parseFloat(cs.borderTopRightRadius) || 0, line: insetLine(cs.boxShadow),
    flow: cs.position === "static", plate: plateEl ? getComputedStyle(plateEl).backgroundColor : "transparent",
  };
}

/** Замер обеих раскладок: другая ставится на один пересчёт (её переходы снимаются) и снимается; прокрутка лент — на
 *  месте. Заодно — стиль коробок (ходу в кадре нажатия ничего не нужно читать) и запускает ли смена раскладки переходы
 *  прежнего «перестроения» (`legacy`: тогда их снимать и в ходе). */
function measure(): Geo | null {
  if (!dom) return null;
  // заготовленные «растяжки» прятали фон коробок — замер стиля без них
  unprep();
  const { wrap } = dom;
  const its = items(wrap);
  const nar = wrap.classList.contains("hp-nar");
  const films = Array.from(wrap.querySelectorAll<HTMLElement>(".p2-film")).map((el) => [el, el.scrollLeft] as const);
  const look = its.map(lookOf);
  const a = read(wrap, its);
  wrap.classList.toggle("hp-nar");
  let legacy = settle() > 0;
  const b = read(wrap, its);
  wrap.classList.toggle("hp-nar");
  legacy = settle() > 0 || legacy;
  films.forEach(([el, s]) => {
    if (el.scrollLeft !== s) el.scrollLeft = s;
  });
  const w = nar ? b : a;
  const n = nar ? a : b;
  watchGeo(its);
  stale = false;
  return { items: its, wide: w.at, narrow: n.at, wrapW: w.wrapAt, plate: w.plate, look, legacy };
}

/** Замер устаревает, когда помеченное меняет размер (текст, вариант, окно). */
function watchGeo(its: Item[]) {
  geoObs?.disconnect();
  sizes.clear();
  geoObs = new ResizeObserver((es) => {
    for (const e of es) {
      const k = `${Math.round(e.contentRect.width)}x${Math.round(e.contentRect.height)}`;
      const was = sizes.get(e.target);
      if (was !== undefined && was !== k && performance.now() > ownSwitch) stale = true;
      sizes.set(e.target, k);
    }
  });
  for (const it of its) geoObs.observe(it.scale ? (it.el.firstElementChild ?? it.el) : it.el);
}

/** Замер верен, если на экране те же помеченные элементы и ни один не менял размер — без чтения раскладки. */
function fresh(): Geo | null {
  if (!dom || !geo || stale) return null;
  const els = marked(dom.wrap);
  if (els.length !== geo.items.length || els.some((el, i) => el !== geo!.items[i].el)) return null;
  return geo;
}

/** Полоса края колоды: живые копии мест плит и слоёв (без содержимого и входа) в ширину колоды; видна их правая
 *  полоса 48 px — фоны, тени и углы плит у края ровно те же, что у колоды. Копии повторяют места (transform, классы —
 *  а с ними и переходы) в том же кадре, что и плиты: плиты едут — копии едут вместе с ними. */
const copies = new Map<Element, { slot: HTMLElement; plate: HTMLElement | null; shade: HTMLElement | null }>();
let bandObs: MutationObserver | null = null;
let bandSize: ResizeObserver | null = null;

function copyAttrs(from: HTMLElement, to: HTMLElement, plate: boolean) {
  if (to.className !== from.className) to.className = from.className;
  to.style.cssText = from.style.cssText;
  to.style.animation = "none";
  if (plate) {
    to.style.padding = "0";
    to.style.boxShadow = "none";
  }
}

/** Тень копии плиты — отдельно от её фона (`hp-bsh`): тень коробки, продлённой за край колоды, — в левой части полосы
 *  она та же, что у широкой плиты под полосой (без ступеньки на границе полосы), а к краю гаснет маской, как у угла
 *  плиты. Сама копия плиты — фон и углы, без тени. */
function copyShade(from: HTMLElement, shade: HTMLElement) {
  const sh = getComputedStyle(from).boxShadow;
  const box = shade.firstElementChild as HTMLElement;
  const want = sh && sh !== "none" ? sh : "none";
  if (box.style.boxShadow !== want) box.style.boxShadow = want;
  shade.style.display = want === "none" ? "none" : "";
}

function syncBand() {
  if (!dom) return;
  const { wrap, band } = dom;
  const deck = wrap.querySelector<HTMLElement>(".p2-deck");
  if (!deck) return;
  const slots = Array.from(deck.children).filter((x): x is HTMLElement => x instanceof HTMLElement && x.classList.contains("p2-slot"));
  for (const [k, c] of copies) {
    if (!slots.includes(k as HTMLElement)) {
      c.slot.remove();
      copies.delete(k);
    }
  }
  let prev: HTMLElement | null = null;
  for (const slot of slots) {
    let c = copies.get(slot);
    const first = slot.firstElementChild instanceof HTMLElement ? slot.firstElementChild : null;
    if (!c) {
      const cs = document.createElement("div");
      c = { slot: cs, plate: null, shade: null };
      copies.set(slot, c);
    }
    copyAttrs(slot, c.slot, false);
    if (first) {
      if (!c.shade) {
        c.shade = document.createElement("div");
        c.shade.className = "hp-bsh";
        c.shade.appendChild(document.createElement("i"));
        c.slot.appendChild(c.shade);
      }
      if (!c.plate) {
        c.plate = document.createElement("div");
        c.slot.appendChild(c.plate);
      }
      copyAttrs(first, c.plate, true);
      copyShade(first, c.shade);
    } else {
      c.plate?.remove();
      c.shade?.remove();
      c.plate = null;
      c.shade = null;
    }
    // порядок копий — порядок мест (одинаковый z-index рисуется по порядку)
    if ((prev ? prev.nextSibling : band.firstChild) !== c.slot) band.insertBefore(c.slot, prev ? prev.nextSibling : band.firstChild);
    prev = c.slot;
  }
  watchBand(deck, slots);
}

/** Следить за местами: их атрибуты (transform, классы), атрибуты их плит, состав колоды. */
function watchBand(deck: HTMLElement, slots: HTMLElement[]) {
  bandObs?.disconnect();
  bandObs = new MutationObserver(syncBand);
  bandObs.observe(deck, { childList: true });
  for (const sl of slots) {
    bandObs.observe(sl, { attributes: true, attributeFilter: ["style", "class"], childList: true });
    if (sl.firstElementChild) bandObs.observe(sl.firstElementChild, { attributes: true, attributeFilter: ["style", "class"] });
  }
  if (!bandSize) {
    // ширина копий — колоды (меняется только с окном)
    bandSize = new ResizeObserver(() => {
      if (dom) dom.band.style.width = `${deck.offsetWidth}px`;
    });
    bandSize.observe(deck);
  }
}

/** Ход помеченного: каждый к месту другой раскладки — анимацией (Web Animations: начало и конец заданы явно, пересчёт
 *  стилей между ними не нужен). Открытие: из своего места (широкая раскладка) к узкому, и стоит там до смены раскладки;
 *  закрытие: из узкого места к своему (раскладка уже широкая). */
function place(g: Geo, ms: number, toNarrow: boolean, paused: boolean) {
  const its = g.items;
  const d = its.map((_, i) => shiftOf(g.wide[i], g.narrow[i]));
  const kf = (t: string) => (toNarrow ? [{ transform: "none" }, { transform: t }] : [{ transform: t }, { transform: "none" }]);
  const timing: KeyframeAnimationOptions = { duration: ms, easing: EASE, fill: "forwards" };
  if (prep && (prep.geo !== g || prep.toNarrow !== toNarrow || prep.ms !== ms)) unprep();
  moves = [];
  erasers = [];
  // анимации заводятся сразу; на паузе (закрытие) — стоят в начале до следующего кадра
  const done0 = () => {
    if (paused) for (const m of moves) if (m.playState !== "paused") m.pause();
  };
  its.forEach((it, i) => {
    const el = it.el;
    // сдвиг помеченного предка уже несёт элемент — свой сдвиг за его вычетом
    let base = { dx: 0, dy: 0 };
    for (let p = el.parentElement; p && p !== dom!.wrap; p = p.parentElement) {
      const j = its.findIndex((x) => x.el === p);
      if (j >= 0 && !its[j].scale) {
        base = d[j];
        break;
      }
    }
    let transform: string | null;
    let origin = "0 0";
    if (it.scale) {
      const s = scaleCss(g.wide[i], g.narrow[i], g.wrapW[i]);
      transform = s?.transform ?? null;
      origin = s?.origin ?? origin;
    } else transform = moveCss(shiftOf(g.wide[i], g.narrow[i], base));
    if (transform) {
      el.style.willChange = "transform";
      el.style.transformOrigin = origin;
      moves.push(el.animate(kf(transform), timing));
    }
    if (it.stretch) {
      const ready = prep && prep.geo === g && prep.toNarrow === toNarrow && prep.ms === ms ? prep.map.get(el) : undefined;
      const anims = ready ?? stretch(el, g.wide[i], g.narrow[i], g.look[i], kf, timing);
      if (ready && !paused) for (const a of ready) a.play();
      moves.push(...anims);
    }
    if (it.erase) {
      const plateEl = el.closest<HTMLElement>(".p2-plate");
      const e = eraserOf(g.wide[i], g.narrow[i], g.plate[i]);
      if (plateEl && e) {
        const x = document.createElement("i");
        x.className = "hp-erase";
        x.setAttribute("aria-hidden", "true");
        x.style.cssText = `left:${e.x}px;top:${e.y}px;width:${e.w}px;height:${e.h}px;background:${g.look[i].plate}`;
        plateEl.appendChild(x);
        erasers.push(x);
        moves.push(x.animate(kf(`translate(${e.dx}px, ${e.dy}px)`), timing));
      }
    }
  });
  done0();
  prep = null;
}

/** Коробка, которая в узкой раскладке у́же (поле текста, карточки вариантов, степпер): её фон и обводка на время хода —
 *  три куска постоянного размера (`stretchOf`): левый край стоит, середина сжимается scaleX, правый край едет. Сама
 *  коробка — без фона (`hp-k`), её содержимое — над кусками. */
function stretch(el: HTMLElement, a: Box, b: Box, look: Look, kf: (t: string) => Keyframe[], timing: KeyframeAnimationOptions): Animation[] {
  const out: Animation[] = [];
  const k = stretchOf(a.w, b.w, look.radius);
  if (!k) return out;
  const { line, fill } = look;
  stretched.push({ el, pos: el.style.position });
  if (look.flow) el.style.position = "relative";
  el.classList.add("hp-k");
  const mk = (cls: string, css: string) => {
    const x = document.createElement("i");
    x.className = `hp-kp ${cls}`;
    x.setAttribute("aria-hidden", "true");
    x.style.cssText = `${css};background:${fill}${line ? `;border:1px solid ${line}` : ""}`;
    el.insertBefore(x, el.firstChild);
    return x;
  };
  const r = k.r;
  // поле текста (`data-hpk="cover"`): правый край — над текстом, а за ним до края плиты — «шторка» цвета плиты: текст,
  // который уже (или ещё) свёрстан шире видимой коробки, не выходит за её край
  const cover = el.dataset.hpk === "cover";
  if (cover) {
    const ext = mk("hp-kx", `left:${k.right + r}px;width:${k.cut + 48}px;z-index:1;border-radius:0`);
    ext.style.background = look.plate;
    ext.style.border = "0";
    out.push(ext.animate(kf(`translateX(${-k.cut}px)`), timing));
  }
  const right = mk("hp-kr", `left:${k.right}px;width:${r}px;border-radius:0 ${r}px ${r}px 0${line ? ";border-left:0" : ""}${cover ? ";z-index:1" : ""}`);
  const mid = mk("hp-km", `left:${r}px;width:${k.mid}px;transform-origin:0 0${line ? ";border-left:0;border-right:0" : ""}`);
  mk("hp-kl", `left:0;width:${r}px;border-radius:${r}px 0 0 ${r}px${line ? ";border-right:0" : ""}`);
  out.push(mid.animate(kf(`scaleX(${k.scale})`), timing));
  out.push(right.animate(kf(`translateX(${-k.cut}px)`), timing));
  return out;
}

/** «Растяжки», заведённые заранее (наведение на «Помощник»): куски стоят в начале своего хода на паузе — коробка выглядит
 *  как была, а в кадре нажатия им остаётся только поехать (вставка кусков и перерисовка коробок — до нажатия). */
let prep: { geo: Geo; toNarrow: boolean; ms: number; map: Map<HTMLElement, Animation[]> } | null = null;

function kfOf(toNarrow: boolean) {
  return (t: string): Keyframe[] => (toNarrow ? [{ transform: "none" }, { transform: t }] : [{ transform: t }, { transform: "none" }]);
}

function prepStretch(g: Geo) {
  if (!dom) return;
  const toNarrow = !dom.wrap.classList.contains("hp-v");
  const ms = Math.round((toNarrow ? OPEN_MS : CLOSE_MS) * speed());
  if (prep && prep.geo === g && prep.toNarrow === toNarrow && prep.ms === ms) return;
  unprep();
  const timing: KeyframeAnimationOptions = { duration: ms, easing: EASE, fill: "forwards" };
  const map = new Map<HTMLElement, Animation[]>();
  g.items.forEach((it, i) => {
    if (!it.stretch) return;
    const anims = stretch(it.el, g.wide[i], g.narrow[i], g.look[i], kfOf(toNarrow), timing);
    for (const a of anims) a.pause();
    map.set(it.el, anims);
  });
  prep = { geo: g, toNarrow, ms, map };
}

/** Заготовка не пригодилась (наведение ушло, замер устарел): куски снимаются, коробки — со своим фоном. */
function unprep() {
  if (!prep) return;
  for (const anims of prep.map.values()) for (const a of anims) a.cancel();
  const els = new Set(prep.map.keys());
  stretched = stretched.filter(({ el, pos }) => {
    if (!els.has(el)) return true;
    el.classList.remove("hp-k");
    el.style.position = pos;
    el.querySelectorAll(":scope > .hp-kp").forEach((x) => x.remove());
    return false;
  });
  prep = null;
}

/** Ход кончился: анимации, ластики и подсказки слоёв снимаются (раскладка уже та же, что их конечные места). */
function clearPlaced() {
  for (const a of moves) a.cancel();
  for (const x of erasers) x.remove();
  for (const { el, pos } of stretched) {
    el.classList.remove("hp-k");
    el.style.position = pos;
    el.querySelectorAll(":scope > .hp-kp").forEach((x) => x.remove());
  }
  stretched = [];
  for (const el of Array.from(dom?.wrap.querySelectorAll<HTMLElement>("[data-hpm],[data-hps]") ?? [])) {
    el.style.transformOrigin = "";
    el.style.willChange = "";
  }
  moves = [];
  erasers = [];
}

function done(open: boolean) {
  running = null;
  // указатель всё ещё на «Помощнике» или ✕ — следующий ход готовится заранее (позже, не в кадре смены раскладки)
  if (dom?.wrap.classList.contains("hp-prep")) {
    const at = prepared;
    window.setTimeout(() => {
      if (dom && !running && prepared === at && dom.wrap.classList.contains("hp-prep")) prepareHelper();
    }, 200);
  }
  if (open !== state) {
    state = open;
    const c = commit;
    if (c) startTransition(() => c(open));
  }
  if (pending !== null && pending !== open) {
    const next = pending;
    pending = null;
    go(next);
  } else pending = null;
}

/** Открытие. Кадр нажатия: край колоды, плита помощника, тень края, ход помеченного, гашение полного вида и названия
 *  шагов; следующим кадром (`hp-v2`) — то, что проявляется с задержкой (компактный вид, каскад помощника): первый кадр
 *  хода легче. Через 520 мс раскладка становится узкой. */
function open() {
  if (!dom) return;
  const { wrap } = dom;
  const ms = Math.round(OPEN_MS * speed());
  const g = fresh() ?? measure();
  geo = g;
  if (g) place(g, ms, true, false);
  wrap.classList.add("hp-run", "hp-v");
  // следующий кадр после кадра нажатия (нажатие приходит и между кадрами, и из rAF — два rAF надёжно дают «следующий»)
  const run = { dir: "open" as const, step2: 0, timer: 0 };
  run.step2 = requestAnimationFrame(() => {
    run.step2 = requestAnimationFrame(() => wrap.classList.add("hp-v2"));
  });
  running = run;
  run.timer = window.setTimeout(() => {
    if (!dom) return;
    const w = dom.wrap;
    // раскладка — узкая, разом: на экране всё уже на её местах
    ownSwitch = performance.now() + 250;
    w.classList.add("hp-nar", "hp-v2");
    w.classList.remove("hp-run");
    clearPlaced();
    if (!geo || geo.legacy) settle();
    // курсор — в поле помощника (следующим кадром: кадр смены раскладки — только она)
    requestAnimationFrame(() => w.querySelector<HTMLTextAreaElement>("#hp-help .gh-ta")?.focus({ preventScroll: true }));
    done(true);
  }, ms + TAIL_MS);
}

/** Закрытие. Кадр нажатия: раскладка — широкая, разом (переходы, которые она запустила бы, снимаются), помеченное
 *  стоит на узких местах (анимации на паузе в начале), на экране ничего не меняется; следующим кадром — ход: помеченное
 *  едет к своим местам, край колоды накрывает плиту помощника, компактный вид гаснет, полный проявляется. Смена
 *  раскладки и начало хода — в разных кадрах. */
function close() {
  if (!dom) return;
  const { wrap } = dom;
  const ms = Math.round(CLOSE_MS * speed());
  const g = fresh() ?? measure();
  geo = g;
  ownSwitch = performance.now() + 250;
  wrap.classList.add("hp-run");
  wrap.classList.remove("hp-nar");
  if (!g || g.legacy) settle();
  if (g) place(g, ms, false, true);
  const run = { dir: "close" as const, step2: 0, timer: 0 };
  const go2 = () => {
    if (!dom || running !== run) return;
    for (const m of moves) m.play();
    dom.wrap.classList.remove("hp-v", "hp-v2");
    run.timer = window.setTimeout(endClose, ms + TAIL_MS);
  };
  run.step2 = requestAnimationFrame(() => {
    run.step2 = requestAnimationFrame(go2);
  });
  running = run;
  // фокус из плиты помощника — на пункт шапки (следующим кадром: кадр нажатия — только ход)
  const help = wrap.querySelector("#hp-help");
  if (help?.contains(document.activeElement)) requestAnimationFrame(() => document.getElementById("hp-nav")?.focus({ preventScroll: true }));
}

function endClose() {
  if (!dom) return;
  dom.wrap.classList.remove("hp-run");
  clearPlaced();
  done(false);
}

/** Без хода (уменьшить движение): раскладка и вид — сразу. */
function jump(to: boolean) {
  if (!dom) return;
  const { wrap } = dom;
  wrap.classList.toggle("hp-v", to);
  wrap.classList.toggle("hp-v2", to);
  wrap.classList.toggle("hp-nar", to);
  settle();
  done(to);
}

/** Пункт шапки «Помощник» — сразу, без перерисовки React (его className React потом поставит тот же: `useHelperWant`). */
function navNow(to: boolean) {
  const nav = document.getElementById("hp-nav");
  if (!nav) return;
  nav.classList.toggle("p2-nav-on", to);
  nav.setAttribute("aria-expanded", String(to));
  nav.title = to ? "Закрыть помощника" : "Открыть помощника";
}

function go(to: boolean) {
  if (want !== to) {
    want = to;
    navNow(to);
    // React узнаёт о перемене после кадра нажатия
    window.setTimeout(emit, 0);
  }
  if (!dom) return;
  if (running) {
    // ход идёт — следующий начнётся, когда он доиграет
    pending = to;
    return;
  }
  const now = dom.wrap.classList.contains("hp-v");
  if (now === to) return done(to);
  if (prefersReducedMotion()) return jump(to);
  if (to) open();
  else close();
}

/** Открыть или закрыть помощника (пункт шапки, ✕, Esc): ход начинается в этом же кадре. */
export function setHelper(open: boolean) {
  go(open);
}

/** Переключить помощника. */
export function toggleHelper() {
  go(!want);
}

/** Состояние React изменилось не отсюда (помощник закрылся из чата, из другого места): ход к нему. */
export function syncHelper(open: boolean) {
  state = open;
  if (open !== want || (!running && dom && dom.wrap.classList.contains("hp-v") !== open)) go(open);
}

/** Подготовка хода (наведение, фокус на «Помощник» или ✕): замер обеих раскладок и слои хода — до нажатия. */
export function prepareHelper() {
  if (!dom || running || prefersReducedMotion()) return;
  if (!fresh()) geo = measure();
  prepared = performance.now();
  dom.wrap.classList.add("hp-prep");
  if (geo) prepStretch(geo);
}

/** Наведение ушло без нажатия: слои хода больше не держатся. */
export function releaseHelper() {
  if (!dom || running) return;
  const at = prepared;
  window.setTimeout(() => {
    if (!dom || running || prepared !== at) return;
    dom.wrap.classList.remove("hp-prep");
    unprep();
  }, 600);
}

/** Обёртка колоды на месте: состояние без хода, `onCommit` — как сообщить его React. */
export function attachHelper(d: Dom, open: boolean, onCommit: (open: boolean) => void): () => void {
  dom = d;
  commit = onCommit;
  state = open;
  want = open;
  d.wrap.classList.toggle("hp-v", open);
  d.wrap.classList.toggle("hp-v2", open);
  d.wrap.classList.toggle("hp-nar", open);
  syncBand();
  emit();
  const onResize = () => {
    stale = true;
  };
  window.addEventListener("resize", onResize);
  return () => {
    window.removeEventListener("resize", onResize);
    geoObs?.disconnect();
    geoObs = null;
    bandObs?.disconnect();
    bandObs = null;
    bandSize?.disconnect();
    bandSize = null;
    copies.clear();
    d.band.replaceChildren();
    if (running) {
      window.clearTimeout(running.timer);
      cancelAnimationFrame(running.step2);
    }
    running = null;
    pending = null;
    if (dom === d) {
      dom = null;
      commit = null;
      geo = null;
    }
  };
}
