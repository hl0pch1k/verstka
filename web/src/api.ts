// Thin typed client over the Verstka HTTP API. All URLs are relative (/api/...) so the same build
// works behind the Vite dev proxy and when FastAPI serves web/dist directly.
import type {
  ChatResponse, CheckSpec, DiffResponse, ExplainResponse, FixRequest, GenerateRequest, GenerateResponse,
  Generation, GenerationMeta, Health, Job, SkillsResponse, StrategyInfo, TemplateListItem, TemplateManifest, UploadResponse,
} from "./types";

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
  strategies: () => request<StrategyInfo[]>("/api/strategies"),
  skills: () => request<SkillsResponse>("/api/skills"),
  checks: () => request<CheckSpec[]>("/api/checks"),

  templates: () => request<TemplateListItem[]>("/api/templates"),
  template: (id: string) => request<TemplateManifest>(`/api/templates/${encodeURIComponent(id)}`),
  uploadTemplate: (file: File, useModels = true) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("use_models", useModels ? "true" : "false");
    return request<UploadResponse>("/api/templates", { method: "POST", body: fd });
  },

  job: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  jobEventsUrl: (id: string) => `/api/jobs/${encodeURIComponent(id)}/events`,

  generations: () => request<GenerationMeta[]>("/api/generations"),
  generation: (gid: string) => request<Generation>(`/api/generations/${encodeURIComponent(gid)}`),
  createGeneration: (req: GenerateRequest) => request<GenerateResponse>("/api/generations", json(req)),
  deleteGeneration: (gid: string) => request<{ deleted: boolean }>(`/api/generations/${encodeURIComponent(gid)}`, { method: "DELETE" }),
  explain: (gid: string, strategy: string, index: number) =>
    request<ExplainResponse>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/explain/${index}`),
  fixes: (gid: string, strategy: string, body: FixRequest) =>
    request<{ job_id: string }>(`/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/fixes`, json(body)),
  diff: (gid: string, strategy: string, other: string, otherStrategy: string) =>
    request<DiffResponse>(
      `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/diff/${encodeURIComponent(other)}/${encodeURIComponent(otherStrategy)}`,
    ),
  fileUrl: (gid: string, strategy: string, name: string) =>
    `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(strategy)}/files/${name}`,

  chat: (body: { session_id: string; message: string; template_id?: string | null; generation_id?: string | null }) =>
    request<ChatResponse>("/api/chat", json(body)),
};
