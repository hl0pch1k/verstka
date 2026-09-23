// Multi-step user flows of the app store (upload → analyse → adopt, generate → load → narrate).
// Kept outside store.tsx so the store stays a readable list of state and actions. Both promises always
// resolve: failures are reported through toasts / assistant messages, never thrown at the caller.
import { api } from "../api";
import { pushToast } from "../components/ui/Toasts";
import type { GenerateRequest, GenerateResponse, Generation, Job, JobKind, TabKey, TemplateListItem, TemplateManifest, UploadResponse } from "../types";
import { describeGeneration, firstLine, newestTemplate } from "./narrate";
import { plural } from "./utils";

interface CommonDeps {
  runJob(jobId: string, label: string, opts?: { kind?: JobKind; items?: string[]; onDone?: (job: Job) => void; onFailed?: (job: Job) => void }): void;
  report(e: unknown, prefix: string): void;
  pushMessage(role: "user" | "assistant", text: string): void;
  setTab(t: TabKey): void;
}

export interface UploadDeps extends CommonDeps {
  setTemplates(list: TemplateListItem[]): void;
  /** Puts the manifest into the state and selects its template in one batch. */
  adoptManifest(m: TemplateManifest): void;
}

export function uploadTemplateFlow(file: File, useModels: boolean, d: UploadDeps): Promise<void> {
  return new Promise<void>((resolve) => {
    void (async () => {
      if (!/\.pptx$/i.test(file.name)) {
        pushToast("error", "Шаблон должен быть файлом .pptx");
        return resolve();
      }
      let res: UploadResponse;
      try {
        res = await api.uploadTemplate(file, useModels);
      } catch (e) {
        d.report(e, "Не удалось загрузить шаблон");
        return resolve();
      }
      if (useModels && !res.use_models) pushToast("info", "Модели не настроены — шаблон разбирается эвристиками");
      d.runJob(res.job_id, `Разбираю шаблон «${file.name}»`, {
        kind: "analyze",
        onDone: async (job) => {
          try {
            const list = await api.templates();
            d.setTemplates(list);
            const fromJob = (job.result as { template_id?: string } | null)?.template_id;
            const tid = fromJob ?? list.find((t) => t.source_file === file.name)?.template_id ?? newestTemplate(list)?.template_id;
            if (!tid) throw new Error("сервер не вернул идентификатор шаблона");
            const m = await api.template(tid);
            d.adoptManifest(m);
            const fallback = `Шаблон «${m.source_file}» разобран: ${plural(m.patterns.length, "макет", "макета", "макетов")} из ${plural(m.n_slides, "слайда", "слайдов", "слайдов")}.`;
            d.pushMessage("assistant", m.narration || fallback);
            pushToast("success", "Шаблон разобран");
          } catch (e) {
            d.report(e, "Шаблон разобран, но не загрузился");
          }
          resolve();
        },
        onFailed: (job) => {
          d.pushMessage("assistant", `Не получилось разобрать «${file.name}»: ${firstLine(job.error ?? job.message)}`);
          resolve();
        },
      });
    })();
  });
}

export interface GenerationDeps extends CommonDeps {
  refreshGenerations(): Promise<void>;
  fetchGeneration(gid: string): Promise<Generation | null>;
  titleOf(strategy: string): string;
}

export function generationFlow(req: GenerateRequest, d: GenerationDeps): Promise<void> {
  return new Promise<void>((resolve) => {
    void (async () => {
      let res: GenerateResponse;
      try {
        res = await api.createGeneration(req);
      } catch (e) {
        d.report(e, "Не удалось начать сборку презентации");
        return resolve();
      }
      d.setTab("variants"); // the result screen shows the build while the job runs
      d.runJob(res.job_id, `Собираю ${plural(req.strategies.length, "вариант", "варианта", "вариантов")}`, {
        kind: "generate",
        items: req.strategies,
        onDone: async () => {
          await d.refreshGenerations();
          const g = await d.fetchGeneration(res.generation_id);
          if (g) {
            d.setTab("variants");
            d.pushMessage("assistant", describeGeneration(g, d.titleOf));
            pushToast("success", "Презентация готова");
          }
          resolve();
        },
        onFailed: (job) => {
          d.pushMessage("assistant", `Не получилось собрать презентацию: ${firstLine(job.error ?? job.message)}`);
          void d.refreshGenerations();
          resolve();
        },
      });
    })();
  });
}
