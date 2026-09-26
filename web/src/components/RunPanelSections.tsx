// «Паспорт запуска»: the sections of a run_manifest — facts, models, timings, the check summary and the fixes.
import type { ReactNode } from "react";
import { fmtSeconds, fmtWhen, plural, scoreTone, cn, TONE_TEXT } from "../lib/utils";
import type { AuditSummary, PlannerInfo, RunManifest } from "../types";
import { plannedByText, templateTitle } from "../lib/plain";
import { describeFix } from "./AuditFixes";
import { normalizeFix } from "./AuditHelpers";
import { Badge } from "./ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { Progress } from "./ui/Progress";

const STAGE_LABEL: Record<string, string> = {
  analyze: "Разбор шаблона",
  plan: "План (общий для вариантов)",
  render: "Сборка PowerPoint",
  audit: "Проверка и правки",
  export: "PDF, веб-версия и превью",
  other: "Прочее",
  total: "Всего",
};
const STAGE_TITLE: Record<string, string> = { other: "Очередь за другими вариантами и сохранение файлов" };
export const stageLabel = (k: string) => STAGE_LABEL[k] ?? k;

const ROLE_LABEL: Record<string, string> = { llm: "Тексты и план", vlm: "Проверка по картинке", embed: "Поиск похожего", audit: "Проверка" };
const BACKEND_NAME: Record<string, string> = { openrouter: "OpenRouter", groq: "Groq", cloudru: "Cloud.ru", ollama: "Ollama", vllm: "vLLM" };

export function Section({ title, count, actions, children, className }: { title: string; count?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader actions={actions}>
        <CardTitle count={count}>{title}</CardTitle>
      </CardHeader>
      <CardBody>{children}</CardBody>
    </Card>
  );
}

export function Table({ head, rows, empty }: { head: string[]; rows: ReactNode[][]; empty: string }) {
  if (rows.length === 0) return <p className="py-2 text-footnote text-zinc-500">{empty}</p>;
  return (
    <table className="w-full text-footnote">
      <thead>
        <tr className="text-left text-caption text-zinc-500">
          {head.map((h, i) => (
            <th key={`${h}${i}`} className="pb-2 pr-4 font-semibold last:pr-0">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-100">
        {rows.map((cells, i) => (
          <tr key={i}>
            {cells.map((c, j) => (
              <td key={j} className="py-2 pr-4 align-top last:pr-0">{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Who made the plan, short: the models are named on their own lines of the passport, so «агент», not «агент: слайды
 *  продумала модель Qwen3 32B» again. */
function plannedBy(by: string | undefined, strategyTitle: (name: string) => string, planner?: PlannerInfo | null): string {
  const who = planner?.planned_by === "supplied" ? "supplied" : by ?? planner?.planned_by ?? null;
  if (who === "agent") return "агент";
  if (who === "model") return "модель";
  return plannedByText(by, strategyTitle, planner ? { ...planner, model_label: null } : planner);
}

/** The request's switches that decide which models a run asked (GenerationMeta); undefined on older runs. */
export interface RunSwitches { use_models?: boolean; audit_models?: boolean; outline_supplied?: boolean }

/** Did the run ask the role's model? false: the switch was off (or nothing needed it); null: unknown (older runs). The
 *  vision model looks at slide images only in the model check; the text model plans (unless the plan came with the
 *  request) and joins the model check. */
export function roleUsed(role: string, m: RunManifest, run?: RunSwitches | null): boolean | null {
  if (run?.use_models === false) return false;
  if (role === "vlm") return run?.audit_models === undefined ? null : run.audit_models;
  if (role === "llm") {
    const supplied = run?.outline_supplied || m.planner?.supplied;
    return supplied && run?.audit_models === false ? false : null;
  }
  return null;
}

/** A role the run did not ask: «выключена» for a check the person turned off, «без модели» for the rest. */
const unusedText = (role: string) => (role === "vlm" ? "выключена" : "без модели");

/** The passport's facts in one grid: the template, when, which Verstka, who planned and which model did what (the
 *  variant is the drawer's menu). A role the run did not use says so instead of naming a model that did nothing. */
export function Facts({ m, strategyTitle, plannedBy: by, planner, run }: { m: RunManifest; strategyTitle(name: string): string; plannedBy?: string; planner?: PlannerInfo | null; run?: RunSwitches | null }) {
  const roles = Object.entries(m.providers);
  const facts: Array<{ label: string; value: ReactNode; title?: string }> = [
    { label: "Шаблон", value: templateTitle(m.template.file), title: m.template.file },
    { label: "Собран", value: fmtWhen(m.created_at) },
    { label: "Версия Verstka", value: m.verstka_version, title: [m.git_commit ? `коммит ${m.git_commit}` : null, m.platform].filter(Boolean).join("\n") },
    { label: "План составил", value: plannedBy(by, strategyTitle, planner) },
    ...(roles.length
      ? roles.map(([role, p]) => ({
          label: ROLE_LABEL[role] ?? role,
          value: roleUsed(role, m, run) === false ? unusedText(role) : modelName(p, role === "llm" ? m.planner?.model : null),
        }))
      : [{ label: "Модели", value: "без моделей" }]),
  ];
  return (
    <dl className="grid grid-cols-3 gap-x-6 gap-y-4">
      {facts.map((f) => (
        <div key={f.label} className="min-w-0" title={f.title || undefined}>
          <dt className="text-caption text-zinc-500">{f.label}</dt>
          <dd className="mt-0.5 text-footnote font-semibold text-zinc-900">{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

type Link = { backend?: string; model?: string; label?: string; off?: boolean };

/** «Qwen3.8-27B (OpenRouter)» → «Qwen3.8-27B · OpenRouter». */
const tidyLabel = (label: string) => label.replace(/\s*\(([^)]+)\)\s*$/, " · $1");

/** The model of a role in words: the one that answered when the run knows it, else the first link of the chain. */
function modelName(p: RunManifest["providers"][string], answered?: string | null): string {
  if (p.backend === "none" || p.backend === "mock") return "без модели";
  const chain = ((p as { chain?: Link[] }).chain ?? []).filter((l) => !l.off);
  const hit = (answered && chain.find((l) => l.model === answered)) || chain[0];
  if (hit) return tidyLabel(hit.label ?? hit.model ?? "модель");
  const where = BACKEND_NAME[p.backend];
  return [p.model, where].filter(Boolean).join(" · ") || "модель";
}

export function Timings({ m, className }: { m: RunManifest; className?: string }) {
  const measured = Object.entries(m.timings_s).filter(([k, v]) => k !== "total" && Number.isFinite(v));
  const sum = measured.reduce((s, [, v]) => s + v, 0);
  const plan = m.timings_s.plan ?? 0;
  const total = m.timings_s.total ?? sum;
  // a variant's total leaves out the plan, which all the variants share: the badge counts it in
  const all = total + 0.5 < sum ? total + plan : total;
  // the rows add up to the badge: what no stage measured (the variant waits for the others' layout, the files are
  // saved) is a row of its own when it is worth a second
  const rest = measured.length ? all - sum : 0;
  const stages: Array<[string, number]> = rest > 1 ? [...measured, ["other", rest]] : measured;
  const max = Math.max(...stages.map(([, v]) => v), 0.001);
  return (
    <Section title="Время по этапам" className={className} actions={<Badge tone="neutral">≈ {fmtSeconds(all)}</Badge>}>
      {stages.length === 0 ? (
        <p className="text-footnote text-zinc-500">Этапы не измерялись</p>
      ) : (
        <ul className="space-y-3">
          {stages.map(([k, v], i) => (
            <li key={k} className="text-footnote" title={STAGE_TITLE[k]}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-zinc-700">{stageLabel(k)}</span>
                <span className="font-semibold tabular-nums text-zinc-900">{fmtSeconds(v)}</span>
              </div>
              <Progress size="sm" value={v / max} appear={Math.min(i, 6) * 40} className="mt-1" />
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function Fixes({ m, slideOf, templateSlide }: { m: RunManifest; slideOf(outlineId: string): number | null; templateSlide(patternId: string): number | null }) {
  const list = m.applied_fixes;
  if (list.length === 0) return null;
  return (
    <Section title="Автоисправления" count={list.length}>
      <ul className="scroll-thin max-h-72 divide-y divide-zinc-100 overflow-y-auto">
        {list.map((f, i) => {
          const r = normalizeFix(f);
          const d = describeFix(r, slideOf, templateSlide);
          return (
            <li key={i} className="flex items-baseline gap-3 py-2 text-footnote">
              <span className="w-20 shrink-0 text-zinc-500">{d.slide ? `Слайд ${d.slide}` : "Все слайды"}</span>
              <span className="min-w-0 flex-1 text-zinc-900">
                {d.title}
                {d.extra && <span className="text-zinc-500">: {d.extra}</span>}
              </span>
              {r.iteration !== null && <span className="shrink-0 tabular-nums text-zinc-500">проход {r.iteration}</span>}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

export function Audit({ m, fallback, run }: { m: RunManifest; fallback: AuditSummary | null; run?: RunSwitches | null }) {
  const a = m.audit;
  const num = (k: keyof AuditSummary): number | null => {
    const v = a[k] ?? fallback?.[k];
    return typeof v === "number" ? v : null;
  };
  const score = num("score");
  const checks = (Array.isArray(a.checks_run) ? a.checks_run : fallback?.checks_run ?? []) as string[];
  // the check by image did not run: «—», not a «0» that reads as «a model looked and found nothing»
  const visionOff = roleUsed("vlm", m, run) === false;
  const items: Array<{ label: string; value: number | null; cls: string; title?: string }> = [
    { label: "Ошибки", value: num("errors"), cls: "text-red-600" },
    { label: "Предупреждения", value: num("warnings"), cls: "text-amber-700" },
    { label: "Заметки", value: num("infos"), cls: "text-accent-700" },
    { label: "По картинке", value: visionOff ? null : num("model_flags"), cls: "text-accent-700", title: visionOff ? "Проверка по картинке выключена" : undefined },
    { label: "Автоисправления", value: m.applied_fixes.length, cls: "text-accent-700" },
  ];
  return (
    <Section
      title="Итог проверки"
      count={checks.length ? plural(checks.length, "проверка", "проверки", "проверок") : null}
      actions={score !== null && <span className={cn("text-title3 font-bold tabular-nums", TONE_TEXT[scoreTone(score)])} title="Оценка качества из 100">{Math.round(score)}</span>}
    >
      <dl className="grid grid-cols-5 gap-3">
        {items.map((it) => (
          <div key={it.label} className="flex flex-col rounded-xl bg-zinc-100 px-4 py-3" title={it.title}>
            <dt className="order-2 mt-0.5 text-caption text-zinc-500">{it.label}</dt>
            <dd className={cn("order-1 text-title3 font-bold tabular-nums", it.value ? it.cls : "text-zinc-900")}>{it.value ?? "—"}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}
