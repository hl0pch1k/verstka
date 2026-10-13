// Работа над одним слайдом без React (R-fixing, R-fixed, R-picture): шаги запуска «Исправить слайд», «Заменить» /
// «Убрать» изображение и «Вернуть как было» — чистый редьюсер, как presenceNext. У варианта одна задача за раз (сервер
// отвечает 409): пока на варианте идёт работа или возврат, новый запуск и второй возврат на нём отклоняются (тот же
// объект состояния); другой вариант той же презентации работает сам по себе — у каждого своя работа (`runs`).
// Каждый запуск — новый номер `seq`; шаги прежнего запуска (поздний ответ, конец его задачи) новый не трогают.
// Задача над вариантом, которую этот экран не запускал (начатая до возвращения на него, помощником, листом
// «Подробнее»), видна по идущим задачам хранилища (`variantLiveJob`). Задачи, сеть и перечитывание — useSlideJob.
import type { ActiveJob } from "../../lib/jobState";
import type { PictureChangeResult, SlideFixResult } from "../../types";
import { VARIANT_BUSY } from "../details/variantWork";
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

/** Работа каждого варианта (ключ — вариант); номер последнего запуска — один на все. */
export interface SlideJobState { seq: number; runs: Record<string, SlideRun | undefined> }
export const JOB0: SlideJobState = { seq: 0, runs: {} };

/** Работа варианта `strategy`; null — её нет. */
export const runOf = (s: SlideJobState, strategy: string): SlideRun | null => s.runs[strategy] ?? null;

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
  | { type: "clear"; strategy: string };

/** Идёт задача (сама работа или «Вернуть как было»): новая не начинается. */
export const slideBusy = (run: SlideRun | null | undefined): boolean => !!run && (run.phase === "work" || run.undo === "work");

/** Вариант, чья работа — запуск `seq`; null — такого запуска больше нет (его сменил новый). */
const ownerOf = (s: SlideJobState, seq: number): string | null => {
  for (const [k, r] of Object.entries(s.runs)) if (r && r.seq === seq) return k;
  return null;
};
const put = (s: SlideJobState, strategy: string, run: SlideRun | null, seq = s.seq): SlideJobState => {
  const runs = { ...s.runs };
  if (run) runs[strategy] = run;
  else delete runs[strategy];
  return { seq, runs };
};

export function slideJobNext(s: SlideJobState, a: SlideJobAction): SlideJobState {
  switch (a.type) {
    case "start": {
      if (slideBusy(runOf(s, a.strategy))) return s;
      const seq = s.seq + 1;
      return put(s, a.strategy, {
        seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "work", jobId: null, startedAt: a.at, endedAt: null, wish: a.wish.trim(),
        action: a.action, requested: a.requested, fix: null, picture: null, error: null, undo: null, undoError: null,
      }, seq);
    }
    case "accepted": {
      const k = ownerOf(s, a.seq);
      const r = k === null ? null : s.runs[k]!;
      return k !== null && r && r.phase === "work" ? put(s, k, { ...r, jobId: a.jobId, startedAt: a.at }) : s;
    }
    case "settled": {
      const k = ownerOf(s, a.seq);
      if (k === null) return s;
      const r = s.runs[k]!;
      return put(s, k, { ...r, phase: "done", endedAt: a.at, fix: a.fix ?? r.fix, picture: a.picture ?? r.picture, error: a.error ?? null });
    }
    case "undo": {
      const r = runOf(s, a.strategy);
      if (slideBusy(r)) return s;
      if (r && r.phase === "done" && r.kind === a.kind && r.slide === a.slide) return put(s, a.strategy, { ...r, undo: "work", undoError: null });
      const seq = s.seq + 1;
      return put(s, a.strategy, {
        seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "done", jobId: null, startedAt: a.at, endedAt: a.at, wish: "", action: null,
        requested: [], fix: null, picture: null, error: null, undo: "work", undoError: null,
      }, seq);
    }
    case "undoFailed": {
      const k = ownerOf(s, a.seq);
      return k === null ? s : put(s, k, { ...s.runs[k]!, undo: "error", undoError: a.error });
    }
    case "undone": {
      const k = ownerOf(s, a.seq);
      return k === null ? s : put(s, k, null);
    }
    case "clear": {
      const r = runOf(s, a.strategy);
      const changedNothing = !!r && r.phase === "done" && r.undo !== "work" && !r.fix?.applied && !r.picture?.applied;
      return changedNothing ? put(s, a.strategy, null) : s;
    }
  }
}

/** Задача над вариантом `strategy` презентации `gid`, которую этот экран не запускал (`own` — задача его работы):
 *  исправление слайда, начатое до возвращения на экран, правка помощника, «Исправить всё» и «Вернуть как было» листа
 *  «Подробнее». Сервер держит одну задачу на вариант — пока она идёт, работа над ним здесь не начинается. Самая новая. */
export function variantLiveJob(live: readonly ActiveJob[], gid: string, strategy: string, own: string | null): ActiveJob | null {
  let found: ActiveJob | null = null;
  for (const j of live) if (j.id !== own && j.target && j.target.generation === gid && j.target.strategy === strategy) found = j;
  return found;
}

/** Почему работа над вариантом не начнётся, пока идёт чужая задача `j` (подсказка выключенной кнопки), и какой слайд она
 *  меняет (дуга на его миниатюре; null — весь вариант). */
export function liveWork(j: ActiveJob): { why: string; slide: number | null } {
  const slide = j.target && j.target.slide > 0 ? j.target.slide : null;
  if (j.kind === "slide_fix" && slide) return { why: `Агент сейчас исправляет слайд ${slide}`, slide };
  if (j.kind === "picture" && slide) return { why: `Агент меняет изображение на слайде ${slide}`, slide };
  return { why: VARIANT_BUSY, slide };
}

/** Почему новая работа над вариантом сейчас не начнётся (подсказка выключенной кнопки); null — начнётся. */
export function busyWhy(run: SlideRun | null | undefined): string | null {
  if (!run || !slideBusy(run)) return null;
  if (run.undo === "work") return "Возвращаю как было — дождитесь конца";
  return run.kind === "fix" ? `Агент сейчас исправляет слайд ${run.slide}` : `Агент меняет изображение на слайде ${run.slide}`;
}
