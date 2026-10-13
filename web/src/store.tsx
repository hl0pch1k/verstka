// Application state: one React context, consumed by every panel through useApp().
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { generationFlow, uploadTemplateFlow } from "./lib/flows";
import { foldJobEvent, type ActiveJob } from "./lib/jobState";
import { trackJob } from "./lib/jobs";
import { errText, firstLine, newestTemplate, slideCount } from "./lib/narrate";
import { templateTitle, tplLabel } from "./lib/plain";
import { LS, storage, uid } from "./lib/utils";
import { decodeImage, viewTransition } from "./lib/motion";
import { draftBrief, writeDraft } from "./lib/draft";
import { variantRev, withRev } from "./lib/rev";
import { uiReducer, UI0, type UiAction, type UiState } from "./ui/deck/geometry";
import { textError, type TextIssue } from "./ui/create/textRules";
import type {
  ChatMessage, GenerateRequest, Generation, GenerationMeta, Health, ImprovedFrom, ImproveSource, Job, JobKind, ModelsStatus, Notice, NoticeArea, StrategyInfo, TemplateListItem, TemplateManifest, Variant,
} from "./types";

export type { ActiveJob } from "./lib/jobState";
export type { Notice, NoticeArea } from "./types";
export type { TextIssue } from "./ui/create/textRules";
/** `items`: what the job works on (the strategies of a generation) — the build screen shows one card per item.
 *  `generation` / `slides`: the deck a generation builds and the slide count asked for (the build's rail).
 *  `area`: where a failure is told («Не получилось: …»); by default — by the job's kind (`jobArea`).
 *  `quiet`: the caller tells the failure itself (no «Не получилось: …» line from the store). */
export interface RunJobOptions {
  kind?: JobKind; items?: string[]; template?: string | null; onDone?: (job: Job) => void; onFailed?: (job: Job) => void;
  target?: { generation: string; strategy: string; slide: number }; quiet?: boolean; area?: NoticeArea;
  generation?: string | null; slides?: number | null;
}

/** Where a job's failure stands by default: template analysis at the template step, a build on the build screen, the
 *  work on a built deck (fixes, edits, pictures) on the result. */
const jobArea = (kind: JobKind): NoticeArea =>
  kind === "analyze" ? "template" : kind === "generate" ? "build" : kind === "other" ? "global" : "result";

export interface AppState {
  health: Health | null; healthError: boolean;
  /** How the model answers lately (GET /api/models/status); null until the first answer. */
  modelStatus: ModelsStatus | null; refreshModelStatus(): Promise<void>;
  strategies: StrategyInfo[];
  strategyTitle(name: string): string;
  templates: TemplateListItem[]; refreshTemplates(): Promise<void>;
  /** Removes a template from the library; the selection moves to the newest one left. Throws with the server's text. */
  deleteTemplate(id: string): Promise<void>;
  /** Gives a template a name of its own (an empty one brings back the file's). */
  renameTemplate(id: string, title: string): Promise<void>;
  /** A template's name for people by its id (the name it was given, else its file's); `file` for a template that is
   *  gone from the library (an old deck's). */
  templateLabel(id: string | null | undefined, file?: string | null): string;
  /** Drops an already deleted template from the list (the picker plays the tile's exit first). */
  forgetTemplate(id: string): void;
  templateId: string | null; selectTemplate(id: string | null): void;
  manifest: TemplateManifest | null; manifestLoading: boolean;
  generations: GenerationMeta[]; refreshGenerations(): Promise<void>;
  generationId: string | null; generation: Generation | null; generationLoading: boolean;
  /** `hold`: keep the open deck on screen until the new one is ready, then swap inside a view transition (history). */
  /** Open a deck; resolves to it (null when it did not load — the failure is already reported). */
  loadGeneration(gid: string, opts?: { hold?: boolean }): Promise<Generation | null>;
  activeStrategy: string | null; setActiveStrategy(s: string): void; activeVariant: Variant | null;
  selectedSlide: number; setSelectedSlide(n: number): void; // 1-based
  /** Экран, раскрытые шаги, слои и листы «Слоёв» (`ui/deck/geometry.ts`); меняется только через `dispatch`. */
  ui: UiState; dispatch(a: UiAction): void;
  activeJob: ActiveJob | null;
  runJob(jobId: string, label: string, opts?: RunJobOptions): void;
  messages: ChatMessage[]; pushMessage(role: "user" | "assistant", text: string): void; // ts = unix seconds (fmtDate-compatible)
  /** Строки статуса по областям — показываются рядом с местом действия (всплывающих уведомлений в «Слоях» нет). */
  notices: Partial<Record<NoticeArea, Notice>>;
  /** Ставит строку статуса области (новая заменяет прежнюю). */
  notify(area: NoticeArea, kind: Notice["kind"], text: string): void;
  /** Убирает строку статуса области. */
  clearNotice(area: NoticeArea): void;
  uploadTemplate(file: File, useModels: boolean, improve?: boolean): Promise<void>;
  startGeneration(req: GenerateRequest, expectedSlides?: number | null): Promise<void>;
  /** Текст шага «Текст» (черновик): хранится в localStorage `verstka.brief_draft` и переживает перезагрузку. */
  brief: string;
  /** Новый текст поля. Снимает ошибку у поля и строку области «Текст»: она была о прежнем тексте. */
  setBrief(text: string): void;
  /** Ошибка у поля «Текст» (красная рамка и строка); null — ошибки нет. */
  textIssue: TextIssue | null;
  setTextIssue(issue: TextIssue | null): void;
  /** Проверка поля перед сборкой (V2 `txStart`): ошибка — она встаёт у поля, плиты поднимают шаг «Текст»
   *  («Все параметры» сворачиваются) и возвращается false; текст годится — true. */
  checkText(): boolean;
  /** A text handed to the create screen's field once (the agent's written text, «Изменить»); null when none waits. */
  composerText: string | null;
  /** The parameters handed with it (a deck's own: «Изменить текст» on a deck restores how it was built). They stay
   *  after the field takes the text — the parameters step takes them itself. */
  composerPreset: ComposerPreset | null;
  /** Opens the create screen with `text` in the field (it replaces the saved draft once), and the deck's parameters.
   *  An improved deck's text comes back in «Улучшить готовую», with the deck it was read from. */
  editText(text: string, preset?: ComposerPreset): void;
  /** The create screen's field took the handed text (the preset stays for the parameters step). */
  takeComposerText(): void;
  /** «Улучшить готовую»: the deck read back. Handed to the text step, it stays while the improve mode lives
   *  (`ui.improve`) — the build sends it as `improved_from`; the text step drops it when the mode ends. */
  improveSource: ImproveSource | null;
  takeImproveSource(): void;
}

/** A deck's own parameters for the create screen (GenerationMeta): what «Изменить текст» restores with its text. */
export interface ComposerPreset {
  audience?: string | null;
  purpose?: string | null;
  slides?: number | null;
  useModels?: boolean;
  auditModels?: boolean;
  /** «Генерировать изображения» as the deck was built (null: the server's default). */
  pictures?: boolean | null;
  strategies?: string[];
  /** «Улучшить готовую»: the deck this text was read from (its audit stays the «было» of the next build). */
  improvedFrom?: ImprovedFrom | null;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApp() must be called inside <AppProvider>");
  return value;
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(n) ? Math.round(n) : lo));
const titleIn = (list: StrategyInfo[], name: string) => list.find((s) => s.name === name)?.title ?? name;

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [modelStatus, setModelStatus] = useState<ModelsStatus | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [templates, setTemplates] = useState<TemplateListItem[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(() => storage.get(LS.template));
  const [manifest, setManifest] = useState<TemplateManifest | null>(null);
  const [manifestLoading, setManifestLoading] = useState(() => !!storage.get(LS.template));
  const [generations, setGenerations] = useState<GenerationMeta[]>([]);
  const [generationId, setGenerationId] = useState<string | null>(() => storage.get(LS.generation));
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [generationLoading, setGenerationLoading] = useState(() => !!storage.get(LS.generation));
  const [activeStrategy, setActiveStrategyState] = useState<string | null>(null);
  const [selectedSlide, setSelectedSlideState] = useState(1);
  // a reload on a deck opens on the result screen at once (its skeleton covers the load and cross-fades into the deck),
  // never on the create screen first; boot goes back to «Создать» when the stored deck does not load. The helper
  // starts closed (UI0): the page itself must be self-explanatory.
  const [ui, dispatch] = useReducer(uiReducer, UI0, (s0): UiState => (storage.get(LS.generation) ? { ...s0, screen: "result" } : s0));
  const [composerText, setComposerText] = useState<string | null>(null);
  const [composerPreset, setComposerPreset] = useState<ComposerPreset | null>(null);
  const [improveSource, setImproveSource] = useState<ImproveSource | null>(null);
  const editText = useCallback((text: string, preset?: ComposerPreset) => {
    setComposerText(text);
    setComposerPreset(preset ?? null);
    // an improved deck's «Изменить текст» returns into the improve mode, with the deck it was read from (the note over
    // the field and the strip 01 tell it); any other text leaves it
    const from = preset?.improvedFrom ?? null;
    setImproveSource(from ? { brief: text, name: from.name, template_id: from.template_id, slides: from.slides ?? 0, tables: 0, charts: 0, pictures: 0, audit: from.audit ?? null } : null);
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: !!from } });
  }, []);
  const takeComposerText = useCallback(() => setComposerText(null), []);
  const takeImproveSource = useCallback(() => setImproveSource(null), []);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const liveJobs = useRef(new Map<string, ActiveJob>()); // every job still running, the newest last
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [brief, setBriefState] = useState(draftBrief);
  const [textIssue, setTextIssue] = useState<TextIssue | null>(null);

  // Latest values for callbacks that must stay referentially stable.
  const latest = useRef({ templateId, templates, manifest, generationId, generation, activeStrategy, strategies, ui, brief });
  latest.current = { templateId, templates, manifest, generationId, generation, activeStrategy, strategies, ui, brief };
  const genSeq = useRef(0);
  const jobSubs = useRef(new Map<string, () => void>());

  const [notices, setNotices] = useState<Partial<Record<NoticeArea, Notice>>>({});
  const notify = useCallback((area: NoticeArea, kind: Notice["kind"], text: string) => {
    setNotices((n) => ({ ...n, [area]: { kind, text, at: Date.now() } }));
  }, []);
  const clearNotice = useCallback((area: NoticeArea) => {
    setNotices((n) => {
      if (!n[area]) return n;
      const next = { ...n };
      delete next[area];
      return next;
    });
  }, []);
  /** A failure as the area's status line. Network failures flip the header's «нет связи»; `quietOffline` skips the
   *  line for background loads. */
  const report = useCallback((e: unknown, prefix: string, area: NoticeArea, quietOffline = false) => {
    const offline = e instanceof ApiError && e.status === 0;
    if (offline) setHealthError(true);
    if (!(offline && quietOffline)) notify(area, "error", `${prefix}: ${errText(e)}`);
  }, [notify]);

  const setBrief = useCallback((text: string) => {
    setBriefState(text);
    setTextIssue(null);
    clearNotice("text");
  }, [clearNotice]);
  // черновик пишется через 300 мс после последней правки, а при уходе со страницы — сразу
  useEffect(() => {
    const t = window.setTimeout(() => writeDraft({ brief }), 300);
    return () => window.clearTimeout(t);
  }, [brief]);
  useEffect(() => {
    const flush = () => writeDraft({ brief: latest.current.brief });
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);
  const checkText = useCallback(() => {
    const issue = textError(latest.current.brief);
    if (!issue) return true;
    setTextIssue(issue);
    // пустое поле — «Улучшить готовую» кончилась (V2 `txStart`: `txImp: false`)
    if (issue.kind === "empty") dispatch({ type: "set", patch: { improve: false } });
    dispatch({ type: "open", step: "text" });
    return false;
  }, []);

  const pushMessage = useCallback((role: "user" | "assistant", text: string) => {
    setMessages((list) => [...list, { id: uid("m"), role, text, ts: Date.now() / 1000 }]);
  }, []);

  // A new function identity whenever strategies arrive, so memoised consumers re-render with the real titles.
  const strategyTitle = useMemo(() => (name: string) => titleIn(strategies, name), [strategies]);

  const selectTemplate = useCallback((id: string | null) => {
    setTemplateId(id);
    storage.set(LS.template, id);
  }, []);

  // quiet: the indicator simply keeps its last state when the call fails (the red banner covers a lost server)
  const refreshModelStatus = useCallback(async () => {
    try {
      const st = await api.modelsStatus();
      setModelStatus((prev) => (prev && JSON.stringify(prev) === JSON.stringify(st) ? prev : st));
    } catch {
      /* an older server without the endpoint, or offline */
    }
  }, []);

  const forgetTemplate = useCallback((id: string) => {
    const rest = latest.current.templates.filter((t) => t.template_id !== id);
    setTemplates(rest);
    if (latest.current.templateId === id) selectTemplate(newestTemplate(rest)?.template_id ?? null);
  }, [selectTemplate]);

  const deleteTemplate = useCallback(async (id: string) => {
    await api.deleteTemplate(id);
    forgetTemplate(id);
  }, [forgetTemplate]);

  const renameTemplate = useCallback(async (id: string, title: string) => {
    const item = await api.renameTemplate(id, title);
    setTemplates((list) => list.map((t) => (t.template_id === id ? { ...t, ...item } : t)));
    setManifest((m) => (m && m.template_id === id ? { ...m, title: item.title ?? null } : m));
  }, []);

  const templateLabel = useCallback((id: string | null | undefined, file?: string | null) => {
    const t = id ? templates.find((x) => x.template_id === id) : undefined;
    return t ? tplLabel(t) : templateTitle(file, id ?? undefined);
  }, [templates]);

  const refreshTemplates = useCallback(async () => {
    try {
      setTemplates(await api.templates());
      clearNotice("template");
    } catch (e) {
      report(e, "Не удалось обновить список шаблонов", "template");
    }
  }, [report, clearNotice]);

  const clearGeneration = useCallback(() => {
    genSeq.current += 1;
    setGenerationId(null);
    setGeneration(null);
    setGenerationLoading(false);
    setActiveStrategyState(null);
    setSelectedSlideState(1);
    storage.set(LS.generation, null);
  }, []);

  const refreshGenerations = useCallback(async () => {
    try {
      const list = await api.generations();
      setGenerations(list);
      const current = latest.current.generation?.id; // a loaded generation that was deleted meanwhile
      if (current && !list.some((g) => g.id === current)) clearGeneration();
    } catch (e) {
      report(e, "Не удалось обновить список презентаций", "global");
    }
  }, [report, clearGeneration]);

  /** Loads a generation. A reload of the already open one keeps the chosen variant and slide (clamped). `hold` (another
   *  deck picked over an open one, from the history): the open deck stays on screen while the new one loads and its
   *  first slide decodes, then the new deck replaces it inside a view transition — never a skeleton in between (the
   *  history row shows the wait); a failed load leaves the open deck as it was. `area`: where a failure is told (the
   *  result; the build screen for a deck that has just been built). */
  const fetchGeneration = useCallback(async (gid: string, quiet = false, hold = false, area: NoticeArea = "result"): Promise<Generation | null> => {
    const seq = ++genSeq.current;
    const sameAsOpen = latest.current.generation?.id === gid;
    const holding = hold && !sameAsOpen && !!latest.current.generation;
    if (!holding) {
      setGenerationId(gid);
      storage.set(LS.generation, gid);
    }
    if (!sameAsOpen && !holding) {
      setGeneration(null);
      setGenerationLoading(true);
    }
    try {
      const g = await api.generation(gid);
      if (seq !== genSeq.current) return g; // a newer load has started — do not touch the state
      const names = g.variants.map((v) => v.strategy);
      const keep = sameAsOpen ? latest.current.activeStrategy : null;
      const nextStrategy = keep && names.includes(keep) ? keep : names[0] ?? null;
      const next = g.variants.find((v) => v.strategy === nextStrategy);
      const max = slideCount(next);
      if (holding) {
        // the slide the deck opens on, decoded first (it paints at once, no blank stage); a slow image does not hold it
        const first = next?.slides[0];
        if (next && first) await Promise.race([decodeImage(withRev(first, variantRev(next))).catch(() => {}), new Promise((r) => window.setTimeout(r, 800))]);
        if (seq !== genSeq.current) return g;
      }
      const apply = () => {
        if (holding) {
          setGenerationId(gid);
          storage.set(LS.generation, gid);
        }
        setGeneration(g);
        setActiveStrategyState(nextStrategy);
        setSelectedSlideState((cur) => (sameAsOpen ? clamp(cur, 1, max) : 1));
      };
      if (holding) viewTransition(apply);
      else apply();
      clearNotice("result"); // the deck opened: an earlier «Не удалось открыть презентацию» is stale
      const { templateId: tid, templates: list } = latest.current;
      if (g.template_id && g.template_id !== tid && list.some((t) => t.template_id === g.template_id)) selectTemplate(g.template_id);
      return g;
    } catch (e) {
      if (seq !== genSeq.current) return null;
      if (e instanceof ApiError && e.status === 404 && !holding) clearGeneration();
      if (!quiet) report(e, "Не удалось открыть презентацию", area);
      return null;
    } finally {
      if (seq === genSeq.current) setGenerationLoading(false);
    }
  }, [report, clearNotice, selectTemplate, clearGeneration]);

  const loadGeneration = useCallback(async (gid: string, opts?: { hold?: boolean }) => await fetchGeneration(gid, false, !!opts?.hold), [fetchGeneration]);

  const setActiveStrategy = useCallback((s: string) => {
    const variant = latest.current.generation?.variants.find((v) => v.strategy === s);
    if (latest.current.generation && !variant) return;
    setActiveStrategyState(s);
    setSelectedSlideState((cur) => clamp(cur, 1, slideCount(variant)));
  }, []);

  const setSelectedSlide = useCallback((n: number) => {
    const { generation: g, activeStrategy: s } = latest.current;
    const variant = g?.variants.find((v) => v.strategy === s);
    setSelectedSlideState(clamp(n, 1, variant ? slideCount(variant) : Math.max(1, n)));
  }, []);

  const runJob = useCallback((jobId: string, label: string, opts?: RunJobOptions) => {
    jobSubs.current.get(jobId)?.();
    // the slot shows the newest job; jobs run side by side (the fixes of every variant) keep it busy until the last
    // one ends — the screen never unblocks while a job still runs (its actions would hit «already running»)
    const settle = (p: Partial<ActiveJob>) => {
      jobSubs.current.delete(jobId);
      liveJobs.current.delete(jobId);
      const other = [...liveJobs.current.values()].pop() ?? null;
      if (other) return void setActiveJob((cur) => (cur && cur.id === jobId ? other : cur));
      setActiveJob((cur) => (cur && cur.id === jobId ? { ...cur, ...p } : cur));
      window.setTimeout(() => setActiveJob((cur) => (cur && cur.id === jobId ? null : cur)), 1500);
    };
    const first: ActiveJob = { id: jobId, label, progress: 0, message: "В очереди…", status: "queued", kind: opts?.kind ?? "other", startedAt: Date.now(), items: opts?.items, template: opts?.template, target: opts?.target, generation: opts?.generation ?? null, slides: opts?.slides ?? null };
    liveJobs.current.set(jobId, first);
    setActiveJob(first);
    const stop = trackJob(jobId, {
      onEvent: (ev) => {
        if (ev.status === "done" || ev.status === "failed") return; // settled below, once the full job record is fetched
        const cur = liveJobs.current.get(jobId);
        if (!cur) return;
        const next = foldJobEvent(cur, ev, (name) => titleIn(latest.current.strategies, name));
        liveJobs.current.set(jobId, next);
        setActiveJob((shown) => (shown && shown.id === jobId ? next : shown));
      },
      onDone: (job) => {
        settle({ status: "done", progress: 1, message: "Готово" });
        opts?.onDone?.(job);
      },
      onFailed: (job) => {
        const reason = firstLine(job.error ?? job.message);
        settle({ status: "failed", message: reason });
        // the line stays where the action was after the job slot clears (a failed build keeps its screen); with the
        // helper open it stays too — the line is part of the screen, not a pop-up repeating the helper's message
        if (!opts?.quiet) notify(opts?.area ?? jobArea(opts?.kind ?? "other"), "error", `Не получилось: ${reason}`);
        opts?.onFailed?.(job);
      },
    });
    jobSubs.current.set(jobId, stop);
  }, [notify]);

  const adoptManifest = useCallback((m: TemplateManifest) => {
    setManifest(m); // same batch as the id: the manifest effect sees a match and skips the refetch
    selectTemplate(m.template_id);
  }, [selectTemplate]);

  // «Улучшить готовую»: the deck read back opens «Создать» with its text, plate 02 under the folded plate 01
  const improveReady = useCallback((src: ImproveSource) => {
    setImproveSource(src);
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: true } });
  }, []);

  const uploadTemplate = useCallback(
    (file: File, useModels: boolean, improve?: boolean) =>
      uploadTemplateFlow(file, useModels, { runJob, report, notify, clearNotice, pushMessage, dispatch, setTemplates, adoptManifest }, improve ? improveReady : undefined),
    [runJob, report, notify, clearNotice, pushMessage, adoptManifest, improveReady],
  );

  const startGeneration = useCallback(
    (req: GenerateRequest, expectedSlides?: number | null) =>
      generationFlow(req, { runJob, report, notify, clearNotice, pushMessage, dispatch, refreshGenerations, fetchGeneration: (gid) => fetchGeneration(gid, false, false, "build"), refreshModelStatus, titleOf: (name) => titleIn(latest.current.strategies, name) }, expectedSlides ?? null),
    [runJob, report, notify, clearNotice, pushMessage, refreshGenerations, fetchGeneration, refreshModelStatus],
  );

  // Health loop: first success boots the data (lists + restore from localStorage); afterwards keeps the banner truthful.
  useEffect(() => {
    let alive = true;
    let timer = 0;
    let booted = false;
    const boot = async () => {
      const [st, tp, gn] = await Promise.allSettled([api.strategies(), api.templates(), api.generations()]);
      if (!alive) return;
      if (st.status === "fulfilled") setStrategies(st.value);
      if (gn.status === "fulfilled") setGenerations(gn.value);
      const failed = [st, tp, gn].find((r): r is PromiseRejectedResult => r.status === "rejected");
      if (failed) report(failed.reason, "Не удалось загрузить данные", "global", true);
      if (tp.status === "fulfilled") {
        setTemplates(tp.value);
        const stored = latest.current.templateId; // drop a stale id, fall back to the newest template
        if (!stored || !tp.value.some((t) => t.template_id === stored)) selectTemplate(newestTemplate(tp.value)?.template_id ?? null);
      }
      const storedGen = storage.get(LS.generation);
      // a stored deck that loads needs no move: the screen started on the result (the reducer's initial state), and a
      // place the person went to meanwhile (a layer, «Создать») stays as it is
      if (storedGen && (await fetchGeneration(storedGen, true))) return;
      if (alive) {
        setGenerationLoading(false);
        // the stored deck is gone (404 cleared it) or did not load, and no other deck was opened meanwhile
        const now = storage.get(LS.generation);
        if (storedGen && (now === null || now === storedGen) && latest.current.ui.screen === "result") dispatch({ type: "go", screen: "create" });
      }
    };
    const tick = async () => {
      let ok = true;
      try {
        const h = await api.health();
        if (!alive) return;
        setHealth((prev) => (prev && JSON.stringify(prev) === JSON.stringify(h) ? prev : h));
        setHealthError(false);
      } catch {
        if (!alive) return;
        ok = false;
        setHealthError(true);
      }
      if (ok && !booted) {
        booted = true;
        await boot();
      }
      if (alive) timer = window.setTimeout(tick, ok ? 20000 : 4000);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [report, selectTemplate, fetchGeneration]);

  // Manifest follows templateId (re-runs when the API comes back online).
  useEffect(() => {
    if (!templateId) {
      setManifest(null);
      setManifestLoading(false);
      return;
    }
    if (latest.current.manifest?.template_id === templateId) return void setManifestLoading(false);
    if (healthError) return;
    let alive = true;
    setManifest(null);
    setManifestLoading(true);
    api.template(templateId).then(
      (m) => alive && setManifest(m),
      (e) => {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) selectTemplate(null);
        else report(e, "Не удалось загрузить шаблон", "template", true);
      },
    ).finally(() => alive && setManifestLoading(false));
    return () => {
      alive = false;
    };
  }, [templateId, healthError, report, selectTemplate]);

  useEffect(() => {
    const subs = jobSubs.current;
    return () => subs.forEach((stop) => stop());
  }, []);

  const activeVariant = useMemo(() => generation?.variants.find((v) => v.strategy === activeStrategy) ?? null, [generation, activeStrategy]);

  const value = useMemo<AppState>(() => ({
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, deleteTemplate, forgetTemplate, renameTemplate, templateLabel, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, ui, dispatch, activeJob, runJob, messages, pushMessage, notices, notify, clearNotice, uploadTemplate, startGeneration,
    brief, setBrief, textIssue, setTextIssue, checkText,
    composerText, composerPreset, editText, takeComposerText, improveSource, takeImproveSource,
  }), [
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, deleteTemplate, forgetTemplate, renameTemplate, templateLabel, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, ui, activeJob, runJob, messages, pushMessage, notices, notify, clearNotice, uploadTemplate, startGeneration,
    brief, setBrief, textIssue, checkText,
    composerText, composerPreset, editText, takeComposerText, improveSource, takeImproveSource,
  ]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
