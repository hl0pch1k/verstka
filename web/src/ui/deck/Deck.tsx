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
  return <div className={cls("p2-fxbox", show(on))}>{children}</div>;
}

export function Deck({ h1, h2, h3, p1, p2, p3, m3, b3, p4, s1, s2, s3, layers }: DeckProps) {
  const { ui, dispatch } = useApp();
  const g = deckGeometry(ui);
  // помощник сужает колоду. «Создать» перестраивается вместе с ней (CSS по `.hp-nar`), обе его раскладки считаются по
  // ширине обёртки (DeckWrapContext); «Сборка», слои и лист «Подробнее» пока решают по цели хода (useDeckLayout) и
  // перестраиваются перекрёстным затуханием (usePlateFit, useLayer)
  const deckRef = useRef<HTMLElement>(null);
  const wrap = useWrapWidth(deckRef);
  const layout = useDeckLayout(deckRef, ui.helper, wrap);
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
  // overflow: clip, а не hidden, как на доске: вид тот же, но колода не становится прокручиваемой — scrollIntoView или
  // фокус на элементе плиты ниже края не сдвигают все плиты вверх
  const style = { position: "relative", zIndex: 0, minWidth: 0, height: 812, borderRadius: 40, overflow: "clip", ...(layout.width > 0 && { "--deck-w": `${layout.width}px` }) } as CSSProperties;
  return (
    <DeckWrapContext.Provider value={wrap}>
    <DeckFitContext.Provider value={layout}>
    <main ref={deckRef} className="p2-deck" data-fit={layout.fit} style={style}>
      <Plate z={1} y={g.y[0]} className="p2-rise" label="Шаг 1 — шаблон" style={{ background: "#FFFFFF", color: "#0B1220", animationDelay: "0ms" }}>
        <Strip n="01" {...s1} on={g.strips} onClick={more ? () => dispatch({ type: "open", step: "tpl" }) : undefined} label="Вернуться к шагу «Шаблон»" />
        <StepBox on={heads}>
          <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 24, height: 64 }}>
            <button type="button" className="p2-head" aria-expanded={tplOpen} aria-controls="p2-b1"
              onClick={() => dispatch({ type: "open", step: ui.open === "tpl" ? "text" : "tpl" })}>
              <span className="p2-num" aria-hidden="true" style={{ color: "#0B1220" }}>01</span>
              <StepTitle text="Шаблон" color="#0B1220" />
            </button>
            <div className="p2-hx">{h1}</div>
          </div>
          <div>{p1}</div>
        </StepBox>
      </Plate>

      <Plate z={2} y={g.y[1]} className="p2-p2 p2-rise" label="Шаг 2 — текст"
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
          <div>{p2}</div>
        </StepBox>
      </Plate>

      <Plate z={3} y={g.y[2]} className="p2-p3 p2-dark p2-rise" label="Шаг 3 — параметры и запуск"
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
            <div>{p3}</div>
            {m3}
          </StepBox>
        )}
        {b3}
      </Plate>

      <Plate z={4} y={g.y[3]} slotClass={S4[g.s4]} label="Результат"
        style={{ background: "#FFFFFF", color: "#0B1220", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.4)" }}>
        {p4}
      </Plate>

      {layers}
    </main>
    </DeckFitContext.Provider>
    </DeckWrapContext.Provider>
  );
}
