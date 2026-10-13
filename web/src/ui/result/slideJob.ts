// Работа над одним слайдом без React (R-fixing, R-fixed, R-picture): шаги запуска «Исправить слайд», «Заменить» /
// «Убрать» изображение и «Вернуть как было» — чистый редьюсер, как presenceNext. У варианта одна задача за раз (сервер
// отвечает 409): пока на варианте идёт работа или возврат, новый запуск и второй возврат на нём отклоняются (тот же
// объект состояния); другой вариант той же презентации работает сам по себе — у каждого своя работа (`runs`).
// Каждый запуск — новый номер `seq`; шаги прежнего запуска (поздний ответ, конец его задачи) новый не трогают.
// Задача над вариантом, которую этот экран не запускал (начатая до возвращения на него, помощником, листом
// «Подробнее»), видна по идущим задачам хранилища (`variantLiveJob`); задача над слайдом (исправление, изображение,
// правка помощника, «Вернуть как было» слайда) становится работой экрана (`adopt`, `adoptPlan`) — у неё та же карточка
// хода, что у своей, и тот же итог у места действия. Задачи, сеть и перечитывание — useSlideJob.
import { humanError } from "../../lib/errors";
import type { ActiveJob } from "../../lib/jobState";
import type { Job, JobKind, PictureChangeResult, SlideFixResult } from "../../types";
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
  /** Неудачу ещё не показали у её места (человек был на другом слайде, без режима «Замечания», вне экрана): работа не
   *  уходит со сменой слайда, пока строку не увидели (`seen`); до тех пор о ней говорит строка результата. */
  unseen: boolean;
  /** Тихая строка итога у места действия (правка помощника, которую экран подхватил: что сделано или почему слайд остался
   *  прежним); null — её нет. */
  note: string | null;
  /** «Вернуть как было»: идёт или не получилось (строка `undoError`). */
  undo: "work" | "error" | null;
  undoError: string | null;
  /** Изменение сохранено, а презентация на экране не перечиталась: `change` — после работы (на экране прежний слайд,
   *  итога нет), `undo` — после «Вернуть как было» (на экране ещё исправленный). У места действия — строка с
   *  «Обновить», пока хранилище держит презентацию несвежей (`staleOf`); перечиталась — вид снова по презентации. */
  stale: "change" | "undo" | null;
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
  /** Работа `seq` кончилась: итог, отказ при запуске или неудача задачи (она ждёт, пока её строку увидят у места —
   *  `unseen`). `stale` — итог применён, а презентация не перечиталась. */
  | { type: "settled"; seq: number; at: number; fix?: SlideFixResult; picture?: PictureChangeResult; error?: string | null; stale?: boolean; note?: string | null }
  /** Задача над слайдом, которую экран не запускал (`adoptPlan`), становится его работой: номер задачи, её часы, замечания
   *  слайда для карточки хода; `undo` — это «Вернуть как было» (работа кончилась, идёт возврат). */
  | { type: "adopt"; kind: SlideJobKind; strategy: string; slide: number; jobId: string; startedAt: number; requested: Remark[]; undo: boolean }
  /** «Вернуть как было» на слайде: у кончившейся работы того же рода на этом слайде — её; иначе (перезагрузка: итога
   *  на странице нет) — свой запуск, сразу кончившийся, с идущим возвратом. */
  | { type: "undo"; kind: SlideJobKind; strategy: string; slide: number; at: number }
  | { type: "undoFailed"; seq: number; error: string }
  /** Вернулось как было, а презентация не перечиталась: на экране ещё прежний итог — строка с «Обновить». */
  | { type: "undoStale"; seq: number }
  /** Вернулось как было: итога больше нет — слайд снова со своими замечаниями. */
  | { type: "undone"; seq: number }
  /** Другой слайд или вариант: строка неудачи (увиденная) или «слайд остался прежним» уходит; итог, который можно вернуть,
   *  и неудача, которую ещё не видели у её места, остаются. Экран сначала снимает строки, потом отмечает увиденное
   *  (`seen`): неудача, до места которой только что дошли, не уходит в том же кадре. */
  | { type: "clear"; strategy: string }
  /** Строку неудачи работы варианта показали у её места: дальше она уходит со сменой слайда, как прежде. */
  | { type: "seen"; strategy: string }
  /** Неудача работы, чей экран закрылся (`SlideFail` хранилища): новый экран заводит её кончившейся работой с этой
   *  строкой — она встанет у своего места. Своя работа на варианте идёт или эта задача уже здесь — без перемен. */
  | { type: "failedAway"; strategy: string; slide: number; kind: SlideJobKind; action: "generate" | "remove" | null; jobId: string; error: string; at: number };

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
        action: a.action, requested: a.requested, fix: null, picture: null, error: null, note: null, undo: null, undoError: null, stale: null, unseen: false,
      }, seq);
    }
    case "adopt": {
      const r = runOf(s, a.strategy);
      if (slideBusy(r) || r?.jobId === a.jobId) return s;
      const seq = s.seq + 1;
      return put(s, a.strategy, {
        seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: a.undo ? "done" : "work", jobId: a.jobId, startedAt: a.startedAt,
        endedAt: a.undo ? a.startedAt : null, wish: "", action: null, requested: a.requested, fix: null, picture: null, error: null, note: null,
        undo: a.undo ? "work" : null, undoError: null, stale: null, unseen: false,
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
      // подхваченная замена изображения узнаёт, что делали («Заменить» или «Убрать»), из итога
      return put(s, k, {
        ...r, phase: "done", endedAt: a.at, fix: a.fix ?? r.fix, picture: a.picture ?? r.picture, action: r.action ?? a.picture?.action ?? null,
        error: a.error ?? null, note: a.note ?? null, stale: a.stale ? "change" : null, unseen: !!a.error,
      });
    }
    case "undo": {
      const r = runOf(s, a.strategy);
      if (slideBusy(r)) return s;
      if (r && r.phase === "done" && r.kind === a.kind && r.slide === a.slide) return put(s, a.strategy, { ...r, undo: "work", undoError: null, stale: null });
      const seq = s.seq + 1;
      return put(s, a.strategy, {
        seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "done", jobId: null, startedAt: a.at, endedAt: a.at, wish: "", action: null,
        requested: [], fix: null, picture: null, error: null, note: null, undo: "work", undoError: null, stale: null, unseen: false,
      }, seq);
    }
    case "undoFailed": {
      const k = ownerOf(s, a.seq);
      return k === null ? s : put(s, k, { ...s.runs[k]!, undo: "error", undoError: a.error });
    }
    case "undoStale": {
      const k = ownerOf(s, a.seq);
      return k === null ? s : put(s, k, { ...s.runs[k]!, undo: null, undoError: null, stale: "undo" });
    }
    case "undone": {
      const k = ownerOf(s, a.seq);
      return k === null ? s : put(s, k, null);
    }
    case "clear": {
      const r = runOf(s, a.strategy);
      // строка «не обновилась» с «Обновить» остаётся: изменение сохранено, экран его ещё не показал
      // неудача, которую ещё не показали у её места, ждёт его (иначе она не была бы сказана нигде)
      const changedNothing = !!r && r.phase === "done" && r.undo !== "work" && !r.fix?.applied && !r.picture?.applied && !r.stale && !r.note && !r.unseen;
      return changedNothing ? put(s, a.strategy, null) : s;
    }
    case "seen": {
      const r = runOf(s, a.strategy);
      return r && r.unseen ? put(s, a.strategy, { ...r, unseen: false }) : s;
    }
    case "failedAway": {
      const r = runOf(s, a.strategy);
      if (slideBusy(r) || r?.jobId === a.jobId) return s;
      const seq = s.seq + 1;
      return put(s, a.strategy, {
        seq, kind: a.kind, strategy: a.strategy, slide: a.slide, phase: "done", jobId: a.jobId, startedAt: a.at, endedAt: a.at, wish: "", action: a.action,
        requested: [], fix: null, picture: null, error: a.error, note: null, undo: null, undoError: null, stale: null, unseen: true,
      }, seq);
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
  if (j.kind === "undo") return { why: UNDO_BUSY, slide };
  if (j.kind === "slide_fix" && slide) return { why: `Агент сейчас исправляет слайд ${slide}`, slide };
  if (j.kind === "picture" && slide) return { why: `Агент меняет изображение на слайде ${slide}`, slide };
  return { why: VARIANT_BUSY, slide };
}

/** Несвежесть работы, которую показывает экран: строка с «Обновить» — пока хранилище держит презентацию несвежей
 *  (`staleNow`); перечиталась — null, и вид снова по презентации (итог, возврат). */
export const staleOf = (run: SlideRun | null | undefined, staleNow: boolean): SlideRun["stale"] => (run?.stale && staleNow ? run.stale : null);

/** Почему новая работа над вариантом сейчас не начнётся (подсказка выключенной кнопки); null — начнётся. */
export function busyWhy(run: SlideRun | null | undefined): string | null {
  if (!run || !slideBusy(run)) return null;
  if (run.undo === "work") return UNDO_BUSY;
  return run.kind === "fix" ? `Агент сейчас исправляет слайд ${run.slide}` : `Агент меняет изображение на слайде ${run.slide}`;
}

const UNDO_BUSY = "Возвращаю как было — дождитесь конца";

/** Как экран подхватывает задачу над вариантом, которую не запускал (`j` — `variantLiveJob`), чтобы она выглядела как
 *  своя: исправление слайда и правка помощника на слайде — работа `fix` (карточка хода R-fixing), изображение —
 *  `picture` (ход в карточке «Изображение», R-picture), «Вернуть как было» слайда — возврат работы того рода, каким
 *  было последнее изменение слайда (`undoKind`). Задача над всем вариантом («Исправить всё», возврат из «Агента») — не
 *  слайда: её не подхватывают (кнопки выключены с её причиной). Своя работа над вариантом ещё идёт — тоже нет. */
export function adoptPlan(j: ActiveJob | null, run: SlideRun | null, undoKind: (slide: number) => SlideJobKind): { kind: SlideJobKind; slide: number; undo: boolean; source: JobKind } | null {
  if (!j || !j.target || j.target.slide < 1 || slideBusy(run) || run?.jobId === j.id) return null;
  const slide = j.target.slide;
  if (j.kind === "slide_fix" || j.kind === "edit") return { kind: "fix", slide, undo: false, source: j.kind };
  if (j.kind === "picture") return { kind: "picture", slide, undo: false, source: j.kind };
  if (j.kind === "undo") return { kind: undoKind(slide), slide, undo: true, source: j.kind };
  return null;
}

/** Что не получилось у работы над слайдом — словами места действия; `edit` — правка помощника («поменять слайд»). */
export function jobWhat(kind: SlideJobKind, action: "generate" | "remove" | null, slide?: number, edit = false): string {
  const on = slide ? ` ${slide}` : "";
  if (edit) return `поменять слайд${on}`;
  if (kind === "fix") return `исправить слайд${on}`;
  return `${action === "remove" ? "убрать изображение" : "заменить изображение"}${slide ? ` на слайде ${slide}` : ""}`;
}

/** Работа над слайдом не удалась, а человек её места не видит (ушёл с экрана, режим «Замечания» выключен, другой слайд):
 *  строка результата — «Не получилось исправить слайд 5: модель не ответила», без технического хвоста. */
export function awayFailText(kind: SlideJobKind, action: "generate" | "remove" | null, slide: number, job: Pick<Job, "error" | "message">, edit = false): string {
  const why = humanError(job.error ?? job.message, "");
  const lead = `Не получилось ${jobWhat(kind, action, slide, edit)}`;
  return why ? `${lead}: ${why[0].toLowerCase()}${why.slice(1).replace(/[.\s]+$/, "")}.` : `${lead}. Попробуйте ещё раз.`;
}

/** Неудача работы над слайдом, чьё место человек не видел (строка результата до тех пор, пока он не дойдёт до места):
 *  задача, презентация, вариант, слайд, род работы; `text` — строка результата («Не получилось исправить слайд 5: …»),
 *  `error` — строка у места («Модель не ответила»). */
export interface SlideFail { jobId: string; gid: string; strategy: string; slide: number; kind: SlideJobKind; action: "generate" | "remove" | null; text: string; error: string }

/** Где человек на экране результата: вариант и слайд, включён ли режим «Замечания», открыта ли колонка «Изображение»,
 *  открыто ли что-то поверх. */
export interface ResultAt { result: boolean; layered: boolean; strategy: string; slide: number; remarks: boolean; picture: boolean }

/** Место работы над слайдом на экране: исправление — панель замечаний на его слайде, изображение — карточка
 *  «Изображение» на его слайде; ничего поверх. Только здесь строка неудачи видна (и считается увиденной). */
export const placeShown = (w: { strategy: string; slide: number; kind: SlideJobKind }, at: ResultAt): boolean =>
  at.result && !at.layered && at.strategy === w.strategy && at.slide === w.slide && (w.kind === "fix" ? at.remarks : at.picture);

/** Почему «Вернуть как было» не нажимается, пока презентация несвежая: возврат отменил бы последнее изменение на сервере,
 *  а на экране его ещё нет. */
export const STALE_FIRST = "Сначала обновите презентацию";
/** «Вернуть как было» (панель, карточка «Изображение», «Качество», «Агент»): выключено с причиной, пока презентация
 *  несвежая. */
export const undoOffOf = (staleNow: boolean): string | null => (staleNow ? STALE_FIRST : null);

/** Строка результата о неудаче работы (`slideFail`) этой презентации — пока место работы не на экране (там строка стоит
 *  у работы: одна строка на неудачу). */
export const failInRow = (f: SlideFail | null | undefined, gid: string, at: ResultAt): SlideFail | null =>
  f && f.gid === gid && !placeShown(f, at) ? f : null;

/** Запасная строка «не обновилась» в ряду результата: презентация несвежая, а ни одна работа экрана не говорит этого у
 *  своего места на экране. */
export const staleInRow = (staleNow: boolean, staleRuns: readonly SlideRun[], at: ResultAt): boolean =>
  staleNow && !staleRuns.some((r) => placeShown(r, at));

/** Строка `slideFail` после «больше не нужна» (`dropSlideFail`): работу увидели у места (`jobId`) или над вариантом
 *  началась новая (`gid` + `strategy`); не та — остаётся. */
export function slideFailAfter(cur: SlideFail | null, m: { jobId?: string | null; gid?: string; strategy?: string }): SlideFail | null {
  if (!cur) return cur;
  const hit = m.jobId ? cur.jobId === m.jobId : !!m.gid && cur.gid === m.gid && (!m.strategy || cur.strategy === m.strategy);
  return hit ? null : cur;
}

/** «Показать» у строки неудачи изображения ждёт, пока карточку можно открыть: вариант сменился, слайд тот, панель
 *  режима «Замечания» ушла с экрана (`fading` — она ещё гаснет; пока она на экране, картинки не выбираются). `open` —
 *  открыть карточку картинки слайда; `wait` — ещё рано; `drop` — человек ушёл на другой слайд или вариант или снова
 *  включил «Замечания» (U3): ждать нечего, карточка потом не выскочит сама. */
export function revealStep(pending: { strategy: string; slide: number } | null, at: { strategy: string; slide: number; remarks: boolean; fading: boolean }): "open" | "wait" | "drop" | null {
  if (!pending) return null;
  if (at.remarks || at.strategy !== pending.strategy || at.slide !== pending.slide) return "drop";
  return at.fading ? "wait" : "open";
}

/** Короткие слова строки под названием компактного вида: колонке шапки при открытом помощнике мало места (246 px при
 *  1280) — длинная фраза обрезалась бы до «Изменения сохр…» (читается как успех) или теряла бы номер слайда. Полная фраза
 *  — в подсказке. */
export const HEAD_STALE = "Не обновилась";
export const headFail = (slide: number) => `Слайд ${slide}: не вышло`;

/** Строка под названием компактного вида (помощник открыт) — та же строка ряда результата, с тем же действием, короткими
 *  словами (`text`; полная фраза — `title`): неудача запуска или открытия — как есть, без действия; неудача работы, чьё
 *  место не на экране, — «Слайд N: не вышло» и «Показать»; несвежая презентация — «Не обновилась» и «Обновить», если
 *  лента помощника уже не говорит этого живой строкой (`feedSays`): одна строка на одно. */
export function compactRow(o: { err: string | null; fail: SlideFail | null; stale: string | null; feedSays: boolean }): { text: string; title: string; act: "show" | "refresh" | null } | null {
  if (o.err) return { text: o.err, title: o.err, act: null };
  if (o.fail) return { text: headFail(o.fail.slide), title: o.fail.text, act: "show" };
  if (o.stale && !o.feedSays) return { text: HEAD_STALE, title: o.stale, act: "refresh" };
  return null;
}
