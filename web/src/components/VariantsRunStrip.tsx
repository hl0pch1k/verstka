// Footer strip under the variant: run_manifest basics (strategy, total time, audit score, version, providers).
import type { ReactNode } from "react";
import { ArrowUpRight, Clock3, Cpu, FileCog, Gauge, GitCommitHorizontal, Route } from "lucide-react";
import { fmtDate, fmtSeconds, scoreTone, shortSha } from "../lib/utils";
import type { Generation, Variant } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { renderIcon, type IconProp } from "./ui/icon";

interface Props {
  variant: Variant;
  generation: Generation;
  score: number | null;
  strategyTitle(name: string): string;
  onOpenRun(): void;
}

function Item({ icon, label, title, children }: { icon: IconProp; label: string; title?: string; children: ReactNode }) {
  return (
    <div className="flex max-w-[320px] items-center gap-2" title={title}>
      {renderIcon(icon, "h-4 w-4 shrink-0 text-zinc-400")}
      <span className="shrink-0 text-xs text-zinc-500">{label}</span>
      <span className="truncate text-[13px] font-medium text-zinc-900">{children}</span>
    </div>
  );
}

export function VariantsRunStrip({ variant, generation, score, strategyTitle, onOpenRun }: Props) {
  const m = variant.run_manifest;
  const totalSeconds = m?.timings_s.total ?? generation.summary?.[variant.strategy]?.seconds ?? generation.seconds ?? null;
  const stages = m ? Object.entries(m.timings_s).filter(([k]) => k !== "total") : [];
  const timingsTitle = stages.length ? stages.map(([k, v]) => `${k}: ${fmtSeconds(v)}`).join("\n") : undefined;
  const providers = m ? Object.entries(m.providers) : [];
  const models = Array.from(new Set(providers.map(([, p]) => p.model || p.backend).filter((name) => name && name !== "none")));
  const providersTitle = providers.length ? providers.map(([role, p]) => `${role}: ${p.backend}${p.model ? ` · ${p.model}` : ""}`).join("\n") : undefined;

  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-zinc-200 bg-white px-5 py-2.5 shadow-card">
      <Item icon={Route} label="Стратегия">
        {strategyTitle(m?.strategy ?? variant.strategy)}
      </Item>
      <Item icon={Clock3} label="Время" title={timingsTitle}>
        {fmtSeconds(totalSeconds)}
      </Item>
      <div className="flex items-center gap-2">
        <Gauge className="h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
        <span className="text-xs text-zinc-500">Аудит</span>
        <Badge tone={scoreTone(score)} size="sm">
          {score === null ? "не запускался" : `${Math.round(score)} / 100`}
        </Badge>
      </div>
      {m ? (
        <>
          <Item icon={GitCommitHorizontal} label="Версия" title={m.git_commit ? `commit ${m.git_commit}` : undefined}>
            {m.verstka_version}
            {m.git_commit && <span className="ml-1 font-mono text-xs font-normal text-zinc-500">{shortSha(m.git_commit)}</span>}
          </Item>
          <Item icon={Cpu} label="Модели" title={providersTitle}>
            {models.length ? models.join(", ") : "без моделей"}
          </Item>
        </>
      ) : (
        <span className="flex items-center gap-1.5 text-xs text-zinc-400">
          <FileCog className="h-3.5 w-3.5" aria-hidden />
          run_manifest.json для варианта отсутствует
        </span>
      )}
      <span className="ml-auto flex shrink-0 items-center gap-3">
        {m && <span className="text-xs text-zinc-400">{fmtDate(m.created_at)}</span>}
        <Button size="sm" variant="ghost" iconRight={ArrowUpRight} onClick={onOpenRun}>
          Паспорт запуска
        </Button>
      </span>
    </footer>
  );
}
