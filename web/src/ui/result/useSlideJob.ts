// Работа над одним слайдом открытой презентации (R-fixing, R-fixed, R-picture): «Исправить слайд» (задача
// `slide_fix`), «Заменить» / «Убрать» изображение (задача `picture`) и «Вернуть как было» («верни как было», задача
// `edit`; одно на всё приложение — хранилище `revertVariant`, им же пользуется лист «Подробнее»). Задачи идут через
// `runJob` хранилища тихо — ход и неудачу показывает место действия (панель замечаний, карточка «Изображение»), а не
// строка уведомления. Шаги запуска — чистый slideJobNext (slideJob.ts): у варианта одна
// задача за раз (сервер отвечает 409), второй запуск в том же кадре отклоняется; у другого варианта — своя работа. Задача
// над вариантом, которую этот экран не запускал (начатая до возвращения на него, помощником, листом «Подробнее»): задача
// над слайдом — исправление, изображение, правка помощника, «Вернуть как было» слайда — подхватывается и выглядит как
// своя (`adoptPlan`: карточка хода R-fixing или ход в карточке «Изображение», замечания слайда рядами; её конец хранилище
// сообщает после того, как запустивший перечитал презентацию, — `watchJob`, итог встаёт у места действия; не удалась, а
// её места человек не видит — строка результата, экран не молчит); задача над всем вариантом — `elsewhere`: кнопки
// работы выключены с причиной. Своя задача, кончившаяся неудачей, когда экрана уже нет и её никто не подхватил, —
// строка результата открытой презентации (`tellAway`). Ход задачи — из идущих задач хранилища
// по её номеру (а не из слота самой новой задачи). По готовности презентация
// перечитывается (`reloadIfOpen`: тот же вариант и слайд, превью — по новой ревизии `withRev`) — и тогда, когда человек
// уже ушёл с экрана результата: вернувшись, он видит новый слайд. Состояние этого экрана (итог, строки, часы) живёт,
// пока открыта эта презентация (ResultBody с ключом id), и переживает её перечитывание.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { asPictureResult } from "../../lib/pictures";
import { useApp, type ActiveJob } from "../../store";
import type { AgentEvent, Job, PictureChangeRequest, PictureChangeResult, SlideFixRequest, SlideFixResult } from "../../types";
import { useStale, type Refresh } from "../shell/StaleLine";
import { asEditResult } from "../helper/chat";
import { undoRefusal } from "../details/variantWork";
import { asSlideFixResult } from "./fix";
import type { Remark } from "./marks";
import {
  adoptPlan, awayFailText, JOB0, jobWhat, liveWork, runOf, slideBusy, slideJobNext, variantLiveJob, type SlideJobAction, type SlideJobKind, type SlideJobState, type SlideRun,
} from "./slideJob";

export type { SlideJobKind, SlideRun } from "./slideJob";

export interface SlideLive { events: AgentEvent[]; progress: number; message: string }

export interface SlideJob {
  run: SlideRun | null;
  /** Брифовый вид: нет работы, идёт, кончилась. */
  phase: "idle" | "work" | "done";
  result: SlideFixResult | PictureChangeResult | null;
  /** Идёт задача этого экрана над вариантом (сама работа или «Вернуть как было»): новая не начинается. */
  busy: boolean;
  /** Над вариантом идёт задача, которую этот экран не запускал: почему работа не начнётся и какой слайд она меняет
   *  (null — весь вариант); null — такой задачи нет. */
  elsewhere: { why: string; slide: number | null } | null;
  /** Ход задачи этого запуска: шаги агента, доля, последняя строка (после конца — последние увиденные). */
  live: SlideLive;
  /** Презентация несвежая (изменение сохранено, а перечитать не вышло): строка и «Обновить» для места действия, чья
   *  работа это изменение (`run.stale`); null — свежая. */
  refresh: Refresh | null;
  /** Слайд, над которым идёт работа (своя, подхваченная или чужая над вариантом): дуга на его миниатюре; null — нет. */
  spin: number | null;
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

/** Что экран результата сообщает о себе для подхваченной работы: замечания слайда (ряды карточки хода), род последнего
 *  изменения слайда (что возвращает «Вернуть как было»), видит ли человек место работы (режим «Замечания» на её слайде
 *  или колонка «Изображение» на нём). Читается в момент события — всегда свежее. */
export interface SlideJobCtx {
  remarksOf(slide: number): Remark[];
  undoKind(slide: number): SlideJobKind;
  looking(run: SlideRun): boolean;
}

export function useSlideJob(gid: string, strategy: string, ctx?: SlideJobCtx): SlideJob {
  const { runJob, reloadIfOpen, revertVariant, liveJobs, watchJob, tellAway } = useApp();
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
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
  const run = runOf(state, strategy);

  // ход задачи — из идущих задач хранилища по её номеру (рядом может идти другая — правка помощника, исправление
  // другого варианта); задача кончилась — остаётся последнее увиденное (панель доигрывает разворот эскиза)
  const mine = (run?.jobId && liveJobs.find((j) => j.id === run.jobId)) || null;
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
        // применённое изменение — новая версия презентации: сначала она (и без экрана результата), потом итог — сцена
        // разворачивается в новый слайд. Не перечиталась — итог ждёт (`stale`): на экране прежний слайд, у места
        // действия строка «изменения сохранены, а экран не обновился» с «Обновить» (одна строка — store её больше нигде
        // не пишет); перечиталась — итог встаёт сам
        let lost = false;
        const reread = async () => {
          await reloadIfOpen(gid, () => {
            lost = true;
          });
          return lost;
        };
        if (kind === "fix") {
          const res = asSlideFixResult(job.result);
          if (!res) return void send({ type: "settled", seq: s, at: Date.now(), error: "Сервер не смог исправить слайд. Попробуйте ещё раз." });
          const stale = res.applied ? await reread() : false;
          send({ type: "settled", seq: s, at: Date.now(), fix: res, stale });
        } else {
          const res = asPictureResult(job.result);
          if (!res) return void send({ type: "settled", seq: s, at: Date.now(), error: "Сервер не смог поменять изображение. Попробуйте ещё раз." });
          const stale = res.applied ? await reread() : false;
          send({ type: "settled", seq: s, at: Date.now(), picture: res, stale, error: res.applied ? null : humanError(res.reply, "Изображение не поменялось. Попробуйте ещё раз.") });
        }
      },
      onFailed: (job) => {
        // экрана уже нет (ушли с результата), и задачу никто не подхватил: строка результата — вернувшись, человек её увидит
        if (!alive.current) tellAway(jobId, gid, awayFailText(kind, pic ? pic.action ?? "generate" : null, n, job));
        send({ type: "settled", seq: s, at: Date.now(), error: jobError(job, what) });
      },
    });
    return true;
  }, [gid, strategy, runJob, reloadIfOpen, send, tellAway]) as SlideJob["start"];

  // «Вернуть как было» — общее для всех мест действия (хранилище `revertVariant`): второй возврат или возврат во время
  // чужой задачи над вариантом не уходит на сервер, а возвращает отказ строкой
  const undoAt = useCallback((kind: SlideJobKind, to: string, slide: number) => {
    const before = box.current;
    const now = send({ type: "undo", kind, strategy: to, slide, at: Date.now() });
    const mineNow = runOf(now, to);
    if (now === before || !mineNow) return; // идёт другая работа
    const s = mineNow.seq;
    void revertVariant(gid, to, { slide }).then(({ why, stale }) => {
      // вернулось как было — итога больше нет: слайд снова со своими замечаниями; экран не перечитался — строка с
      // «Обновить» на месте итога
      if (why !== null) send({ type: "undoFailed", seq: s, error: why });
      else send(stale ? { type: "undoStale", seq: s } : { type: "undone", seq: s });
    });
  }, [gid, revertVariant, send]);

  const undo = useCallback(() => {
    const cur = runOf(box.current, strategy);
    if (cur && cur.phase === "done") undoAt(cur.kind, cur.strategy, cur.slide);
  }, [undoAt, strategy]);
  const revert = useCallback((to: string, slide: number) => undoAt("fix", to, slide), [undoAt]);

  const clear = useCallback(() => void send({ type: "clear", strategy }), [send, strategy]);

  // задача над этим вариантом, которую экран не запускал (своя — у `run`)
  const other = variantLiveJob(liveJobs, gid, strategy, run?.jobId ?? null);
  // задача над слайдом подхватывается: та же работа экрана, что у своей (карточка хода, итог у места действия)
  const plan = adoptPlan(other, run, (k) => ctxRef.current?.undoKind(k) ?? "fix");
  const subs = useRef(new Map<string, () => void>());
  useEffect(() => {
    const own = subs.current;
    return () => {
      own.forEach((stop) => stop());
      own.clear();
    };
  }, []);
  const planKey = plan && other ? `${other.id}|${plan.kind}|${plan.slide}|${plan.undo}` : null;
  useEffect(() => {
    if (!plan || !other || subs.current.has(other.id)) return;
    const jobId = other.id;
    let seq = -1;
    // конец задачи — после того, как запустивший отработал своё (перечитал презентацию); `stale` — не перечиталась
    const stop = watchJob(jobId, (job, ok, stale) => {
      subs.current.delete(jobId);
      if (seq >= 0) settleAdopted(seq, plan, job, ok, stale);
    });
    const now = send({
      type: "adopt", kind: plan.kind, strategy, slide: plan.slide, jobId, startedAt: other.startedAt, undo: plan.undo,
      requested: plan.kind === "fix" && !plan.undo ? ctxRef.current?.remarksOf(plan.slide) ?? [] : [],
    });
    const r = runOf(now, strategy);
    if (!r || r.jobId !== jobId) return stop();
    seq = r.seq;
    subs.current.set(jobId, stop);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- одна подхваченная задача — один раз (planKey)
  }, [planKey]);

  /** Конец подхваченной задачи: итог — как у своей (перечитанная презентация, «Исправлено», «Новое изображение», строка
   *  правки помощника); неудача — строка у места действия, а если человек его не видит — строка результата. */
  const settleAdopted = (seq: number, p: NonNullable<ReturnType<typeof adoptPlan>>, job: Job, ok: boolean, stale: boolean) => {
    const r = Object.values(box.current.runs).find((x) => x?.seq === seq);
    if (!r) return;
    const at = Date.now();
    if (p.undo) {
      const no = ok ? undoRefusal(job.result) : jobError(job, "вернуть как было");
      if (no) return void send({ type: "undoFailed", seq, error: no });
      return void send(stale ? { type: "undoStale", seq } : { type: "undone", seq });
    }
    if (!ok) {
      if (alive.current && ctxRef.current?.looking(r)) return void send({ type: "settled", seq, at, error: jobError(job, jobWhat(p.kind, r.action)) });
      tellAway(job.id, gid, awayFailText(p.kind, r.action, p.slide, job));
      return void send({ type: "settled", seq, at });
    }
    if (p.source === "slide_fix") {
      const res = asSlideFixResult(job.result);
      if (!res) return void send({ type: "settled", seq, at, error: "Сервер не смог исправить слайд. Попробуйте ещё раз." });
      return void send({ type: "settled", seq, at, fix: res, stale: res.applied && stale });
    }
    if (p.source === "picture") {
      const res = asPictureResult(job.result);
      if (!res) return void send({ type: "settled", seq, at, error: "Сервер не смог поменять изображение. Попробуйте ещё раз." });
      return void send({ type: "settled", seq, at, picture: res, stale: res.applied && stale, error: res.applied ? null : humanError(res.reply, "Изображение не поменялось. Попробуйте ещё раз.") });
    }
    // правка помощника: тихая строка — что сделано или почему слайд остался прежним (его же ответ)
    const e = asEditResult(job.result);
    const said = (e?.reply ?? "").split("\n")[0].trim().replace(/[.\s]+$/, "");
    const note = !e ? null : e.changed ? (said ? `${said}.` : "Слайд изменён.") : `Слайд остался прежним${said ? `: ${said[0].toLowerCase()}${said.slice(1)}` : ""}.`;
    send({ type: "settled", seq, at, note, stale: !!e?.changed && stale });
  };

  const elsewhere = useMemo(() => (other && !plan ? liveWork(other) : null), [other, plan]);
  const refresh = useStale(gid);
  const spin = run && run.jobId && (run.phase === "work" || run.undo === "work") ? run.slide : elsewhere?.slide ?? null;

  return {
    run,
    phase: !run ? "idle" : run.phase,
    result: run?.fix ?? run?.picture ?? null,
    busy: slideBusy(run),
    elsewhere,
    live,
    refresh,
    spin,
    start,
    undo,
    revert,
    clear,
  };
}
