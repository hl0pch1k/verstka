// Колода «Слоёв»: четыре плиты одна над другой (01 шаблон, 02 текст, 03 параметры и запуск → сборка, 04 результат)
// и слои поверх. Где стоит каждая плита и что видно — `deckGeometry(ui)`; плиты ездят 520 мс (`.p2-slot`).
// Разметка — boards/V2.dc.html, `<main class="p2-deck">`. Содержимое плит и слоёв приносят задачи своих областей
// через пропсы-слоты; сама колода рисует места плит, полосы, большие номера и заголовки шагов.
// Помощник сужает колоду: содержимое «Создать» (ряд заголовка справа от названия `.p2-hx` и тело каждого шага)
// перестраивается вместе с ней каждый кадр — на той же кривой и за то же время (V2 версии 100; create.css, блок
// «Колода, суженная помощником», и ui/create/morph.ts); название шага сжимается transform'ом (StepTitle). Ничего, что
// есть в обеих раскладках, не гаснет.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { deckGeometry, type Geometry } from "./geometry";
import { Plate } from "./Plate";
import { Strip, type StripData } from "./Strip";
import { DeckFitContext, DeckWrapContext, useDeckLayout, useWrapWidth } from "./useDeckFit";
import { stackGeometry } from "./stack";
import { useHeldHeight, useStackMetrics } from "./useStackMetrics";
import { helperBeside, isStack, useTier } from "../shell/tier";
import { openSheets } from "../shell/sheets";

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
const DOWN_MS = 560;

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

export function Deck({ h1, h2, h3, p1, p2, p3, m3, b3, p4, s1, s2, s3, layers }: DeckProps) {
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
  const layout = useDeckLayout(deckRef, ui.helper && helperBeside(tier), width);
  const metrics = useStackMetrics(deckRef, stack && wrap !== null);
  const sg = stack && metrics ? stackGeometry(ui, metrics) : null;
  const ys = sg ? sg.y : g.y;
  const height = useHeldHeight(sg ? sg.height : 812);
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
  // стопкой поверх колоды — слой или помощник (плита снизу, под ней затемнение): плиты колоды под ним не принимают
  // фокус и не читаются (inert), Tab ходит по плите сверху; на компьютере слои и помощник — в колоде и рядом, так не делается
  const covered = stack && openSheets(ui).length > 0;
  // то, что открыло плиту сверху (карточка, кнопка на плите), inert лишает фокуса — колода помнит его и возвращает фокус,
  // когда плита уехала, а фокус остался ни на чём
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = deckRef.current;
    if (!el) return;
    const slots = Array.from(el.querySelectorAll<HTMLElement>(":scope > .p2-slot:not(.p2-lay)"));
    if (covered) {
      const a = document.activeElement;
      if (a instanceof HTMLElement && slots.some((s) => s.contains(a))) opener.current = a;
    }
    for (const s of slots) {
      if (covered) s.setAttribute("inert", "");
      else s.removeAttribute("inert");
    }
    if (!covered && opener.current) {
      const o = opener.current;
      opener.current = null;
      const now = document.activeElement;
      // фокус ещё в уезжающей плите (лист, раздел, помощник) или ни на чём — обратно к тому, что её открыло
      const away = !now || now === document.body || !!now.closest(".p2-lay, .hp-help");
      if (o.isConnected && away) o.focus({ preventScroll: true });
    }
  }, [covered, wrap]);
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
        <Plate z={1} y={ys[0]} height={height} className="p2-p1 p2-rise" label="Шаг 1 — шаблон" style={{ background: "#FFFFFF", color: "#0B1220", animationDelay: "0ms" }}>
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

        <Plate z={2} y={ys[1]} height={height} className="p2-p2 p2-rise" label="Шаг 2 — текст"
          style={{ background: "#E9F1FF", color: "#0B1220", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.16)", animationDelay: "40ms" }}>
          <Strip n="02" {...s2} on={g.strips} onClick={more ? () => dispatch({ type: "open", step: "text" }) : undefined} label="Вернуться к шагу «Текст»" />
          <StepBox on={heads}>
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

        <Plate z={3} y={ys[2]} height={height} className="p2-p3 p2-dark p2-rise" label="Шаг 3 — параметры и запуск"
          style={{ background: "#0B1220", color: "#FFFFFF", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.28)", animationDelay: "80ms" }}>
          <Strip n="03" {...s3} on={ui.screen === "result"} dark />
          {/* большая «03» гаснет и проявляется вместе с заголовками 01 и 02; на сборке остаётся рядом с фазами */}
          <span className={show(head3 || ui.screen === "build")}>
            <span className="p2-num p2-num3" aria-hidden="true" style={{ position: "absolute", top: 40, left: 48, color: "#FFFFFF" }}>03</span>
          </span>
          {c3 && (
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

        <Plate z={4} y={ys[3]} height={height} slotClass={S4[g.s4]} label="Результат"
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
