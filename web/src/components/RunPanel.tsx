// «Паспорт запуска» of the variant in the drawer's menu (run_manifest): facts with the models, timings, the check
// summary and the fixes; «Для разработчиков» (folded) holds the JSON files, the skills and agents, the agent's journal and the
// comparison with another run.
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, FileJson, GitCompare } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { templateTitle } from "../lib/plain";
import { cn, fmtWhen, plural, shortSha } from "../lib/utils";
import { useApp } from "../store";
import type { DiffResponse } from "../types";
import { RunPanelRegistry } from "./RunPanelRegistry";
import { Audit, Facts, Fixes, Section, Timings } from "./RunPanelSections";
import { AgentJournal } from "./simple/AgentPanel";
import { Button, LinkButton } from "./ui/Button";
import { Card } from "./ui/Card";
import { Collapsible } from "./ui/Collapsible";
import { EmptyState } from "./ui/EmptyState";
import { Notice } from "./ui/Notice";
import { Spinner } from "./ui/Spinner";

const selectCls = "h-10 min-w-0 cursor-pointer rounded-xl border-0 bg-zinc-100 px-3 text-footnote outline-none focus:bg-white focus:shadow-selected disabled:cursor-not-allowed disabled:opacity-40";
/** A chosen value reads as a value; the empty «Выберите…» reads as a placeholder (no class-merging: one or the other). */
const selectText = (filled: boolean) => (filled ? "font-semibold text-zinc-900" : "font-normal text-zinc-500");

const JSON_FILES: Array<{ name: string; label: string }> = [
  { name: "outline.json", label: "План" },
  { name: "layout_plan.json", label: "Раскладка" },
  { name: "audit_report.json", label: "Проверка" },
  { name: "run_manifest.json", label: "Паспорт запуска" },
];

function DiffView({ d, strategyTitle }: { d: DiffResponse; strategyTitle(name: string): string }) {
  const skills = Object.entries(d.diff.skills);
  const providers = Object.entries(d.diff.providers);
  const rows: Array<{ label: string; from: string; to: string }> = [];
  if (d.diff.strategy) rows.push({ label: "Вариант", from: strategyTitle(d.diff.strategy.from), to: strategyTitle(d.diff.strategy.to) });
  if (d.diff.audit_score) rows.push({ label: "Оценка качества", from: d.diff.audit_score.from === null ? "—" : String(d.diff.audit_score.from), to: d.diff.audit_score.to === null ? "—" : String(d.diff.audit_score.to) });
  for (const [role, ch] of providers) rows.push({ label: `Модель · ${role}`, from: ch.from ? ch.from.model ?? "—" : "без модели", to: ch.to ? ch.to.model ?? "—" : "без модели" });
  for (const [name, ch] of skills) rows.push({ label: `Навык · ${name}`, from: ch.from ? `v${ch.from.version} · ${shortSha(ch.from.sha256)}` : "не участвовал", to: ch.to ? `v${ch.to.version} · ${shortSha(ch.to.sha256)}` : "не участвовал" });
  if (rows.length === 0) return <Notice tone="success" title="Отличий нет" />;
  return (
    <table className="w-full text-footnote">
      <thead>
        <tr className="text-left text-caption text-zinc-500">
          <th className="pb-2 font-semibold">Что изменилось</th>
          <th className="pb-2 font-semibold">Этот запуск</th>
          <th className="pb-2" />
          <th className="pb-2 font-semibold">Другой запуск</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-100">
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="py-2 pr-3 font-semibold text-zinc-900">{r.label}</td>
            <td className="py-2 pr-3 font-mono text-caption text-zinc-700">{r.from}</td>
            <td className="py-2 pr-3 text-zinc-400"><ArrowRight className="h-3.5 w-3.5" aria-hidden /></td>
            <td className="py-2 font-mono text-caption text-zinc-700">{r.to}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Compare() {
  const { generationId, activeStrategy, generations, strategyTitle } = useApp();
  const [otherGid, setOtherGid] = useState<string>("");
  const [otherStrategy, setOtherStrategy] = useState<string>("");
  const [result, setResult] = useState<DiffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = useMemo(() => generations.filter((g) => g.status !== "running" && g.status !== "failed"), [generations]);
  const other = done.find((g) => g.id === otherGid) ?? null;
  const otherStrategies = other?.strategies ?? [];

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [generationId, activeStrategy, otherGid, otherStrategy]);
  useEffect(() => {
    if (other && !other.strategies.includes(otherStrategy)) setOtherStrategy(other.strategies[0] ?? "");
  }, [other, otherStrategy]);

  const run = async () => {
    if (!generationId || !activeStrategy || !otherGid || !otherStrategy) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.diff(generationId, activeStrategy, otherGid, otherStrategy));
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <select className={cn(selectCls, "flex-1", selectText(!!otherGid))} value={otherGid} onChange={(e) => setOtherGid(e.target.value)} aria-label="Другой запуск">
          <option value="">Выберите запуск…</option>
          {done.map((g) => (
            <option key={g.id} value={g.id}>
              {fmtWhen(g.created_at)} · {g.title || templateTitle(g.template_file, g.template_id)}{g.id === generationId ? " · этот" : ""}
            </option>
          ))}
        </select>
        <select className={cn(selectCls, "min-w-[160px]", selectText(!!other))} value={otherStrategy} onChange={(e) => setOtherStrategy(e.target.value)} disabled={!other} aria-label="Вариант другого запуска">
          {!other && <option value="">Вариант…</option>}
          {otherStrategies.map((s) => (
            <option key={s} value={s}>{strategyTitle(s)}</option>
          ))}
        </select>
        <Button variant="secondary" size="md" icon={GitCompare} loading={loading} disabled={!otherGid || !otherStrategy || !generationId} onClick={() => void run()}>
          Сравнить
        </Button>
      </div>
      {error ? <Notice tone="danger" title="Не удалось сравнить">{error}</Notice> : result ? <DiffView d={result} strategyTitle={strategyTitle} /> : null}
    </div>
  );
}

/** «Для разработчиков»: the JSON files of the variant, the skills and agents, the agent's journal, the comparison. */
function Developers() {
  const { generation, activeVariant } = useApp();
  const v = activeVariant ?? generation?.variants[0] ?? null;
  const log = v?.agent?.log ?? [];
  if (!generation || !v) return null;
  return (
    <Collapsible title="Для разработчиков" keepMounted={false}>
      <div className="flex flex-wrap gap-2">
        {JSON_FILES.map((f) => (
          <LinkButton key={f.name} variant="secondary" size="sm" icon={FileJson} href={api.fileUrl(generation.id, v.strategy, f.name)} target="_blank" rel="noopener noreferrer" title={f.name}>
            {f.label}
          </LinkButton>
        ))}
      </div>
      <div className="mt-4 divide-y divide-zinc-100 border-t border-zinc-100">
        <RunPanelRegistry manifest={v.run_manifest ?? null} />
        {log.length > 0 && (
          <Collapsible variant="plain" title="Журнал агента" hint={plural(log.length, "запись", "записи", "записей")} keepMounted={false}>
            <AgentJournal log={log} />
          </Collapsible>
        )}
        <Collapsible variant="plain" title="Сравнить с другим запуском" keepMounted={false}>
          <Compare />
        </Collapsible>
      </div>
    </Collapsible>
  );
}

export function RunPanel() {
  const { generation, generationLoading, activeVariant, strategyTitle, manifest } = useApp();

  if (generationLoading && !generation) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner showLabel label="Загружаю паспорт запуска" />
      </div>
    );
  }
  if (!generation) return null;
  const m = activeVariant?.run_manifest ?? null;
  const outline = activeVariant?.outline ?? null;
  const slideOf = (outlineId: string) => {
    const i = outline?.slides.findIndex((s) => s.id === outlineId) ?? -1;
    return i >= 0 ? i + 1 : null;
  };
  const templateSlide = (pid: string) => (manifest?.template_id === generation.template_id ? manifest.patterns.find((p) => p.id === pid)?.source_slide ?? null : null);
  return (
    <>
      {!m ? (
        <Card>
          <EmptyState compact icon={FileJson} title="У этого варианта нет паспорта" hint="Соберите презентацию заново" />
        </Card>
      ) : (
        <>
          <Section title="Паспорт запуска">
            <Facts m={m} strategyTitle={strategyTitle} plannedBy={outline?.planned_by} planner={activeVariant?.planner} run={generation} />
          </Section>
          <Timings m={m} />
          <Audit m={m} fallback={activeVariant?.audit?.summary ?? null} run={generation} />
          <Fixes m={m} slideOf={slideOf} templateSlide={templateSlide} />
        </>
      )}
      <Developers />
    </>
  );
}
