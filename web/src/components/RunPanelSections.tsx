// «Паспорт запуска»: the sections of a run_manifest — facts, models, skills, timings, fixes and the check summary.
import type { ReactNode } from "react";
import { cn, fmtSeconds, fmtWhen, plural, scoreTone, shortSha } from "../lib/utils";
import type { AuditSummary, RunManifest } from "../types";
import { describeFix } from "./AuditFixes";
import { normalizeFix } from "./AuditHelpers";
import { Badge } from "./ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";

const STAGE_LABEL: Record<string, string> = { analyze: "Разбор шаблона", plan: "План", render: "Сборка PPTX", audit: "Проверка и правки", export: "PDF, HTML и превью", total: "Всего" };
export const stageLabel = (k: string) => STAGE_LABEL[k] ?? k;

const ROLE_LABEL: Record<string, string> = { llm: "Тексты и план", vlm: "Проверка по картинке", embed: "Поиск похожего", audit: "Проверка" };
const noModels = (m: RunManifest) => Object.values(m.providers).every((p) => p.backend === "none" || p.backend === "mock");

export function Section({ title, hint, actions, children, className }: { title: string; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader actions={actions}>
        <CardTitle hint={hint}>{title}</CardTitle>
      </CardHeader>
      <CardBody>{children}</CardBody>
    </Card>
  );
}

export function Table({ head, rows, empty }: { head: string[]; rows: ReactNode[][]; empty: string }) {
  if (rows.length === 0) return <p className="py-2 text-[13px] text-zinc-500">{empty}</p>;
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-xs text-zinc-500">
          {head.map((h) => (
            <th key={h} className="pb-2 pr-4 font-medium last:pr-0">{h}</th>
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

export function Facts({ m, strategyTitle }: { m: RunManifest; strategyTitle(name: string): string }) {
  const facts: Array<{ label: string; value: ReactNode; title?: string }> = [
    { label: "Версия Verstka", value: <span>{m.verstka_version}{m.git_commit && <span className="ml-1.5 font-mono text-xs text-zinc-500">{shortSha(m.git_commit)}</span>}</span>, title: m.git_commit ? `git commit ${m.git_commit}` : undefined },
    { label: "Собран", value: fmtWhen(m.created_at), title: m.created_at },
    { label: "Вариант", value: strategyTitle(m.strategy), title: m.strategy },
    { label: "Шаблон", value: m.template.file, title: m.template.id },
    { label: "Платформа", value: m.platform },
    { label: "Хэш текста / плана", value: <span className="font-mono text-xs">{shortSha(m.inputs.brief_sha256)} / {shortSha(m.inputs.outline_sha256)}</span>, title: `brief ${m.inputs.brief_sha256 ?? "—"}\noutline ${m.inputs.outline_sha256}` },
  ];
  return (
    <div className="grid grid-cols-3 gap-x-6 gap-y-4">
      {facts.map((f) => (
        <div key={f.label} className="min-w-0" title={f.title}>
          <div className="text-xs text-zinc-500">{f.label}</div>
          <div className="mt-0.5 truncate text-[13px] font-medium text-zinc-900">{f.value}</div>
        </div>
      ))}
    </div>
  );
}

export function Providers({ m }: { m: RunManifest }) {
  const rows = Object.entries(m.providers).map(([role, p]) => [
    <span key="r" className="font-medium text-zinc-900" title={role}>{ROLE_LABEL[role] ?? role}</span>,
    <Badge key="b" tone={p.backend === "none" || p.backend === "mock" ? "neutral" : "success"} size="sm">{p.backend === "none" ? "без модели" : p.backend}</Badge>,
    <span key="m" className="font-mono text-xs text-zinc-700">{p.model ?? "—"}</span>,
  ]);
  return (
    <Section title="Модели" hint="Какая модель отвечала за каждую роль">
      <Table head={["Роль", "Где работает", "Модель"]} rows={rows} empty="Запуск выполнен без моделей — план и проверка работали по правилам." />
    </Section>
  );
}

export function Skills({ m }: { m: RunManifest }) {
  const rows = Object.entries(m.skills).map(([name, s]) => [
    <span key="n" className="font-mono text-xs font-medium text-zinc-900">{name}</span>,
    <Badge key="v" tone="accent" size="sm">v{s.version}</Badge>,
    <span key="s" className="font-mono text-xs text-zinc-500" title={s.sha256}>{shortSha(s.sha256)}</span>,
  ]);
  return (
    <Section title="Навыки" hint="Версии и хэши инструкций, с которыми собран вариант">
      <Table head={["Навык", "Версия", "SHA-256"]} rows={rows} empty={noModels(m) ? "Вариант собран без моделей — навыки не вызывались." : "Навыки в паспорте не записаны."} />
    </Section>
  );
}

export function Timings({ m }: { m: RunManifest }) {
  const stages = Object.entries(m.timings_s).filter(([k, v]) => k !== "total" && Number.isFinite(v));
  const total = m.timings_s.total ?? stages.reduce((s, [, v]) => s + v, 0);
  const max = Math.max(...stages.map(([, v]) => v), 0.001);
  return (
    <Section title="Время по этапам" hint="Сколько занял каждый шаг сборки" actions={<Badge tone="neutral">{fmtSeconds(total)} всего</Badge>}>
      {stages.length === 0 ? (
        <p className="py-2 text-[13px] text-zinc-500">Этапы не измерялись.</p>
      ) : (
        <ul className="space-y-2.5">
          {stages.map(([k, v]) => (
            <li key={k} className="grid grid-cols-[140px_1fr_56px] items-center gap-3 text-[13px]">
              <span className="truncate text-zinc-700" title={k}>{stageLabel(k)}</span>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
                <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${Math.max(2, (v / max) * 100)}%` }} />
              </div>
              <span className="text-right font-medium tabular-nums text-zinc-900">{fmtSeconds(v)}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function Fixes({ m, slideOf, templateSlide }: { m: RunManifest; slideOf(outlineId: string): number | null; templateSlide(patternId: string): number | null }) {
  const list = m.applied_fixes;
  return (
    <Section title="Автоисправления" hint="Что проверка качества поправила сама, по проходам" actions={<Badge tone={list.length ? "accent" : "neutral"}>{list.length}</Badge>}>
      {list.length === 0 ? (
        <p className="py-2 text-[13px] text-zinc-500">Исправлять ничего не пришлось.</p>
      ) : (
        <ul className="scroll-thin max-h-72 divide-y divide-zinc-100 overflow-y-auto">
          {list.map((f, i) => {
            const r = normalizeFix(f);
            const d = describeFix(r, slideOf, templateSlide);
            return (
              <li key={i} className="flex items-baseline gap-3 py-2 text-[13px]" title={JSON.stringify(f)}>
                <span className="w-16 shrink-0 text-xs tabular-nums text-zinc-400">{r.iteration !== null ? `проход ${r.iteration}` : ""}</span>
                <span className="w-16 shrink-0 text-zinc-500">{d.slide ? `Слайд ${d.slide}` : "Все слайды"}</span>
                <span className="min-w-0 flex-1 text-zinc-900">
                  {d.title}
                  {d.extra && <span className="text-zinc-500"> — {d.extra}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

export function Audit({ m, fallback }: { m: RunManifest; fallback: AuditSummary | null }) {
  const a = m.audit;
  const num = (k: keyof AuditSummary): number | null => {
    const v = a[k] ?? fallback?.[k];
    return typeof v === "number" ? v : null;
  };
  const score = num("score");
  const checks = (Array.isArray(a.checks_run) ? a.checks_run : fallback?.checks_run ?? []) as string[];
  const items: Array<{ label: string; value: number | null; cls: string }> = [
    { label: "Ошибки", value: num("errors"), cls: "text-red-600" },
    { label: "Предупреждения", value: num("warnings"), cls: "text-amber-600" },
    { label: "Заметки", value: num("infos"), cls: "text-sky-600" },
    { label: "Замечания модели", value: num("model_flags"), cls: "text-accent-700" },
  ];
  return (
    <Section
      title="Итог проверки"
      hint={<span title={checks.join(", ")}>{checks.length ? `${plural(checks.length, "проверка", "проверки", "проверок")} по правилам шаблона` : "Проверка не запускалась"}</span>}
      actions={<Badge tone={scoreTone(score)}>{score === null ? "нет оценки" : `${Math.round(score)}/100`}</Badge>}
    >
      <dl className="divide-y divide-zinc-100">
        {items.map((it) => (
          <div key={it.label} className="flex items-baseline justify-between py-2 text-[13px]">
            <dt className="text-zinc-600">{it.label}</dt>
            <dd className={cn("text-[15px] font-semibold tabular-nums", it.value ? it.cls : "text-zinc-900")}>{it.value ?? "—"}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}
