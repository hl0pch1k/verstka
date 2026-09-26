// «Навыки и агенты» (developers): the live registry of the server (GET /api/skills) in one list with the agents,
// each compared with the version recorded in the open run_manifest.
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import type { RunManifest, SkillsResponse } from "../types";
import { Table } from "./RunPanelSections";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Collapsible } from "./ui/Collapsible";
import { Notice } from "./ui/Notice";
import { Spinner } from "./ui/Spinner";

type Match = { label: string; tone: BadgeTone };

function compare(manifest: RunManifest | null, name: string, version: string, sha: string): Match | null {
  if (!manifest) return null;
  const used = manifest.skills[name];
  if (!used) return { label: "не участвовал", tone: "neutral" };
  if (used.sha256 === sha) return { label: "как в запуске", tone: "success" };
  if (used.version !== version) return { label: `в запуске v${used.version}`, tone: "warn" };
  return { label: "текст изменён", tone: "warn" };
}

export function RunPanelRegistry({ manifest }: { manifest: RunManifest | null }) {
  const [open, setOpen] = useState(false);
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
    if (open && !data && !loading) void load();
    // load once, when the list is first opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const rows = data
    ? [
        ...data.skills.map((s) => ({ name: s.name, role: s.role, version: s.version, sha: s.sha256, description: s.description })),
        ...(data.agents ?? []).map((a) => ({ name: a.name, role: "агент", version: a.version, sha: a.sha256, description: "" })),
      ]
    : [];
  const count = data ? rows.length : manifest ? Object.keys(manifest.skills).length : null;

  return (
    <Collapsible
      variant="plain"
      title="Навыки и агенты"
      hint={count ?? undefined}
      open={open}
      onOpenChange={setOpen}
      keepMounted={false}
    >
      {/* the refresh sits over the list, so this row's chevron lines up with its neighbours' */}
      {data && !error && (
        <div className="mb-2 flex justify-end">
          <Button size="sm" variant="ghost" icon={RefreshCw} loading={loading} onClick={() => void load()}>
            Обновить
          </Button>
        </div>
      )}
      {error ? (
        <Notice tone="danger" title="Список навыков не загрузился" action={<Button variant="white" size="sm" onClick={() => void load()}>Повторить</Button>}>
          {error}
        </Notice>
      ) : !data ? (
        <div className="flex h-16 items-center justify-center">
          <Spinner showLabel label="Загружаю" />
        </div>
      ) : (
        // the list arrives where the (delayed) spinner stood: it fades in
        <div className="animate-fade">
        <Table
          head={["Название", "Роль", "Версия", manifest ? "К запуску" : ""]}
          empty="На сервере нет навыков"
          rows={rows.map((r) => {
            const m = compare(manifest, r.name, r.version, r.sha);
            return [
              <span key="n" className="block min-w-0" title={[r.description, r.sha].filter(Boolean).join("\n")}>
                <span className="font-mono text-caption font-semibold text-zinc-900">{r.name}</span>
              </span>,
              <span key="r" className="text-zinc-700">{r.role}</span>,
              <Badge key="v" tone="accent" size="sm">v{r.version}</Badge>,
              m ? <Badge key="m" tone={m.tone} size="sm">{m.label}</Badge> : <span key="m" />,
            ];
          })}
        />
        </div>
      )}
    </Collapsible>
  );
}
