// Заголовок плиты «Сборка»: что агент делает сейчас («Продумываю слайды» → «Сверяю план с текстом» → …). Все фазы
// лежат друг на друге (V2 `bdPhases`, классы p2-ph): прошедшая уходит вверх и гаснет (240 мс), новая поднимается снизу
// (360 мс). Фаза держится не меньше DWELL_MS — быстрая сборка без модели всё равно читается шагами; конец сборки
// (готово, остановилась) встаёт сразу. Для чтения с экрана — скрытый h1 с вежливым live.
// Помощник сужает колоду: фаза остаётся в своей клетке и мельчает той же кривой (scale до .75, длинная — сколько нужно,
// `--phs` — columns.ts `phaseFit`); кегль — от ширины окна, один в обеих раскладках (build.css `--bd-phf`). Мельче 18 px
// фаза не становится: не встаёт в клетку и при 18 (окно около 1280) — в узкой раскладке она в две строки 18/24: две
// копии в одном месте (однострочная гаснет, двухстрочная проявляется, обе — постоянной ширины, мельчают тем же scale).
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { STAGE_TITLE } from "../../lib/stage";
import { cls } from "../kit/cls";
import { PHASE_ROLL, type BuildPhase } from "./buildView";
import { phaseFit, type BuildMorph } from "./columns";

const DWELL_MS = 1100;

export function Phases({ phase, morph }: { phase: BuildPhase; morph: BuildMorph }) {
  const [shown, setShown] = useState(phase);
  const since = useRef(performance.now());
  useEffect(() => {
    if (phase === shown) return;
    const end = phase === "done" || phase === "failed";
    const t = window.setTimeout(() => {
      since.current = performance.now();
      setShown(phase);
    }, end ? 0 : Math.max(0, DWELL_MS - (performance.now() - since.current)));
    return () => window.clearTimeout(t);
  }, [phase, shown]);
  const at = PHASE_ROLL.indexOf(shown);
  return (
    <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 32, height: 64 }}>
      <span className="p2-spc" aria-hidden="true" style={{ display: "block", width: 160, height: 64, flex: "none" }} />
      <div className="p2-phs p2-in" style={{ position: "relative", flex: 1, minWidth: 0, height: 48, animationDelay: "40ms" }}>
        {PHASE_ROLL.map((p, i) => {
          const f = phaseFit(p, morph.font, morph.cell);
          return (
            <span key={p} className={cls("p2-ph bd-ph", i === at ? "p2-ph-on" : i < at ? "p2-ph-past" : "p2-ph-next")} aria-hidden="true"
              style={{ "--phs": f.scale } as CSSProperties}>
              {f.two ? (
                <span className="hp-sw bd-ph2">
                  <span className="hp-wo">{STAGE_TITLE[p]}</span>
                  <span className="hp-no bd-phn" style={{ width: f.width, marginTop: f.top, lineHeight: `${f.line}px` }}>{f.loose ? STAGE_TITLE[p].replace(/\u00a0/g, " ") : STAGE_TITLE[p]}</span>
                </span>
              ) : STAGE_TITLE[p]}
            </span>
          );
        })}
        <h1 className="p2-sr" aria-live="polite">{STAGE_TITLE[shown]}</h1>
      </div>
    </div>
  );
}
