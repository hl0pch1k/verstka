// Работа над одним слайдом открытой презентации (R-fixing, R-fixed, R-picture): «Исправить слайд» (задача
// `slide_fix`), «Заменить» / «Убрать» изображение (задача `picture`) и «Вернуть как было» («верни как было», задача
// `edit`). Задачи идут через `runJob` хранилища тихо — ход и неудачу показывает место действия (панель замечаний,
// карточка «Изображение»), а не строка уведомления. По готовности презентация перечитывается (`loadGeneration`
// оставляет вариант и слайд), и превью меняются по новой ревизии (`withRev`). У варианта одна задача за раз (сервер
// отвечает 409): пока идёт одна, вторая не начинается. Состояние живёт, пока открыта эта презентация (ResultBody
// с ключом id), и переживает её перечитывание.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { asPictureResult } from "../../lib/pictures";
import { useApp } from "../../store";
import type { AgentEvent, Job, PictureChangeRequest, PictureChangeResult, SlideFixRequest, SlideFixResult } from "../../types";
import { asSlideFixResult, type Remark } from "./remarks";

export type SlideJobKind = "fix" | "picture";

export interface SlideRun {
  /** Номер запуска: новая работа — новый номер (ключ движения сцены и панели). */
  seq: number;
  kind: SlideJobKind;
  strategy: string;
  slide: number;
  /** work — задача идёт (или презентация перечитывается после неё); done — кончилась (итог, отказ или неудача). */
  phase: "work" | "done";
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

export interface SlideJob {
  run: SlideRun | null;
  /** Брифовый вид: нет работы, идёт, кончилась. */
  phase: "idle" | "work" | "done";
  result: SlideFixResult | PictureChangeResult | null;
  /** Идёт задача (сама работа или «Вернуть как было»): новая не начинается. */
  busy: boolean;
  /** Ход задачи этого запуска: шаги агента, доля, последняя строка (после конца — последние увиденные). */
  live: { events: AgentEvent[]; progress: number; message: string };
  start(kind: "fix", n: number, body: SlideFixRequest, requested: Remark[]): Promise<boolean>;
  start(kind: "picture", n: number, body: PictureChangeRequest): Promise<boolean>;
  undo(): void;
  /** Убирает итог или строку неудачи (новая работа на другом месте, «Отмена»). */
  clear(): void;
}

const EMPTY = { events: [] as AgentEvent[], progress: 0, message: "" };

/** Неудача задачи по-человечески: первая русская строка ошибки, иначе — что не получилось. */
const jobError = (job: Job, what: string) => humanError(job.error ?? job.message, `Не получилось ${what}. Попробуйте ещё раз.`);
/** Отказ сервера при запуске (409 — вариант уже меняется, 503 — нет модели изображений, 422 — нечего исправлять). */
const startError = (e: unknown, what: string) =>
  humanError(e instanceof ApiError || e instanceof Error ? e.message : String(e), `Не получилось ${what}. Попробуйте ещё раз.`);

export function useSlideJob(gid: string, strategy: string): SlideJob {
  const { runJob, loadGeneration, activeJob } = useApp();
  const [run, setRun] = useState<SlideRun | null>(null);
  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const patch = useCallback((s: number, p: Partial<SlideRun>) => {
    const at = p.phase === "done" ? { endedAt: Date.now() } : {};
    if (alive.current) setRun((r) => (r && r.seq === s ? { ...r, ...at, ...p } : r));
  }, []);
  const busyRef = useRef(false);
  busyRef.current = !!run && (run.phase === "work" || run.undo === "work");

  // ход задачи — из слота `activeJob`, пока он её; слот уходит к другой задаче — остаётся последнее увиденное
  const kept = useRef(EMPTY);
  const mine = !!run?.jobId && activeJob?.id === run.jobId;
  if (mine && activeJob) kept.current = { events: activeJob.agent ?? [], progress: activeJob.progress, message: activeJob.message };
  // кончилась — ход стоит на последнем увиденном, пока панель доигрывает разворот эскиза
  const live = run?.jobId ? kept.current : EMPTY;

  const start = useCallback(async (kind: SlideJobKind, n: number, body: SlideFixRequest | PictureChangeRequest, requested: Remark[] = []) => {
    if (busyRef.current) return false;
    const s = ++seq.current;
    busyRef.current = true;
    kept.current = EMPTY;
    const pic = kind === "picture" ? (body as PictureChangeRequest) : null;
    const wish = (kind === "fix" ? (body as SlideFixRequest).wishes : pic?.wish) ?? "";
    setRun({
      seq: s, kind, strategy, slide: n, phase: "work", jobId: null, startedAt: Date.now(), endedAt: null, wish: wish.trim(), action: pic ? pic.action ?? "generate" : null,
      requested, fix: null, picture: null, error: null, undo: null, undoError: null,
    });
    const what = kind === "fix" ? "исправить слайд" : pic?.action === "remove" ? "убрать изображение" : "заменить изображение";
    let jobId: string;
    try {
      jobId = (kind === "fix" ? await api.fixSlide(gid, strategy, n, body as SlideFixRequest) : await api.changePicture(gid, strategy, n, body as PictureChangeRequest)).job_id;
    } catch (e) {
      patch(s, { phase: "done", error: startError(e, what) });
      busyRef.current = false;
      return false;
    }
    patch(s, { jobId, startedAt: Date.now() });
    const label = kind === "fix" ? `Исправляю слайд ${n}` : pic?.action === "remove" ? `Убираю изображение со слайда ${n}` : `Меняю изображение на слайде ${n}`;
    runJob(jobId, label, {
      kind: kind === "fix" ? "slide_fix" : "picture",
      target: { generation: gid, strategy, slide: n },
      area: "result",
      quiet: true,
      onDone: async (job) => {
        if (kind === "fix") {
          const res = asSlideFixResult(job.result);
          if (!res) return patch(s, { phase: "done", error: "Сервер не смог исправить слайд. Попробуйте ещё раз." });
          // применённое исправление — новая версия презентации: сначала она, потом итог (сцена разворачивается в новый слайд)
          if (res.applied && alive.current) await loadGeneration(gid);
          patch(s, { phase: "done", fix: res });
        } else {
          const res = asPictureResult(job.result);
          if (!res) return patch(s, { phase: "done", error: "Сервер не смог поменять изображение. Попробуйте ещё раз." });
          if (res.applied && alive.current) await loadGeneration(gid);
          patch(s, { phase: "done", picture: res, error: res.applied ? null : humanError(res.reply, "Изображение не поменялось. Попробуйте ещё раз.") });
        }
      },
      onFailed: (job) => patch(s, { phase: "done", error: jobError(job, what) }),
    });
    return true;
  }, [gid, strategy, runJob, loadGeneration, patch]) as SlideJob["start"];

  const undo = useCallback(() => {
    const cur = run;
    if (!cur || cur.phase !== "done" || busyRef.current) return;
    const s = cur.seq;
    busyRef.current = true;
    patch(s, { undo: "work", undoError: null });
    void (async () => {
      let jobId: string;
      try {
        jobId = (await api.editVariant(gid, cur.strategy, { message: "верни как было", slide: cur.slide })).job_id;
      } catch (e) {
        busyRef.current = false;
        return patch(s, { undo: "error", undoError: startError(e, "вернуть как было") });
      }
      runJob(jobId, "Возвращаю как было", {
        kind: "edit",
        target: { generation: gid, strategy: cur.strategy, slide: cur.slide },
        area: "result",
        quiet: true,
        onDone: async (job) => {
          const r = job.result as { changed?: boolean; reply?: string } | null;
          if (r && r.changed === false) {
            busyRef.current = false;
            return patch(s, { undo: "error", undoError: humanError(r.reply, "Вернуть не получилось. Попробуйте ещё раз.") });
          }
          if (alive.current) await loadGeneration(gid);
          // вернулось как было — итога больше нет: слайд снова со своими замечаниями
          if (alive.current) setRun((x) => (x && x.seq === s ? null : x));
          busyRef.current = false;
        },
        onFailed: (job) => {
          busyRef.current = false;
          patch(s, { undo: "error", undoError: jobError(job, "вернуть как было") });
        },
      });
    })();
  }, [run, gid, runJob, loadGeneration, patch]);

  // кончилась работа — снова можно начинать
  useEffect(() => {
    if (run && run.phase === "done" && run.undo !== "work") busyRef.current = false;
  }, [run]);

  const clear = useCallback(() => setRun((r) => (r && r.phase === "done" && r.undo !== "work" ? null : r)), []);

  return {
    run,
    phase: !run ? "idle" : run.phase,
    result: run?.fix ?? run?.picture ?? null,
    busy: !!run && (run.phase === "work" || run.undo === "work"),
    live,
    start,
    undo,
    clear,
  };
}
