// Thin typed client over the Verstka HTTP API. All URLs are relative (/api/...) so the same build
// works behind the Vite dev proxy and when FastAPI serves web/dist directly.
import type {
  BrandConflict, BrandSpec, ChatResponse, CheckSpec, DatasetSummary, DiffResponse, ExplainResponse, FixRequest, GenerateRequest, GenerateResponse,
  Generation, GenerationMeta, Health, Job, ModelsStatus, PictureChangeRequest, RebuildRequest, SkillsResponse, SlideFixRequest, StrategyInfo, TemplateListItem, TemplateManifest, UploadResponse,
} from "./types";
import { parseManifest, type ExampleManifest } from "./ui/create/dataRules";

/** Разобранный брендбук (итог задачи POST /api/brandbooks и ответ GET /api/brandbooks/{id}): что прочитано и чем он
 *  расходится с шаблоном (`result` расхождения — при «брендбук важнее»). */
export interface BrandbookResult {
  brand: BrandSpec; conflicts: BrandConflict[];
  /** Что не встало при применении к шаблону (брендированная копия), по-русски — если сервер их пришлёт. */
  warnings?: string[];
}
/** Цель брифа, как её поняла сборка (POST /api/goals, verstka/data/intent.py `GoalsRead.payload`). */
export interface ServerGoal {
  quote: string; dataset_id: string | null; file: string | null; sheet?: string | null; task: string; task_title: string;
  viz: string | null; viz_title: string | null; label: string; source?: string; confidence?: number;
}
/** Предложение брифа, на которое данные не отвечают, и почему («в данных нет плана»). */
export interface GoalNote { quote: string; reason: string; dataset_id?: string | null; file?: string | null; source?: string }
export interface GoalsAnswer {
  source: string; model: string | null; cached: boolean; seconds: number; error: string | null; skipped: string | null;
  goals: ServerGoal[]; notes: GoalNote[];
}
/** Пример: манифест и его файлы, уже скачанные (данные — по порядку, брендбук — отдельно). */
export interface ExampleBundle { manifest: ExampleManifest; files: File[]; brandbook: File | null }

/** Файл примера по ссылке манифеста (сервер отдаёт их сам — GET /api/examples/{name}/files/…). */
async function fetchFile(url: string, name: string): Promise<File> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new ApiError(0, `Сеть недоступна: ${(e as Error).message}`);
  }
  if (!res.ok) throw new ApiError(res.status, `Не удалось скачать «${name}»`);
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type });
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, `Сеть недоступна: ${(e as Error).message}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  modelsStatus: () => request<ModelsStatus>("/api/models/status"),
  strategies: () => request<StrategyInfo[]>("/api/strategies"),
  skills: () => request<SkillsResponse>("/api/skills"),
  checks: () => request<CheckSpec[]>("/api/checks"),

  templates: () => request<TemplateListItem[]>("/api/templates"),
  template: (id: string) => request<TemplateManifest>(`/api/templates/${encodeURIComponent(id)}`),
  uploadTemplate: (file: File, useModels = true, improve = false) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("use_models", useModels ? "true" : "false");
    // «Улучшить готовую»: the deck is analysed as the template and read back as the author's text
    if (improve) fd.append("improve", "true");
    return request<UploadResponse>("/api/templates", { method: "POST", body: fd });
  },

  job: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  jobEventsUrl: (id: string) => `/api/jobs/${encodeURIComponent(id)}/events`,

  generations: () => request<GenerationMeta[]>("/api/generations"),
  generation: (gid: string) => request<Generation>(`/api/generations/${encodeURIComponent(gid)}`),
  createGeneration: (req: GenerateRequest) => request<GenerateResponse>("/api/generations", json(req)),
  deleteGeneration: (gid: string) => request<{ deleted: boolean }>(`/api/generations/${encodeURIComponent(gid)}`, { method: "DELETE" }),
  deleteTemplate: (id: string) => request<{ deleted: boolean }>(`/api/templates/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** The slide previews a variant has so far («slide-001.jpg»…): the build asks for these while the export renders them. */
  slideList: (gid: string, strategy: string) => request<{ slides: string[] }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/slides`),
  /** An empty title brings back the file's name. */
  renameTemplate: (id: string, title: string) => request<TemplateListItem>(`/api/templates/${encodeURIComponent(id)}`, json({ title }, "PATCH")),
  explain: (gid: string, strategy: string, index: number) =>
    request<ExplainResponse>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/explain/${index}`),
  fixes: (gid: string, strategy: string, body: FixRequest) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/fixes`, json(body)),
  /** Fixes the remarks of one slide (and follows the person's wishes); only that slide of the deck changes. */
  fixSlide: (gid: string, strategy: string, n: number, body: SlideFixRequest) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/slides/${n}/fix`, json(body)),
  /** «Пересобрать слайд так»: слайд с данными другим вариантом визуализации (`option` — с 0, номер в
   *  `OutlineSlide.data.options`). Ответ — задача; неподходящий вариант — 422 с причиной, файла с данными нет — 409. */
  rebuildSlide: (gid: string, strategy: string, n: number, option: number) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/slides/${n}/rebuild`, json({ option } satisfies RebuildRequest)),
  /** An edit of the variant in words («верни как было» undoes the last change exactly). */
  changePicture: (gid: string, strategy: string, n: number, body: PictureChangeRequest) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/slides/${n}/image`, json(body)),
  editVariant: (gid: string, strategy: string, body: { message: string; slide?: number | null }) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/edits`, json(body)),
  diff: (gid: string, strategy: string, other: string, otherStrategy: string) =>
    request<DiffResponse>(
      `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/diff/${encodeURIComponent(other)}/${encodeURIComponent(otherStrategy)}`,
    ),
  fileUrl: (gid: string, strategy: string, name: string) =>
    `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/files/${name}`,

  // ── вторая ступень: файлы с данными и брендбук (§6 описания решения)
  /** Файлы с данными: чтение и профиль синхронно, по карточке на таблицу (у книги XLSX — на лист). */
  uploadDatasets: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    return request<DatasetSummary[]>("/api/datasets", { method: "POST", body: fd });
  },
  /** «Цели из текста» так, как их поймёт сборка: цели брифа над приложенными наборами и предложения без ответа в данных. */
  goals: (body: { brief: string; dataset_ids: string[]; use_models: boolean }, signal?: AbortSignal) =>
    request<GoalsAnswer>("/api/goals", { ...json(body), signal }),
  /** Набор по id (карточка «Изменить текст» презентации): поля карточки (`DatasetSummary`) и полный профиль. */
  getDataset: (id: string) => request<DatasetSummary & { profile?: unknown; plan?: unknown }>(`/api/datasets/${encodeURIComponent(id)}`),
  deleteDataset: (id: string) => request<{ deleted: boolean }>(`/api/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** Брендбук: файл (PDF, токены JSON, архив .zip), папка (файлы с путями) или ссылка Figma. Разбор — задачей (её
   *  события — шаги: open · palette · fonts · logos · rules · compare); `template_id` — с чем сверять. */
  uploadBrandbook: (src: File | File[] | { figmaUrl: string }, templateId?: string | null, useModels = true, priority: "brand" | "template" = "brand") => {
    const fd = new FormData();
    if (Array.isArray(src)) for (const f of src) fd.append("files", f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    else if ("figmaUrl" in src) fd.append("figma_url", src.figmaUrl.trim());
    else fd.append("file", src, src.name);
    if (templateId) fd.append("template_id", templateId);
    // «Модель пишет тексты» выключен — PDF читается без модели зрения (по тексту); расхождения — для выбранного приоритета
    fd.append("use_models", useModels ? "true" : "false");
    fd.append("brand_priority", priority);
    return request<{ job_id: string; brandbook_id: string }>("/api/brandbooks", { method: "POST", body: fd });
  },
  /** Брендбук и его расхождения с шаблоном `templateId` (другой шаблон — свои расхождения). */
  getBrandbook: (id: string, templateId?: string | null, priority?: "brand" | "template") => {
    const q = new URLSearchParams();
    if (templateId) q.set("template_id", templateId);
    // `result` расхождений — что получит колода с этим приоритетом (app.py `get_brandbook`, 5832003)
    if (priority) q.set("brand_priority", priority);
    const qs = q.toString();
    return request<BrandbookResult>(`/api/brandbooks/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`);
  },
  deleteBrandbook: (id: string) => request<{ deleted: boolean }>(`/api/brandbooks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** Файл брендбука (логотип): путь — как в `BrandLogo.file`. */
  brandbookFileUrl: (id: string, path: string) => `/api/brandbooks/${encodeURIComponent(id)}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
  /** Пример («данные продаж», «брендбук VK Cloud»): GET /api/examples/{name} — манифест ссылок, файлы скачиваются,
   *  чтобы уйти на сервер тем же путём, что свои (POST /api/datasets, POST /api/brandbooks). */
  loadExample: async (name: string): Promise<ExampleBundle> => {
    const manifest = parseManifest(await request<unknown>(`/api/examples/${encodeURIComponent(name)}`), name);
    const [files, brandbook] = await Promise.all([
      Promise.all(manifest.files.map((f) => fetchFile(f.url, f.name))),
      manifest.brandbook ? fetchFile(manifest.brandbook.url, manifest.brandbook.name) : Promise.resolve(null),
    ]);
    return { manifest, files, brandbook };
  },

  chat: (body: { session_id: string; message: string; template_id?: string | null; generation_id?: string | null; strategy?: string | null; slide?: number | null }) =>
    request<ChatResponse>("/api/chat", json(body)),
};
