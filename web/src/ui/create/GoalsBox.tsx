// «Цели из текста» под полем (boards/V2.dc.html версии 105, модуль ds, `.dt-goal`): показывают, что текст влияет на выбор
// графика (ТЗ: «показать рост», «сравнить регионы») — «покажи рост выручки» → линейный график. Целей нет — «графики
// выберу по данным». Помощник сужает колоду: подпись меняет формулировку на месте, «→ тип графика» у целей сжимается и
// гаснет, поля коробки и таблеток мельчают той же кривой (create.css).
import { useLayoutEffect, useMemo, useRef } from "react";
import { goalsLabel, goalsOf } from "./dataRules";
import { DsIcon } from "./dsKit";

export function GoalsBox({ text }: { text: string }) {
  const goals = useMemo(() => goalsOf(text), [text]);
  const label = goalsLabel(goals.length);
  // сайт: «→ тип графика» сжимается до нуля от своей ширины (--gtw — замер), а не от 220 px холста: ход идёт той же
  // кривой до конца, а не кончается раньше
  const box = useRef<HTMLDivElement>(null);
  const key = goals.map((g) => g.q + g.to).join("|");
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => el.querySelectorAll<HTMLElement>(".dt-gt").forEach((t) => t.style.setProperty("--gtw", `${Math.ceil(t.scrollWidth)}px`));
    measure();
    void document.fonts?.ready.then(measure);
  }, [key]);
  return (
    <div className="dt-goal p2-in" style={{ animationDelay: "120ms" }}>
      <p className="dt-gl">
        <DsIcon name="target" size={16} color="#2563EB" style={{ flex: "none" }} />
        <span className="hp-sw"><span className="hp-wo">{label.wide}</span><span className="hp-no">{label.narrow}</span></span>
      </p>
      {goals.length > 0 && (
        <div ref={box} className="dt-gcs">
          {goals.map((g) => (
            <span key={g.task} className="dt-gc" title={`«${g.q}» → ${g.to}`}>«{g.q}»<span className="dt-gt">{"\u00a0→ "}{g.to}</span></span>
          ))}
        </div>
      )}
    </div>
  );
}
