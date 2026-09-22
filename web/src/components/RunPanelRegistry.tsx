// «Запуск»: the live skills registry (GET /api/skills) — what the server would use for the next run,
// with a per-skill comparison against the versions recorded in the open run_manifest.
import { useCallback, useEffect, useState } from "react";
import { BookOpen, RefreshCw } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { plural, shortSha } from "../lib/utils";
import type { RunManifest, SkillsResponse } from "../types";
import { Table } from "./RunPanelSections";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Collapsible } from "./ui/Collapsible";
import { Spinner } from "./ui/Spinner";

type Match = { label: string; tone: BadgeTone };

function compare(manifest: RunManifest | null, name: string, version: string, sha: string): Match | null {
  const used = manifest?.skills[name];
  if (!manifest) return null;
  if (!used) return { label: "не участвовал", tone: "neutral" };
  if (used.sha256 === sha) return { label: "как в запуске", tone: "success" };
  if (used.version !== version) return { label: `в запуске v${used.version}`, tone: "warn" };
  return { label: "текст изменён", tone: "warn" };
}

export function RunPanelRegistry({ manifest }: { manifest: RunManifest | null }) {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.skills());
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const skills = data?.skills ?? [];
  const agents = data?.agents ?? [];
  const changed = manifest ? skills.filter((s) => compare(manifest, s.name, s.version, s.sha256)?.tone === "warn").length : 0;
  const hint = loading && !data ? "загружаем…" : error ? "не удалось загрузить" : data ? `${plural(skills.length, "навык", "навыка", "навыков")} · ${plural(agents.length, "агент", "агента", "агентов")}` : undefined;

  return (
    <Collapsible
      title="Реестр навыков и агентов на сервере"
      hint={hint}
      icon={BookOpen}
      right={
        <>
          {changed > 0 && (
            <Badge tone="warn" dot>
              {plural(changed, "навык изменился", "навыка изменились", "навыков изменились")} с момента запуска
            </Badge>
          )}
          <Button size="sm" variant="ghost" icon={RefreshCw} loading={loading} onClick={() => void load()} aria-label="Обновить реестр" />
        </>
      }
    >
      {error ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          <span>Не удалось получить реестр: {error}</span>
          <Button size="sm" onClick={() => void load()}>Повторить</Button>
        </div>
      ) : !data ? (
        <div className="flex h-16 items-center justify-center">
          <Spinner showLabel label="Загружаем реестр" />
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-8">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Навыки</h4>
            <Table
              head={["Навык", "Роль", "Версия", "SHA-256", manifest ? "К запуску" : ""]}
              empty="На сервере не зарегистрировано ни одного навыка."
              rows={skills.map((s) => {
                const m = compare(manifest, s.name, s.version, s.sha256);
                return [
                  <span key="n" className="block min-w-0" title={s.description}>
                    <span className="font-mono text-xs font-medium text-zinc-900">{s.name}</span>
                    {s.description && <span className="block max-w-[320px] truncate text-xs text-zinc-500">{s.description}</span>}
                  </span>,
                  <span key="r" className="text-xs text-zinc-600">{s.role}</span>,
                  <Badge key="v" tone="accent" size="sm">v{s.version}</Badge>,
                  <span key="s" className="font-mono text-xs text-zinc-500" title={s.sha256}>{shortSha(s.sha256)}</span>,
                  m ? <Badge key="m" tone={m.tone} size="sm">{m.label}</Badge> : <span key="m" />,
                ];
              })}
            />
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Агенты</h4>
            <Table
              head={["Агент", "Версия", "SHA-256"]}
              empty="Агенты не зарегистрированы."
              rows={agents.map((a) => [
                <span key="n" className="font-mono text-xs font-medium text-zinc-900">{a.name}</span>,
                <Badge key="v" tone="accent" size="sm">v{a.version}</Badge>,
                <span key="s" className="font-mono text-xs text-zinc-500" title={a.sha256}>{shortSha(a.sha256)}</span>,
              ])}
            />
          </div>
        </div>
      )}
    </Collapsible>
  );
}
