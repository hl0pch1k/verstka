// Quality check, below the remarks: what was already fixed automatically (in words), and which checks exist.
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { CheckSpec } from "../types";
import { ACTION_DONE, categoryLabel, normalizeFix, SEVERITY_RANK, type FixRecord } from "./AuditHelpers";
import { Button } from "./ui/Button";
import { Collapsible } from "./ui/Collapsible";
import { Spinner } from "./ui/Spinner";

/** «rematch → p9» → «слайд 9 шаблона»; anything else is shown as is. */
function resultText(result: string | null, templateSlide: (patternId: string) => number | null): string | null {
  if (!result) return null;
  const m = result.match(/→\s*(p\d+)/);
  if (m) {
    const n = templateSlide(m[1]);
    return n ? `теперь по образцу слайда ${n} шаблона` : null;
  }
  // technical tokens and the English lines of older runs add nothing in words
  return /[а-яё]/i.test(result) && !/^slide \d+:/.test(result) ? result : null;
}

/** A fix record in words: the slide it touched, what was done and, when known, how. */
export function describeFix(r: FixRecord, slideOf: (outlineId: string) => number | null, templateSlide: (patternId: string) => number | null): { slide: number | null; title: string; extra: string | null } {
  const said = resultText(r.result, templateSlide);
  // an in-place edit describes itself in full («Шрифт заменён на Play…»); the others get a done-deed title
  const own = r.action === "xml" && said ? said : null;
  return {
    slide: r.slide ?? (r.outlineId ? slideOf(r.outlineId) : null),
    title: own ?? ACTION_DONE[r.kind ?? ""] ?? ACTION_DONE[r.action ?? ""] ?? "Поправлено оформление",
    extra: own ? null : said,
  };
}

export function AppliedFixes({ fixes, slideOf, templateSlide }: {
  fixes: Record<string, unknown>[];
  /** outline id (sl3) → 1-based slide number */
  slideOf(outlineId: string): number | null;
  /** pattern id (p9) → slide number of the template */
  templateSlide(patternId: string): number | null;
}) {
  const rows = useMemo(() => fixes.map(normalizeFix), [fixes]);
  if (rows.length === 0) return null;
  return (
    <Collapsible title="Что уже исправлено автоматически" hint={plural(rows.length, "правка", "правки", "правок")} defaultOpen={false} keepMounted={false} bodyClassName="px-0 pb-2 pt-0">
      <ol className="divide-y divide-zinc-100">
        {rows.map((r, idx) => {
          const { slide: n, title, extra } = describeFix(r, slideOf, templateSlide);
          return (
            <li key={idx} className="flex items-baseline gap-3 px-6 py-2.5 text-[13px]">
              <span className="w-16 shrink-0 text-zinc-500">{n ? `Слайд ${n}` : "Все слайды"}</span>
              <span className="min-w-0 text-zinc-900">
                {title}
                {extra && <span className="text-zinc-500"> — {extra}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </Collapsible>
  );
}

type LoadState = { status: "idle" | "loading" | "error" | "ready"; checks: CheckSpec[]; error: string | null };

/** The check registry is static for a running server: fetched once per page load. */
let checksCache: CheckSpec[] | null = null;

export function ChecksReference() {
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>(() => (checksCache ? { status: "ready", checks: checksCache, error: null } : { status: "idle", checks: [], error: null }));

  useEffect(() => {
    if (!open || checksCache) return;
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
  }, [open, attempt]);

  const groups = useMemo(() => {
    const map = new Map<string, CheckSpec[]>();
    for (const c of state.checks) map.set(c.category, [...(map.get(c.category) ?? []), c]);
    return [...map.entries()].map(([category, list]) => ({ category, list: [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.title.localeCompare(b.title, "ru")) }));
  }, [state.checks]);

  return (
    <Collapsible title="Какие проверки выполняются" hint="правила шаблона, читаемость, целостность файла" open={open} onOpenChange={setOpen} keepMounted={false} bodyClassName="px-0 pb-3 pt-0">
      {state.status === "loading" && <div className="flex justify-center py-6"><Spinner showLabel label="Загружаю список" /></div>}
      {state.status === "error" && (
        <div className="flex items-center gap-3 px-6 py-4 text-[13px] text-red-700">
          Не удалось загрузить список: {state.error}
          <Button size="sm" icon={RefreshCw} onClick={() => setAttempt((n) => n + 1)}>Повторить</Button>
        </div>
      )}
      {state.status === "ready" &&
        groups.map(({ category, list }) => (
          <section key={category} className="px-6 pt-3">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">{categoryLabel(category)}</h4>
            <ul>
              {list.map((c) => (
                <li key={c.id} className="flex items-baseline gap-3 py-1.5" title={c.id}>
                  <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 self-start rounded-full", c.severity === "error" ? "bg-red-500" : c.severity === "warn" ? "bg-amber-400" : "bg-sky-400")} aria-hidden />
                  <span className="min-w-0 flex-1 text-[13px] text-zinc-800">
                    {c.title}
                    {c.kind === "model" && <span className="text-zinc-400"> · открытой моделью</span>}
                  </span>
                  <span className="shrink-0 text-xs text-zinc-400">{SEVERITY_LABEL[c.severity].toLowerCase()}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </Collapsible>
  );
}
