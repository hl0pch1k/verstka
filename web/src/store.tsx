// Application state: one React context, consumed by every panel through useApp().
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { pushToast } from "./components/ui/Toasts";
import { generationFlow, uploadTemplateFlow } from "./lib/flows";
import { humanizeJobMessage, variantProgress, type VariantProgress } from "./lib/jobText";
import { trackJob } from "./lib/jobs";
import { errText, firstLine, newestTemplate, slideCount } from "./lib/narrate";
import { LS, storage, uid } from "./lib/utils";
import type {
  ChatMessage, DetailKey, GenerateRequest, Generation, GenerationMeta, Health, Job, JobKind, JobStatus, ModelsStatus, Screen, StrategyInfo, TabKey, TemplateListItem, TemplateManifest, Variant,
} from "./types";

export interface ActiveJob { id: string; label: string; progress: number; message: string; status: JobStatus; kind: JobKind; startedAt: number; items?: string[]; variants?: Record<string, VariantProgress> }
/** `items`: what the job works on (the strategies of a generation) — the build screen shows one card per item. */
export interface RunJobOptions { kind?: JobKind; items?: string[]; onDone?: (job: Job) => void; onFailed?: (job: Job) => void }

export interface AppState {
  health: Health | null; healthError: boolean;
  /** How the model answers lately (GET /api/models/status); null until the first answer. */
  modelStatus: ModelsStatus | null; refreshModelStatus(): Promise<void>;
  strategies: StrategyInfo[];
  strategyTitle(name: string): string;
  templates: TemplateListItem[]; refreshTemplates(): Promise<void>;
  templateId: string | null; selectTemplate(id: string | null): void;
  manifest: TemplateManifest | null; manifestLoading: boolean;
  generations: GenerationMeta[]; refreshGenerations(): Promise<void>;
  generationId: string | null; generation: Generation | null; generationLoading: boolean;
  loadGeneration(gid: string): Promise<void>;
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
  toast(kind: "error" | "success" | "info", text: string): void;
  uploadTemplate(file: File, useModels: boolean): Promise<void>;
  startGeneration(req: GenerateRequest): Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApp() must be called inside <AppProvider>");
  return value;
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(n) ? Math.round(n) : lo));
const clamp01 = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
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
  const [screen, setScreen] = useState<Screen>("create");
  const [detail, setDetail] = useState<DetailKey | null>(null);
  const setTab = useCallback((t: TabKey) => {
    if (t === "template") return setDetail("template");
    if (t === "brief") {
      setScreen("create");
      return setDetail(null);
    }
    setScreen("result");
    setDetail(t === "plan" ? "plan" : t === "why" ? "why" : t === "audit" ? "quality" : t === "export" || t === "run" ? "tech" : null);
  }, []);
  const [agentOpen, setAgentOpen] = useState(false); // the helper starts closed: the page itself must be self-explanatory
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  // Latest values for callbacks that must stay referentially stable.
  const latest = useRef({ templateId, templates, manifest, generationId, generation, activeStrategy, strategies });
  latest.current = { templateId, templates, manifest, generationId, generation, activeStrategy, strategies };
  const genSeq = useRef(0);
  const jobSubs = useRef(new Map<string, () => void>());

  const toast = useCallback((kind: "error" | "success" | "info", text: string) => void pushToast(kind, text), []);
  /** Network failures flip the red «API недоступен» banner; `quietOffline` skips the toast for background loads. */
  const report = useCallback((e: unknown, prefix: string, quietOffline = false) => {
    const offline = e instanceof ApiError && e.status === 0;
    if (offline) setHealthError(true);
    if (!(offline && quietOffline)) pushToast("error", `${prefix}: ${errText(e)}`);
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

  /** Loads a generation. A reload of the already open one keeps the chosen variant and slide (clamped). */
  const fetchGeneration = useCallback(async (gid: string, quiet = false): Promise<Generation | null> => {
    const seq = ++genSeq.current;
    const sameAsOpen = latest.current.generation?.id === gid;
    setGenerationId(gid);
    storage.set(LS.generation, gid);
    if (!sameAsOpen) {
      setGeneration(null);
      setGenerationLoading(true);
    }
    try {
      const g = await api.generation(gid);
      if (seq !== genSeq.current) return g; // a newer load has started — do not touch the state
      const names = g.variants.map((v) => v.strategy);
      const keep = sameAsOpen ? latest.current.activeStrategy : null;
      const nextStrategy = keep && names.includes(keep) ? keep : names[0] ?? null;
      const max = slideCount(g.variants.find((v) => v.strategy === nextStrategy));
      setGeneration(g);
      setActiveStrategyState(nextStrategy);
      setSelectedSlideState((cur) => (sameAsOpen ? clamp(cur, 1, max) : 1));
      const { templateId: tid, templates: list } = latest.current;
      if (g.template_id && g.template_id !== tid && list.some((t) => t.template_id === g.template_id)) selectTemplate(g.template_id);
      return g;
    } catch (e) {
      if (seq !== genSeq.current) return null;
      if (e instanceof ApiError && e.status === 404) clearGeneration();
      if (!quiet) report(e, "Не удалось открыть презентацию");
      return null;
    } finally {
      if (seq === genSeq.current) setGenerationLoading(false);
    }
  }, [report, selectTemplate, clearGeneration]);

  const loadGeneration = useCallback(async (gid: string) => void (await fetchGeneration(gid)), [fetchGeneration]);

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
    const patch = (p: Partial<ActiveJob>) => setActiveJob((cur) => (cur && cur.id === jobId ? { ...cur, ...p } : cur));
    const settle = (p: Partial<ActiveJob>) => {
      jobSubs.current.delete(jobId);
      patch(p);
      window.setTimeout(() => setActiveJob((cur) => (cur && cur.id === jobId ? null : cur)), 1500);
    };
    setActiveJob({ id: jobId, label, progress: 0, message: "В очереди…", status: "queued", kind: opts?.kind ?? "other", startedAt: Date.now(), items: opts?.items });
    const stop = trackJob(jobId, {
      onEvent: (ev) => {
        if (ev.status === "done" || ev.status === "failed") return; // settled below, once the full job record is fetched
        const message = ev.message ? humanizeJobMessage(ev.message, (name) => titleIn(latest.current.strategies, name)) : "";
        // every event is folded in here (renders may coalesce several): the per-variant cards never miss a step
        const step = ev.message ? variantProgress(ev.message) : null;
        setActiveJob((cur) =>
          cur && cur.id === jobId
            ? {
                ...cur,
                status: ev.status,
                progress: Math.max(cur.progress, clamp01(ev.progress)),
                message: message || cur.message,
                variants: step ? { ...cur.variants, [step.name]: step.state } : cur.variants,
              }
            : cur,
        );
      },
      onDone: (job) => {
        settle({ status: "done", progress: 1, message: "Готово" });
        opts?.onDone?.(job);
      },
      onFailed: (job) => {
        const reason = firstLine(job.error ?? job.message);
        settle({ status: "failed", message: reason });
        pushToast("error", `${label}: ${reason}`);
        opts?.onFailed?.(job);
      },
    });
    jobSubs.current.set(jobId, stop);
  }, []);

  const adoptManifest = useCallback((m: TemplateManifest) => {
    setManifest(m); // same batch as the id: the manifest effect sees a match and skips the refetch
    selectTemplate(m.template_id);
  }, [selectTemplate]);

  const uploadTemplate = useCallback(
    (file: File, useModels: boolean) => uploadTemplateFlow(file, useModels, { runJob, report, pushMessage, setTab, setTemplates, adoptManifest }),
    [runJob, report, pushMessage, adoptManifest],
  );

  const startGeneration = useCallback(
    (req: GenerateRequest) =>
      generationFlow(req, { runJob, report, pushMessage, setTab, refreshGenerations, fetchGeneration, refreshModelStatus, titleOf: (name) => titleIn(latest.current.strategies, name) }),
    [runJob, report, pushMessage, refreshGenerations, fetchGeneration, refreshModelStatus],
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
      else if (alive) setGenerationLoading(false);
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
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, setTab, screen, setScreen, detail, setDetail, agentOpen, setAgentOpen, activeJob, runJob, messages, pushMessage, toast, uploadTemplate, startGeneration,
  }), [
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, setTab, screen, detail, agentOpen, setAgentOpen, activeJob, runJob, messages, pushMessage, toast, uploadTemplate, startGeneration,
  ]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
