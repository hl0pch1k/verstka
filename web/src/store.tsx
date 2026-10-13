// Application state: one React context, consumed by every panel through useApp().
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { endedToShow, endSeen, followBuild, generationFlow, improveArrives, liveBuildToShow, uploadTemplateFlow, watchingBuild, type GenerationDeps } from "./lib/flows";
import { foldJobEvent, type ActiveJob } from "./lib/jobState";
import { trackJob } from "./lib/jobs";
import { errText, firstLine, newestTemplate, slideCount } from "./lib/narrate";
import { templateTitle, tplLabel } from "./lib/plain";
import { LS, storage, uid } from "./lib/utils";
import { decodeImage } from "./lib/motion";
import { draftBrief, writeDraft } from "./lib/draft";
import { reloadPlan, replayWanted } from "./lib/reload";
import { variantRev, withRev } from "./lib/rev";
import { uiReducer, UI0, type UiAction, type UiState } from "./ui/deck/geometry";
import { textError, writerOn, type TextIssue } from "./ui/create/textRules";
import { buildRunning, draftParams, type Params } from "./ui/create/params";
import { askFor, completeAsk, failedBuildJob, parsePendingBuild, pendingFor, requestOf, resumeBuild, type PendingBuild } from "./ui/build/resume";
import { openStrategy } from "./ui/result/resultView";
import { useVariantWork, type VariantWorkApi } from "./ui/details/useVariantWork";
import { slideFailAfter, type SlideFail } from "./ui/result/slideJob";
import { busyKeys } from "./ui/details/variantWork";
import type {
  ChatMessage, GenerateRequest, Generation, GenerationMeta, Health, ImprovedFrom, ImproveSource, Job, JobKind, ModelsStatus, Notice, NoticeArea, StrategyInfo, TemplateListItem, TemplateManifest, Variant,
} from "./types";

export type { ActiveJob } from "./lib/jobState";
export type { Notice, NoticeArea } from "./types";
export type { TextIssue } from "./ui/create/textRules";
export type { Params } from "./ui/create/params";
/** `items`: what the job works on (the strategies of a generation) — the build screen shows one card per item.
 *  `generation` / `slides`: the deck a generation builds and the slide count asked for (the build's rail).
 *  `area`: where a failure is told («Не получилось: …»); by default — by the job's kind (`jobArea`).
 *  `quiet`: the caller tells the failure itself (no «Не получилось: …» line from the store). */
export interface RunJobOptions {
  /** `onDone` may return a promise (a re-read of the deck): watchers (`watchJob`) hear the end after it settles. */
  kind?: JobKind; items?: string[]; template?: string | null; onDone?: (job: Job) => void | Promise<void>; onFailed?: (job: Job) => void;
  target?: { generation: string; strategy: string; slide: number }; quiet?: boolean; area?: NoticeArea;
  generation?: string | null; slides?: number | null;
  /** When the job began (ms): a build found again after a reload keeps its own clock. */
  startedAt?: number;
}

/** The request of the build in progress, kept in localStorage (LS.build): a page opened again follows the build and
 *  can repeat it («Собрать ещё раз») with the same inputs. */
const readPendingBuild = (): PendingBuild | null => parsePendingBuild(storage.get(LS.build));

/** Where a job's failure stands by default: template analysis at the template step, a build on the build screen, the
 *  work on a built deck (fixes, edits, pictures, anything else) on the result. */
const jobArea = (kind: JobKind): NoticeArea => (kind === "analyze" ? "template" : kind === "generate" ? "build" : "result");

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
  /** Open a deck; resolves to it (null when it did not load — the failure is already reported). `hold` («Мои
   *  презентации»): the open deck stays until the new one is ready and its first slide decoded, then the new one takes
   *  its place at once — the history layer covers the plate meanwhile and moves the deck itself; a deck that is gone
   *  (404) leaves the list. `strategy`: the variant it opens on (the history card's cover), else the first. `area`:
   *  where a failure is told (the result by default; the build screen for «Открыть ещё раз» of a finished build). */
  loadGeneration(gid: string, opts?: { hold?: boolean; strategy?: string | null; area?: NoticeArea }): Promise<Generation | null>;
  /** «Мои презентации» closed while deck `gid` was being opened: its load is dropped — the open deck stays as it was
   *  (`hold`), or, when none was open, none opens. A load already applied stays. */
  cancelLoad(gid: string): void;
  /** Re-reads deck `gid` after a change made to it (a slide fix, a picture, «верни как было») — only while it is still
   *  the open deck; the screen, the variant and the slide stay. A job that ends after the person left the result screen
   *  still lands: the deck shows the change on the way back. Another deck being opened over it («Мои презентации»): the
   *  re-read waits and runs when that load is dropped or fails (the open deck stays). Resolves to the deck read, or null
   *  when it was not reloaded (another deck is open, the re-read waits) or did not load — then `onError` hears why. The
   *  re-read is quiet: the open deck stays as it was, no «Не удалось открыть презентацию» on the result — the place of
   *  the action tells the failure itself, once. */
  reloadIfOpen(gid: string, onError?: (e: unknown) => void): Promise<Generation | null>;
  /** Открытая презентация, которую изменили (слайд, изображение, «Исправить всё», «Вернуть как было», правка помощника),
   *  а перечитать не вышло (`reloadIfOpen` не прочитал её): на экране она прежняя. Места действия говорят это строкой с
   *  «Обновить», «Мои презентации» перечитывают её. Уходит, когда открытая презентация прочиталась (любым путём) или
   *  открыли другую. */
  stale: StaleDeck | null;
  /** «Обновить»: несвежая презентация `gid` читается ещё раз (тихо: не прочиталась — `stale` с новой причиной);
   *  resolves true, когда прочиталась. Пока читается — `refreshing`. */
  refreshDeck(gid: string): Promise<boolean>;
  refreshing: string | null;
  activeStrategy: string | null; setActiveStrategy(s: string): void; activeVariant: Variant | null;
  selectedSlide: number; setSelectedSlide(n: number): void; // 1-based
  /** Экран, раскрытые шаги, слои и листы «Слоёв» (`ui/deck/geometry.ts`); меняется только через `dispatch`. */
  ui: UiState; dispatch(a: UiAction): void;
  activeJob: ActiveJob | null;
  /** Every job still running, the newest last, with its live progress (jobs run side by side — «Исправь всё» starts one
   *  per variant; `activeJob` shows only the newest). */
  liveJobs: ActiveJob[];
  runJob(jobId: string, label: string, opts?: RunJobOptions): void;
  /** Конец идущей задачи для того, кто её не запускал (экран результата подхватил чужую работу над слайдом): `cb` слышит
   *  его после того, как запустивший отработал своё (перечитал презентацию); `stale` — презентация задачи после этого
   *  несвежая. Возвращает отписку; null — задача уже не идёт (её конца не будет: подхватывать нечего). */
  watchJob(jobId: string, cb: (job: Job, ok: boolean, stale: boolean) => void): (() => void) | null;
  /** Неудача работы над слайдом, которую человек не видел у её места (был на другом слайде, без режима «Замечания»,
   *  вне экрана результата): строка результата этой презентации с «Показать» — пока он не дошёл до места (там строка
   *  стоит у работы) или не начал новую работу над вариантом. Своя строка, не `notices.result` (её читает «Мои
   *  презентации» как неудачу открытия). Одна — самая новая. */
  slideFail: SlideFail | null;
  /** Работа не удалась без человека у её места: `slideFail` — если её конец не слышит экран, подхвативший её (он скажет
   *  сам). */
  failAway(f: SlideFail): void;
  /** Строка `slideFail` больше не нужна: её работу увидели у места (`jobId`) или над вариантом началась новая работа
   *  (`gid` + `strategy`). */
  dropSlideFail(match: { jobId?: string | null; gid?: string; strategy?: string }): void;
  /** «Мои презентации»: идущая сборка (мета с `job_id`) — экран «Сборка» с её задачей; задачу уже ведут — экран просто
   *  возвращается к ней (и показывает её, даже если с тех пор подключились к другой). false — вести нечего (у меты нет
   *  задачи). Мета — полная (`GET /api/generations/{gid}`): «Собрать ещё раз» повторит её запрос. */
  followDeck(g: GenerationMeta): boolean;
  /** Полная мета сборки, которую ведут по задаче без неё (помощник начал сборку, а мета тогда не прочиталась): запрос
   *  сборки — полоса 02 экрана «Сборка» и «Собрать ещё раз» — берётся из неё, если он ещё заглушка этой сборки. */
  adoptBuildMeta(g: GenerationMeta): void;
  /** Варианты, над которыми идёт задача (`workKey(gid, strategy)` по цели задачи): сервер держит одну задачу на вариант,
   *  и кнопки работы над ним выключены, где бы её ни начали. */
  busyVariants: string[];
  /** Работа над вариантами (ui/details/useVariantWork): «Исправить замечания» листа «Подробнее» и единственное «Вернуть
   *  как было» — для вкладок «Качество», «Агент» и исправления слайда. Состояние по `workKey` переживает закрытие листа. */
  work: VariantWorkApi["work"];
  fixIssues: VariantWorkApi["fixIssues"];
  revertVariant: VariantWorkApi["revertVariant"];
  /** Сборка, которую показывает экран «Сборка»: самая новая задача `generate` — идущая или законченная (неудача
   *  остаётся на экране, пока с него не ушли: слот `activeJob` пустеет через 1,5 с после конца задачи). */
  buildJob: ActiveJob | null;
  /** Запрос сборки, которую показывает (или вот-вот покажет) экран «Сборка», с её генерацией (`gid`): свой запрос
   *  страницы или собранный из меты чужой сборки, к которой подключились; до подключения после перезагрузки — из
   *  LS.build. Полосы 01/02 экрана «Сборка» говорят о нём (ui/build/resume `buildTopic`), а не о черновике поля. */
  buildAsk: PendingBuild | null;
  /** Своя сборка страницы — начатая здесь («Создать презентацию», «Собрать ещё раз») или найденная по LS.build после
   *  перезагрузки (её генерация); null — своей нет. Только её запрос лежит в LS.build; у чужой сборки, к которой
   *  подключились, «Вернуться к тексту» берёт её текст, а не черновик поля. */
  ownBuild: string | null;
  /** Идёт хотя бы одна сборка (задача `generate` в очереди или в работе): вторая поверх не начинается. */
  building: boolean;
  /** Сборка, которая кончилась, пока человек был в другом месте (не на её экране «Сборка»): экран она не уводит —
   *  «Создать» говорит о ней строкой («Сборка готова · Открыть», «Сборка не удалась · Посмотреть»). Уходит, когда
   *  человек её увидел (её экран «Сборка» или её презентация на результате) и когда началась новая сборка. */
  buildEnd: BuildEnd | null;
  /** «Посмотреть» у неудачной сборки, кончившейся в другом месте (и её карточка в «Мои презентации»): экран «Сборка»
   *  показывает именно её — с её причиной и запросом, даже если с тех пор экран вёл другую сборку. */
  showEnded(end: BuildEnd): void;
  /** «Вернуться к сборке»: экран «Сборка» с идущей сборкой — самой новой из тех, что ведёт страница, если экран показывает
   *  законченную (неудачу, на которую смотрели через «Посмотреть»). */
  goBuild(): void;
  /** «Собрать ещё раз»: тот же запрос сборки повторно. Обещание — как у startGeneration: решается, когда повторная сборка
   *  кончилась или не началась (её начало видно по `buildJob`, отказ — по строке области «Сборка»); false — повторять
   *  нечего (запрос неизвестен). `deck` — открытая презентация (результат): повторяется её запрос — свой запрос
   *  страницы, если это её сборка, иначе собранный из меты (`requestOf`), а не запрос последней сборки. */
  retryBuild(deck?: GenerationMeta | null): Promise<boolean>;
  messages: ChatMessage[]; pushMessage(role: "user" | "assistant", text: string): void; // ts = unix seconds (fmtDate-compatible)
  /** Строки статуса по областям — показываются рядом с местом действия (всплывающих уведомлений в «Слоях» нет). */
  notices: Partial<Record<NoticeArea, Notice>>;
  /** Ставит строку статуса области (новая заменяет прежнюю). */
  notify(area: NoticeArea, kind: Notice["kind"], text: string): void;
  /** Убирает строку статуса области. */
  clearNotice(area: NoticeArea): void;
  /** Загрузка шаблона (шаг 01) или чтение презентации («Улучшить готовую», `improve`). `onJob` — задача разбора, когда
   *  сервер принял файл. Одно за раз: пока идёт одно, другое не начинается (`analyzing`). */
  uploadTemplate(file: File, useModels: boolean, improve?: boolean, onJob?: (jobId: string) => void): Promise<void>;
  /** Что сейчас разбирается: свой шаблон (`template`) или презентация для «Улучшить готовую» (`deck`); null — ничего.
   *  Пока идёт одно, второе выключено (обе задачи выбирают свой шаблон, кто кончил последним — тот и выбран бы). */
  analyzing: "template" | "deck" | null;
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
  /** Параметры шага 03 (черновик рядом с текстом, ключ `params` в `verstka.brief_draft`). */
  params: Params;
  /** Новые параметры: часть полей или функция от прежних. */
  setParams(patch: Partial<Params> | ((p: Params) => Params)): void;
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
  /** The parameters step took the handed parameters. */
  takeComposerPreset(): void;
  /** «Улучшить готовую»: the deck read back. Handed to the text step, it stays while the improve mode lives
   *  (`ui.improve`) — the build sends it as `improved_from`; the text step drops it when the mode ends. */
  improveSource: ImproveSource | null;
  takeImproveSource(): void;
}

/** Несвежая открытая презентация: её id, почему не перечиталась (`reloadFailText`) и когда. */
export interface StaleDeck { gid: string; error: unknown; at: number }

/** Сборка, кончившаяся без человека на её экране: её презентация, её задача и чем кончилась. */
export interface BuildEnd { gid: string; job: string; ok: boolean }

/** A deck's own parameters for the create screen (GenerationMeta): what «Изменить текст» restores with its text. */
export interface ComposerPreset {
  audience?: string | null;
  purpose?: string | null;
  slides?: number | null;
  useModels?: boolean;
  /** Older decks: the switch «Модель проверяет слайды по картинке» stood for `audit_models` — restored when `eyes` is
   *  not known. */
  auditModels?: boolean;
  /** «Модель проверяет слайды по картинке» (the designer's look) as the deck was built (null: the server's default). */
  eyes?: boolean | null;
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

/** The request of deck `g` for «Собрать ещё раз»: the page's own (LS.build) when it is this deck's, else from its meta. */
const askOf = (g: GenerationMeta, pending: PendingBuild | null): PendingBuild =>
  pending && pending.gid === g.id ? pending : { gid: g.id, request: requestOf(g), expected: g.slides ?? null };

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
  // a reload during a build opens on the build screen: boot follows the build again (LS.build)
  const [ui, dispatch] = useReducer(uiReducer, UI0, (s0): UiState =>
    (readPendingBuild() ? { ...s0, screen: "build" } : storage.get(LS.generation) ? { ...s0, screen: "result" } : s0));
  const [composerText, setComposerText] = useState<string | null>(null);
  const [composerPreset, setComposerPreset] = useState<ComposerPreset | null>(null);
  const [improveSource, setImproveSource] = useState<ImproveSource | null>(null);
  // «Улучшить готовую»: презентация прочитана, пока человек был не на «Создать» — режим ждёт его возвращения
  const [improveWait, setImproveWait] = useState<ImproveSource | null>(null);
  const editText = useCallback((text: string, preset?: ComposerPreset) => {
    // «Изменить текст» — свой текст поверх прочитанной в фоне презентации: ждущий режим уходит
    setImproveWait(null);
    setComposerText(text);
    setComposerPreset(preset ?? null);
    // an improved deck's «Изменить текст» returns into the improve mode, with the deck it was read from (the note over
    // the field and the strip 01 tell it); any other text leaves it
    const from = preset?.improvedFrom ?? null;
    setImproveSource(from ? { brief: text, name: from.name, template_id: from.template_id, slides: from.slides, tables: 0, charts: 0, pictures: 0, audit: from.audit ?? null } : null);
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: !!from } });
  }, []);
  const takeComposerText = useCallback(() => setComposerText(null), []);
  const takeComposerPreset = useCallback(() => setComposerPreset(null), []);
  const takeImproveSource = useCallback(() => setImproveSource(null), []);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const liveJobs = useRef(new Map<string, ActiveJob>()); // every job still running, the newest last
  const [liveList, setLiveList] = useState<ActiveJob[]>([]);
  const syncLive = useCallback(() => setLiveList([...liveJobs.current.values()]), []);
  const [busyVariants, setBusyVariants] = useState<string[]>([]);
  const syncBusyVariants = useCallback(() => {
    const next = busyKeys(liveJobs.current.values());
    setBusyVariants((cur) => (cur.length === next.length && cur.every((k, i) => k === next[i]) ? cur : next));
  }, []);
  const [buildJob, setBuildJob] = useState<ActiveJob | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildEnd, setBuildEnd] = useState<BuildEnd | null>(null);
  // каждая законченная сборка, как её видел экран «Сборка» в конце (задача с причиной и часами): «Посмотреть» у сборки,
  // кончившейся в другом месте, возвращает на экран именно её, а не сборку, которую экран вёл с тех пор
  const endedBuilds = useRef(new Map<string, ActiveJob>());
  // the newest build and its request (startGeneration once the server took it, or a build found again after a reload):
  // «Собрать ещё раз» repeats it; LS.build is written only for the deck this request belongs to
  const lastBuild = useRef<PendingBuild | null>(null);
  // every build's request the page knows (its own, the ones it followed): the build screen shows one build at a time —
  // switching back to an earlier one brings its own request back, never another deck's
  const asks = useRef(new Map<string, PendingBuild>());
  // the same request for the screen (the build screen's strips 01/02): a ref does not re-render
  const [buildAsk, setBuildAsk] = useState<PendingBuild | null>(readPendingBuild);
  const keepBuild = useCallback((p: PendingBuild) => {
    lastBuild.current = p;
    asks.current.set(p.gid, p);
    setBuildAsk(p);
  }, []);
  // the page's own build (started here, or found again by LS.build): only its request lives in LS.build
  const [ownBuild, setOwnBuild] = useState<string | null>(() => readPendingBuild()?.gid ?? null);
  const ownRef = useRef(ownBuild);
  ownRef.current = ownBuild;
  // attachBuild needs the generation flow's deps, defined further down: loadGeneration and boot reach it through this
  const attachRef = useRef<(g: GenerationMeta, pending?: PendingBuild | null) => void>(() => {});
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [brief, setBriefState] = useState(draftBrief);
  const [textIssue, setTextIssue] = useState<TextIssue | null>(null);
  const [params, setParamsState] = useState(draftParams);
  const setParams = useCallback((patch: Partial<Params> | ((p: Params) => Params)) => {
    setParamsState((p) => (typeof patch === "function" ? patch(p) : { ...p, ...patch }));
  }, []);

  // Latest values for callbacks that must stay referentially stable.
  const latest = useRef({ templateId, templates, manifest, generationId, generation, activeStrategy, strategies, ui, brief, params, health, modelStatus, buildJob });
  latest.current = { templateId, templates, manifest, generationId, generation, activeStrategy, strategies, ui, brief, params, health, modelStatus, buildJob };
  const genSeq = useRef(0);
  // the deck asked for last (fetchGeneration): a reload after a change never races a deck being opened over it
  const askedGen = useRef<string | null>(null);
  // a re-read of the open deck skipped while another deck was being opened over it: it runs when that load is dropped
  // (cancelLoad) or fails — the open deck stays and must show the change (reloadSkipped)
  const skippedReload = useRef<string | null>(null);
  const replayRef = useRef<(openId: string | null) => void>(() => {});
  const [stale, setStaleState] = useState<StaleDeck | null>(null);
  // the same for callbacks that run before the next render (a job's watchers hear the end right after the re-read)
  const staleRef = useRef<StaleDeck | null>(null);
  const setStale = useCallback((v: StaleDeck | null) => {
    staleRef.current = v;
    setStaleState(v);
  }, []);
  const [refreshing, setRefreshing] = useState<string | null>(null);
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
  // черновик (текст и параметры) пишется через 300 мс после последней правки, а при уходе со страницы — сразу
  useEffect(() => {
    const t = window.setTimeout(() => writeDraft({ brief }), 300);
    return () => window.clearTimeout(t);
  }, [brief]);
  useEffect(() => {
    const t = window.setTimeout(() => writeDraft({ params }), 300);
    return () => window.clearTimeout(t);
  }, [params]);
  useEffect(() => {
    const flush = () => writeDraft({ brief: latest.current.brief, params: latest.current.params });
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);
  const checkText = useCallback(() => {
    // тема годится, только когда агент пишет текст по теме (`writerOn` — то же правило, что у поля и его строк);
    // иначе нужен готовый текст
    const { brief: text, health: h, modelStatus: status, params: p } = latest.current;
    const issue = textError(text, null, { writer: writerOn({ health: h, status, useModels: p.useModels }) });
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

  const watchers = useRef(new Map<string, Set<(job: Job, ok: boolean, stale: boolean) => void>>());
  const clearGeneration = useCallback(() => {
    genSeq.current += 1;
    askedGen.current = null;
    setStale(null);
    setGenerationId(null);
    setGeneration(null);
    setGenerationLoading(false);
    setActiveStrategyState(null);
    setSelectedSlideState(1);
    storage.set(LS.generation, null);
  }, [setStale]);

  const refreshGenerations = useCallback(async () => {
    try {
      const list = await api.generations();
      setGenerations(list);
      clearNotice("history"); // the list is fresh: an earlier «Не удалось обновить список презентаций» is stale
      const current = latest.current.generation?.id; // a loaded generation that was deleted meanwhile
      if (current && !list.some((g) => g.id === current)) clearGeneration();
    } catch (e) {
      // the line stands in the header of «Мои презентации» (the list shown there may be stale)
      report(e, "Не удалось обновить список презентаций", "history");
    }
  }, [report, clearGeneration, clearNotice]);

  /** Loads a generation. A reload of the already open one keeps the chosen variant and slide (clamped). `hold` (another
   *  deck picked over an open one, from the history): the open deck stays on screen while the new one loads and its
   *  first slide decodes, then the new deck replaces it at once — never a skeleton in between (the history card shows
   *  the wait, the history layer covers the plate and closes in the same moment; a view transition would cross-fade a
   *  snapshot of the layer over its own slide down); a failed load leaves the open deck as it was. `area`: where a
   *  failure is told (the result; the build screen for a deck that has just been built). `want`: the variant a newly
   *  opened deck shows (a reload of the open one keeps its own). */
  const fetchGeneration = useCallback(async (gid: string, quiet = false, hold = false, area: NoticeArea = "result", want: string | null = null, onError?: (e: unknown) => void): Promise<Generation | null> => {
    const seq = ++genSeq.current;
    askedGen.current = gid;
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
      if (seq !== genSeq.current) {
        // a newer load has started — do not touch the state; a re-read of the open deck it cut off runs again when that
        // load is dropped or fails (the open deck stays)
        if (sameAsOpen) skippedReload.current = gid;
        return g;
      }
      const names = g.variants.map((v) => v.strategy);
      const nextStrategy = openStrategy(names, sameAsOpen ? latest.current.activeStrategy : null, want);
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
        // the open deck is read anew, or another deck took its place: a waiting re-read has nothing left to show, and
        // the screen is fresh (no «не обновилась» line)
        skippedReload.current = null;
        setStale(null);
        setGeneration(g);
        setActiveStrategyState(nextStrategy);
        setSelectedSlideState((cur) => (sameAsOpen ? clamp(cur, 1, max) : 1));
      };
      apply();
      clearNotice("result"); // the deck opened: an earlier «Не удалось открыть презентацию» is stale
      // the template and the text of «Создать» stay as they are: opening a deck is not a new draft (a build the person
      // watched to its end selects its template itself — flows `selectBuilt`)
      return g;
    } catch (e) {
      if (seq !== genSeq.current) return null;
      // the open deck stayed: a change made to it reloads it again (reloadIfOpen asks for the deck asked for last), and
      // a re-read it skipped meanwhile runs now
      if (holding) {
        askedGen.current = latest.current.generation?.id ?? null;
        replayRef.current(askedGen.current);
      }
      if (e instanceof ApiError && e.status === 404) {
        if (!holding) clearGeneration();
        // picked from «Мои презентации» and gone meanwhile: the list drops it (offline — the list stays as it is)
        if (hold) void refreshGenerations();
      }
      if (!quiet) report(e, "Не удалось открыть презентацию", area);
      // a quiet re-read of the open deck after a change: the change is saved, the screen shows the deck as it was — the
      // places of action say it with «Обновить» (a deck that is gone has closed)
      else if (sameAsOpen && !(e instanceof ApiError && e.status === 404)) setStale({ gid, error: e, at: Date.now() });
      onError?.(e);
      return null;
    } finally {
      if (seq === genSeq.current) setGenerationLoading(false);
    }
  }, [report, clearNotice, clearGeneration, refreshGenerations, setStale]);

  const loadGeneration = useCallback(async (gid: string, opts?: { hold?: boolean; strategy?: string | null; area?: NoticeArea }) => {
    const load = fetchGeneration(gid, false, !!opts?.hold, opts?.area ?? "result", opts?.strategy ?? null);
    const seq = genSeq.current; // fetchGeneration takes its number before its first await
    const g = await load;
    // a deck still being built opens on its build — unless another deck was asked for meanwhile (or this one was dropped)
    if (seq === genSeq.current && g?.status === "running" && g.job_id) attachRef.current(g);
    return g;
  }, [fetchGeneration]);

  const cancelLoad = useCallback((gid: string) => {
    // nothing pending for it: another deck was asked for since, or it has already opened
    if (askedGen.current !== gid || latest.current.generation?.id === gid) return;
    const open = latest.current.generation;
    if (!open) return clearGeneration(); // nothing was open: the half-opened deck goes (its id, its skeleton)
    genSeq.current += 1; // the held deck stays: the load in flight lands nowhere
    askedGen.current = open.id;
    replayRef.current(open.id); // a re-read it skipped meanwhile runs now
  }, [clearGeneration]);

  const reloadIfOpen = useCallback(async (gid: string, onError?: (e: unknown) => void) => {
    const plan = reloadPlan(gid, latest.current.generation?.id ?? null, askedGen.current);
    if (plan === "none") return null;
    // another deck is being opened over this one: the re-read waits for that load to be dropped or to fail
    if (plan === "wait") {
      skippedReload.current = gid;
      return null;
    }
    // quiet: a failed re-read leaves the open deck as it was, the place of the action tells it (onError)
    return fetchGeneration(gid, true, false, "result", null, onError);
  }, [fetchGeneration]);
  const refreshDeck = useCallback(async (gid: string) => {
    setRefreshing(gid);
    const g = await reloadIfOpen(gid);
    setRefreshing((cur) => (cur === gid ? null : cur));
    return !!g;
  }, [reloadIfOpen]);
  replayRef.current = (openId) => {
    if (!replayWanted(skippedReload.current, openId)) return;
    skippedReload.current = null;
    void fetchGeneration(openId!, true);
  };

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
    const build = opts?.kind === "generate";
    const gid = opts?.generation ?? null;
    const syncBuilding = () => setBuilding([...liveJobs.current.values()].some(buildRunning));
    // the slot shows the newest job; jobs run side by side (the fixes of every variant) keep it busy until the last
    // one ends — the screen never unblocks while a job still runs (its actions would hit «already running»)
    const settle = (p: Partial<ActiveJob>) => {
      jobSubs.current.delete(jobId);
      const last = liveJobs.current.get(jobId);
      liveJobs.current.delete(jobId);
      syncLive();
      syncBusyVariants();
      if (build) {
        // the build screen keeps the ended build (a failure stays on it), with the clock stopped; a build the screen no
        // longer shows is kept aside — «Посмотреть» brings it back (showEnded)
        const endedAt = Date.now();
        if (last) endedBuilds.current.set(jobId, { ...last, ...p, endedAt });
        setBuildJob((cur) => (cur && cur.id === jobId ? { ...cur, ...p, endedAt } : cur));
        syncBuilding();
        if (gid && readPendingBuild()?.gid === gid) storage.set(LS.build, null);
      }
      const other = [...liveJobs.current.values()].pop() ?? null;
      if (other) return void setActiveJob((cur) => (cur && cur.id === jobId ? other : cur));
      setActiveJob((cur) => (cur && cur.id === jobId ? { ...cur, ...p } : cur));
      window.setTimeout(() => setActiveJob((cur) => (cur && cur.id === jobId ? null : cur)), 1500);
    };
    const first: ActiveJob = { id: jobId, label, progress: 0, message: "В очереди…", status: "queued", kind: opts?.kind ?? "other", startedAt: opts?.startedAt ?? Date.now(), items: opts?.items, template: opts?.template, target: opts?.target, generation: gid, slides: opts?.slides ?? null };
    liveJobs.current.set(jobId, first);
    syncLive();
    syncBusyVariants();
    setActiveJob(first);
    if (build) {
      setBuildJob(first);
      setBuildEnd(null); // a new build: the line about the previous one is stale
      syncBuilding();
      // a reload finds the page's own build again and can repeat it — with its own request (never another deck's); a
      // build followed from the list or the helper does not take the record over
      const pending = gid && gid === ownRef.current ? pendingFor(asks.current.get(gid) ?? lastBuild.current, gid) : null;
      if (pending) storage.set(LS.build, JSON.stringify(pending));
    }
    // who did not start the job hears its end after its owner (a deck re-read included): `stale` — the job's deck stayed
    // unread
    const deck = opts?.target?.generation ?? gid;
    const tell = (job: Job, ok: boolean) => {
      const set = watchers.current.get(jobId);
      watchers.current.delete(jobId);
      set?.forEach((cb) => cb(job, ok, !!deck && staleRef.current?.gid === deck));
    };
    const stop = trackJob(jobId, {
      onEvent: (ev) => {
        if (ev.status === "done" || ev.status === "failed") return; // settled below, once the full job record is fetched
        const cur = liveJobs.current.get(jobId);
        if (!cur) return;
        const next = foldJobEvent(cur, ev, (name) => titleIn(latest.current.strategies, name));
        liveJobs.current.set(jobId, next);
        syncLive();
        setActiveJob((shown) => (shown && shown.id === jobId ? next : shown));
        if (build) setBuildJob((shown) => (shown && shown.id === jobId ? next : shown));
      },
      onDone: (job) => {
        settle({ status: "done", progress: 1, message: "Готово" });
        void Promise.resolve(opts?.onDone?.(job)).catch(() => {}).then(() => tell(job, true));
      },
      onFailed: (job) => {
        const reason = firstLine(job.error ?? job.message);
        settle({ status: "failed", message: reason });
        // the line stays where the action was after the job slot clears (a failed build keeps its screen); with the
        // helper open it stays too — the line is part of the screen, not a pop-up repeating the helper's message
        if (!opts?.quiet) notify(opts?.area ?? jobArea(opts?.kind ?? "other"), "error", `Не получилось: ${reason}`);
        opts?.onFailed?.(job);
        tell(job, false);
      },
    });
    jobSubs.current.set(jobId, stop);
  }, [notify, syncBusyVariants, syncLive]);

  const watchJob = useCallback((jobId: string, cb: (job: Job, ok: boolean, stale: boolean) => void) => {
    if (!liveJobs.current.has(jobId)) return null;
    let set = watchers.current.get(jobId);
    if (!set) watchers.current.set(jobId, (set = new Set()));
    set.add(cb);
    return () => {
      const cur = watchers.current.get(jobId);
      cur?.delete(cb);
      if (cur && !cur.size) watchers.current.delete(jobId);
    };
  }, []);
  const [slideFail, setSlideFail] = useState<SlideFail | null>(null);
  const failAway = useCallback((f: SlideFail) => {
    if (watchers.current.get(f.jobId)?.size) return;
    setSlideFail(f);
  }, []);
  const dropSlideFail = useCallback((m: { jobId?: string | null; gid?: string; strategy?: string }) => {
    setSlideFail((cur) => slideFailAfter(cur, m));
  }, []);

  // работа над вариантами: идёт ли задача над вариантом — по идущим задачам, ревизия — открытой презентации
  const variantLive = useCallback((key: string) => busyKeys(liveJobs.current.values()).includes(key), []);
  const variantRevOf = useCallback((gid: string, strategy: string) => {
    const g = latest.current.generation;
    const v = g && g.id === gid ? g.variants.find((x) => x.strategy === strategy) : null;
    return v ? variantRev(v) : null;
  }, []);
  const { work, fixIssues, revertVariant } = useVariantWork({ runJob, reloadIfOpen, live: variantLive, rev: variantRevOf, deck: generation, staleGid: stale?.gid ?? null });

  const adoptManifest = useCallback((m: TemplateManifest) => {
    setManifest(m); // same batch as the id: the manifest effect sees a match and skips the refetch
    selectTemplate(m.template_id);
  }, [selectTemplate]);

  // «Улучшить готовую»: the deck read back opens «Создать» with its text, plate 02 under the folded plate 01 — when the
  // person is on «Создать». Elsewhere (a deck, a build) the screen stays: the mode waits and opens when they come back
  const improveReady = useCallback((src: ImproveSource) => {
    if (improveArrives(latest.current.ui.screen) === "wait") return void setImproveWait(src);
    setImproveWait(null);
    setImproveSource(src);
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: true } });
  }, []);
  useEffect(() => {
    if (!improveWait || ui.screen !== "create") return;
    setImproveWait(null);
    setImproveSource(improveWait);
    dispatch({ type: "set", patch: { improve: true, open: "text", more: false } });
  }, [improveWait, ui.screen]);

  // the build that ended away is seen: its build screen, or its deck on the result (no section over them). A finished
  // build whose end the person did not see (they were in «Мои презентации» over its build screen, or came back while
  // the list was read) opens now, as it would have at its end — the build screen never stays on a finished build with no
  // way on; left again while it loads — the line on «Создать» comes back
  const openBuiltRef = useRef<(end: BuildEnd) => void>(() => {});
  useEffect(() => {
    if (!buildEnd || !endSeen(buildEnd, ui.screen, buildJob?.id, generationId, ui.sect)) return;
    setBuildEnd(null);
    if (buildEnd.ok && ui.screen === "build") openBuiltRef.current(buildEnd);
  }, [buildEnd, ui.screen, ui.sect, buildJob, generationId]);

  const [analyzing, setAnalyzing] = useState<"template" | "deck" | null>(null);
  const uploadTemplate = useCallback((file: File, useModels: boolean, improve?: boolean, onJob?: (jobId: string) => void) => {
    setAnalyzing(improve ? "deck" : "template");
    return uploadTemplateFlow(file, useModels, { runJob, report, notify, clearNotice, pushMessage, dispatch, setTemplates, adoptManifest, refreshTemplates }, improve ? improveReady : undefined, onJob)
      .finally(() => setAnalyzing(null));
  }, [runJob, report, notify, clearNotice, pushMessage, adoptManifest, improveReady, refreshTemplates]);

  const generationDeps = useMemo<GenerationDeps>(() => ({
    runJob, report, notify, clearNotice, pushMessage, dispatch, refreshGenerations, fetchGeneration: (gid) => fetchGeneration(gid, false, false, "build"), refreshModelStatus,
    titleOf: (name) => titleIn(latest.current.strategies, name),
    watching: (jobId) => watchingBuild(latest.current.ui.screen, latest.current.buildJob?.id, jobId, latest.current.ui.sect),
    endedAway: (gid, job, ok) => setBuildEnd({ gid, job, ok }),
    selectBuilt: (id) => {
      const { templateId: tid, templates: list } = latest.current;
      if (id && id !== tid && list.some((t) => t.template_id === id)) selectTemplate(id);
    },
  }), [runJob, report, notify, clearNotice, pushMessage, refreshGenerations, fetchGeneration, refreshModelStatus, selectTemplate]);

  openBuiltRef.current = (end) => {
    void fetchGeneration(end.gid, false, false, "build").then((g) => {
      const { ui: u, buildJob: shown } = latest.current;
      if (!watchingBuild(u.screen, shown?.id, end.job, u.sect)) return void setBuildEnd(end);
      // the deck did not load: the build-area line and «Открыть ещё раз» (BuildPlate)
      if (!g) return;
      dispatch({ type: "go", screen: "result" });
      generationDeps.selectBuilt(g.template_id);
    });
  };

  const showEnded = useCallback((end: BuildEnd) => {
    const back = endedToShow(latest.current.buildJob, end, (id) => endedBuilds.current.get(id));
    if (back) {
      setBuildJob(back);
      const ask = asks.current.get(end.gid);
      if (ask) keepBuild(ask);
    }
    dispatch({ type: "go", screen: "build" });
  }, [keepBuild]);

  const goBuild = useCallback(() => {
    const next = liveBuildToShow(latest.current.buildJob, [...liveJobs.current.values()]);
    if (next) {
      setBuildJob(next);
      const ask = next.generation ? asks.current.get(next.generation) : undefined;
      if (ask) keepBuild(ask);
    }
    dispatch({ type: "go", screen: "build" });
  }, [keepBuild]);

  const startGeneration = useCallback((req: GenerateRequest, expectedSlides?: number | null) => {
    const expected = expectedSlides ?? null;
    // the request belongs to the deck the server answers with; a refused start leaves the shown build's request as it was
    return generationFlow(req, generationDeps, expected, (gid) => {
      ownRef.current = gid; // before the build is followed: its record goes to LS.build
      setOwnBuild(gid);
      keepBuild({ gid, request: req, expected });
    });
  }, [generationDeps, keepBuild]);

  const retryBuild = useCallback(async (deck?: GenerationMeta | null) => {
    // a deck: its own request (the page's, if it is its build), else from its meta. No deck: the build the build screen
    // shows — its own request, never the request of another build followed since
    const shown = latest.current.buildJob?.generation ?? lastBuild.current?.gid ?? null;
    const last = deck ? askOf(deck, asks.current.get(deck.id) ?? lastBuild.current)
      : askFor(shown, [asks.current.get(shown ?? ""), lastBuild.current, readPendingBuild()]);
    if (!last) return false;
    await startGeneration(last.request, last.expected);
    return true;
  }, [startGeneration]);

  /** A deck still being built (a reload, a running deck opened from the list): its job is followed again — the build
   *  screen shows it from where it is (the job's record brings the agent's whole timeline). */
  const attachBuild = useCallback((g: GenerationMeta, pending?: PendingBuild | null) => {
    if (!g.job_id || liveJobs.current.has(g.job_id)) return;
    const ask = askOf(g, pending ?? readPendingBuild());
    keepBuild(ask);
    followBuild({
      jobId: g.job_id, generation: g.id, strategies: g.strategies, template: g.template_id, slides: g.slides ?? ask.expected,
      startedAt: g.created_at ? g.created_at * 1000 : undefined,
    }, generationDeps);
    dispatch({ type: "go", screen: "build" });
  }, [generationDeps, keepBuild]);
  attachRef.current = attachBuild;

  const followDeck = useCallback((g: GenerationMeta) => {
    if (!g.job_id) return false;
    const live = liveJobs.current.get(g.job_id);
    if (!live) {
      attachBuild(g);
      return true;
    }
    // the page already follows it: the build screen shows this build (another one followed since may be on it) — with
    // its own request (strips 01/02, «Собрать ещё раз»), not the request of the build followed last
    if (live.kind === "generate") {
      setBuildJob((cur) => (cur && cur.id === live.id ? cur : live));
      keepBuild(asks.current.get(g.id) ?? askOf(g, lastBuild.current));
    }
    dispatch({ type: "go", screen: "build" });
    return true;
  }, [attachBuild, keepBuild]);

  const adoptBuildMeta = useCallback((g: GenerationMeta) => {
    const ask = completeAsk(lastBuild.current, g);
    if (ask) keepBuild(ask);
  }, [keepBuild]);

  /** A build that failed while the page was closed: nothing follows its job any more — the build screen shows its
   *  failure (B-failed) from the deck's meta (the reason) and, while the server remembers it, its job's record (the
   *  agent's timeline, where it stopped); «Собрать ещё раз» repeats its request. */
  const showFailedBuild = useCallback((g: GenerationMeta, rec: Job | null, pending: PendingBuild | null) => {
    keepBuild(askOf(g, pending));
    setBuildJob(failedBuildJob(g, rec, (name) => titleIn(latest.current.strategies, name)));
    dispatch({ type: "go", screen: "build" });
  }, [keepBuild]);

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
      // a failure stands where its data is shown: the templates and the variants at the template step, the list of decks
      // in the header of «Мои презентации» (offline: the header's banner tells it)
      if (tp.status === "rejected") report(tp.reason, "Не удалось загрузить шаблоны", "template", true);
      else if (st.status === "rejected") report(st.reason, "Не удалось загрузить варианты оформления", "template", true);
      if (gn.status === "rejected") report(gn.reason, "Не удалось загрузить список презентаций", "history", true);
      if (tp.status === "fulfilled") {
        setTemplates(tp.value);
        const stored = latest.current.templateId; // drop a stale id, fall back to the newest template
        if (!stored || !tp.value.some((t) => t.template_id === stored)) selectTemplate(newestTemplate(tp.value)?.template_id ?? null);
      }
      // a build that ran when the page was left (LS.build), else the newest one running now (the list: started in another
      // tab, or before LS.build was written): followed again while its job runs. The page's own build that ended
      // meanwhile shows its failure on the build screen (failed) or opens on its deck (done); gone — the stored deck or
      // «Создать»
      const pending = readPendingBuild();
      let own: Generation | null = null;
      if (pending) {
        try {
          own = await api.generation(pending.gid);
        } catch {
          own = null;
        }
        if (!alive) return;
      }
      const pick = resumeBuild(pending, own, gn.status === "fulfilled" ? gn.value : []);
      // the stored build is over or gone: its record goes (a build followed again writes it anew)
      if (pending && !(pick?.kind === "attach" && pick.meta.id === pending.gid)) storage.set(LS.build, null);
      let shown = false; // the build screen has a build to show
      if (pick?.kind === "attach") {
        // a deck from the list carries its text cut short: «Собрать ещё раз» takes the request from the deck itself
        let g: GenerationMeta | null = pick.meta;
        if (pick.listed) {
          try {
            g = await api.generation(pick.meta.id);
          } catch {
            g = null;
          }
          if (!alive) return;
        }
        if (g?.status === "running" && g.job_id) {
          attachRef.current(g, pending);
          shown = true;
        }
      } else if (pick?.kind === "failed") {
        let rec: Job | null = null;
        if (pick.meta.job_id) {
          try {
            rec = await api.job(pick.meta.job_id);
          } catch {
            rec = null; // the server restarted since: the deck's meta tells the reason
          }
          if (!alive) return;
        }
        showFailedBuild(pick.meta, rec, pending);
        shown = true;
      } else if (pick?.kind === "done" && (await fetchGeneration(pick.meta.id, true))) {
        if (alive) dispatch({ type: "go", screen: "result" });
        return;
      }
      if (!alive) return;
      if (pending && !shown && latest.current.ui.screen === "build") dispatch({ type: "go", screen: storage.get(LS.generation) ? "result" : "create" });
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
  }, [report, selectTemplate, fetchGeneration, showFailedBuild]);

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
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, cancelLoad, reloadIfOpen, stale, refreshDeck, refreshing, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, ui, dispatch, activeJob, liveJobs: liveList, runJob, watchJob, slideFail, failAway, dropSlideFail, followDeck, adoptBuildMeta, busyVariants, work, fixIssues, revertVariant, buildJob, buildAsk, ownBuild, building, buildEnd, showEnded, goBuild, retryBuild, messages, pushMessage, notices, notify, clearNotice, uploadTemplate, analyzing, startGeneration,
    brief, setBrief, textIssue, setTextIssue, checkText, params, setParams,
    composerText, composerPreset, editText, takeComposerText, takeComposerPreset, improveSource, takeImproveSource,
  }), [
    health, healthError, modelStatus, refreshModelStatus, strategies, strategyTitle, templates, refreshTemplates, deleteTemplate, forgetTemplate, renameTemplate, templateLabel, templateId, selectTemplate, manifest, manifestLoading,
    generations, refreshGenerations, generationId, generation, generationLoading, loadGeneration, cancelLoad, reloadIfOpen, stale, refreshDeck, refreshing, activeStrategy, setActiveStrategy, activeVariant,
    selectedSlide, setSelectedSlide, ui, activeJob, liveList, runJob, watchJob, slideFail, failAway, dropSlideFail, followDeck, adoptBuildMeta, busyVariants, work, fixIssues, revertVariant, buildJob, buildAsk, ownBuild, building, buildEnd, showEnded, goBuild, retryBuild, messages, pushMessage, notices, notify, clearNotice, uploadTemplate, analyzing, startGeneration,
    brief, setBrief, textIssue, checkText, params, setParams,
    composerText, composerPreset, editText, takeComposerText, takeComposerPreset, improveSource, takeImproveSource,
  ]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
