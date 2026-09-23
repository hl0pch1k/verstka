// «Паспорт запуска» of a variant (run_manifest): versions of skills, models, timings, fixes, the check summary, the
// live skills registry of the server and a comparison with another run.
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, FileJson, GitCompare, Info } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { templateName } from "../lib/plain";
import { fmtWhen, scoreTone, shortSha } from "../lib/utils";
import { useApp } from "../store";
import type { DiffResponse } from "../types";
import { RunPanelRegistry } from "./RunPanelRegistry";
import { Audit, Facts, Fixes, Providers, Section, Skills, Timings } from "./RunPanelSections";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Spinner } from "./ui/Spinner";
import { Tabs } from "./ui/Tabs";

const selectCls = "h-10 min-w-0 cursor-pointer rounded-xl border-0 bg-zinc-100 px-3 text-[13px] font-medium text-zinc-900 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none";

function DiffView({ d, strategyTitle }: { d: DiffResponse; strategyTitle(name: string): string }) {
  const skills = Object.entries(d.diff.skills);
  const providers = Object.entries(d.diff.providers);
  const rows: Array<{ label: string; from: string; to: string }> = [];
  if (d.diff.strategy) rows.push({ label: "Вариант", from: strategyTitle(d.diff.strategy.from), to: strategyTitle(d.diff.strategy.to) });
  if (d.diff.audit_score) rows.push({ label: "Оценка качества", from: d.diff.audit_score.from === null ? "—" : String(d.diff.audit_score.from), to: d.diff.audit_score.to === null ? "—" : String(d.diff.audit_score.to) });
  for (const [role, ch] of providers) rows.push({ label: `Модель · ${role}`, from: ch.from ? `${ch.from.backend} · ${ch.from.model ?? "—"}` : "без модели", to: ch.to ? `${ch.to.backend} · ${ch.to.model ?? "—"}` : "без модели" });
  for (const [name, ch] of skills) rows.push({ label: `Навык · ${name}`, from: ch.from ? `v${ch.from.version} · ${shortSha(ch.from.sha256)}` : "не участвовал", to: ch.to ? `v${ch.to.version} · ${shortSha(ch.to.sha256)}` : "не участвовал" });
  if (rows.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-800">
        <Info className="h-4 w-4" aria-hidden />
        Отличий нет: те же версии навыков, модели, вариант и оценка качества.
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
    <Section title="Сравнить с другим запуском" hint="Чем отличаются версии навыков, модели, вариант и оценка качества">
      <div className="flex flex-wrap items-center gap-2">
        <select className={selectCls} value={otherGid} onChange={(e) => setOtherGid(e.target.value)} aria-label="Другой запуск">
          <option value="">Выберите запуск…</option>
          {done.map((g) => (
            <option key={g.id} value={g.id}>
              {fmtWhen(g.created_at)} · {templateName(g.template_file, g.template_id)}{g.id === generationId ? " · этот" : ""}
            </option>
          ))}
        </select>
        <select className={selectCls} value={otherStrategy} onChange={(e) => setOtherStrategy(e.target.value)} disabled={!other} aria-label="Вариант другого запуска">
          {!other && <option value="">Вариант…</option>}
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
          <p className="text-[13px] text-zinc-500">Выберите запуск и вариант — покажем, чем отличаются их паспорта: какими версиями навыков и какими моделями собрана каждая презентация.</p>
        )}
      </div>
    </Section>
  );
}

export function RunPanel() {
  const { generation, generationLoading, activeVariant, activeStrategy, setActiveStrategy, strategyTitle, setTab, manifest } = useApp();

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
        title="Паспорт запуска появится после сборки"
        hint="Каждый вариант сохраняет run_manifest.json: версии навыков, модели, настройки, время этапов и коммит — по нему видно, чем собрана презентация."
      />
    );
  }
  const m = activeVariant?.run_manifest ?? null;
  const variants = generation.variants;
  const outline = activeVariant?.outline ?? null;
  const slideOf = (outlineId: string) => {
    const i = outline?.slides.findIndex((s) => s.id === outlineId) ?? -1;
    return i >= 0 ? i + 1 : null;
  };
  const templateSlide = (pid: string) => (manifest?.template_id === generation.template_id ? manifest.patterns.find((p) => p.id === pid)?.source_slide ?? null : null);
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
        <EmptyState compact icon={FileJson} title="У этого варианта нет паспорта" hint="run_manifest.json не сохранился — так бывает, если сборка прервалась." action={<Button size="sm" onClick={() => setTab("variants")}>К слайдам</Button>} />
      ) : (
        <>
          <Section title="Сведения о запуске" hint="Из run_manifest.json — по нему любую презентацию можно воспроизвести">
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
          <Fixes m={m} slideOf={slideOf} templateSlide={templateSlide} />
        </>
      )}
      <RunPanelRegistry manifest={m} />
      <Compare />
    </div>
  );
}
