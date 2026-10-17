// «Цели из текста» под полем (boards/V2.dc.html версии 105, модуль ds, `.dt-goal`): показывают, что текст влияет на выбор
// графика (ТЗ: «показать рост», «сравнить регионы») — «покажи рост выручки» → линейный график. Целей нет — «графики
// выберу по данным». Помощник сужает колоду: подпись меняет формулировку на месте, «→ тип графика» у целей сжимается и
// гаснет, поля коробки и таблеток мельчают той же кривой (create.css).
// Цели — те, что возьмёт сборка (POST /api/goals, useGoals.ts): пока ответа нет (или без файлов, или запрос не удался) —
// мгновенная прикидка по тексту (`goalsOf`). Сменились таблетки — ряд меняется перекрёстным затуханием (useSwap: гаснет
// 120 мс, подменяется невидимым, проявляется 240 мс), высота ряда та же. Предложение брифа, на которое данные не
// отвечают, — тихая строка справа от подписи (стопкой — под ней), одна; все — в подсказке.
// Сайт: таблетка, которая не помещается в коробку целиком (тесная колода, много целей), гаснет в этой раскладке
// (`goalsFit`: hp-wo — только в широкой, hp-no — только в узкой), а не обрезается посреди слова; все цели — в подсказке.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { useSwap } from "../kit/useSwap";
import { useDeckWrap } from "../deck/useDeckFit";
import { isStack, useTier } from "../shell/tier";
import { datasetIds, goalChips, goalNoteLine, goalsFit, goalsLabel, goalsOf, type GoalChip } from "./dataRules";
import { DsIcon } from "./dsKit";
import { useServerGoals } from "./useGoals";

export function GoalsBox({ text }: { text: string }) {
  const { data, params } = useApp();
  // наборы — когда все разобраны (пока файлы читаются, запрос на каждый готовый отменял бы предыдущий)
  const ids = datasetIds(data.cards);
  const settled = useRef<string[]>(ids);
  if (!data.busy) settled.current = ids;
  const answer = useServerGoals(text, settled.current, params.useModels);
  const guess = useMemo(() => goalsOf(text), [text]);
  const chips = useMemo(() => goalChips(answer, guess), [answer, guess]);
  const note = useMemo(() => goalNoteLine(answer?.notes ?? []), [answer]);

  // ряд таблеток и подпись меняются перекрёстным затуханием: показанный набор — по ключу, его таблетки помнятся
  const chipKey = chips.map((c) => `${c.key}→${c.to ?? ""}`).join("|");
  const byKey = useRef(new Map<string, GoalChip[]>());
  byKey.current.set(chipKey, chips);
  const sw = useSwap(chipKey);
  const shown = byKey.current.get(sw.shown) ?? chips;
  if (byKey.current.size > 8) for (const k of byKey.current.keys()) if (k !== chipKey && k !== sw.shown) byKey.current.delete(k);
  const label = goalsLabel(shown.length);
  const noteSw = useSwap(note?.line ?? "");
  const noteAll = useRef(new Map<string, string>());
  if (note) noteAll.current.set(note.line, note.all);

  const wrap = useDeckWrap();
  // ширины текста цели и «→ графика» (замер); «→ график» сжимается до нуля от своей ширины (--gtw), а не от 220 px
  // холста — ход идёт той же кривой до конца
  const box = useRef<HTMLDivElement>(null);
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
  }, [sw.shown]);
  // подгонка под строку колоды холста — только на компьютере: стопкой (окно уже 1280) таблетки переносятся рядами
  // (create.css) и видны все цели
  const stack = isStack(useTier());
  const fit = !stack && w.length === shown.length ? goalsFit(w, wrap) : null;
  const all = shown.map((g) => (g.to ? `«${g.q}» → ${g.to}` : `«${g.q}»`)).join(" · ");
  // не поместившиеся цели — счётом в подписи («· ещё 3»); все — в подсказке коробки
  const more = (ok: boolean[] | undefined) => {
    const n = ok ? ok.filter((x) => !x).length : 0;
    return n ? ` · ещё ${n}` : "";
  };
  return (
    <div className="dt-goal p2-in" style={{ animationDelay: "120ms" }} title={all || undefined}>
      <p className="dt-gl">
        <DsIcon name="target" size={16} color="#2563EB" style={{ flex: "none" }} />
        <span className={cls("hp-sw", sw.cls)}><span className="hp-wo">{label.wide}{more(fit?.wide)}</span><span className="hp-no">{label.narrow}{more(fit?.narrow)}</span></span>
        {/* предложение брифа без ответа в данных: тихая строка, одна (все — в подсказке) */}
        <span className={cls("dt-gn", noteSw.cls, !noteSw.shown && "dt-gn-0")} role="note" title={noteAll.current.get(noteSw.shown) || undefined}
          aria-hidden={!noteSw.shown || undefined}>
          {noteSw.shown && <><Icon name="info" size={14} /><span>{noteSw.shown}</span></>}
        </span>
      </p>
      <div ref={box} className={cls("dt-gcs", sw.cls)}>
        {shown.map((g, i) => {
          const wide = fit ? fit.wide[i] : true, narrow = fit ? fit.narrow[i] : true;
          return (
            <span key={g.key} className={cls("dt-gc", wide && !narrow && "hp-wo", !wide && narrow && "hp-no", !wide && !narrow && "dt-gc-x")} title={g.title}>
              <span className="dt-gq">«{g.q}»</span>{g.to && <span className="dt-gt">{" → "}{g.to}</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}
