// Сборка после перезагрузки страницы. Чистые функции, без React: что лежит в localStorage (LS.build), к какой сборке
// страница возвращается (идущая — снова следить за ней, упавшая без страницы — её неудача на экране «Сборка», законченная
// — её презентация), с каким запросом «Собрать ещё раз» её повторяет и как выглядит сборка, которая остановилась, пока
// страницы не было (её задачу уже никто не ведёт — store собирает её вид здесь).
import { foldJobEvent, type ActiveJob } from "../../lib/jobState";
import { firstLine } from "../../lib/narrate";
import type { GenerateRequest, GenerationMeta, ImprovedFrom, Job } from "../../types";

/** Запрос сборки и её генерация: «Собрать ещё раз» повторяет именно его. `expected` — число слайдов, которое экран
 *  прочёл в тексте (заглушки раскадровки), на сервер не уходит. Так же лежит в localStorage (LS.build). */
export interface PendingBuild { gid: string; request: GenerateRequest; expected: number | null }

/** LS.build: запрос идущей сборки; null — записи нет или она испорчена. */
export function parsePendingBuild(raw: string | null | undefined): PendingBuild | null {
  try {
    const v = JSON.parse(raw || "null") as Partial<PendingBuild> | null;
    if (!v || typeof v.gid !== "string" || !v.request || typeof v.request.template_id !== "string") return null;
    return { gid: v.gid, request: v.request, expected: typeof v.expected === "number" ? v.expected : null };
  } catch {
    return null;
  }
}

/** Запрос `last` годится для LS.build генерации `gid`, только если это её запрос: запрос другой сборки (страница
 *  успела присоединиться к чужой, пока свою ещё не приняли) к ней не пристаёт. */
export function pendingFor(last: PendingBuild | null, gid: string | null | undefined): PendingBuild | null {
  return last && gid && last.gid === gid ? { gid, request: last.request, expected: last.expected } : null;
}

/** Запрос сборки `gid` среди известных странице (`known`: свой, из LS.build, собранные из меты при подключении) —
 *  только именно её; null — его нет: «Собрать ещё раз» не повторит запрос другой сборки. */
export function askFor(gid: string | null | undefined, known: (PendingBuild | null | undefined)[]): PendingBuild | null {
  if (!gid) return null;
  return known.find((p): p is PendingBuild => !!p && p.gid === gid) ?? null;
}

/** «Вернуться к тексту» на экране «Сборка» (B-failed): у своей сборки страницы (`own`) — черновик поля «Создать»; у
 *  чужой, к которой подключились (другая вкладка, помощник), — её собственный текст и параметры (`ask` — запрос
 *  показанной сборки `shown`). null — к черновику: своя сборка или запрос показанной неизвестен. */
export function backToText(ask: PendingBuild | null, own: string | null, shown: string | null | undefined): { brief: string; preset: AskPreset } | null {
  if (!ask || !shown || ask.gid !== shown || ask.gid === own || !ask.request.brief.trim()) return null;
  const r = ask.request;
  return {
    brief: r.brief,
    preset: {
      audience: r.audience ?? null, purpose: r.purpose ?? null, slides: r.slides ?? null, useModels: r.use_models, eyes: r.eyes ?? null,
      pictures: r.pictures ?? null, strategies: r.strategies, improvedFrom: r.improved_from ?? null,
      ...(r.eyes === undefined || r.eyes === null ? { auditModels: r.audit_models } : {}),
    },
  };
}
/** Параметры «Создать» из запроса сборки (store `ComposerPreset`). */
export interface AskPreset {
  audience: string | null; purpose: string | null; slides: number | null; useModels: boolean; eyes: boolean | null; pictures: boolean | null;
  strategies: string[]; improvedFrom: ImprovedFrom | null; auditModels?: boolean;
}

/** Запрос презентации по её мете — сборка найдена без своего запроса (начата не с этой страницы). Мета идущей сборки
 *  ещё без `use_models`: модель включена, сервер сам выключит её, если модели нет. Мета из списка (`/api/generations`)
 *  несёт текст обрезанным — запрос берётся из меты самой презентации. */
export function requestOf(g: GenerationMeta): GenerateRequest {
  return {
    template_id: g.template_id, brief: g.brief ?? "", audience: g.audience ?? null, purpose: g.purpose ?? null, slides: g.slides ?? null,
    language: g.language, extra_instructions: g.extra_instructions ?? null, strategies: g.strategies,
    use_models: g.use_models ?? true, audit_models: !!g.audit_models, autofix: g.autofix ?? true, exports: g.exports ?? ["pdf", "html"],
    pictures: g.pictures ?? null, eyes: g.eyes ?? null, improved_from: g.improved_from ?? null,
  };
}

/** Полная мета сборки прочиталась позже (помощник начал сборку, а первое чтение меты не удалось — экран вёл её по
 *  задаче из ответа, с запросом-заглушкой без темы и вариантов): запрос сборки — полоса 02 и «Собрать ещё раз» — из
 *  этой меты. Только если на экране запрос этой же сборки и он неполный (без вариантов); иначе null — менять нечего. */
export function completeAsk(ask: PendingBuild | null, g: GenerationMeta): PendingBuild | null {
  if (!ask || ask.gid !== g.id || ask.request.strategies.length) return null;
  return { gid: g.id, request: requestOf(g), expected: g.slides ?? ask.expected };
}

/** О чём говорят полосы 01/02 экрана «Сборка»: шаблон (`template`, `templateFile` — имя файла шаблона, которого нет в
 *  библиотеке) и тема (`brief`) самой сборки, «Улучшить готовую» (`improved`), пишет ли текст агент (`useModels`). */
export interface BuildTopic { template: string | null; templateFile: string | null; brief: string | null; useModels: boolean; improved: ImprovedFrom | null }

/** Тема и шаблон сборки на экране «Сборка» (`job`): её запрос (`ask` — свой запрос страницы или собранный из меты
 *  при подключении), только если он этой сборки; иначе — мета её презентации (`decks`: открытая и список), шаблон — из
 *  задачи. До того, как задача найдена (перезагрузка во время сборки), — запрос из LS.build. Черновик поля «Создать»
 *  сюда не попадает: подключились к чужой сборке — полосы о ней. Ни запроса, ни меты — тема неизвестна (null), а не
 *  «Тема ещё не задана». null — говорить не о чем. */
export function buildTopic(
  job: { generation?: string | null; template?: string | null } | null, ask: PendingBuild | null, decks: (GenerationMeta | null)[],
): BuildTopic | null {
  const gid = job ? job.generation ?? null : ask?.gid ?? null;
  const own = ask && gid && ask.gid === gid ? ask.request : null;
  const deck = gid ? decks.find((g) => g?.id === gid) ?? null : null;
  const req = own ?? (deck ? requestOf(deck) : null);
  const template = job?.template ?? req?.template_id ?? null;
  if (!req && !template) return null;
  return {
    template, templateFile: deck?.template_file ?? null, brief: req ? req.brief : null, useModels: req?.use_models ?? true,
    improved: req?.improved_from ?? null,
  };
}

/** К чему вернуться при загрузке: `attach` — сборка идёт (снова следить), `failed` — сборка из LS.build упала, пока
 *  страницы не было (её неудача), `done` — она кончилась (её презентация). `listed` — мета из списка: текст в ней
 *  обрезан, за полной мета спрашивается отдельно. */
export interface Resume { kind: "attach" | "failed" | "done"; meta: GenerationMeta; listed: boolean }

/** Сборка идёт и у неё есть задача — за ней можно следить. */
const followable = (g: GenerationMeta | null | undefined): boolean => !!g && g.status === "running" && !!g.job_id;

/** Сначала — сборка из LS.build (`pending`, её мета `pendingMeta` спрошена отдельно; не спросилась — ищется в списке):
 *  идёт — `attach`, упала — `failed`, кончилась — `done`. Её нет (удалена) или записи нет — самая новая идущая сборка
 *  из списка, у которой есть задача (начата в другой вкладке или до того, как запись легла). Чужая неудача из списка
 *  на экран не встаёт: её уже видели там, где она случилась. null — возвращаться не к чему. */
export function resumeBuild(pending: PendingBuild | null, pendingMeta: GenerationMeta | null, list: GenerationMeta[]): Resume | null {
  if (pending) {
    const listed = !pendingMeta;
    const own = pendingMeta ?? list.find((g) => g.id === pending.gid) ?? null;
    if (own && followable(own)) return { kind: "attach", meta: own, listed };
    if (own?.status === "failed") return { kind: "failed", meta: own, listed };
    if (own?.status === "done") return { kind: "done", meta: own, listed };
  }
  const running = list.filter(followable).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
  return running ? { kind: "attach", meta: running, listed: true } : null;
}

/** Сборка, которая остановилась, пока страницы не было, как её показывает экран «Сборка» (B-failed): причина — из меты
 *  (`error`), начало — `created_at`. Запись её задачи (`rec`, пока сервер её помнит) приносит ленту агента — где
 *  остановилась — и конец; без неё конец неизвестен (`endedAt: null` — часы ставят прочерк). */
export function failedBuildJob(g: GenerationMeta, rec: Job | null, titleOf: (name: string) => string): ActiveJob {
  const own = rec && g.job_id && rec.id === g.job_id ? rec : null;
  let job: ActiveJob = {
    id: g.job_id ?? `failed-${g.id}`, label: "Собираю презентацию", progress: 0, message: "", status: "running", kind: "generate",
    startedAt: (g.created_at ?? own?.created_at ?? 0) * 1000, items: g.strategies, template: g.template_id, generation: g.id, slides: g.slides ?? null,
  };
  for (const ev of own?.agent ?? []) if (ev.status !== "done" && ev.status !== "failed") job = foldJobEvent(job, ev, titleOf);
  const why = g.error ?? own?.error ?? null;
  return {
    ...job,
    status: "failed",
    progress: Math.max(job.progress, own?.progress ?? 0),
    message: why ? firstLine(why, "") : "",
    endedAt: own?.finished_at ? own.finished_at * 1000 : null,
  };
}
