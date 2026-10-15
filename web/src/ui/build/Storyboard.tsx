// Раскадровка сборки (boards/B-start, B-sketch, V2 `bdBoard`): заголовок «Раскадровка» со строкой хода, сегменты
// вариантов и карточка на каждый слайд выбранного варианта. До плана — безымянные заглушки (пульс), потом номера,
// эскизы формы (pop 360 мс, по 60 мс друг за другом), метки критика «Замечание» и «Переделан», рамка 2 px на слайде,
// о котором говорит агент или который верстается (с бегущей полоской), галочка сверстанного и настоящее превью — по три
// за такт. Колонок столько, чтобы все слайды были видны (columns.ts), не меньше четырёх, пока карточка не уже 150 px;
// не помещаются — список прокручивается сам к слайду в работе (если человек не листает его сам). Сменилось число
// колонок (слайдов стало больше) — сетка меняется перекрёстным затуханием (useSwap).
// Помощник сужает колоду (V2 версии 100): те же колонки, сужаются — их число считается по ширине раскадровки в широкой
// раскладке (от ширины окна, columns.ts `buildMorph`), посреди хода не меняется; у сегментов вариантов слова хода гаснут
// и сжимаются кеглем до нуля (галочки остаются), сегменты плотнее. Сайт: в тесной колоде (1280) при трёх вариантах
// «Раскадровка» со строкой хода сжимается и гаснет (сегментам иначе нет места), а у меток «Замечание» и «Переделан»
// остаётся значок (карточки уже 100 px). Строка хода для чтения с экрана («сверстано 5 из 12») — в скрытом узле, который
// есть всегда (видимая строка, уходя, становится visibility:hidden — живая область пропала бы вместе с ней).
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { BOARD_GAP } from "../../lib/stage";
import { smoothScroll } from "../../lib/motion";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { useSwap } from "../kit/useSwap";
import type { BuildView, CardView } from "./buildView";
import { boardColumns, boardLabel, MIN_CARD, type BuildMorph } from "./columns";
import { SlideSketch } from "./SlideSketch";

/** Ширины пульсирующих строк заглушки: [заголовок в карточке, подпись под ней], % (V2 `GHOST`). */
const GHOST: Array<[number, number]> = [[56, 64], [44, 52], [64, 72], [52, 48], [60, 68], [48, 56], [58, 60], [42, 50], [62, 66], [50, 58], [54, 62], [46, 54]];
/** Человек листает раскадровку сам — она не прокручивается к слайду в работе столько времени. */
const HOLD_MS = 5000;

export interface VariantSeg { name: string; label: string; desc: string }

/** Колонки списка `box`: ширина — раскадровки в широкой раскладке (`list`, от ширины окна: ход помощника колонок не
 *  меняет), высота — замер (на ходу не меняется); окно уже 901 px (колода в столбик, помощник под ней) — живая ширина. */
function useColumns(box: RefObject<HTMLElement>, n: number, aspect: number, list: number | null): number {
  const [cols, setCols] = useState(4);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => {
      const w = list ?? el.clientWidth;
      if (w <= 0) return;
      setCols(boardColumns(w, el.clientHeight, n, aspect, MIN_CARD));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [box, n, aspect, list]);
  return cols;
}

function cardLabel(c: CardView, planned: boolean, laying: boolean): string {
  if (!planned) return "Слайд ещё не продуман";
  const what = c.state === "done" || c.state === "laid" ? " — сверстан" : c.form ? ` — эскиз «${c.form}»` : " — ещё не продуман";
  return `Слайд ${c.n}${c.title ? ` · ${c.title}` : ""}${what}${c.state === "critic" ? ", замечание критика" : ""}${c.state === "revised" ? ", переделан по замечанию критика" : ""}${c.focus ? (laying ? ", сейчас верстается" : ", о нём сейчас говорит агент") : ""}`;
}

function Card({ c, i, planned, aspect }: { c: CardView; i: number; planned: boolean; aspect: number }) {
  const ghost = GHOST[i % GHOST.length];
  const laid = c.state === "laid" || c.state === "done";
  const imDelay = `${(i % 3) * 60}ms`;
  return (
    <div className="p2-in" data-n={c.n} style={{ animationDelay: `${Math.min(i, 15) * 40}ms` }}>
      <div className="p2-sbf" role="img" aria-label={cardLabel(c, planned, c.work)} title={planned ? `Слайд ${c.n}${c.title ? ` · ${c.title}` : ""}` : undefined}
        style={{ aspectRatio: String(aspect) }}>
        {!planned && <span className="bs-gh bs-pulse" aria-hidden="true" style={{ width: `${ghost[0]}%` }} />}
        {planned && !c.kind && !laid && <span className="bk-gh bk-pulse" aria-hidden="true" />}
        {c.kind && <SlideSketch key={`${c.kind}${c.formula ? "+f" : ""}`} kind={c.kind} formula={c.formula} style={{ animationDelay: `${(i % 4) * 60}ms` }} />}
        {c.preview && (
          <img className="p2-pop" src={c.preview} alt="" draggable={false}
            style={{ position: "absolute", inset: 0, display: "block", width: "100%", height: "100%", objectFit: "cover", animationDelay: imDelay }} />
        )}
        {laid && <span className="p2-sbok p2-pop" aria-hidden="true" style={{ animationDelay: imDelay }}><Icon name="check" size={12} /></span>}
        {c.state === "critic" && (
          <span className="bk-badge bk-badge-warn p2-pop" title="Критик оставил замечание к этому слайду">
            <Icon name="warning" size={12} /><span className="bd-bw">Замечание</span>
          </span>
        )}
        {c.state === "revised" && (
          <span className="bk-badge bk-badge-ok p2-pop" title="Слайд переделан по замечанию критика">
            <Icon name="refresh" size={12} /><span className="bd-bw">Переделан</span>
          </span>
        )}
        {c.work && <span className="p2-work" aria-hidden="true" />}
        <span className={cls("bd-ring", c.focus && "bd-ring-on")} aria-hidden="true" />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, height: 20, marginTop: 8 }}>
        {!planned && <span className="bs-cap bs-pulse" aria-hidden="true" style={{ width: `${ghost[1]}%` }} />}
        {planned && <span className="bk-cn p2-in" style={{ animationDelay: `${Math.min(i, 15) * 40}ms` }}>{c.n}</span>}
        {planned && !c.form && !laid && <span className="bk-capgh bk-pulse" aria-hidden="true" />}
        {/* сверстанный слайд подписан своим заголовком, эскиз — формой */}
        {c.state === "done" && (c.title || c.form)
          ? <span key="title" className="bk-cf p2-in">{c.title ?? c.form}</span>
          : c.form && <span key="form" className="bk-cf p2-in">{c.form}</span>}
      </div>
    </div>
  );
}

export function Storyboard({ view, segs, onPick, aspect, morph, wide }: {
  view: BuildView;
  /** Сегменты вариантов: имя, название и подпись (V2 `VN`, `VD`). */
  segs: VariantSeg[];
  onPick(name: string): void;
  /** Пропорции слайдов шаблона (ширина / высота). */
  aspect: number;
  /** Обе раскладки плиты по ширине окна (columns.ts). */
  morph: BuildMorph;
  /** Окно шире 900 px: колода и помощник рядом (иначе — столбиком, раскладка одна). */
  wide: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cols = useSwap(useColumns(box, view.cards.length, aspect, wide ? morph.list : null));
  // человек листает раскадровку (колесо, касание, клавиши, полоса прокрутки) — она стоит, где он её оставил
  const heldUntil = useRef(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const hold = () => void (heldUntil.current = performance.now() + HOLD_MS);
    const onKey = (e: KeyboardEvent) => ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(e.key) && hold();
    el.addEventListener("wheel", hold, { passive: true });
    el.addEventListener("touchmove", hold, { passive: true });
    el.addEventListener("pointerdown", hold);
    el.addEventListener("keydown", onKey);
    return () => {
      el.removeEventListener("wheel", hold);
      el.removeEventListener("touchmove", hold);
      el.removeEventListener("pointerdown", hold);
      el.removeEventListener("keydown", onKey);
    };
  }, []);
  // слайд в работе всегда виден: список прокручивается к нему сам, только когда нужно
  const focus = view.cards.find((c) => c.focus)?.n ?? null;
  useEffect(() => {
    const el = box.current;
    const card = focus ? el?.querySelector<HTMLElement>(`[data-n="${focus}"]`) : null;
    if (!el || !card || performance.now() < heldUntil.current) return;
    const top = card.offsetTop;
    if (top < el.scrollTop || top + card.offsetHeight > el.scrollTop + el.clientHeight) {
      el.scrollTo({ top: Math.max(0, top - (el.clientHeight - card.offsetHeight) / 2), behavior: smoothScroll() });
    }
  }, [focus]);

  return (
    <>
      <div className="p2-in p2-wrap bd-sbh" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 40, marginTop: 24, animationDelay: "120ms" }}>
        <p className={cls("bd-sbl", !boardLabel(morph, segs.length) && "bd-sbl-go")} style={{ display: "flex", flexDirection: "column", minWidth: 0, margin: 0, whiteSpace: "nowrap" }}>
          <span style={{ fontSize: 15, fontWeight: 700, lineHeight: "20px", color: "#FFFFFF" }}>Раскадровка</span>
          <span aria-hidden="true" style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{view.board}</span>
        </p>
        <span className="p2-sr" aria-live="polite">{view.board}</span>
        {segs.length > 0 && (
          <div role="group" aria-label="Какую раскадровку показать" className={cls("bd-segs", !morph.words && "bd-segs-s")}
            style={{ display: "flex", gap: 4, padding: 4, borderRadius: 999, background: "rgba(255,255,255,.06)" }}>
            {segs.map((s) => {
              const v = view.variants.find((x) => x.name === s.name);
              const on = s.name === view.variant;
              return (
                <button key={s.name} type="button" className={cls("p2-seg bk-seg", on && "p2-seg-on")} aria-pressed={on}
                  title={[s.desc, v?.tip].filter(Boolean).join(" · ")} onClick={() => onPick(s.name)}>
                  <span>{s.label}</span>
                  {v?.status && (
                    <span key={v.status} className="bk-vst p2-in">
                      {v.done && <Icon name="check" size={12} className="p2-pop" />}
                      <span className="hq-vsw">{v.status}</span>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div ref={box} className="bd-board" style={{ position: "relative", flex: 1, minHeight: 0, marginTop: 16, overflowY: "auto" }}>
        <div className={cls("p2-g4", cols.cls)} aria-label={`Раскадровка: ${view.board}`}
          style={{ display: "grid", gridTemplateColumns: `repeat(${cols.shown}, minmax(0, 1fr))`, gap: BOARD_GAP }}>
          {view.cards.map((c, i) => <Card key={c.n} c={c} i={i} planned={view.planned} aspect={aspect} />)}
        </div>
      </div>
    </>
  );
}
