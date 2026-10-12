// Application state: one React context, consumed by every panel through useApp().
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { generationFlow, uploadTemplateFlow } from "./lib/flows";
import { foldJobEvent, type ActiveJob } from "./lib/jobState";
import { trackJob } from "./lib/jobs";
import { errText, firstLine, newestTemplate, slideCount } from "./lib/narrate";
import { templateTitle, tplLabel } from "./lib/plain";
import { LS, storage, uid } from "./lib/utils";
import { decodeImage, viewTransition } from "./lib/motion";
import { variantRev, withRev } from "./lib/rev";
import type {
  ChatMessage, DetailKey, GenerateRequest, Generation, GenerationMeta, Health, ImprovedFrom, ImproveSource, Job, JobKind, ModelsStatus, Screen, StrategyInfo, TabKey, TemplateListItem, TemplateManifest, Variant,
} from "./types";

export type { ActiveJob } from "./lib/jobState";
/** Сообщение о ходе действия (ошибка, готово, сведение) и время, когда оно пришло (мс). */
export interface Notice { kind: "error" | "success" | "info"; text: string; at: number }
/** `items`: what the job works on (the strategies of a generation) — the build screen shows one card per item.
 *  `generation` / `slides`: the deck a generation builds and the slide count asked for (the build's rail).
 *  `quiet`: the caller tells the failure itself (no «Не получилось: …» toast from the store). */
export interface RunJobOptions {
  kind?: JobKind; items?: string[]; template?: string | null; onDone?: (job: Job) => void; onFailed?: (job: Job) => void;
  target?: { generation: string; strategy: string; slide: number }; quiet?: boolean;
  generation?: string | null; slides?: number | null;
}

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
  /** Old view names (the agent and flows speak them) → screen + drawer. */
  setTab(t: TabKey): void;
  screen: Screen; setScreen(s: Screen): void;
  detail: DetailKey | null; setDetail(d: DetailKey | null): void;
  agentOpen: boolean; setAgentOpen(v: boolean): void;
  activeJob: ActiveJob | null;
  runJob(jobId: string, label: string, opts?: RunJobOptions): void;
  messages: ChatMessage[]; pushMessage(role: "user" | "assistant", text: string): void; // ts = unix seconds (fmtDate-compatible)
  /** Записывает сообщение в `notice` (всплывающих уведомлений в «Слоях» нет; Task 2 заменит это строками статуса). */
  toast(kind: Notice["kind"], text: string): void;
  /** Последнее сообщение `toast()`; null — сообщений не было. */
  notice: Notice | null;
  uploadTemplate(file: File, useModels: boolean, improve?: boolean): Promise<void>;
  startGeneration(req: GenerateRequest, expectedSlides?: number | null): Promise<void>;
  /** A text handed to the create screen's field once (the agent's written text, «Изменить»); null when none waits. */
  composerText: string | null;
  /** The parameters handed with it (a deck's own: «Изменить текст» on a deck restores how it was built). */
  composerPreset: ComposerPreset | null;
  /** Opens the create screen with `text` in the field (it replaces the saved draft once), and the deck's parameters. */
  editText(text: string, preset?: ComposerPreset): void;
  /** The create screen took the handed text. */
  takeComposerText(): void;
  /** «Улучшить готовую презентацию»: the deck read back, handed to the create screen once (null when none waits). */
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
  // never on the create screen first; boot goes back to «Создать» when the stored deck does not load
  const [screen, setScreen] = useState<Screen>(() => (storage.get(LS.generation) ? "result" : "create"));
  const [detail, setDetail] = useState<DetailKey | null>(null);
  const setTab = useCallback((t: TabKey) => {
    if (t === "template") return setDetail("template");
    if (t === "agent") {
      setScreen("result");
      return setDetail("agent");
    }
    if (t === "brief") {
      setScreen("create");
      return setDetail(null);
    }
    setScreen("result");
    setDetail(t === "plan" ? "plan" : t === "why" ? "why" : t === "audit" ? "quality" : t === "export" || t === "run" ? "tech" : null);
  }, []);
  const [agentOpen, setAgentOpen] = useState(false); // the helper starts closed: the page itself must be self-explanatory
  const [composerText, setComposerText] = useState<string | null>(null);
  const [composerPreset, setComposerPreset] = useState<ComposerPreset | null>(null);
  const editText = useCallback((text: string, preset?: ComposerPreset) => {
    setComposerText(text);
    setComposerPreset(preset ?? null);
    setDetail(null);
    setScreen("create");
  }, []);
  const takeComposerText = useCallback(() => {
    setComposerText(null);
    setComposerPreset(null);
  }, []);
  const [improveSource, setImproveSource] = useState<ImproveSource | null>(null);
  const takeImproveSource = useCallback(() => setImproveSource(null), []);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const liveJobs = useRef(new Map<string, ActiveJob>()); // every job still running, the newest last
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  // Latest values for callbacks that must stay referentially stable.
  const latest = useRef({ templateId, templates, manifest, generationId, generation, activeStrategy, strategies, screen, agentOpen });
  latest.current = { templateId, templates, manifest, generationId, generation, activeStrategy, strategies, screen, agentOpen };
  const genSeq = useRef(0);
  const jobSubs = useRef(new Map<string, () => void>());

  const [notice, setNotice] = useState<Notice | null>(null);
  const toast = useCallback((kind: Notice["kind"], text: string) => setNotice({ kind, text, at: Date.now() }), []);
  /** Network failures flip the red «API недоступен» banner; `quietOffline` skips the notice for background loads. */
  const report = useCallback((e: unknown, prefix: string, quietOffline = false) => {
    const offline = e instanceof ApiError && e.status === 0;
    if (offline) setHealthError(true);
    if (!(offline && quietOffline)) toast("error", `${prefix}: ${errText(e)}`);
  }, [toast]);

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
    } catch (e) {
      report(e, "Не удалось обновить список шаблонов");
    }
  }, [report]);

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
      report(e, "Не удалось обновить список презентаций");
    }
  }, [report, clearGeneration]);

  /** Loads a generation. A reload of the already open one keeps the chosen variant and slide (clamped). `hold` (another
   *  deck picked over an open one, from the history): the open deck stays on screen while the new one loads and its
   *  first slide decodes, then the new deck replaces it inside a view transition — never a skeleton in between (the
   *  history row shows the wait); a failed load leaves the open deck as it was. */
  const fetchGeneration = useCallback(async (gid: string, quiet = false, hold = false): Promise<Generation | null> => {
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
      const { templateId: tid, templates: list } = latest.current;
      if (g.template_id && g.template_id !== tid && list.some((t) => t.template_id === g.template_id)) selectTemplate(g.template_id);
      return g;
    } catch (e) {
      if (seq !== genSeq.current) return null;
      if (e instanceof ApiError && e.status === 404 && !holding) clearGeneration();
      if (!quiet) report(e, "Не удалось открыть презентацию");
      return null;
    } finally {
      if (seq === genSeq.current) setGenerationLoading(false);
    }
  }, [report, selectTemplate, clearGeneration]);

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
        // one notice per failure: with the helper open, its own message tells the story
        if (!opts?.quiet && (!opts?.onFailed || !latest.current.agentOpen)) toast("error", `Не получилось: ${reason}`);
        opts?.onFailed?.(job);
      },
    });
    jobSubs.current.set(jobId, stop);
  }, [toast]);

  const adoptManifest = useCallback((m: TemplateManifest) => {
    setManifest(m); // same batch as the id: the manifest effect sees a match and skips the refetch
    selectTemplate(m.template_id);
  }, [selectTemplate]);

  const uploadTemplate = useCallback(
    (file: File, useModels: boolean, improve?: boolean) =>
      uploadTemplateFlow(file, useModels, { runJob, report, toast, pushMessage, setTab, setTemplates, adoptManifest }, improve ? (src) => { setImproveSource(src); setScreen("create"); } : undefined),
    [runJob, report, toast, pushMessage, adoptManifest],
  );

  const startGeneration = useCallback(
    (req: GenerateRequest, expectedSlides?: number | null) =>
      generationFlow(req, { runJob, report, toast, pushMessage, setTab, refreshGenerations, fetchGeneration, refreshModelStatus, titleOf: (name) => titleIn(latest.current.strategies, name), setAgentOpen, currentScreen: () => latest.current.screen }, expectedSlides ?? null),
    [runJob, report, toast, pushMessage, refreshGenerations, fetchGeneration, refreshModelStatus],
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
      if (failed) report(failed.reason, "Не удалось загрузить данные", true);
      if (tp.status === "fulfilled") {
        setTemplates(tp.value);
        const stored = latest.current.templateId; // drop a stale id, fall back to the newest template
        if (!stored || !tp.value.some((t) => t.template_id === stored)) selectTemplate(newestTemplate(tp.value)?.template_id ?? null);
      }
      const storedGen = storage.get(LS.generation);
      if (storedGen && (await fetchGeneration(storedGen, true)) && alive) setTab("variants");
      else if (alive) {
        setGenerationLoading(false);
        // the stored deck is gone (404 cleared it) or did not load, and no other deck was opened meanwhile
        const now = storage.get(LS.generation);
        if (storedGen && (now === null || now === storedGen) && latest.current.screen === "result") setScreen("create");
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
        else report(e, "Не удалось загрузить шаблон", true);
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
    selectedSlide, setSelectedSlide, setTab, screen, setScreen, detail, setDetail, agentOpen, setAgentOpen, activeJob, runJob, messages, pushMessage, toast, notice, uploadTemplate, startGeneration,
    composerText, composerPreset, editText, takeComposerText, improveSource, takeImproveSource,
  }), [
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, deleteTemplate, forgetTemplate, renameTemplate, templateLabel, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, setTab, screen, detail, agentOpen, setAgentOpen, activeJob, runJob, messages, pushMessage, toast, notice, uploadTemplate, startGeneration,
    composerText, composerPreset, editText, takeComposerText, improveSource, takeImproveSource,
  ]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
