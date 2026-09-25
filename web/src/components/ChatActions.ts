// Side effects of the agent's replies: tracks the jobs the agent has started and narrates their results back into the chat.
import { useCallback, useRef } from "react";
import { api } from "../api";
import { describeGeneration, errText, firstLine } from "../lib/narrate";
import { plural } from "../lib/utils";
import { useApp, type AppState } from "../store";
import type { ChatResponse, FixResult, Generation, TabKey } from "../types";

const TABS: readonly TabKey[] = ["template", "brief", "plan", "variants", "why", "audit", "export", "run", "agent"];
const asTab = (name: string): TabKey | null => TABS.find((t) => t === name) ?? null;

interface FixOutcome { strategy: string; before: number | null; done: boolean; result: FixResult | null; error: string | null }

/** The job result arrives as `unknown`: accept it only when it really looks like a FixResult. */
function asFixResult(value: unknown): FixResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Partial<FixResult>;
  if (typeof r.score !== "number") return null;
  return { score: r.score, errors: Number(r.errors ?? 0), warnings: Number(r.warnings ?? 0), applied: Array.isArray(r.applied) ? r.applied : [] };
}

function describeFixes(list: FixOutcome[], title: (name: string) => string): string {
  const okCount = list.filter((o) => o.done).length;
  const rows = list.map((o) => {
    if (!o.done) return `• ${title(o.strategy)} — не получилось: ${o.error ?? "неизвестная ошибка"}`;
    if (!o.result) return `• ${title(o.strategy)} — исправления применены`;
    const after = Math.round(o.result.score);
    const before = o.before === null ? null : Math.round(o.before);
    const parts = [before !== null && before !== after ? `оценка ${before} → ${after}` : `оценка ${after}`];
    parts.push(o.result.errors === 0 ? "без ошибок" : plural(o.result.errors, "ошибка", "ошибки", "ошибок"));
    if (o.result.warnings) parts.push(plural(o.result.warnings, "предупреждение", "предупреждения", "предупреждений"));
    return `• ${title(o.strategy)} — ${parts.join(", ")}`;
  });
  const head =
    okCount === list.length ? `Исправления готовы: ${list.length === 1 ? "вариант обновлён" : `${plural(list.length, "вариант", "варианта", "вариантов")} обновлены`}.`
    : okCount > 0 ? `Исправлено ${okCount} из ${list.length} вариантов.`
    : "Исправить автоматически не получилось.";
  const tail = okCount > 0 ? "Слайды и файлы пересобраны, оставшиеся замечания — в «Проверке качества»." : "Попробуйте исправить замечания по одному в «Проверке качества».";
  return [head, ...rows, tail].join("\n");
}

function trackGeneration(app: () => AppState, jobId: string, gid: string) {
  app().setTab("variants"); // the result screen shows the build while the job runs
  app().runJob(jobId, "Собираю презентацию", {
    kind: "generate",
    onDone: async () => {
      let g: Generation;
      try {
        g = await api.generation(gid);
      } catch (e) {
        app().toast("error", `Презентация собрана, но не открылась: ${errText(e)}`);
        return;
      }
      await app().refreshGenerations();
      await app().loadGeneration(gid);
      app().setTab("variants");
      app().pushMessage("assistant", describeGeneration(g, app().strategyTitle));
      app().toast("success", "Презентация готова");
    },
    onFailed: (job) => {
      app().pushMessage("assistant", `Не получилось собрать презентацию: ${firstLine(job.error ?? job.message)}. Попробуйте ещё раз или уточните текст.`);
      void app().refreshGenerations();
    },
  });
}

function trackFixes(app: () => AppState, jobs: { strategy: string; job_id: string }[], gid: string | null) {
  if (jobs.length === 0) return;
  const open = app().generation;
  const scoreBefore = (strategy: string) => (open && open.id === gid ? open.variants.find((v) => v.strategy === strategy)?.audit?.summary.score ?? null : null);
  const outcomes: FixOutcome[] = jobs.map((j) => ({ strategy: j.strategy, before: scoreBefore(j.strategy), done: false, result: null, error: null }));
  let left = jobs.length;

  const settle = async () => {
    left -= 1;
    if (left > 0) return;
    if (gid && outcomes.some((o) => o.done)) {
      await app().refreshGenerations();
      await app().loadGeneration(gid);
      app().setTab("audit");
    }
    app().pushMessage("assistant", describeFixes(outcomes, app().strategyTitle));
  };

  jobs.forEach((j, i) => {
    app().runJob(j.job_id, `Исправляю: ${app().strategyTitle(j.strategy)}`, {
      kind: "fix",
      onDone: (job) => {
        outcomes[i].done = true;
        outcomes[i].result = asFixResult(job.result);
        void settle();
      },
      onFailed: (job) => {
        outcomes[i].error = firstLine(job.error ?? job.message);
        void settle();
      },
    });
  });
}

/** Returns a stable handler that performs the `actions` of a chat response (jobs to follow, tabs to open). */
export function useChatActions(): (res: ChatResponse) => void {
  const state = useApp();
  const latest = useRef(state);
  latest.current = state; // job callbacks fire minutes later: always read the freshest store

  return useCallback((res: ChatResponse) => {
    const app = () => latest.current;
    for (const action of res.actions ?? []) {
      if (action.type === "generation_started") trackGeneration(app, action.job_id, action.generation_id);
      else if (action.type === "jobs") trackFixes(app, action.jobs ?? [], res.generation_id ?? app().generationId);
      else if (action.type === "open_tab") {
        const tab = asTab(action.tab);
        if (action.slide) app().setSelectedSlide(action.slide);
        if (tab) app().setTab(tab);
      }
    }
  }, []);
}
