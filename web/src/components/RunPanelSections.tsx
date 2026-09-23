// «Запуск»: the sections of a run_manifest — facts, providers, skills, timings, fixes and audit summary.
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Bot, Clock3, Cpu, Info, ListChecks, OctagonAlert, Puzzle, Wand2 } from "lucide-react";
import { cn, fmtDate, fmtSeconds, scoreTone, shortSha } from "../lib/utils";
import type { AuditSummary, RunManifest } from "../types";
import { Badge } from "./ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import type { IconProp } from "./ui/icon";

/** Safe text for unknown JSON values (fix results, usage counters). */
export function str(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

const STAGE_LABEL: Record<string, string> = { analyze: "Разбор шаблона", plan: "Планирование", render: "Рендер PPTX", audit: "Аудит и автофикс", export: "Экспорт PDF/HTML", total: "Всего" };
export const stageLabel = (k: string) => STAGE_LABEL[k] ?? k;

const ROLE_LABEL: Record<string, string> = { llm: "LLM · тексты и структура", vlm: "VLM · визуальные проверки", embed: "Эмбеддинги", audit: "Аудит" };

export function Section({ icon, title, hint, actions, children, className }: { icon: IconProp; title: string; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader actions={actions}>
        <CardTitle icon={icon} hint={hint}>{title}</CardTitle>
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
    { label: "Создан", value: fmtDate(m.created_at), title: m.created_at },
    { label: "Стратегия", value: strategyTitle(m.strategy), title: m.strategy },
    { label: "Шаблон", value: m.template.file, title: m.template.id },
    { label: "Платформа", value: m.platform },
    { label: "Хэш брифа / аутлайна", value: <span className="font-mono text-xs">{shortSha(m.inputs.brief_sha256)} / {shortSha(m.inputs.outline_sha256)}</span>, title: `brief ${m.inputs.brief_sha256 ?? "—"}\noutline ${m.inputs.outline_sha256}` },
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
    <Section icon={Cpu} title="Провайдеры" hint="Какой backend и модель отвечали за каждую роль">
      <Table head={["Роль", "Backend", "Модель"]} rows={rows} empty="Запуск выполнен без моделей — планировщик и аудит работали детерминированно." />
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
    <Section icon={Puzzle} title="Навыки" hint="Версии и хэши инструкций, с которыми собран вариант">
      <Table head={["Навык", "Версия", "SHA-256"]} rows={rows} empty="Реестр навыков в манифесте пуст." />
    </Section>
  );
}

export function Timings({ m }: { m: RunManifest }) {
  const stages = Object.entries(m.timings_s).filter(([k, v]) => k !== "total" && Number.isFinite(v));
  const total = m.timings_s.total ?? stages.reduce((s, [, v]) => s + v, 0);
  const max = Math.max(...stages.map(([, v]) => v), 0.001);
  return (
    <Section icon={Clock3} title="Тайминги" hint="Секунды на каждый этап" actions={<Badge tone="neutral">{fmtSeconds(total)} всего</Badge>}>
      {stages.length === 0 ? (
        <p className="py-2 text-[13px] text-zinc-500">Этапы не измерялись.</p>
      ) : (
        <ul className="space-y-2.5">
          {stages.map(([k, v]) => (
            <li key={k} className="grid grid-cols-[150px_1fr_64px] items-center gap-3 text-[13px]">
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

export function Fixes({ m }: { m: RunManifest }) {
  const list = m.applied_fixes;
  return (
    <Section icon={Wand2} title="Автоисправления" hint="Что аудит поправил сам" actions={<Badge tone={list.length ? "accent" : "neutral"}>{list.length}</Badge>}>
      {list.length === 0 ? (
        <p className="py-2 text-[13px] text-zinc-500">Автофикс ничего не менял — вариант прошёл аудит без правок.</p>
      ) : (
        <ul className="scroll-thin max-h-72 divide-y divide-zinc-100 overflow-y-auto">
          {list.map((f, i) => (
            <li key={i} className="flex items-start gap-3 py-2 text-[13px]">
              <span className="w-8 shrink-0 text-xs tabular-nums text-zinc-400">#{str(f.iteration)}</span>
              <Badge size="sm" tone="info" className="font-mono">{str(f.action)}</Badge>
              {f.outline_id !== undefined && <span className="shrink-0 font-mono text-xs text-zinc-500">{str(f.outline_id)}</span>}
              <span className="min-w-0 flex-1 break-words text-zinc-700">{str(f.result ?? f.description)}</span>
            </li>
          ))}
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
  const items: Array<{ icon: LucideIcon; label: string; value: number | null; cls: string }> = [
    { icon: OctagonAlert, label: "Ошибки", value: num("errors"), cls: "text-red-600" },
    { icon: AlertTriangle, label: "Предупреждения", value: num("warnings"), cls: "text-amber-600" },
    { icon: Info, label: "Заметки", value: num("infos"), cls: "text-sky-600" },
    { icon: Bot, label: "Флаги модели", value: num("model_flags"), cls: "text-accent-700" },
  ];
  return (
    <Section
      icon={ListChecks}
      title="Итог аудита"
      hint={checks.length ? `${checks.length} проверок: ${checks.join(", ")}` : "Аудит не запускался"}
      actions={<Badge tone={scoreTone(score)}>{score === null ? "нет оценки" : `${Math.round(score)} / 100`}</Badge>}
    >
      <div className="grid grid-cols-4 gap-4">
        {items.map((it) => (
          <div key={it.label}>
            <div className="flex items-center gap-1.5 text-xs text-zinc-500">
              <it.icon className="h-3.5 w-3.5" aria-hidden />
              {it.label}
            </div>
            <div className={cn("mt-1 text-xl font-semibold tabular-nums", it.value ? it.cls : "text-zinc-900")}>{it.value ?? "—"}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}
