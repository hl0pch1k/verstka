// «Цели из текста» под полем (boards/V2.dc.html версии 105, модуль ds, `.dt-goal`): показывают, что текст влияет на выбор
// графика (ТЗ: «показать рост», «сравнить регионы») — «покажи рост выручки» → линейный график. Целей нет — «графики
// выберу по данным». Помощник сужает колоду: подпись меняет формулировку на месте, «→ тип графика» у целей сжимается и
// гаснет, поля коробки и таблеток мельчают той же кривой (create.css).
// Сайт: таблетка, которая не помещается в коробку целиком (тесная колода, много целей), гаснет в этой раскладке
// (`goalsFit`: hp-wo — только в широкой, hp-no — только в узкой), а не обрезается посреди слова; все цели — в подсказке.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { cls } from "../kit/cls";
import { useDeckWrap } from "../deck/useDeckFit";
import { goalsFit, goalsLabel, goalsOf } from "./dataRules";
import { DsIcon } from "./dsKit";

export function GoalsBox({ text }: { text: string }) {
  const goals = useMemo(() => goalsOf(text), [text]);
  const label = goalsLabel(goals.length);
  const wrap = useDeckWrap();
  // ширины текста цели и «→ графика» (замер); «→ график» сжимается до нуля от своей ширины (--gtw), а не от 220 px
  // холста — ход идёт той же кривой до конца
  const box = useRef<HTMLDivElement>(null);
  const key = goals.map((g) => g.q + g.to).join("|");
  const [w, setW] = useState<{ q: number; gt: number }[]>([]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    let alive = true;
    const measure = () => {
      if (!alive) return;
      const next = Array.from(el.querySelectorAll<HTMLElement>(".dt-gc")).map((c) => {
        const gt = c.querySelector<HTMLElement>(".dt-gt");
        const q = c.querySelector<HTMLElement>(".dt-gq");
        const g = gt ? Math.ceil(gt.scrollWidth) : 0;
        gt?.style.setProperty("--gtw", `${g}px`);
        return { q: q ? q.getBoundingClientRect().width : 0, gt: g };
      });
      setW((cur) => (cur.length === next.length && cur.every((x, i) => Math.abs(x.q - next[i].q) < 0.5 && x.gt === next[i].gt) ? cur : next));
    };
    measure();
    void document.fonts?.ready.then(measure);
    return () => {
      alive = false;
    };
  }, [key]);
  const fit = w.length === goals.length ? goalsFit(w, wrap) : null;
  const all = goals.map((g) => `«${g.q}» → ${g.to}`).join(" · ");
  return (
    <div className="dt-goal p2-in" style={{ animationDelay: "120ms" }} title={all || undefined}>
      <p className="dt-gl">
        <DsIcon name="target" size={16} color="#2563EB" style={{ flex: "none" }} />
        <span className="hp-sw"><span className="hp-wo">{label.wide}</span><span className="hp-no">{label.narrow}</span></span>
      </p>
      {goals.length > 0 && (
        <div ref={box} className="dt-gcs">
          {goals.map((g, i) => {
            const wide = fit ? fit.wide[i] : true, narrow = fit ? fit.narrow[i] : true;
            return (
              <span key={g.task} className={cls("dt-gc", wide && !narrow && "hp-wo", !wide && narrow && "hp-no", !wide && !narrow && "dt-gc-x")}>
                <span className="dt-gq">«{g.q}»</span><span className="dt-gt">{" → "}{g.to}</span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
