// Работа над одним слайдом без React (R-fixing, R-fixed, R-picture): шаги запуска «Исправить слайд», «Заменить» /
// «Убрать» изображение и «Вернуть как было» — чистый редьюсер, как presenceNext. У варианта одна задача за раз (сервер
// отвечает 409): пока идёт работа или возврат, новый запуск и второй возврат отклоняются (тот же объект состояния).
// Каждый запуск — новый номер `seq`; шаги прежнего запуска (поздний ответ, конец его задачи) новый не трогают.
// Задачи, сеть и перечитывание презентации — useSlideJob.
import type { PictureChangeResult, SlideFixResult } from "../../types";
import type { Remark } from "./marks";

export type SlideJobKind = "fix" | "picture";

export interface SlideRun {
  /** Номер запуска: новая работа — новый номер (ключ движения сцены и панели). */
  seq: number;
  kind: SlideJobKind;
  strategy: string;
  slide: number;
  /** work — задача идёт (или презентация перечитывается после неё); done — кончилась (итог, отказ или неудача). */
  phase: "work" | "done";
  /** Задача сервера; null — сервер ещё не ответил на запуск (или отказал). */
  jobId: string | null;
  startedAt: number;
  /** Когда работа кончилась (мс): часы хода останавливаются здесь. */
  endedAt: number | null;
  /** Пожелание человека («Ваши правки»). */
  wish: string;
  /** Изображение: что сделать. */
  action: "generate" | "remove" | null;
  /** Исправление: замечания, которые просили исправить, — как они стояли на слайде при запуске. */
  requested: Remark[];
  fix: SlideFixResult | null;
  picture: PictureChangeResult | null;
  /** Неудача запуска или задачи — строкой у места действия. */
  error: string | null;
  /** «Вернуть как было»: идёт или не получилось (строка `undoError`). */
  undo: "work" | "error" | null;
  undoError: string | null;
}

export interface SlideJobState { seq: number; run: SlideRun | null }
export const JOB0: SlideJobState = { seq: 0, run: null };

export type SlideJobAction =
  | { type: "start"; kind: SlideJobKind; strategy: string; slide: number; wish: string; action: "generate" | "remove" | null; requested: Remark[]; at: number }
  /** Сервер принял запуск `seq`: его задача, часы — с этого момента. */
  | { type: "accepted"; seq: number; jobId: string; at: number }
  /** Работа `seq` кончилась: итог, отказ при запуске или неудача задачи. */
  | { type: "settled"; seq: number; at: number; fix?: SlideFixResult; picture?: PictureChangeResult; error?: string | null }
  /** «Вернуть как было» на слайде: у кончившейся работы того же рода на этом слайде — её; иначе (перезагрузка: итога
   *  на странице нет) — свой запуск, сразу кончившийся, с идущим возвратом. */
  | { type: "undo"; kind: SlideJobKind; strategy: string; slide: number; at: number }
  | { type: "undoFailed"; seq: number; error: string }
  /** Вернулось как было: итога больше нет — слайд снова со своими замечаниями. */
  | { type: "undone"; seq: number }
  /** Другой слайд: строка неудачи или «слайд остался прежним» уходит; итог, который можно вернуть, остаётся. */
  | { type: "clear" };

/** Идёт задача (сама работа или «Вернуть как было»): новая не начинается. */
export const slideBusy = (run: SlideRun | null): boolean => !!run && (run.phase === "work" || run.undo === "work");

const mine = (s: SlideJobState, seq: number) => !!s.run && s.run.seq === seq;

export function slideJobNext(s: SlideJobState, a: SlideJobAction): SlideJobState {
  switch (a.type) {
    case "start": {
      if (slideBusy(s.run)) return s;
      const seq = s.seq + 1;
      return {
        seq,
        run: {
          seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "work", jobId: null, startedAt: a.at, endedAt: null, wish: a.wish.trim(),
          action: a.action, requested: a.requested, fix: null, picture: null, error: null, undo: null, undoError: null,
        },
      };
    }
    case "accepted":
      return mine(s, a.seq) && s.run!.phase === "work" ? { ...s, run: { ...s.run!, jobId: a.jobId, startedAt: a.at } } : s;
    case "settled": {
      if (!mine(s, a.seq)) return s;
      const r = s.run!;
      return { ...s, run: { ...r, phase: "done", endedAt: a.at, fix: a.fix ?? r.fix, picture: a.picture ?? r.picture, error: a.error ?? null } };
    }
    case "undo": {
      if (slideBusy(s.run)) return s;
      const r = s.run;
      if (r && r.phase === "done" && r.kind === a.kind && r.strategy === a.strategy && r.slide === a.slide) return { ...s, run: { ...r, undo: "work", undoError: null } };
      const seq = s.seq + 1;
      return {
        seq,
        run: {
          seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "done", jobId: null, startedAt: a.at, endedAt: a.at, wish: "", action: null,
          requested: [], fix: null, picture: null, error: null, undo: "work", undoError: null,
        },
      };
    }
    case "undoFailed":
      return mine(s, a.seq) ? { ...s, run: { ...s.run!, undo: "error", undoError: a.error } } : s;
    case "undone":
      return mine(s, a.seq) ? { ...s, run: null } : s;
    case "clear": {
      const r = s.run;
      const changedNothing = !!r && r.phase === "done" && r.undo !== "work" && !r.fix?.applied && !r.picture?.applied;
      return changedNothing ? { ...s, run: null } : s;
    }
  }
}

/** Почему новая работа над вариантом сейчас не начнётся (подсказка выключенной кнопки); null — начнётся. */
export function busyWhy(run: SlideRun | null): string | null {
  if (!run || !slideBusy(run)) return null;
  if (run.undo === "work") return "Возвращаю как было — дождитесь конца";
  return run.kind === "fix" ? `Агент сейчас исправляет слайд ${run.slide}` : `Агент меняет изображение на слайде ${run.slide}`;
}
