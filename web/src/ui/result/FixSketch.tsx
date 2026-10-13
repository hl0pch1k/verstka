// «Агент исправляет слайд» на сцене (R-fixing, V2 `rm-fx`, утверждено владельцем): по «Исправить слайд» сцена
// сжимается до scale(.5) за 520 мс в двумерный эскиз — такой же, как карточка раскадровки сборки (тёмная плитка со
// схемой формы слайда, ui/build/SlideSketch); пока агент работает, линии схемы перерисовываются и внизу бежит рабочая
// полоса; когда исправление готово и новое превью декодировано, эскиз разворачивается обратно в слайд (520 мс), и через
// 560 мс панель показывает «Исправлено». Движение — классы rf-mini / rm-dk / rf-sk / rf-work (result.css), только
// transform и opacity.
import { useEffect, useRef, useState } from "react";
import { decodeImage } from "../../lib/motion";
import type { SketchKind } from "../../lib/stage";
import { SlideSketch } from "../build/SlideSketch";
import { cls } from "../kit/cls";

export type FxPhase = "pre" | "mini" | "post";

/** Эскиз держится хотя бы столько, сколько сцена сжимается, и ещё немного — короткая задача не дёргает сцену. */
const MIN_MINI = 900;
/** Разворот обратно (520 мс) и пауза до «Исправлено» (V2: 560 мс). */
const POST_MS = 560;
/** Сколько разворот ждёт декодирования нового превью, прежде чем развернуться как есть. */
const DECODE_WAIT = 1500;

/** Фаза эскиза исправления `seq` на этой сцене. `seq` — запуск исправления, видимый здесь (null — его здесь нет:
 *  другой слайд, режим выключен); `done` — задача кончилась и презентация перечитана; `src` — превью слайда, в которое
 *  эскиз разворачивается. Исправление, которое кончилось, пока его не было видно, не играется. */
export function useFixStage(seq: number | null, done: boolean, src: string | null): FxPhase | null {
  const [st, setSt] = useState<{ seq: number; phase: FxPhase } | null>(null);
  const played = useRef(new Set<number>());
  const miniAt = useRef(0);
  const srcRef = useRef(src);
  srcRef.current = src;

  // запуск: со следующего кадра сцена сжимается (переход стартует из развёрнутого состояния)
  useEffect(() => {
    if (seq === null || played.current.has(seq)) return void setSt(null);
    if (done) {
      // кончилось там, где его не видели (или до первого кадра), — без движения
      if (!st || st.seq !== seq) {
        played.current.add(seq);
        setSt(null);
      }
      return;
    }
    if (st && st.seq === seq) return;
    setSt({ seq, phase: "pre" });
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        miniAt.current = Date.now();
        setSt((cur) => (cur && cur.seq === seq ? { seq, phase: "mini" } : cur));
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [seq, done]); // st — только сверка запуска

  // готово: эскиз держится свой минимум, новое превью декодируется — разворот
  const phase = st?.phase ?? null;
  const cur = st?.seq ?? null;
  useEffect(() => {
    if (!done || cur === null || cur !== seq || (phase !== "pre" && phase !== "mini")) return;
    let off = false;
    const wait = phase === "pre" ? MIN_MINI : Math.max(0, miniAt.current + MIN_MINI - Date.now());
    const hold = window.setTimeout(() => {
      const u = srcRef.current;
      const ready = u ? Promise.race([decodeImage(u).catch(() => {}), new Promise((r) => window.setTimeout(r, DECODE_WAIT))]) : Promise.resolve();
      void ready.then(() => {
        if (!off) setSt((x) => (x && x.seq === cur ? { seq: cur, phase: "post" } : x));
      });
    }, wait);
    return () => {
      off = true;
      window.clearTimeout(hold);
    };
  }, [done, cur, seq, phase]);

  // развернулся — эскиз снимается, панель показывает итог
  useEffect(() => {
    if (phase !== "post" || cur === null) return;
    const t = window.setTimeout(() => {
      played.current.add(cur);
      setSt((x) => (x && x.seq === cur ? null : x));
    }, POST_MS);
    return () => window.clearTimeout(t);
  }, [phase, cur]);

  return seq !== null && st && st.seq === seq ? st.phase : null;
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
