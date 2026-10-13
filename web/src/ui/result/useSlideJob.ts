// Работа над одним слайдом открытой презентации (R-fixing, R-fixed, R-picture): «Исправить слайд» (задача
// `slide_fix`), «Заменить» / «Убрать» изображение (задача `picture`) и «Вернуть как было» («верни как было», задача
// `edit`; одно на всё приложение — хранилище `revertVariant`, им же пользуется лист «Подробнее»). Задачи идут через
// `runJob` хранилища тихо — ход и неудачу показывает место действия (панель замечаний, карточка «Изображение»), а не
// строка уведомления. Шаги запуска — чистый slideJobNext (slideJob.ts): у варианта одна
// задача за раз (сервер отвечает 409), второй запуск в том же кадре отклоняется. По готовности презентация
// перечитывается (`reloadIfOpen`: тот же вариант и слайд, превью — по новой ревизии `withRev`) — и тогда, когда человек
// уже ушёл с экрана результата: вернувшись, он видит новый слайд. Состояние этого экрана (итог, строки, часы) живёт,
// пока открыта эта презентация (ResultBody с ключом id), и переживает её перечитывание.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { asPictureResult } from "../../lib/pictures";
import { useApp, type ActiveJob } from "../../store";
import type { AgentEvent, Job, PictureChangeRequest, PictureChangeResult, SlideFixRequest, SlideFixResult } from "../../types";
import { asSlideFixResult } from "./fix";
import type { Remark } from "./marks";
import { JOB0, slideBusy, slideJobNext, type SlideJobAction, type SlideJobKind, type SlideJobState, type SlideRun } from "./slideJob";

export type { SlideJobKind, SlideRun } from "./slideJob";

export interface SlideLive { events: AgentEvent[]; progress: number; message: string }

export interface SlideJob {
  run: SlideRun | null;
  /** Брифовый вид: нет работы, идёт, кончилась. */
  phase: "idle" | "work" | "done";
  result: SlideFixResult | PictureChangeResult | null;
  /** Идёт задача (сама работа или «Вернуть как было»): новая не начинается. */
  busy: boolean;
  /** Ход задачи этого запуска: шаги агента, доля, последняя строка (после конца — последние увиденные). */
  live: SlideLive;
  start(kind: "fix", n: number, body: SlideFixRequest, requested: Remark[]): Promise<boolean>;
  start(kind: "picture", n: number, body: PictureChangeRequest): Promise<boolean>;
  /** «Вернуть как было» для итога этой работы. */
  undo(): void;
  /** «Вернуть как было» исправления слайда без итога на странице (перезагрузка): последнее изменение варианта — его. */
  revert(strategy: string, slide: number): void;
  /** Другой слайд: строка неудачи или «слайд остался прежним» уходит (итог, который можно вернуть, остаётся). */
  clear(): void;
}

const EMPTY: SlideLive = { events: [], progress: 0, message: "" };
const liveOf = (j: ActiveJob): SlideLive => ({ events: j.agent ?? [], progress: j.progress, message: j.message });

/** Неудача задачи по-человечески: первая русская строка ошибки, иначе — что не получилось. */
const jobError = (job: Job, what: string) => humanError(job.error ?? job.message, `Не получилось ${what}. Попробуйте ещё раз.`);
/** Отказ сервера при запуске (409 — вариант уже меняется, 503 — нет модели изображений, 422 — нечего исправлять). */
const startError = (e: unknown, what: string) =>
  humanError(e instanceof ApiError || e instanceof Error ? e.message : String(e), `Не получилось ${what}. Попробуйте ещё раз.`);

export function useSlideJob(gid: string, strategy: string): SlideJob {
  const { runJob, reloadIfOpen, revertVariant, activeJob } = useApp();
  // Последнее состояние — у шагов (клик, ответ сервера, конец задачи), а не у отрисовки: второй клик в том же кадре
  // видит первый запуск. Экран перерисовывается, пока он открыт; продолжения задач идут и без него.
  const box = useRef<SlideJobState>(JOB0);
  const [state, setState] = useState<SlideJobState>(JOB0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const send = useCallback((a: SlideJobAction): SlideJobState => {
    const next = slideJobNext(box.current, a);
    if (next !== box.current) {
      box.current = next;
      if (alive.current) setState(next);
    }
    return next;
  }, []);
  const run = state.run;

  // ход задачи — из слота `activeJob`, пока он её; слот уходит к другой задаче или пустеет — остаётся последнее
  // увиденное (панель доигрывает разворот эскиза)
  const mine = !!run?.jobId && activeJob?.id === run.jobId ? activeJob : null;
  const [seen, setSeen] = useState<{ jobId: string; live: SlideLive } | null>(null);
  useEffect(() => {
    if (mine) setSeen({ jobId: mine.id, live: liveOf(mine) });
  }, [mine]);
  const live = mine ? liveOf(mine) : run?.jobId && seen?.jobId === run.jobId ? seen.live : EMPTY;

  const start = useCallback(async (kind: "fix" | "picture", n: number, body: SlideFixRequest | PictureChangeRequest, requested: Remark[] = []) => {
    const pic = kind === "picture" ? (body as PictureChangeRequest) : null;
    const before = box.current;
    const now = send({
      type: "start", kind, strategy, slide: n, wish: (kind === "fix" ? (body as SlideFixRequest).wishes : pic?.wish) ?? "",
      action: pic ? pic.action ?? "generate" : null, requested, at: Date.now(),
    });
    if (now === before) return false;
    const s = now.seq;
    const what = kind === "fix" ? "исправить слайд" : pic?.action === "remove" ? "убрать изображение" : "заменить изображение";
    let jobId: string;
    try {
      jobId = (kind === "fix" ? await api.fixSlide(gid, strategy, n, body as SlideFixRequest) : await api.changePicture(gid, strategy, n, body as PictureChangeRequest)).job_id;
    } catch (e) {
      send({ type: "settled", seq: s, at: Date.now(), error: startError(e, what) });
      return false;
    }
    send({ type: "accepted", seq: s, jobId, at: Date.now() });
    const label = kind === "fix" ? `Исправляю слайд ${n}` : pic?.action === "remove" ? `Убираю изображение со слайда ${n}` : `Меняю изображение на слайде ${n}`;
    runJob(jobId, label, {
      kind: kind === "fix" ? "slide_fix" : "picture",
      target: { generation: gid, strategy, slide: n },
      area: "result",
      quiet: true,
      onDone: async (job) => {
        if (kind === "fix") {
          const res = asSlideFixResult(job.result);
          if (!res) return void send({ type: "settled", seq: s, at: Date.now(), error: "Сервер не смог исправить слайд. Попробуйте ещё раз." });
          // применённое исправление — новая версия презентации: сначала она (и без экрана результата), потом итог —
          // сцена разворачивается в новый слайд
          if (res.applied) await reloadIfOpen(gid);
          send({ type: "settled", seq: s, at: Date.now(), fix: res });
        } else {
          const res = asPictureResult(job.result);
          if (!res) return void send({ type: "settled", seq: s, at: Date.now(), error: "Сервер не смог поменять изображение. Попробуйте ещё раз." });
          if (res.applied) await reloadIfOpen(gid);
          send({ type: "settled", seq: s, at: Date.now(), picture: res, error: res.applied ? null : humanError(res.reply, "Изображение не поменялось. Попробуйте ещё раз.") });
        }
      },
      onFailed: (job) => void send({ type: "settled", seq: s, at: Date.now(), error: jobError(job, what) }),
    });
    return true;
  }, [gid, strategy, runJob, reloadIfOpen, send]) as SlideJob["start"];

  // «Вернуть как было» — общее для всех мест действия (хранилище `revertVariant`): второй возврат или возврат во время
  // чужой задачи над вариантом не уходит на сервер, а возвращает отказ строкой
  const undoAt = useCallback((kind: SlideJobKind, to: string, slide: number) => {
    const before = box.current;
    const now = send({ type: "undo", kind, strategy: to, slide, at: Date.now() });
    if (now === before || !now.run) return; // идёт другая работа
    const s = now.run.seq;
    void revertVariant(gid, to, { slide }).then((why) => {
      // вернулось как было — итога больше нет: слайд снова со своими замечаниями
      if (why === null) send({ type: "undone", seq: s });
      else send({ type: "undoFailed", seq: s, error: why });
    });
  }, [gid, revertVariant, send]);

  const undo = useCallback(() => {
    const cur = box.current.run;
    if (cur && cur.phase === "done") undoAt(cur.kind, cur.strategy, cur.slide);
  }, [undoAt]);
  const revert = useCallback((to: string, slide: number) => undoAt("fix", to, slide), [undoAt]);

  const clear = useCallback(() => void send({ type: "clear" }), [send]);

  return {
    run,
    phase: !run ? "idle" : run.phase,
    result: run?.fix ?? run?.picture ?? null,
    busy: slideBusy(run),
    live,
    start,
    undo,
    revert,
    clear,
  };
}
