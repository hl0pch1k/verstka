// «Агент исправляет слайд» на сцене (R-fixing, V2 `rm-fx`, утверждено владельцем): по «Исправить слайд» сцена
// сжимается до scale(.5) за 520 мс в двумерный эскиз — тёмная плитка со схемой формы слайда, как карточка раскадровки
// сборки; пока агент работает, блоки схемы по шагам перестраиваются (fixBlocks.ts) — без полосы загрузки (замечание
// владельца 18.10); когда исправление готово и новое превью декодировано, эскиз разворачивается обратно в слайд
// (520 мс), и через 560 мс панель показывает «Исправлено». Движение — классы rf-mini / rm-dk / rf-bx / rf-bk
// (result.css), только transform и opacity.
import { useEffect, useReducer, useState } from "react";
import { decodeImage } from "../../lib/motion";
import type { SketchKind } from "../../lib/stage";
import { prefersReducedMotion } from "../../lib/motion";
import { cls } from "../kit/cls";
import { FX0, fixStageNext, fxPhase, holdLeft, type FxPhase } from "./fixStage";
import { BLOCKS, blockRadius, blockTransform, layoutAt, litAt, startLayout, STEP_MS, type BlockId } from "./fixBlocks";

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

/** Полоски (заголовок, строки, акцент) — с полукруглыми концами; плашки — со скруглением 5. */
const BAR: Record<BlockId, boolean> = { head: true, l1: true, l2: true, l3: true, l4: true, c1: false, c2: false, c3: false, acc: false };

/** Цвет блока: заголовок, строки, плашки, акцент (result.css). */
const TONE: Record<BlockId, string> = { head: "rf-hd", l1: "rf-ln", l2: "rf-ln", l3: "rf-ln", l4: "rf-ln", c1: "rf-cd", c2: "rf-cd", c3: "rf-cd", acc: "rf-ac" };

/** Шаг перестройки эскиза: идёт, пока сцена сжата (`on`); «уменьшить движение» — стоит первая раскладка. */
function useSketchStep(on: boolean): number {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!on || prefersReducedMotion()) return;
    const t = window.setInterval(() => setStep((s) => s + 1), STEP_MS);
    return () => window.clearInterval(t);
  }, [on]);
  return step;
}

/** Слой эскиза поверх сцены: тёмная подложка закрывает превью, поверх — эскиз формы слайда из девяти блоков, которые по
 *  шагам работы агента перестраиваются (fixBlocks.ts): плашки отходят на новые места и меняют форму, строки
 *  переукладываются, один блок на шаге подсвечивается. Раскладки идут последовательностью (с формы самого слайда), не
 *  по одному кругу. Только transform и opacity. */
export function FixSketch({ phase, kind }: { phase: FxPhase; kind: SketchKind; formula?: boolean }) {
  const start = startLayout(kind);
  const step = useSketchStep(phase === "mini");
  const l = layoutAt(start, step);
  const lit = phase === "mini" && step > 0 ? litAt(start, step) : null;
  return (
    <span className={cls("rm-fx", phase === "mini" && "rf-mini")} aria-hidden="true">
      <span className="rm-dk" />
      <span className="rf-bx">
        {BLOCKS.map((id) => (
          <span key={id} className={cls("rf-bk", TONE[id], lit === id && "rf-lit")}
            style={{ transform: blockTransform(l[id]), opacity: l[id].o, borderRadius: blockRadius(l[id], BAR[id]) }}>
            <span className="rf-gl" style={{ borderRadius: "inherit" }} />
          </span>
        ))}
      </span>
    </span>
  );
}
