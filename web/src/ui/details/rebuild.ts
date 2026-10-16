// «Пересобрать слайд так» (вторая ступень; V2 v105 `dwRebuild`) без React: слайд с данными собирается заново другим
// вариантом визуализации — настоящая задача сервера (POST …/slides/{n}/rebuild), её ход — строкой у самого варианта
// («Пересобираю слайд 4…», на ней фокус), отказ анализа — спокойной строкой там же (422; 409 — сперва перечитать
// презентацию: экран мог отстать), неудача — красной; итог — новый слайд и «Выбран» у этого варианта, у него «Вернуть
// как было» (фокус на ней) и вежливое «Слайд 4 пересобран: вертикальные столбцы»; другое число слайдов — выбран первый
// новый. «Вернуть как было» — как у других правок (store `revertVariant`), после него — фокус на выбранном варианте и
// первый слайд набора. Работа — одна на вариант презентации (сервер держит одну задачу на вариант), живёт вне вкладки
// (`rebuildStore`): лист закрыли — идёт; страницу перезагрузили — её задача записана (`pendingRebuilds`, как LS.build) и
// подхватывается снова (`resumeRebuild`). Шаги — чистый rebuildNext; ход с сервером — startRebuild / followRebuild /
// undoRebuild / resumeRebuild с подставляемыми зависимостями (useRebuild — настоящие, тесты — свои).
import { humanError } from "../../lib/errors";
import type { Job, RebuildResult } from "../../types";

/** Куда перейти фокусу, когда его место встанет на экран: строка хода, «Вернуть как было», выбранный вариант, строка
 *  отказа или неудачи. */
export type FocusWhat = "busy" | "undo" | "row" | "note";

export interface RebuildRun {
  /** Номер запуска: шаги прежнего (поздний ответ, конец его задачи) новый не трогают. */
  seq: number;
  slide: number;
  /** Вариант, которым пересобирают (номер в `data.options`, с 0). */
  option: number;
  /** work — запрос ушёл или задача идёт (и презентация перечитывается после неё); done — пересобрано; failed — нет;
   *  idle — работа кончилась и на месте ничего не стоит (вернулось как было, слайд уже был показан так). */
  phase: "work" | "done" | "failed" | "idle";
  jobId: string | null;
  /** Почему не пересобралось — словами сервера (по-русски), у этого варианта; `tone`: refused — отказ анализа или
   *  сервер занят (спокойно), error — неудача (красным). */
  error: string | null;
  tone: "refused" | "error" | null;
  /** Пересобрано, а презентация на экране не перечиталась: у варианта строка с «Обновить». */
  stale: boolean;
  /** «Вернуть как было»: идёт или не вышло (`undoError`). */
  undo: "work" | "failed" | null;
  undoError: string | null;
  /** Что сказать вежливо (живая строка вкладки): «Слайд 4 пересобран: вертикальные столбцы»; отказ и неудачу говорит
   *  сама строка у варианта (role=status / alert). */
  said: string | null;
  /** Куда перейти фокусу (один раз — `focusSeq`). */
  focus: FocusWhat | null;
  focusSeq: number;
}
/** Работа каждого варианта презентации (ключ — `workKey(gid, strategy)`). */
export type RebuildState = Record<string, RebuildRun | undefined>;
export const REBUILD0: RebuildState = {};

export type RebuildAction =
  | { type: "start"; key: string; slide: number; option: number }
  /** Страницу открыли заново посреди пересборки: её задача (записанная) — снова своя работа, без фокуса. */
  | { type: "resume"; key: string; slide: number; option: number; jobId: string }
  | { type: "accepted"; key: string; seq: number; jobId: string }
  /** Пересобрано; `slide` — первый новый слайд (график ↔ таблица на несколько слайдов). */
  | { type: "done"; key: string; seq: number; stale: boolean; slide: number; said: string }
  | { type: "failed"; key: string; seq: number; error: string; tone: "refused" | "error" }
  /** Ничего делать не пришлось (слайд уже показан так — экран отставал и перечитан). */
  | { type: "settled"; key: string; seq: number; said: string }
  /** «Вернуть как было» пересборки слайда `slide` (и тогда, когда её запуска на странице нет: перезагрузка). */
  | { type: "undo"; key: string; slide: number }
  /** Вернулось; `stale` — а презентация на экране не перечиталась; `slide` — первый слайд набора. */
  | { type: "undone"; key: string; seq: number; stale: boolean; slide: number; said: string }
  | { type: "undoFailed"; key: string; seq: number; error: string };

/** Идёт пересборка или её возврат: новая не начинается. */
export const rebuildBusy = (r: RebuildRun | null | undefined): boolean => !!r && (r.phase === "work" || r.undo === "work");

let counter = 0;
let focusCounter = 0;

const fresh = (slide: number, option: number, over: Partial<RebuildRun> = {}): RebuildRun => ({
  seq: ++counter, slide, option, phase: "work", jobId: null, error: null, tone: null, stale: false, undo: null, undoError: null,
  said: null, focus: null, focusSeq: 0, ...over,
});
const focusOn = (what: FocusWhat | null): Pick<RebuildRun, "focus" | "focusSeq"> => ({ focus: what, focusSeq: what ? ++focusCounter : 0 });

export function rebuildNext(s: RebuildState, a: RebuildAction): RebuildState {
  const r = s[a.key];
  const put = (run: RebuildRun | null): RebuildState => {
    const next = { ...s };
    if (run) next[a.key] = run;
    else delete next[a.key];
    return next;
  };
  const mine = (seq: number) => !!r && r.seq === seq;
  switch (a.type) {
    case "start":
      if (rebuildBusy(r)) return s;
      return put(fresh(a.slide, a.option, focusOn("busy")));
    case "resume":
      if (rebuildBusy(r) || r?.jobId === a.jobId) return s;
      return put(fresh(a.slide, a.option, { jobId: a.jobId }));
    case "accepted":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, jobId: a.jobId }) : s;
    case "done":
      if (!mine(a.seq) || r!.phase !== "work") return s;
      return put({ ...r!, phase: "done", stale: a.stale, slide: a.slide, said: a.said, ...focusOn(a.stale ? "note" : "undo") });
    case "failed":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, phase: "failed", error: a.error, tone: a.tone, said: null, ...focusOn("note") }) : s;
    case "settled":
      return mine(a.seq) && r!.phase === "work" ? put({ ...r!, phase: "idle", said: a.said, ...focusOn("row") }) : s;
    case "undo":
      if (rebuildBusy(r)) return s;
      if (r && r.slide === a.slide && r.phase === "done") return put({ ...r, undo: "work", undoError: null, stale: false, said: null, ...focusOn(null) });
      return put(fresh(a.slide, -1, { phase: "done", undo: "work" }));
    case "undone":
      // вернулось — на месте ничего не стоит, вид снова по презентации; экран не перечитался — строка с «Обновить» у
      // выбранного (второе «Вернуть как было» по несвежему экрану вернуло бы уже сам возврат)
      if (!mine(a.seq) || r!.undo !== "work") return s;
      return put(a.stale
        ? { ...r!, phase: "done", option: -1, undo: null, undoError: null, stale: true, said: a.said, ...focusOn("note") }
        : { ...r!, phase: "idle", slide: a.slide, option: -1, undo: null, undoError: null, stale: false, said: a.said, ...focusOn("row") });
    case "undoFailed":
      return mine(a.seq) && r!.undo === "work" ? put({ ...r!, undo: "failed", undoError: a.error, said: null, ...focusOn("note") }) : s;
  }
}

/** Что стоит в месте действия варианта (под его доводом, 44 px — кнопка, ход, отказ, итог с «Вернуть как было»
 *  сменяют друг друга в одном месте, ничего ниже не сдвигается):
 *  - `button` — «Пересобрать слайд так» (`off` — выключена, `why` — почему);
 *  - `busy` — «Пересобираю слайд N…»;
 *  - `refused` — анализ этот вариант не строит или сервер занят (`text`; `same` — причина та же, что выше);
 *  - `error` — не пересобралось (`text`, красным);
 *  - `stale` — пересобрано, а экран не обновился (строка с «Обновить»);
 *  - `done` — выбранный пересборкой: «Вернуть как было» (`undoing` — идёт, `text` — не вышло);
 *  - `none` — ничего (выбранный анализом). */
export type RowAct =
  | { mode: "button"; off: boolean; why: string | null }
  | { mode: "busy" }
  | { mode: "refused"; text: string; same: boolean }
  | { mode: "error"; text: string }
  | { mode: "stale" }
  | { mode: "done"; undoing: boolean; text: string | null; off: boolean; why: string | null }
  | { mode: "none" };

const bare = (s: string) => s.toLowerCase().replace(/[«»"„“.,:;!?—–-]/g, " ").replace(/\s+/g, " ").trim();

/** Место действия варианта `k` слайда `slide`: `chosen` — выбранный вариант на экране, `undoable` — последнее изменение
 *  варианта — пересборка этого слайда (rebuiltLast), `lock` — над вариантом идёт чужая задача или шаблона нет;
 *  `whyNot` — «почему не он», что уже написано у варианта (отказ с той же причиной её не повторяет). */
export function rowAct(run: RebuildRun | null | undefined, slide: number, k: number, chosen: number, undoable: boolean, lock: { off: boolean; why: string | null }, whyNot?: string | null): RowAct {
  const live = run && run.phase !== "idle" ? run : null;
  const here = !!live && live.slide === slide;
  const busy = rebuildBusy(live);
  const why = lock.why ?? (busy && live ? (live.undo === "work" ? UNDO_BUSY : `Пересобираю слайд ${live.slide} — дождитесь конца`) : null);
  if (k === chosen) {
    if (!undoable) return { mode: "none" };
    if (here && live!.stale && live!.option === -1) return { mode: "stale" };
    const undoing = here && live!.undo === "work";
    return { mode: "done", undoing, text: here && live!.undo === "failed" ? live!.undoError : null, off: !undoing && (lock.off || busy), why: undoing ? null : why };
  }
  if (here && live!.option === k) {
    if (live!.phase === "work") return { mode: "busy" };
    if (live!.phase === "failed" && live!.error) {
      if (live!.tone !== "refused") return { mode: "error", text: live!.error };
      const same = !!whyNot && bare(live!.error).includes(bare(whyNot));
      return { mode: "refused", text: live!.error, same };
    }
    if (live!.phase === "done" && live!.stale) return { mode: "stale" };
  }
  return { mode: "button", off: lock.off || busy, why };
}

const UNDO_BUSY = "Возвращаю как было — дождитесь конца";
/** Строка хода у варианта. */
export const busyText = (slide: number) => `Пересобираю слайд ${slide}…`;
export const UNDO_TEXT = "Возвращаю как было…";
export const STALE_TEXT = "Слайд пересобран, а экран не обновился";
/** Отказ анализа с той же причиной, что уже написана у варианта, — коротко. */
export const REFUSED_SAME = "Этот вариант не подходит — причина выше";

/** Итог задачи пересборки (null — не он). */
export function asRebuildResult(x: unknown): RebuildResult | null {
  const r = x as Partial<RebuildResult> | null;
  return r && typeof r === "object" && r.kind === "rebuild" && typeof r.changed === "boolean" ? (r as RebuildResult) : null;
}

/** Отказ сервера при запуске (422 — вариант не подходит, слайд не из файла, уже показан так; 409 — файла нет, вариант
 *  уже меняется; 404 — нет презентации или шаблона) — его словами, по-русски. */
export const refusalText = (message: string): string => humanError(message, "Не получилось пересобрать слайд. Попробуйте ещё раз.");

/** Задача кончилась неудачей или сервер ответил, что слайд не изменился. */
export function jobFailText(job: Pick<Job, "error" | "message">): string {
  return humanError(job.error ?? job.message, "Не получилось пересобрать слайд. Попробуйте ещё раз.");
}
export function notChangedText(r: RebuildResult): string {
  return humanError(r.reply, "Слайд остался прежним. Попробуйте другой вариант.");
}

const lowerFirst = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);

// ── ход с сервером (зависимости подставляются: useRebuild — настоящие, тесты — свои)

/** Хранилище работ: общее страницы (`rebuildStore`) или своё в тестах. */
export interface RebuildStoreLike { get(): RebuildState; send(a: RebuildAction): RebuildState }

export interface RebuildDeps {
  /** POST …/slides/{n}/rebuild; отказ — ошибка со `status` (ApiError). */
  request(slide: number, option: number): Promise<{ job_id: string }>;
  /** Следить за задачей (store `runJob`, тихо, с целью слайда): конец — `done`, неудача — `failed`. */
  watch(jobId: string, slide: number, done: (job: Job) => void | Promise<void>, failed: (job: Job) => void): void;
  /** Перечитать открытую презентацию; false — не перечиталась (экран прежний). */
  reload(): Promise<boolean>;
  /** Выбрать слайд (только если на экране эта презентация и этот вариант). */
  select(n: number): void;
  /** Записать идущую задачу (перезагрузка её подхватит) и забыть кончившуюся. */
  remember(jobId: string, slide: number, option: number): void;
  forget(jobId: string): void;
  /** Над вариантом идёт чужая задача. */
  taken(): boolean;
  /** «Верни как было» (store `revertVariant`). */
  revert(slide: number): Promise<{ why: string | null; stale: boolean }>;
}

/** Отказ без запроса: над вариантом уже идёт работа (те же слова, что у сервера на 409). */
export const VARIANT_TAKEN = "Этот вариант уже меняется — дождитесь, пока агент закончит";

/** «Пересобрать слайд так»: запуск, задача, итог. */
export async function startRebuild(store: RebuildStoreLike, key: string, slide: number, option: number, deps: RebuildDeps): Promise<void> {
  const before = store.get();
  const now = store.send({ type: "start", key, slide, option });
  if (now === before) return;
  const seq = now[key]!.seq;
  if (deps.taken()) return void store.send({ type: "failed", key, seq, error: VARIANT_TAKEN, tone: "refused" });
  let jobId: string;
  try {
    jobId = (await deps.request(slide, option)).job_id;
  } catch (e) {
    const status = typeof (e as { status?: unknown })?.status === "number" ? (e as { status: number }).status : 0;
    const msg = e instanceof Error ? e.message : String(e);
    const shown = /уже показан так/i.test(msg);
    // экран мог отстать (пересобрано из другой вкладки, страница перезагружена посреди задачи): сперва перечитать
    if (status === 409 || shown) {
      const ok = await deps.reload();
      if (shown && ok) return void store.send({ type: "settled", key, seq, said: refusalText(msg) });
    }
    return void store.send({ type: "failed", key, seq, error: refusalText(msg), tone: status === 409 || status === 422 ? "refused" : "error" });
  }
  store.send({ type: "accepted", key, seq, jobId });
  deps.remember(jobId, slide, option);
  followRebuild(store, key, seq, slide, jobId, deps);
}

/** Следить за задачей пересборки до конца: перечитать презентацию, выбрать первый новый слайд, сказать итог. */
export function followRebuild(store: RebuildStoreLike, key: string, seq: number, slide: number, jobId: string, deps: RebuildDeps): void {
  const fail = (error: string, tone: "refused" | "error") => void store.send({ type: "failed", key, seq, error, tone });
  deps.watch(jobId, slide, async (job) => {
    deps.forget(jobId);
    const r = asRebuildResult(job.result);
    if (!r) return fail(jobFailText(job), "error");
    if (!r.changed) {
      await deps.reload();
      return fail(notChangedText(r), "refused");
    }
    // новый слайд — новая версия презентации: сперва она, потом итог (строка хода держится, пока она читается); не
    // перечиталась — у варианта строка с «Обновить»; слайдов стало больше или меньше — выбран первый новый
    const ok = await deps.reload();
    const to = r.slides?.[0] ?? r.slide ?? slide;
    if (ok && to !== slide) deps.select(to);
    // экран не перечитался — номера прежние: строка с «Обновить» — у того же слайда
    store.send({ type: "done", key, seq, stale: !ok, slide: ok ? to : slide, said: `Слайд ${to} пересобран: ${lowerFirst(r.title || "другой вариант")}` });
  }, (job) => {
    deps.forget(jobId);
    fail(jobFailText(job), "error");
  });
}

/** «Вернуть как было» пересборки: `first` — первый слайд набора после возврата (наименьший из слайдов пересборки). */
export async function undoRebuild(store: RebuildStoreLike, key: string, slide: number, first: number, deps: RebuildDeps): Promise<void> {
  const before = store.get();
  const now = store.send({ type: "undo", key, slide });
  if (now === before) return;
  const seq = now[key]!.seq;
  const { why, stale } = await deps.revert(slide);
  if (why !== null) return void store.send({ type: "undoFailed", key, seq, error: why });
  if (!stale && first !== slide) deps.select(first);
  store.send({ type: "undone", key, seq, stale, slide: first, said: `Слайд ${first} — снова как было` });
}

/** Задача пересборки, записанная до перезагрузки: идёт — снова своя работа (ход на месте, итог как у своей); кончилась
 *  — забыть и перечитать презентацию (её итог уже на сервере); сервер её не знает (`job` → null) — забыть. Сервер не
 *  ответил (`job` бросил) — запись остаётся до следующего раза (false). */
export async function resumeRebuild(store: RebuildStoreLike, key: string, p: PendingRebuild, job: (id: string) => Promise<Job | null>, deps: RebuildDeps): Promise<boolean> {
  let j: Job | null;
  try {
    j = await job(p.jobId);
  } catch {
    return false;
  }
  if (!j) {
    deps.forget(p.jobId);
    return true;
  }
  if (j.status === "queued" || j.status === "running") {
    const now = store.send({ type: "resume", key, slide: p.slide, option: p.option, jobId: p.jobId });
    const r = now[key];
    if (r && r.jobId === p.jobId && r.phase === "work") followRebuild(store, key, r.seq, p.slide, p.jobId, deps);
    return true;
  }
  deps.forget(p.jobId);
  await deps.reload();
  return true;
}

// ── идущие задачи пересборки — в localStorage (как LS.build): перезагрузка страницы подхватывает их
export interface PendingRebuild { gid: string; strategy: string; slide: number; option: number; jobId: string; at: number }
export const LS_REBUILD = "verstka.rebuild";
/** Сутки: задача старше — уже не идёт. */
const PENDING_TTL = 24 * 3600 * 1000;

/** Записанные задачи (испорченная запись — пусто; старше суток — нет). */
export function parsePending(raw: string | null | undefined, now = Date.now()): PendingRebuild[] {
  try {
    const list = JSON.parse(raw || "[]") as unknown;
    if (!Array.isArray(list)) return [];
    return list.filter((p): p is PendingRebuild => !!p && typeof p === "object" && typeof (p as PendingRebuild).gid === "string"
      && typeof (p as PendingRebuild).strategy === "string" && typeof (p as PendingRebuild).jobId === "string"
      && Number.isFinite((p as PendingRebuild).slide) && Number.isFinite((p as PendingRebuild).option)
      && now - ((p as PendingRebuild).at ?? 0) < PENDING_TTL);
  } catch {
    return [];
  }
}
export const withPending = (list: PendingRebuild[], p: PendingRebuild): PendingRebuild[] =>
  [...list.filter((x) => !(x.gid === p.gid && x.strategy === p.strategy) && x.jobId !== p.jobId), p];
export const withoutPending = (list: PendingRebuild[], jobId: string): PendingRebuild[] => list.filter((x) => x.jobId !== jobId);

// ── общее состояние: одно на страницу (вкладку листа монтируют и снимают, работа идёт дальше)
export function makeRebuildStore(): RebuildStoreLike & { subscribe(f: () => void): () => void } {
  let state: RebuildState = REBUILD0;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    send(a: RebuildAction): RebuildState {
      const next = rebuildNext(state, a);
      if (next !== state) {
        state = next;
        listeners.forEach((f) => f());
      }
      return next;
    },
    subscribe(f: () => void): () => void {
      listeners.add(f);
      return () => void listeners.delete(f);
    },
  };
}
export const rebuildStore = makeRebuildStore();

/** Фокус уходит на место `what` один раз: элемент встал на экран (ref) — взял его, если работа этого слайда просит. */
const taken = new Set<number>();
export function takeFocus(run: RebuildRun | null | undefined, slide: number, what: FocusWhat): boolean {
  if (!run || run.focus !== what || run.slide !== slide || !run.focusSeq || taken.has(run.focusSeq)) return false;
  taken.add(run.focusSeq);
  return true;
}
