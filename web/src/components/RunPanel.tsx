// «Запуск»: паспорт варианта (run_manifest) — версии навыков, модели, тайминги, автофиксы, итог аудита,
// живой реестр навыков сервера и сравнение с другим запуском.
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, FileJson, GitCompare, Info } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { fmtDate, scoreTone, shortSha } from "../lib/utils";
import { useApp } from "../store";
import type { DiffResponse } from "../types";
import { RunPanelRegistry } from "./RunPanelRegistry";
import { Audit, Facts, Fixes, Providers, Section, Skills, Timings } from "./RunPanelSections";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Spinner } from "./ui/Spinner";
import { Tabs } from "./ui/Tabs";

const selectCls = "h-9 min-w-0 rounded-lg border border-zinc-200 bg-white px-2.5 text-[13px] text-zinc-900 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20";

function DiffView({ d, strategyTitle }: { d: DiffResponse; strategyTitle(name: string): string }) {
  const skills = Object.entries(d.diff.skills);
  const providers = Object.entries(d.diff.providers);
  const rows: Array<{ label: string; from: string; to: string }> = [];
  if (d.diff.strategy) rows.push({ label: "Стратегия", from: strategyTitle(d.diff.strategy.from), to: strategyTitle(d.diff.strategy.to) });
  if (d.diff.audit_score) rows.push({ label: "Оценка аудита", from: d.diff.audit_score.from === null ? "—" : String(d.diff.audit_score.from), to: d.diff.audit_score.to === null ? "—" : String(d.diff.audit_score.to) });
  for (const [role, ch] of providers) rows.push({ label: `Провайдер · ${role}`, from: ch.from ? `${ch.from.backend} · ${ch.from.model ?? "—"}` : "без модели", to: ch.to ? `${ch.to.backend} · ${ch.to.model ?? "—"}` : "без модели" });
  for (const [name, ch] of skills) rows.push({ label: `Навык · ${name}`, from: ch.from ? `v${ch.from.version} · ${shortSha(ch.from.sha256)}` : "не участвовал", to: ch.to ? `v${ch.to.version} · ${shortSha(ch.to.sha256)}` : "не участвовал" });
  if (rows.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-800">
        <Info className="h-4 w-4" aria-hidden />
        Отличий нет: те же версии навыков, модели, стратегия и оценка аудита.
      </div>
    );
  }
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-xs text-zinc-500">
          <th className="pb-2 font-medium">Что изменилось</th>
          <th className="pb-2 font-medium">Этот запуск</th>
          <th className="pb-2" />
          <th className="pb-2 font-medium">Другой запуск</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-100">
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="py-2 pr-3 font-medium text-zinc-900">{r.label}</td>
            <td className="py-2 pr-3 font-mono text-xs text-zinc-700">{r.from}</td>
            <td className="py-2 pr-3 text-zinc-400"><ArrowRight className="h-3.5 w-3.5" aria-hidden /></td>
            <td className="py-2 font-mono text-xs text-zinc-700">{r.to}</td>
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
    <Section icon={GitCompare} title="Сравнить с другим запуском" hint="Версии навыков, модели, стратегия и оценка аудита двух паспортов">
      <div className="flex flex-wrap items-center gap-2">
        <select className={selectCls} value={otherGid} onChange={(e) => setOtherGid(e.target.value)} aria-label="Другая генерация">
          <option value="">Выберите генерацию…</option>
          {done.map((g) => (
            <option key={g.id} value={g.id}>
              {fmtDate(g.created_at)} · {g.template_file ?? g.template_id}{g.id === generationId ? " · текущая" : ""}
            </option>
          ))}
        </select>
        <select className={selectCls} value={otherStrategy} onChange={(e) => setOtherStrategy(e.target.value)} disabled={!other} aria-label="Стратегия другого запуска">
          {otherStrategies.map((s) => (
            <option key={s} value={s}>{strategyTitle(s)}</option>
          ))}
        </select>
        <Button variant="primary" size="sm" icon={GitCompare} loading={loading} disabled={!otherGid || !otherStrategy || !generationId} onClick={() => void run()}>
          Сравнить
        </Button>
      </div>
      <div className="mt-4">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">Не удалось сравнить: {error}</div>
        ) : result ? (
          <DiffView d={result} strategyTitle={strategyTitle} />
        ) : (
          <p className="text-[13px] text-zinc-500">Выберите генерацию и стратегию — покажем, чем отличаются паспорта запусков: это ответ на вопрос «какая версия навыка собрала эту презентацию».</p>
        )}
      </div>
    </Section>
  );
}

export function RunPanel() {
  const { generation, generationLoading, activeVariant, activeStrategy, setActiveStrategy, strategyTitle, setTab } = useApp();

  if (generationLoading && !generation) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner showLabel label="Загружаем паспорт запуска" />
      </div>
    );
  }
  if (!generation) {
    return (
      <EmptyState
        icon={FileJson}
        title="Паспорт запуска появится после генерации"
        hint="Каждый вариант сохраняет run_manifest.json: версии и хэши навыков, модели, конфиг, тайминги и коммит — так видно, какая версия чего собрала презентацию."
      />
    );
  }
  const m = activeVariant?.run_manifest ?? null;
  const variants = generation.variants;
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          variant="pills"
          items={variants.map((v) => ({ key: v.strategy, label: strategyTitle(v.strategy), badge: v.audit?.summary.score ?? null, badgeTone: scoreTone(v.audit?.summary.score ?? null) }))}
          value={activeStrategy ?? variants[0]?.strategy ?? ""}
          onChange={(k) => setActiveStrategy(k)}
        />
        {m?.git_commit && <Badge tone="neutral" className="font-mono">commit {shortSha(m.git_commit)}</Badge>}
      </div>
      {!m ? (
        <EmptyState compact icon={FileJson} title="У этого варианта нет run_manifest.json" hint="Вариант собран без паспорта — так бывает, если генерация прервалась." action={<Button size="sm" onClick={() => setTab("variants")}>К слайдам</Button>} />
      ) : (
        <>
          <Section icon={FileJson} title="Паспорт запуска" hint="run_manifest.json варианта">
            <Facts m={m} strategyTitle={strategyTitle} />
          </Section>
          <div className="grid grid-cols-2 gap-4">
            <Providers m={m} />
            <Skills m={m} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Timings m={m} />
            <Audit m={m} fallback={activeVariant?.audit?.summary ?? null} />
          </div>
          <Fixes m={m} />
        </>
      )}
      <RunPanelRegistry manifest={m} />
      <Compare />
    </div>
  );
}
