// Заголовок плиты «Сборка»: что агент делает сейчас («Продумываю слайды» → «Сверяю план с текстом» → …). Все фазы
// лежат друг на друге (V2 `bdPhases`, классы p2-ph): прошедшая уходит вверх и гаснет (240 мс), новая поднимается снизу
// (360 мс). Фаза держится не меньше DWELL_MS — быстрая сборка без модели всё равно читается шагами; конец сборки
// (готово, остановилась) встаёт сразу. Для чтения с экрана — скрытый h1 с вежливым live.
// Помощник сужает колоду: фаза остаётся в своей клетке и мельчает той же кривой (scale до .75, длинная — сколько нужно,
// `--phs` — columns.ts `phaseFit`); кегль — от ширины окна, один в обеих раскладках (build.css `--bd-phf`). Мельче 18 px
// фаза не становится: не встаёт в клетку и при 18 (окно около 1280) — в узкой раскладке она в две строки 18/24: две
// копии в одном месте (однострочная гаснет, двухстрочная проявляется, обе — постоянной ширины, мельчают тем же scale);
// строки двухстрочной — явные, каждая без переноса (columns.ts `phaseLines`); «Смотрю на слайды целиком» при обёртке
// 1217 в две строки встаёт только при 16.9 px (columns.ts `phaseFit`).
// Короткие предлоги и союзы привязаны к следующему слову (lib/typo `bindShort`) — в конце строки не остаются.
// Сборка с файлами данных: фаза аналитика — «Изучаю данные» (V2 v105, buildView `stageTitle`); анализ без модели — доли
// секунды, но фаза показывается своим шагом (buildView `phaseStep`).
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { bindShort } from "../../lib/typo";
import { cls } from "../kit/cls";
import { FONTS_STAGE, PHASE_ROLL, phaseStep, stageTitle, type BuildPhase } from "./buildView";
import { phaseFit, phaseLines, type BuildMorph } from "./columns";

const DWELL_MS = 1100;

export function Phases({ phase, morph, data = false, fonts = false }: {
  phase: BuildPhase; morph: BuildMorph;
  /** Подбираются шрифты (до плана): фаза очереди — «Подбираю шрифты…» (короче «Готовлюсь к сборке» — её клетки хватает). */
  fonts?: boolean;
  /** Сборка с файлами данных: фаза аналитика — «Изучаю данные» (buildView `stageTitle`). */
  data?: boolean;
}) {
  const [shown, setShown] = useState(phase);
  const since = useRef(performance.now());
  useEffect(() => {
    if (phase === shown) return;
    const end = phase === "done" || phase === "failed";
    // сборка с данными не проходит «Изучаю данные» молча: анализ без модели — доли секунды, а фаза — шаг сборки
    const next = phaseStep(shown, phase, data);
    const t = window.setTimeout(() => {
      since.current = performance.now();
      setShown(next);
    }, end ? 0 : Math.max(0, DWELL_MS - (performance.now() - since.current)));
    return () => window.clearTimeout(t);
  }, [phase, shown, data]);
  const at = PHASE_ROLL.indexOf(shown);
  return (
    <div className="p2-hrow" style={{ display: "flex", alignItems: "center", gap: 32, height: 64 }}>
      <span className="p2-spc" aria-hidden="true" style={{ display: "block", width: 160, height: 64, flex: "none" }} />
      <div className="p2-phs p2-in" style={{ position: "relative", flex: 1, minWidth: 0, height: 48, animationDelay: "40ms" }}>
        {PHASE_ROLL.map((p, i) => {
          const f = phaseFit(p, morph.font, morph.cell, data);
          const own = p === "queued" && fonts;
          const [l1, l2] = f.two ? (own ? [FONTS_STAGE, ""] : phaseLines(p, data)) : ["", ""];
          const t = bindShort(own ? FONTS_STAGE : stageTitle(p, data));
          return (
            <span key={p} className={cls("p2-ph bd-ph", i === at ? "p2-ph-on" : i < at ? "p2-ph-past" : "p2-ph-next")} aria-hidden="true"
              style={{ "--phs": f.scale } as CSSProperties}>
              {f.two ? (
                <span className="hp-sw bd-ph2">
                  <span className="hp-wo">{t}</span>
                  <span className="hp-no bd-phn" style={{ width: f.width, marginTop: f.top, lineHeight: `${f.line}px` }}><span>{l1}</span><span>{l2}</span></span>
                </span>
              ) : t}
            </span>
          );
        })}
        <h1 className="p2-sr" aria-live="polite">{shown === "queued" && fonts ? FONTS_STAGE : stageTitle(shown, data)}</h1>
      </div>
    </div>
  );
}
