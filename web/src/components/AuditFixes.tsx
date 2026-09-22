// «Аудит»: the collapsible list of applied fixes and the «Справочник проверок» reference loaded from /api/checks.
import { useEffect, useMemo, useState } from "react";
import { BookOpen, History, RefreshCw } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { plural, SEVERITY_LABEL } from "../lib/utils";
import type { CheckSpec } from "../types";
import { actionLabel, categoryLabel, KIND_SHORT, normalizeFix, resultTone, SEVERITY_RANK, SEVERITY_TONE } from "./AuditHelpers";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Collapsible } from "./ui/Collapsible";
import { EmptyState } from "./ui/EmptyState";
import { Spinner } from "./ui/Spinner";

export function AppliedFixes({ fixes, iterations }: { fixes: Record<string, unknown>[]; iterations: number }) {
  const rows = useMemo(() => fixes.map(normalizeFix), [fixes]);
  const hint = rows.length === 0 ? "исправления не применялись" : `${plural(rows.length, "запись", "записи", "записей")} · ${plural(iterations, "итерация", "итерации", "итераций")}`;
  return (
    <Collapsible title="Применённые исправления" hint={hint} icon={History} defaultOpen={false} keepMounted={false} bodyClassName="px-0 py-0">
      {rows.length === 0 ? (
        <EmptyState compact icon={History} title="Пока ничего не исправлялось" hint="Отметьте замечания и нажмите «Исправить выбранные» или примените все автоматические исправления." />
      ) : (
        <ol className="scroll-thin max-h-80 divide-y divide-zinc-100 overflow-y-auto">
          {rows.map((r, idx) => (
            <li key={idx} className="flex items-start gap-3 px-5 py-2.5 text-[13px]">
              <span className="w-5 shrink-0 pt-0.5 text-right text-[11px] tabular-nums text-zinc-400">{idx + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  {r.iteration !== null && (
                    <Badge tone="neutral" size="sm">
                      итерация {r.iteration}
                    </Badge>
                  )}
                  <span className="font-medium text-zinc-900">{actionLabel(r.action)}</span>
                  {r.action && <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">{r.action}</code>}
                  {r.outlineId && (
                    <span className="text-xs text-zinc-500">
                      слайд <code className="font-mono text-[11px] text-zinc-600">{r.outlineId}</code>
                    </span>
                  )}
                </div>
                {r.result && (
                  <div className="mt-1 flex items-start gap-1.5">
                    <Badge tone={resultTone(r.result)} size="sm" className="mt-px">
                      результат
                    </Badge>
                    <span className="min-w-0 break-words text-xs leading-4 text-zinc-600">{r.result}</span>
                  </div>
                )}
                {r.extra.length > 0 && (
                  <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-500">
                    {r.extra.map(([k, v]) => (
                      <div key={k} className="flex gap-1">
                        <dt className="font-mono text-[11px] text-zinc-400">{k}:</dt>
                        <dd className="break-all">{v}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Collapsible>
  );
}

type LoadState = { status: "idle" | "loading" | "error" | "ready"; checks: CheckSpec[]; error: string | null };

/** The check registry is static for a running server: fetched once per page load, shared across tab switches. */
let checksCache: CheckSpec[] | null = null;

export function ChecksReference() {
  const [open, setOpen] = useState(false);
  const [wanted, setWanted] = useState(false); // latches on the first open; the fetch is not tied to the open state
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>(() =>
    checksCache ? { status: "ready", checks: checksCache, error: null } : { status: "idle", checks: [], error: null },
  );

  useEffect(() => {
    if (!wanted || checksCache) return;
    let alive = true;
    setState({ status: "loading", checks: [], error: null });
    api.checks().then(
      (checks) => {
        checksCache = checks;
        if (alive) setState({ status: "ready", checks, error: null });
      },
      (e) => alive && setState({ status: "error", checks: [], error: errText(e) }),
    );
    return () => {
      alive = false;
    };
  }, [wanted, attempt]);

  const groups = useMemo(() => {
    const map = new Map<string, CheckSpec[]>();
    for (const c of state.checks) {
      const list = map.get(c.category);
      if (list) list.push(c);
      else map.set(c.category, [c]);
    }
    return [...map.entries()].map(([category, list]) => ({
      category,
      list: [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.id.localeCompare(b.id)),
    }));
  }, [state.checks]);

  const hint = state.status === "ready" ? `${plural(state.checks.length, "проверка", "проверки", "проверок")} · ${plural(groups.length, "категория", "категории", "категорий")}` : "что именно проверяет аудит";

  return (
    <Collapsible
      title="Справочник проверок"
      hint={hint}
      icon={BookOpen}
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setWanted(true);
      }}
      keepMounted={false}
      bodyClassName="px-0 py-0"
    >
      {state.status === "loading" && (
        <div className="flex items-center justify-center py-8">
          <Spinner showLabel label="Загружаю справочник" />
        </div>
      )}
      {state.status === "error" && (
        <EmptyState
          compact
          icon={BookOpen}
          title="Не удалось загрузить справочник"
          hint={state.error}
          action={
            <Button size="sm" icon={RefreshCw} onClick={() => setAttempt((n) => n + 1)}>
              Повторить
            </Button>
          }
        />
      )}
      {state.status === "ready" && groups.length === 0 && <EmptyState compact icon={BookOpen} title="Справочник пуст" hint="Сервер не вернул ни одной проверки." />}
      {state.status === "ready" && groups.length > 0 && (
        <div className="scroll-thin max-h-[28rem] overflow-y-auto">
          {groups.map(({ category, list }) => (
            <section key={category} className="border-b border-zinc-100 last:border-b-0">
              <h4 className="sticky top-0 z-[1] border-b border-zinc-100 bg-zinc-50 px-5 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                {categoryLabel(category)} <span className="font-normal normal-case tracking-normal text-zinc-400">· {list.length}</span>
              </h4>
              <ul className="divide-y divide-zinc-100">
                {list.map((c) => (
                  <li key={c.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 px-5 py-2.5">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[13px] font-medium text-zinc-900">{c.title}</span>
                        <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">{c.id}</code>
                      </div>
                      {c.description && <p className="mt-0.5 text-xs leading-4 text-zinc-500">{c.description}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <Badge tone={SEVERITY_TONE[c.severity]} size="sm">
                        {SEVERITY_LABEL[c.severity]}
                      </Badge>
                      <Badge tone={c.kind === "model" ? "accent" : "neutral"} size="sm">
                        {KIND_SHORT[c.kind]}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Collapsible>
  );
}
