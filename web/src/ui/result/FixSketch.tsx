// «Агент исправляет слайд» на сцене (R-fixing, V2 `rm-fx`): по «Исправить слайд» сцена сжимается до scale(.5) за
// 520 мс — миниатюра самого слайда; пока агент работает, превью «разбирается» на части (волна отхода и подсветки,
// сканирующая линия, рабочая полоса); когда исправление готово и новое превью декодировано, части гаснут поверх нового
// превью (кросс-фейд из старого), сцена разворачивается обратно (520 мс), и через 560 мс панель показывает
// «Исправлено». Превью нет — тёмный эскиз формы слайда, как карточка раскадровки (ui/build/SlideSketch). Движение —
// классы rf-mini / rf-post / rf-pc / rf-scan / rf-work (result.css), только transform и opacity.
import { useEffect, useReducer, useState, type CSSProperties } from "react";
import { decodeImage } from "../../lib/motion";
import type { SketchKind } from "../../lib/stage";
import { SlideSketch } from "../build/SlideSketch";
import { cls } from "../kit/cls";
import { FX0, fixStageNext, fxPhase, holdLeft, type FxPhase } from "./fixStage";

export type { FxPhase } from "./fixStage";

/** Разворот обратно (520 мс) и пауза до «Исправлено» (V2: 560 мс). */
const POST_MS = 560;
/** Сколько разворот ждёт декодирования нового превью, прежде чем развернуться как есть. */
const DECODE_WAIT = 1500;

/** Фаза эскиза исправления `seq` на этой сцене. `seq` — запуск исправления, видимый здесь (null — его здесь нет:
 *  другой слайд, режим выключен); `done` — задача кончилась и презентация перечитана; `src` — превью слайда, в которое
 *  эскиз разворачивается. Шаги — чистый fixStageNext (fixStage.ts); здесь — только кадры и таймеры. */
export function useFixStage(seq: number | null, done: boolean, src: string | null): FxPhase | null {
  const [st, send] = useReducer(fixStageNext, FX0);
  useEffect(() => send({ type: "sync", seq, done }), [seq, done]);
  const phase = fxPhase(st, seq);
  const at = st.cur?.at ?? 0;

  // запуск: со следующего кадра сцена сжимается (переход стартует из развёрнутого состояния)
  useEffect(() => {
    if (phase !== "pre" || seq === null) return;
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => send({ type: "mini", seq, at: Date.now() }));
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [phase, seq]);

  // готово: эскиз держится свой минимум, новое превью декодируется — разворот
  useEffect(() => {
    if (!done || seq === null || (phase !== "pre" && phase !== "mini")) return;
    let off = false;
    const hold = window.setTimeout(() => {
      const ready = src ? Promise.race([decodeImage(src).catch(() => {}), new Promise((r) => window.setTimeout(r, DECODE_WAIT))]) : Promise.resolve();
      void ready.then(() => {
        if (!off) send({ type: "post", seq });
      });
    }, holdLeft(phase, at, Date.now()));
    return () => {
      off = true;
      window.clearTimeout(hold);
    };
  }, [done, seq, phase, at, src]);

  // развернулся — эскиз снимается, панель показывает итог
  useEffect(() => {
    if (phase !== "post" || seq === null) return;
    const t = window.setTimeout(() => send({ type: "end", seq }), POST_MS);
    return () => window.clearTimeout(t);
  }, [phase, seq]);

  return phase;
}

/** Сетка «разборки» превью: 4 × 3 части. */
const COLS = 4;
const ROWS = 3;
/** Куда часть отходит, пока агент работает (px сцены до её сжатия; сжатая — вдвое меньше): от центра наружу. */
const drift = (c: number, r: number) => ({ dx: ((c + 0.5) / COLS - 0.5) * 28, dy: ((r + 0.5) / ROWS - 0.5) * 24 });

/** Слой исправления поверх сцены. Есть превью слайда — анимация на нём самом: превью разбирается на части, они волной
 *  (по диагонали) отходят от центра, подсвечиваются и встают на место, по слайду проходит сканирующая линия; когда
 *  исправление готово, части гаснут, и под ними уже проявилось новое превью (Shots) — кросс-фейд из старого. Превью
 *  берётся то, что было при запуске (`src` на первом кадре): новое приходит под слой, а не в его части. Превью нет —
 *  прежний эскиз формы слайда (SlideSketch). Только transform и opacity; «уменьшить движение» — части стоят, линия
 *  не бежит (result.css). */
export function FixSketch({ phase, kind, formula, src }: { phase: FxPhase; kind: SketchKind; formula: boolean; src?: string | null }) {
  const [shot] = useState(src ?? null);
  if (!shot) {
    return (
      <span className={cls("rm-fx", phase === "mini" && "rf-mini")} aria-hidden="true">
        <span className="rm-dk" />
        <SlideSketch kind={kind} formula={formula} draw />
        <span className="rf-work" />
      </span>
    );
  }
  const parts = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const { dx, dy } = drift(c, r);
      parts.push(
        <span key={`${r}-${c}`} className="rf-pc"
          style={{
            left: `${(c * 100) / COLS}%`, top: `${(r * 100) / ROWS}%`, width: `${100 / COLS}%`, height: `${100 / ROWS}%`,
            backgroundImage: `url("${shot}")`, backgroundSize: `${COLS * 100}% ${ROWS * 100}%`,
            backgroundPosition: `${(c * 100) / (COLS - 1)}% ${(r * 100) / (ROWS - 1)}%`,
            "--dx": `${dx.toFixed(1)}px`, "--dy": `${dy.toFixed(1)}px`, animationDelay: `${(c + r) * 110}ms`,
          } as CSSProperties} />,
      );
    }
  }
  return (
    <span className={cls("rm-fx rf-live", phase === "mini" && "rf-mini", phase === "post" && "rf-post")} aria-hidden="true">
      {/* подложка под частями: в щелях между отошедшими частями — ровный фон, а не то же превью вторым слоем */}
      <span className="rf-bd" />
      <span className="rf-pcs">{parts}</span>
      <span className="rf-scan" />
      <span className="rf-work" />
    </span>
  );
}
