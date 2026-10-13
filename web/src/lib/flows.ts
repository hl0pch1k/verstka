// Multi-step user flows of the app store (upload → analyse → adopt, generate → load → narrate).
// Kept outside store.tsx so the store stays a readable list of state and actions. Both promises always
// resolve: failures are reported through the store's status lines (`notify`, by area) and the helper's messages, never
// thrown at the caller.
import { api } from "../api";
import type { GenerateRequest, GenerateResponse, Generation, ImproveSource, Job, JobKind, Notice, NoticeArea, TemplateListItem, TemplateManifest, UploadResponse } from "../types";
import type { UiAction } from "../ui/deck/geometry";
import { humanError } from "./errors";
import { describeGeneration, newestTemplate } from "./narrate";
import { templateTitle } from "./plain";
import { templateFileProblem } from "./templateFiles";
import { plural } from "./utils";

interface CommonDeps {
  /** `area`: where the job's failure is told (by default — by its kind). */
  runJob(jobId: string, label: string, opts?: { kind?: JobKind; items?: string[]; template?: string | null; generation?: string | null; slides?: number | null; startedAt?: number; area?: NoticeArea; onDone?: (job: Job) => void; onFailed?: (job: Job) => void }): void;
  report(e: unknown, prefix: string, area: NoticeArea): void;
  /** The status line of an area, next to the action (no pop-ups): a failure or a remark about it. */
  notify(area: NoticeArea, kind: Notice["kind"], text: string): void;
  /** An action that starts again drops its area's old line. */
  clearNotice(area: NoticeArea): void;
  pushMessage(role: "user" | "assistant", text: string): void;
  /** Screen changes (`ui/deck/geometry.ts`). */
  dispatch(a: UiAction): void;
}

export interface UploadDeps extends CommonDeps {
  setTemplates(list: TemplateListItem[]): void;
  /** The template list read again (a failure is told in the template area). */
  refreshTemplates(): Promise<void>;
  /** Puts the manifest into the state and selects its template in one batch. */
  adoptManifest(m: TemplateManifest): void;
}

/** `improve`: «Улучшить готовую» — the deck is read back as text; its lines stand at the text step, not the template's.
 *  `onJob`: the server took the file — the job that analyses it (the analysis box follows its own job, not the newest).
 *  A failed read that still added the deck as a template («…она добавлена как шаблон») refreshes the template list. */
export function uploadTemplateFlow(file: File, useModels: boolean, d: UploadDeps, improve?: (src: ImproveSource) => void, onJob?: (jobId: string) => void): Promise<void> {
  const area: NoticeArea = improve ? "text" : "template";
  return new Promise<void>((resolve) => {
    void (async () => {
      d.clearNotice(area);
      const problem = templateFileProblem(file.name);
      if (problem) {
        d.notify(area, "error", problem);
        return resolve();
      }
      let res: UploadResponse;
      try {
        res = await api.uploadTemplate(file, useModels, !!improve);
      } catch (e) {
        d.report(e, "Не удалось загрузить шаблон", area);
        return resolve();
      }
      if (useModels && !res.use_models) d.notify(area, "info", improve ? "Модель не подключена — прочитаю презентацию по правилам" : "Модель не подключена — разберу шаблон по правилам");
      onJob?.(res.job_id);
      d.runJob(res.job_id, improve ? `Читаю презентацию «${templateTitle(file.name)}»` : `Разбираю шаблон «${templateTitle(file.name)}»`, {
        kind: "analyze",
        area,
        onDone: async (job) => {
          try {
            const list = await api.templates();
            d.setTemplates(list);
            const fromJob = (job.result as { template_id?: string } | null)?.template_id;
            const tid = fromJob ?? list.find((t) => t.source_file === file.name)?.template_id ?? newestTemplate(list)?.template_id;
            if (!tid) throw new Error("сервер не вернул идентификатор шаблона");
            const m = await api.template(tid);
            d.adoptManifest(m);
            const src = (job.result as { improve?: ImproveSource } | null)?.improve;
            // no «прочитана» / «разобран» line: the text step and the template step show the result themselves
            if (improve && src) {
              improve(src);
              d.pushMessage("assistant", improveMessage(src, res.use_models));
            } else {
              const fallback = `Шаблон «${templateTitle(m.source_file)}» разобран: ${plural(m.patterns.length, "макет", "макета", "макетов")} из ${plural(m.n_slides, "слайда", "слайдов", "слайдов")}.`;
              d.pushMessage("assistant", m.narration || fallback);
            }
          } catch (e) {
            d.report(e, "Шаблон разобран, но не загрузился", area);
          }
          resolve();
        },
        onFailed: (job) => {
          d.pushMessage("assistant", failMessage(`Не получилось разобрать «${templateTitle(file.name)}»`, job));
          // презентацию не прочитали как текст, но могли добавить шаблоном («…она добавлена как шаблон»): шаг 01 видит её сразу
          if (improve) void d.refreshTemplates();
          resolve();
        },
      });
    })();
  });
}

/** The helper's line about a failed job: the job's reason in Russian, without its technical tail (`humanError`:
 *  «Модель не ответила: ProviderError: 503» → «модель не ответила»); no Russian left — the lead alone. */
export function failMessage(lead: string, job: Pick<Job, "error" | "message">): string {
  const why = humanError(job.error ?? job.message, "");
  return why ? `${lead}: ${why[0].toLowerCase()}${why.slice(1)}` : `${lead}.`;
}

/** The helper's line after «Улучшить готовую»: what the deck holds and what its own audit found; the model's look at
 *  the new slides is promised only when a model is connected. */
export function improveMessage(src: ImproveSource, modelOn = true): string {
  const held = [
    src.slides ? plural(src.slides, "слайд", "слайда", "слайдов") : null,
    src.tables ? plural(src.tables, "таблица", "таблицы", "таблиц") : null,
    src.charts ? plural(src.charts, "диаграмма", "диаграммы", "диаграмм") : null,
    src.pictures ? plural(src.pictures, "изображение", "изображения", "изображений") : null,
  ].filter(Boolean).join(", ");
  const audit = src.audit
    ? ` Проверка исходной презентации: оценка ${src.audit.score}${src.audit.errors || src.audit.warnings ? ` — ${[src.audit.errors ? plural(src.audit.errors, "ошибка", "ошибки", "ошибок") : null, src.audit.warnings ? plural(src.audit.warnings, "предупреждение", "предупреждения", "предупреждений") : null].filter(Boolean).join(", ")}` : ", замечаний нет"}.`
    : "";
  const probs = src.problems ?? [];
  const wrong = probs.length
    ? ` Что не так в ней, на взгляд дизайнера: ${probs.slice(0, 4).map((p) => `слайд ${p.slide} — ${p.text}`).join("; ")}${probs.length > 4 ? ` и ещё ${plural(probs.length - 4, "замечание", "замечания", "замечаний")}` : ""}.`
    : "";
  return `Прочитал «${templateTitle(src.name)}»${held ? `: ${held}` : ""}.${audit}${wrong} Текст — в поле «Текст», оформление — из самой презентации: соберу вёрстку заново${modelOn ? ", а модель посмотрит на каждый новый слайд" : ""}.`;
}

export interface GenerationDeps extends CommonDeps {
  refreshGenerations(): Promise<void>;
  /** Loads the built deck; a failure is told on the build screen (the person is still there). */
  fetchGeneration(gid: string): Promise<Generation | null>;
  /** The model indicator follows every generation: it may have found the host congested or back. */
  refreshModelStatus(): Promise<void>;
  titleOf(strategy: string): string;
  /** The person is on this build's screen now (`watchingBuild`): only then does its end move the screen. */
  watching(jobId: string): boolean;
  /** The build ended while the person was elsewhere: nothing moves — «Создать» tells it with a line («Сборка готова ·
   *  Открыть», «Сборка не удалась · Посмотреть»), the history card leads to it. */
  endedAway(gid: string, jobId: string, ok: boolean): void;
  /** The finished build's template becomes the one of «Создать» (a followed build — another tab's, the helper's). */
  selectBuilt(templateId: string | null | undefined): void;
}

/** Is the person watching build `jobId`: on the build screen, nothing over it (`sect` — «Мои презентации» or «Шаблоны»
 *  covers the screen: the person is busy there), and the screen shows this build (not another one followed since). A
 *  build's end moves the screen only then — elsewhere work in the background never takes the screen over, and a
 *  finished build never closes a layer under the cursor. */
export const watchingBuild = (screen: string, shownJob: string | null | undefined, jobId: string, sect: string | null = null): boolean =>
  screen === "build" && !sect && shownJob === jobId;

/** The build that ended away (`endedAway`) is seen: the person is on its build screen, or its deck is open on the
 *  result — with no section over it. Then «Создать» no longer tells it; a finished build seen on its build screen opens
 *  as it would have at its end (store). */
export const endSeen = (end: { gid: string; job: string }, screen: string, shownJob: string | null | undefined, openDeck: string | null, sect: string | null = null): boolean =>
  !sect && ((screen === "build" && shownJob === end.job) || (screen === "result" && openDeck === end.gid));

/** «Посмотреть» of a build that ended away: the build the build screen must show — the ended one, kept aside when the
 *  screen has followed another build since (`kept`); null — the screen already shows it (or it is not kept). */
export function endedToShow<J extends { id: string }>(shown: J | null | undefined, end: { job: string }, kept: (jobId: string) => J | undefined): J | null {
  if (shown?.id === end.job) return null;
  return kept(end.job) ?? null;
}

/** «Улучшить готовую»: the deck read back opens «Создать» only when the person is there; elsewhere the mode waits
 *  (`wait`) and opens when they come back — background work never takes the screen over. */
export const improveArrives = (screen: string): "open" | "wait" => (screen === "create" ? "open" : "wait");

/** A build to follow: its job, the deck it builds, the variants and the slide count asked for (the storyboard's
 *  first cards), and when it began (a build found again after a reload keeps its own clock). */
export interface BuildTarget { jobId: string; generation: string; strategies: string[]; template: string | null; slides: number | null; startedAt?: number }

/** Follows a build job to its end. On its build screen a finished build opens on the result (its template becomes the
 *  one of «Создать»), a failed one stays on the build screen (its «Не получилось» reads the build's status line). Ended
 *  while the person was elsewhere (another screen, another deck, another build, a section over the build screen), it
 *  moves nothing: the list is refreshed and «Создать» tells the outcome (`endedAway`; back on its build screen, the store
 *  opens it). Whether the person watches is asked again after every wait — they may have left meanwhile. `ended` is
 *  called once the job has ended either way. */
export function followBuild(t: BuildTarget, d: GenerationDeps, ended?: () => void): void {
  d.runJob(t.jobId, "Собираю презентацию", {
    kind: "generate",
    area: "build",
    items: t.strategies,
    template: t.template,
    generation: t.generation,
    slides: t.slides,
    startedAt: t.startedAt,
    onDone: async () => {
      void d.refreshModelStatus();
      const away = () => {
        d.endedAway(t.generation, t.jobId, true);
        ended?.();
      };
      if (!d.watching(t.jobId)) {
        // «Создать» tells the outcome at once, the list follows
        d.endedAway(t.generation, t.jobId, true);
        await d.refreshGenerations();
        return ended?.();
      }
      await d.refreshGenerations();
      // left while the list was read (another screen, «Мои презентации» over the build): nothing is loaded — the open
      // deck and a deck being opened stay as they are
      if (!d.watching(t.jobId)) return away();
      const g = await d.fetchGeneration(t.generation);
      // no «Презентация готова» line: the result opens by itself — if the person is still on the build's screen (left it
      // while the deck loaded — «Создать» tells it is ready). The deck did not load: on the build screen its line and
      // «Открыть ещё раз» (BuildPlate); left meanwhile — «Сборка готова · Открыть» on «Создать»
      if (g && d.watching(t.jobId)) {
        d.dispatch({ type: "go", screen: "result" });
        d.selectBuilt(g.template_id);
        d.pushMessage("assistant", describeGeneration(g, d.titleOf));
      } else if (!d.watching(t.jobId)) d.endedAway(t.generation, t.jobId, true);
      ended?.();
    },
    onFailed: (job) => {
      if (!d.watching(t.jobId)) d.endedAway(t.generation, t.jobId, false);
      d.pushMessage("assistant", failMessage("Не получилось собрать презентацию", job));
      void d.refreshGenerations();
      void d.refreshModelStatus();
      ended?.();
    },
  });
}

/** `expected`: the slide count the screen read in the text (the build screen's placeholders), never sent.
 *  `started`: the server took the request — the deck it builds (the caller ties the request to it: «Собрать ещё раз»
 *  and LS.build), called before the build is followed.
 *  The build screen stands while the job runs (followBuild). The helper stays as it is: it narrows every screen. */
export function generationFlow(req: GenerateRequest, d: GenerationDeps, expected: number | null = null, started?: (gid: string) => void): Promise<void> {
  return new Promise<void>((resolve) => {
    void (async () => {
      d.clearNotice("build");
      let res: GenerateResponse;
      try {
        res = await api.createGeneration(req);
      } catch (e) {
        d.report(e, "Не удалось начать сборку презентации", "build");
        return resolve();
      }
      started?.(res.generation_id);
      d.dispatch({ type: "go", screen: "build" });
      followBuild({ jobId: res.job_id, generation: res.generation_id, strategies: req.strategies, template: req.template_id, slides: req.slides ?? expected }, d, resolve);
    })();
  });
}
