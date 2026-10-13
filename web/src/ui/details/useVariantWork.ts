// Работа над вариантами открытой презентации, общая для всех мест действия, — живёт в хранилище (AppProvider), а не во
// вкладке листа: «Исправить отмеченные» / «Исправить всё автоматически» (`api.fixes` → задача `fix`) и единственное
// «Вернуть как было» («верни как было» → задача `edit`) — им пользуются вкладки «Качество» и «Агент» и исправление
// слайда на экране результата (useSlideJob). На вариант — одна работа за раз: пока над ним идёт задача хранилища или
// запуск ждёт ответа сервера, второй запуск не уходит на сервер (он ответил бы 409), а возвращает отказ строкой.
// Задачи идут тихо (`quiet`: ход и неудачу показывает место действия) с целью `target` — по ней хранилище знает,
// какие варианты заняты (`busyVariants`). По готовности презентация перечитывается (`reloadIfOpen`). Шаги — чистый
// workNext (variantWork.ts).
import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { variantRev } from "../../lib/rev";
import type { Generation, Job, JobKind } from "../../types";
import { reloadFailText } from "../helper/chat";
import { fixedCount } from "./quality";
import { fixedFromJob, undoRefusal, VARIANT_BUSY, WORK0, workKey, workNext, type UndoBy, type WorkAction, type WorkState } from "./variantWork";

const startError = (e: unknown, what: string) => humanError(e instanceof ApiError || e instanceof Error ? e.message : String(e), `Не получилось ${what}. Попробуйте ещё раз.`);
const jobError = (job: Job, what: string) => humanError(job.error ?? job.message, `Не получилось ${what}. Попробуйте ещё раз.`);

/** Что нужно от хранилища: запуск задачи, перечитывание, идёт ли задача над вариантом и его ревизия на экране. */
export interface VariantWorkDeps {
  runJob(jobId: string, label: string, opts: {
    kind: JobKind; area: "result"; quiet: true; generation: string; target: { generation: string; strategy: string; slide: number };
    onDone(job: Job): void; onFailed(job: Job): void;
  }): void;
  /** Перечитать открытую презентацию; не перечиталась — `onError` слышит почему (строку пишет место действия). */
  reloadIfOpen(gid: string, onError?: (e: unknown) => void): Promise<Generation | null>;
  /** Над вариантом (`workKey`) идёт задача хранилища. */
  live(key: string): boolean;
  /** Ревизия варианта открытой презентации (`variantRev`); не открыта — null. */
  rev(gid: string, strategy: string): string | null;
}

export interface VariantWorkApi {
  /** Состояние по `workKey(gid, strategy)`. */
  work: WorkState;
  /** «Исправить отмеченные» (`ids`) / «Исправить всё автоматически» («all»); `count` — какие замечания считать. */
  fixIssues(gid: string, strategy: string, ids: string[] | "all", count: string[]): void;
  /** «Вернуть как было» последнего изменения варианта (`slide` — на каком слайде его вернуть). `by` — вкладка, у которой
   *  ход и неудача (их состояние в `work`); без него место действия держит своё. Обещание: null — вернулось, иначе — почему
   *  нет (над вариантом уже идёт работа, отказ сервера, неудача задачи). */
  revertVariant(gid: string, strategy: string, opts?: { slide?: number | null; by?: UndoBy }): Promise<string | null>;
}

export function useVariantWork(deps: VariantWorkDeps): VariantWorkApi {
  // последнее состояние — у шагов (клик, ответ сервера, конец задачи), а не у отрисовки: второй клик в том же кадре
  // видит первый запуск
  const box = useRef<WorkState>(WORK0);
  const [work, setWork] = useState<WorkState>(WORK0);
  // запуски, что ждут ответа сервера (задачи ещё нет среди идущих)
  const asking = useRef(new Set<string>());
  const d = useRef(deps);
  d.current = deps;
  const send = useCallback((a: WorkAction): WorkState => {
    const next = workNext(box.current, a);
    if (next !== box.current) {
      box.current = next;
      setWork(next);
    }
    return next;
  }, []);
  const taken = (key: string) => asking.current.has(key) || d.current.live(key);

  const fixIssues = useCallback((gid: string, strategy: string, ids: string[] | "all", count: string[]) => {
    const key = workKey(gid, strategy);
    const before = box.current;
    const now = send({ type: "fix", key, ids });
    if (now === before) return;
    const seq = now[key]!.fix!.seq;
    const fail = (error: string) => void send({ type: "fixFailed", key, seq, error, rev: d.current.rev(gid, strategy) });
    if (taken(key)) return fail(VARIANT_BUSY);
    asking.current.add(key);
    void (async () => {
      let jobId: string;
      try {
        jobId = (await api.fixes(gid, strategy, ids === "all" ? { all_deterministic: true } : { issue_ids: ids })).job_id;
      } catch (e) {
        asking.current.delete(key);
        return fail(startError(e, "исправить замечания"));
      }
      d.current.runJob(jobId, "Исправляю замечания", {
        kind: "fix", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy, slide: 0 },
        onDone: async (job) => {
          // итог держится, пока вариант не изменился (`rev`): презентация не открыта или не перечиталась — вариант
          // читается тихо; не прочитался и так — итога нет, а не «Исправлено» без ревизии навсегда
          let lost: { e: unknown } | null = null;
          const open = await d.current.reloadIfOpen(gid, (e) => {
            lost = { e };
          });
          // открытая не перечиталась: изменение сохранено, а экран прежний — так и сказано у «Исправить» (один раз)
          const failed = lost as { e: unknown } | null;
          if (failed) return void fail(reloadFailText(failed.e));
          const g = open ?? (await api.generation(gid).catch(() => null));
          const v = g?.variants.find((x) => x.strategy === strategy) ?? null;
          if (!v) return void send({ type: "fixLost", key, seq });
          const fixed = fixedFromJob(job.result, count) ?? (v.audit ? fixedCount(count, v.audit) : count.length);
          send({ type: "fixed", key, seq, fixed, rev: variantRev(v) });
        },
        onFailed: (job) => fail(jobError(job, "исправить замечания")),
      });
      asking.current.delete(key);
    })();
  }, [send]);

  const revertVariant = useCallback(async (gid: string, strategy: string, opts: { slide?: number | null; by?: UndoBy } = {}): Promise<string | null> => {
    const key = workKey(gid, strategy);
    if (taken(key)) return VARIANT_BUSY;
    let seq: number | null = null;
    if (opts.by) {
      const before = box.current;
      const now = send({ type: "undo", key, by: opts.by });
      if (now === before) return VARIANT_BUSY;
      seq = now[key]!.undo!.seq;
    } else if (box.current[key]?.fix?.phase === "fix" || box.current[key]?.undo?.busy) return VARIANT_BUSY;
    const slide = opts.slide ?? null;
    asking.current.add(key);
    const why = await new Promise<string | null>((resolve) => {
      api.editVariant(gid, strategy, slide ? { message: "верни как было", slide } : { message: "верни как было" }).then((r) => {
        d.current.runJob(r.job_id, "Возвращаю как было", {
          kind: "edit", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy, slide: slide ?? 0 },
          onDone: async (job) => {
            const no = undoRefusal(job.result);
            if (no) return resolve(no);
            let lost: { e: unknown } | null = null;
            await d.current.reloadIfOpen(gid, (e) => {
              lost = { e };
            });
            const failed = lost as { e: unknown } | null;
            resolve(failed ? reloadFailText(failed.e) : null);
          },
          onFailed: (job) => resolve(jobError(job, "вернуть как было")),
        });
        asking.current.delete(key);
      }, (e) => {
        asking.current.delete(key);
        resolve(startError(e, "вернуть как было"));
      });
    });
    if (why === null) send({ type: "undone", key, seq });
    else if (seq !== null) send({ type: "undoFailed", key, seq, error: why });
    return why;
  }, [send]);

  return { work, fixIssues, revertVariant };
}
