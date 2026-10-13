// «Агент исправляет слайд» на сцене (R-fixing, V2 `rm-fx`, утверждено владельцем): по «Исправить слайд» сцена
// сжимается до scale(.5) за 520 мс в двумерный эскиз — такой же, как карточка раскадровки сборки (тёмная плитка со
// схемой формы слайда, ui/build/SlideSketch); пока агент работает, линии схемы перерисовываются и внизу бежит рабочая
// полоса; когда исправление готово и новое превью декодировано, эскиз разворачивается обратно в слайд (520 мс), и через
// 560 мс панель показывает «Исправлено». Движение — классы rf-mini / rm-dk / rf-sk / rf-work (result.css), только
// transform и opacity.
import { useEffect, useReducer } from "react";
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

/** Слой эскиза поверх сцены: тёмная подложка закрывает превью, поверх — схема формы слайда и рабочая полоса. */
export function FixSketch({ phase, kind, formula }: { phase: FxPhase; kind: SketchKind; formula: boolean }) {
  return (
    <span className={cls("rm-fx", phase === "mini" && "rf-mini")} aria-hidden="true">
      <span className="rm-dk" />
      <SlideSketch kind={kind} formula={formula} draw />
      <span className="rf-work" />
    </span>
  );
}
