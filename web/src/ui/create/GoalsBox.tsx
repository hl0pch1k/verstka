// «Цели из текста» под полем (boards/V2.dc.html версии 105, модуль ds, `.dt-goal`): показывают, что текст влияет на выбор
// графика (ТЗ: «показать рост», «сравнить регионы») — «покажи рост выручки» → линейный график. Целей нет — «графики
// выберу по данным». Помощник сужает колоду: подпись меняет формулировку на месте, «→ тип графика» у целей сжимается и
// гаснет, поля коробки и таблеток мельчают той же кривой (create.css).
// Цели — те, что возьмёт сборка (POST /api/goals, useGoals.ts): пока ответа нет (или без файлов, или запрос не удался) —
// мгновенная прикидка по тексту (`goalsOf`). Сменились таблетки — ряд меняется перекрёстным затуханием (useSwap: гаснет
// 120 мс, подменяется невидимым, проявляется 240 мс), высота ряда та же. Предложение брифа, на которое данные не
// отвечают, — тихая строка справа от подписи (стопкой — под ней), одна; все — в подсказке.
// Сайт (`goalsLayout`): все цели в ряд с «→ видом графика»; не помещаются — в ряд без вида (он в подсказке таблетки);
// и так не помещаются — в два ряда в той же коробке 88 (первый — справа от подписи «Цели из текста», второй — во всю
// ширину, тихая строка — в его конце): у широкой и узкой раскладки свои ряды — две копии на одном месте, сменяются
// проявлением, как hp-wo / hp-no. Таблетка, не поместившаяся и так, гаснет в этой раскладке, а не обрезается посреди
// слова; счёт — «ещё N», все цели — в подсказке. Раскладка сменяется вместе с набором целей (их перекрёстным затуханием).
import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { useSwap } from "../kit/useSwap";
import { useDeckWrap } from "../deck/useDeckFit";
import { isStack, useTier } from "../shell/tier";
import { datasetIds, goalChips, goalNoteLine, goalsLabel, goalsLayout, goalsOf, stillInText, type GoalChip } from "./dataRules";
import { DsIcon } from "./dsKit";
import { useServerGoals } from "./useGoals";

export function GoalsBox({ text }: { text: string }) {
  const { data, params } = useApp();
  // наборы — когда все разобраны (пока файлы читаются, запрос на каждый готовый отменял бы предыдущий)
  const ids = datasetIds(data.cards);
  const settled = useRef<string[]>(ids);
  if (!data.busy) settled.current = ids;
  // ответ для этого текста — как есть; прежний (новый в пути) — только цели, чьи цитаты ещё в тексте: текст заменили
  // (пример, другой бриф) — прикидка, а не цели прежнего текста
  const server = useServerGoals(text, settled.current, params.useModels);
  const answer = useMemo(() => (server.answer && !server.fresh ? stillInText(server.answer, text) : server.answer), [server.answer, server.fresh, text]);
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
  // отступ первого ряда в двух рядах (значок 16 + 8 + «Цели из текста» + 12) и место под «ещё N» в конце второго
  const meter = useRef<HTMLSpanElement>(null);
  const [lab, setLab] = useState({ l: 0, more: 0 });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    let alive = true;
    const measure = () => {
      if (!alive) return;
      // замер — по копии широкой раскладки, в порядке целей (в двух рядах таблетки идут по рядам)
      const els = Array.from(el.querySelectorAll<HTMLElement>(".dt-gc[data-m]")).sort((a, b) => Number(a.dataset.m) - Number(b.dataset.m));
      const next = els.map((c) => {
        const gt = c.querySelector<HTMLElement>(".dt-gt");
        const q = c.querySelector<HTMLElement>(".dt-gq");
        const g = gt ? Math.ceil(gt.scrollWidth) : 0;
        gt?.style.setProperty("--gtw", `${g}px`);
        return { q: q ? q.getBoundingClientRect().width : 0, gt: g };
      });
      setW((cur) => (cur.length === next.length && cur.every((x, i) => Math.abs(x.q - next[i].q) < 0.5 && x.gt === next[i].gt) ? cur : next));
      const [l, m] = Array.from(meter.current?.children ?? []).map((c) => Math.ceil(c.getBoundingClientRect().width));
      if (l) setLab((cur) => (cur.l === l + 36 && cur.more === m + 8 ? cur : { l: l + 36, more: m + 8 }));
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
  const lay = !stack && w.length === shown.length && lab.l ? goalsLayout(w, wrap, lab) : null;
  const two = lay?.mode === "two";
  const all = shown.map((g) => (g.to ? `«${g.q}» → ${g.to}` : `«${g.q}»`)).join(" · ");
  // не поместившиеся цели — счётом в подписи («· ещё 3»); все — в подсказке коробки
  const hidden = (rows: number[] | undefined) => (rows ? rows.filter((x) => !x).length : 0);
  const more = (rows: number[] | undefined) => (two || !hidden(rows) ? "" : ` · ещё ${hidden(rows)}`);
  // в двух рядах подпись короткая и в обеих раскладках та же: справа от неё — первый ряд
  const lbl = two ? { wide: label.narrow, narrow: label.narrow } : label;
  const chip = (g: GoalChip, cl: string | false, m: number | null) => (
    <span key={g.key} className={cls("dt-gc", cl)} title={g.title} data-m={m ?? undefined}>
      <span className="dt-gq">«{g.q}»</span>{g.to && <span className="dt-gt">{"\u00a0→ "}{g.to}</span>}
    </span>
  );
  // два ряда: у широкой и узкой раскладки свои ряды — две копии на одном месте, сменяются проявлением (как стопки hp-tx)
  const rowOf = (rows: number[], k: 0 | 1 | 2, cl: string | false, m: boolean) =>
    shown.map((g, i) => (rows[i] === k ? chip(g, cl, m ? i : null) : null));
  const noteEl = (row2: boolean) => (
    <span className={cls("dt-gn", noteSw.cls, !noteSw.shown && "dt-gn-0", !row2 && two && "dt-gn-off")} role={row2 ? undefined : "note"}
      title={noteAll.current.get(noteSw.shown) || undefined} aria-hidden={row2 || !noteSw.shown || two || undefined}>
      {noteSw.shown && <><Icon name="info" size={14} /><span>{noteSw.shown}</span></>}
    </span>
  );
  const copy = (rows: number[], cl: "hp-wo" | "hp-no", m: boolean) => (
    <div className={cls("dt-g2r", cl)} style={{ "--gi": `${lab.l}px` } as CSSProperties}>
      <div className="dt-grow dt-grow1">{rowOf(rows, 1, false, m)}</div>
      <div className="dt-grow">
        {rowOf(rows, 2, false, m)}
        {hidden(rows) > 0 && <span className="dt-gmore">ещё {hidden(rows)}</span>}
        {noteEl(true)}
      </div>
      {m && rowOf(rows, 0, "dt-gc-x", true)}
    </div>
  );
  return (
    <div className={cls("dt-goal p2-in", two && "dt-goal-2")} style={{ animationDelay: "120ms" }} title={all || undefined}>
      <p className="dt-gl">
        <DsIcon name="target" size={16} color="#2563EB" style={{ flex: "none" }} />
        <span className={cls("hp-sw", sw.cls)}><span className="hp-wo">{lbl.wide}{more(lay?.wide)}</span><span className="hp-no">{lbl.narrow}{more(lay?.narrow)}</span></span>
        {/* предложение брифа без ответа в данных: тихая строка, одна (все — в подсказке); в двух рядах — в конце второго */}
        {noteEl(false)}
      </p>
      <span ref={meter} className="dt-gm" aria-hidden="true"><span>{goalsLabel(1).narrow}</span><span>ещё 9</span></span>
      <div ref={box} className={cls("dt-gcs", sw.cls, lay && lay.mode !== "full" && "dt-gcs-s", two && "dt-gcs-2")}>
        {two && lay ? (
          <>
            {copy(lay.wide, "hp-wo", true)}
            {copy(lay.narrow, "hp-no", false)}
          </>
        ) : (
          shown.map((g, i) => {
            const wide = lay ? lay.wide[i] > 0 : true, narrow = lay ? lay.narrow[i] > 0 : true;
            return chip(g, (wide && !narrow && "hp-wo") || (!wide && narrow && "hp-no") || (!wide && !narrow && "dt-gc-x"), i);
          })
        )}
      </div>
    </div>
  );
}
