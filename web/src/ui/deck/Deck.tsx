// Колода «Слоёв»: четыре плиты одна над другой (01 шаблон, 02 текст, 03 параметры и запуск → сборка, 04 результат)
// и слои поверх. Где стоит каждая плита и что видно — `deckGeometry(ui)`; плиты ездят 520 мс (`.p2-slot`).
// Разметка — boards/V2.dc.html, `<main class="p2-deck">`. Содержимое плит и слоёв приносят задачи своих областей
// через пропсы-слоты; сама колода рисует места плит, полосы, большие номера и заголовки шагов.
// Помощник сужает колоду: места плит не меняют ширину никогда, у́же становится их содержимое (поле справа + 416,
// helper.css `hp-nar`) — один раз, в конце открытия и в начале закрытия; на глазах всё едет transform'ом и гаснет
// прозрачностью (ui/shell/helperMotion.ts; create.css, блок «Колода, суженная помощником»), название шага сжимается
// transform'ом (StepTitle). Ничего, что есть в обеих раскладках, не гаснет.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { LAYER_MS } from "../layers/Layer";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { DECK_H, deckGeometry, type Geometry } from "./geometry";
import { Plate } from "./Plate";
import { Strip, type StripData } from "./Strip";
import { DeckFitContext, DeckWrapContext, useDeckLayout, useWrapWidth } from "./useDeckFit";
import { phoneGeometry, stackGeometry } from "./stack";
import { useHeldHeight, useStackMetrics } from "./useStackMetrics";
import { helperBeside, isPhone, isStack, useTier } from "../shell/tier";
import { openSheets } from "../shell/sheets";
import { scrollFor, stackTarget, useScrollLock } from "../shell/modal";

export interface DeckProps {
  /** Ряд заголовка плиты после кнопки «номер + название»: всё, что справа (кнопки, обложка, сводка, CTA).
   *  Распорку `<span style={{ flex: 1, minWidth: 0 }} />` слот ставит сам там, где она нужна по V2. */
  h1?: ReactNode; h2?: ReactNode; h3?: ReactNode;
  /** Тела шагов «Создать» под рядом заголовка (`#p2-b1`, `#p2-b2`, `#p2-b3` + «Все параметры»); гаснут и проявляются
   *  вместе с заголовком. */
  p1?: ReactNode; p2?: ReactNode; p3?: ReactNode;
  /** Стрелка «Все параметры» под «03» (стоит рядом с цифрой). */
  m3?: ReactNode;
  /** Плита 03 на «Сборке» — после заголовка «Создать», который там снят. */
  b3?: ReactNode;
  /** Телефон: плита 03 «Создать» целиком (доска M-create: сводка, «Параметры», кнопка; «Все параметры» под ними) —
   *  вместо заголовка `h3`, тела `p3` и стрелки `m3`. */
  q3?: ReactNode;
  /** Плита 04 — результат. */
  p4?: ReactNode;
  /** Полосы свёрнутых плит 01, 02 (сборка, результат, «Все параметры») и 03 (результат). */
  s1?: StripData; s2?: StripData; s3?: StripData;
  /** Слои поверх плит внутри колоды (z ≥ 5), а также полосы колоды вроде «01 Итоги квартала.pptx» (z 1). */
  layers?: ReactNode;
}

const S4: Record<Geometry["s4"], string> = {
  on: "p2-s4-on", up: "p2-s4-on p2-s4-up", off: "p2-s4-off", down: "p2-s4-off p2-s4-down",
};
const show = (on: boolean) => (on ? "p2-on" : "p2-off");
/** Возврат на «Создать»: заголовок плиты 03 монтируется скрытым и со следующего кадра проявляется (V2 `enter3`). */
const ENTER_MS = 34;
/** Плита результата уходит вниз 520 мс; флаг `down` снимается, когда она ушла за край (V2 `go('create')`: 560 мс). */
const DOWN_MS = LAYER_MS + 40;
/** Стопкой после смены экрана или шага: столько страница ещё следует за местом нужной плиты, если оно уточняется. */
const SCROLL_WINDOW = 1000;

/** Название шага: место в ряду заголовка держит невидимая мерка (её кегль 32 → 24 px идёт той же кривой), видимое
 *  название поверх неё сжимается до 24 px transform'ом (scale .75 от левого края) вместе с колодой — create.css
 *  `.p2-ttl-sz`, `.p2-ttl-v` по `.hp-nar`. */
function StepTitle({ text, color }: { text: string; color: string }) {
  return (
    <span className="p2-ttl-box">
      <span className="p2-ttl p2-ttl-sz" aria-hidden="true">{text}</span>
      <span className="p2-ttl p2-ttl-v" style={{ color }}>{text}</span>
    </span>
  );
}

/** Содержимое шага (`p2-fxbox`, create.css): место плиты целиком, поля — внутри; ширина — плиты в этом кадре. */
function StepBox({ on, children }: { on: boolean; children: ReactNode }) {
  // стопкой содержимое шага — своей высоты от верха плиты (stack.css), колода меряет низ шапки и низ тела
  return <div className={cls("p2-fxbox", show(on))}>{children}</div>;
}

export function Deck({ h1, h2, h3, p1, p2, p3, m3, b3, q3, p4, s1, s2, s3, layers }: DeckProps) {
  const { ui, dispatch } = useApp();
  const g = deckGeometry(ui);
  // помощник сужает колоду. «Создать», «Сборка», слои и лист «Подробнее» перестраиваются вместе с ней (CSS по `.hp-nar`),
  // обе их раскладки считаются по ширине обёртки (DeckWrapContext); раскладку по цели хода (useDeckLayout, DeckFitContext)
  // читает только «Результат» — его шапка и подпись CTA компактного вида сменяются своим перекрёстным затуханием
  // содержимое колоды встаёт только после замера обёртки (`wrap` не null): сразу в настоящей ширине
  const deckRef = useRef<HTMLElement>(null);
  const wrap = useWrapWidth(deckRef);
  const width = wrap ?? 0;
  // окно уже 1280 — колода стопкой (ui/shell/tier.ts): помощник её не сужает, места плит — по высотам содержимого
  const tier = useTier();
  const stack = isStack(tier);
  // телефон (доски M-create, M-build, M-result): колода во весь экран под шапкой, плиты — на местах досок, содержимое
  // прокручивается внутри своей плиты (`--vis`, stack.css); шаги — свёрнутые ряды и полосы телефона
  const phone = isPhone(tier);
  const layout = useDeckLayout(deckRef, ui.helper && helperBeside(tier), width);
  const metrics = useStackMetrics(deckRef, stack && wrap !== null, phone);
  const sg = stack && metrics ? (phone ? phoneGeometry(ui, metrics) : stackGeometry(ui, metrics)) : null;
  const ys = sg ? sg.y : g.y;
  const vis = sg?.vis;
  const height = useHeldHeight(sg ? sg.height : DECK_H);
  // первая раскладка стопкой (и смена ступени) встаёт на место без хода плит: им неоткуда ехать
  const snapKey = `${tier}/${sg ? 1 : 0}`;
  const [settledKey, setSettledKey] = useState(snapKey);
  const snap = settledKey !== snapKey;
  useEffect(() => {
    if (!snap) return;
    let r2 = 0;
    const r1 = window.requestAnimationFrame(() => {
      r2 = window.requestAnimationFrame(() => setSettledKey(snapKey));
    });
    return () => {
      window.cancelAnimationFrame(r1);
      window.cancelAnimationFrame(r2);
    };
  }, [snap, snapKey]);
  const create = ui.screen === "create";
  const more = create && ui.more;
  const tplOpen = create && ui.open === "tpl";
  // телефон, раскрыт шаблон: плита 02 — полоса над прижатой плитой 03 (на компьютере — её шапка со свёрнутым текстом)
  const strip2 = phone && tplOpen;

  // V2 `go('create')`: с другого экрана содержимое «Создать» в плите 03 встаёт скрытым и проявляется так же плавно,
  // как заголовки 01 и 02 (переход p2-off → p2-on)
  const [seen, setSeen] = useState(ui.screen);
  const [enter3, setEnter3] = useState(false);
  if (seen !== ui.screen) {
    setSeen(ui.screen);
    setEnter3(create);
  }
  useEffect(() => {
    if (!enter3) return;
    const t = window.setTimeout(() => setEnter3(false), ENTER_MS);
    return () => window.clearTimeout(t);
  }, [enter3]);
  // с результата на «Создать» (любым путём) `go` ставит `down`: плита 04 уходит вниз непрозрачной со своим содержимым;
  // один таймер снимает флаг, когда она ушла за край
  useEffect(() => {
    if (!ui.down) return;
    const t = window.setTimeout(() => dispatch({ type: "set", patch: { down: false } }), DOWN_MS);
    return () => window.clearTimeout(t);
  }, [ui.down, dispatch]);
  // содержимое «Создать» в плите 03 стоит, пока открыт «Создать», и доигрывает уход, пока плита результата
  // поднимается из «Создать» (`rise`; в V2 `keep3` ставится и снимается вместе с `rise`)
  const c3 = create || ui.rise;
  const head3 = create && !enter3;
  // заголовки 01 и 02 проявляются в том же кадре, что «03» и содержимое плиты 03 (возврат на «Создать»: все три ждут enter3)
  const heads = g.heads && !enter3;
  // стопкой поверх колоды — слой или помощник (плита снизу, под ней затемнение): плиты колоды и шапка под ним не
  // принимают фокус и не читаются (inert) — Tab ходит только по плите сверху; страница под ней не прокручивается. На
  // компьютере слои и помощник — в колоде и рядом, так не делается. inert ставится в layout-эффекте: слой уже запомнил,
  // что его открыло (ui/shell/modal.ts `useFocusReturn` — его layout-эффект раньше), и вернёт фокус, когда закроется
  const covered = stack && openSheets(ui).length > 0;
  useLayoutEffect(() => {
    const el = deckRef.current;
    if (!el) return;
    const hdr = el.closest(".p2-root")?.querySelector<HTMLElement>(".p2-hdr");
    const under = [...el.querySelectorAll<HTMLElement>(":scope > .p2-slot:not(.p2-lay)"), ...(hdr ? [hdr] : [])];
    for (const s of under) {
      if (covered) s.setAttribute("inert", "");
      else s.removeAttribute("inert");
    }
  }, [covered, wrap]);
  useScrollLock(covered);
  // смена экрана или шага стопкой: плита, которую надо видеть (новый экран, раскрытый шаг), выше окна — страница едет к
  // её верху (плавно; без движения — сразу). Телефон: колода во весь экран и страница не прокручивается
  // (её место может уточниться и после смены: «Изменить текст» у презентации с данными сворачивает плиту 01, когда
  // данные вернулись, — страница доезжает до нового места, пока не прошло SCROLL_WINDOW)
  const target = stackTarget(ui);
  const targetKey = `${ui.screen}/${ui.open}/${ui.more ? 1 : 0}`;
  const targetY = sg && !phone ? sg.y[target] : null;
  const seenKey = useRef(targetKey);
  const changedAt = useRef(-Infinity);
  useEffect(() => {
    if (seenKey.current === targetKey) return;
    seenKey.current = targetKey;
    changedAt.current = performance.now();
  }, [targetKey]);
  useEffect(() => {
    const el = deckRef.current;
    if (!el || targetY === null || performance.now() - changedAt.current > SCROLL_WINDOW) return;
    const to = scrollFor(el.getBoundingClientRect().top + window.scrollY + targetY, window.scrollY);
    if (to !== null) window.scrollTo({ top: to, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [targetKey, targetY]);
  // overflow: clip, а не hidden, как на доске: вид тот же, но колода не становится прокручиваемой — scrollIntoView или
  // фокус на элементе плиты ниже края не сдвигают все плиты вверх
  // `--dkw` — ширина колоды в покое без помощника (= обёртка): по ней закрытые слои и невыбранные вкладки «Подробнее»
  // держат замороженную ширину (layers.css); меняется только с окном
  const style = {
    position: "relative", zIndex: 0, minWidth: 0, height, borderRadius: 40, overflow: "clip",
    ...(width > 0 && { "--dkw": `${width}px` }),
  } as CSSProperties;
  return (
    <DeckWrapContext.Provider value={width}>
    <DeckFitContext.Provider value={layout}>
    <main ref={deckRef} className="p2-deck" style={style} data-snap={snap || undefined}>
      {/* до первого замера обёртки колода пуста: всё, что в ней, встаёт уже в настоящей ширине (useWrapWidth) —
          в том же кадре, до первой отрисовки, и при загрузке ни одна дорожка не едет от угаданной ширины к своей */}
      {wrap !== null && (<>
        <Plate z={1} y={ys[0]} height={height} vis={vis?.[0]} className={cls("p2-p1 p2-rise", phone && !tplOpen && "mp-shut")} label="Шаг 1 — шаблон"
          style={{ background: "#FFFFFF", color: "#0B1220", animationDelay: "0ms" }}>
          {/* полоса 01 видна и тогда, когда плита 01 свёрнута файлами с данными (V2 `s1Cls`, `s1Btn`): её заголовок гаснет */}
          <Strip n="01" {...s1} on={g.strips || g.fold1} onClick={more || g.fold1 ? () => dispatch({ type: "open", step: "tpl" }) : undefined} label="Вернуться к шагу «Шаблон»" />
          <StepBox on={heads && !g.fold1}>
            <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 24, height: 64 }}>
              <button type="button" className="p2-head" aria-expanded={tplOpen} aria-controls="p2-b1"
                onClick={() => dispatch({ type: "open", step: ui.open === "tpl" ? "text" : "tpl" })}>
                <span className="p2-num" aria-hidden="true" style={{ color: "#0B1220" }}>01</span>
                <StepTitle text="Шаблон" color="#0B1220" />
              </button>
              <div className="p2-hx">{h1}</div>
            </div>
            <div className="p2-sb">{p1}</div>
          </StepBox>
        </Plate>

        <Plate z={2} y={ys[1]} height={height} vis={vis?.[1]} className="p2-p2 p2-rise" label="Шаг 2 — текст"
          style={{ background: "#E9F1FF", color: "#0B1220", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.16)", animationDelay: "40ms" }}>
          <Strip n="02" {...s2} on={g.strips || strip2} onClick={more || strip2 ? () => dispatch({ type: "open", step: "text" }) : undefined} label="Вернуться к шагу «Текст»" />
          <StepBox on={heads && !strip2}>
            <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 24, height: 64 }}>
              <button type="button" className="p2-head" aria-expanded={!tplOpen} aria-controls="p2-b2"
                onClick={() => dispatch({ type: "open", step: ui.open === "text" ? "tpl" : "text" })}>
                <span className="p2-num" aria-hidden="true" style={{ color: "#2563EB" }}>02</span>
                <StepTitle text="Текст" color="#0B1220" />
              </button>
              <div className="p2-hx">{h2}</div>
            </div>
            <div className="p2-sb">{p2}</div>
          </StepBox>
        </Plate>

        <Plate z={3} y={ys[2]} height={height} vis={vis?.[2]} className="p2-p3 p2-dark p2-rise" label="Шаг 3 — параметры и запуск"
          style={{ background: "#0B1220", color: "#FFFFFF", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.28)", animationDelay: "80ms" }}>
          <Strip n="03" {...s3} on={ui.screen === "result"} dark />
          {/* большая «03» гаснет и проявляется вместе с заголовками 01 и 02; на сборке остаётся рядом с фазами */}
          <span className={show(head3 || ui.screen === "build")}>
            <span className="p2-num p2-num3" aria-hidden="true" style={{ position: "absolute", top: 40, left: 48, color: "#FFFFFF" }}>03</span>
          </span>
          {c3 && phone && <StepBox on={head3}>{q3}</StepBox>}
          {c3 && !phone && (
            <StepBox on={head3}>
              <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 24, height: 64 }}>
                <button type="button" className="p2-head" aria-expanded={more} aria-controls="p2-b3m" onClick={() => dispatch({ type: "more" })}>
                  <span className="p2-spc" aria-hidden="true" style={{ display: "block", width: 160, height: 64, flex: "none" }} />
                  <StepTitle text="Параметры и запуск" color="#FFFFFF" />
                </button>
                <div className="p2-hx">{h3}</div>
              </div>
              <div className="p2-sb">{p3}</div>
              {m3}
            </StepBox>
          )}
          {b3}
        </Plate>

        <Plate z={4} y={ys[3]} height={height} vis={vis?.[3]} slotClass={S4[g.s4]} label="Результат"
          style={{ background: "#FFFFFF", color: "#0B1220", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.4)" }}>
          {p4}
        </Plate>

        {layers}
      </>)}
    </main>
    </DeckFitContext.Provider>
    </DeckWrapContext.Provider>
  );
}
