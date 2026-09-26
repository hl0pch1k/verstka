// Quality check, below the remarks: what was already fixed automatically (in words), and which checks exist. The
// checks list, when it had to be fetched, fades in where the (delayed) spinner stood.
import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { CheckSpec } from "../types";
import { ACTION_DONE, categoryLabel, normalizeFix, SEVERITY_RANK, type FixRecord } from "./AuditHelpers";
import { SlideTag } from "./AuditIssues";
import { Button } from "./ui/Button";
import { Collapsible } from "./ui/Collapsible";
import { Notice } from "./ui/Notice";
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

export function AppliedFixes({ fixes, slideOf, templateSlide, onShow }: {
  fixes: Record<string, unknown>[];
  /** outline id (sl3) → 1-based slide number */
  slideOf(outlineId: string): number | null;
  /** pattern id (p9) → slide number of the template */
  templateSlide(patternId: string): number | null;
  /** Opens the slide on the result screen (the slide tag is a button then). */
  onShow?(slide: number): void;
}) {
  // the same fix repeated by the passes of the check is one row with its count (×2)
  const rows = useMemo(() => {
    const out: Array<{ slide: number | null; title: string; extra: string | null; n: number }> = [];
    const seen = new Map<string, (typeof out)[number]>();
    for (const r of fixes.map(normalizeFix)) {
      const d = describeFix(r, slideOf, templateSlide);
      const key = `${d.slide ?? ""}|${d.title}|${d.extra ?? ""}`;
      const had = seen.get(key);
      if (had) had.n += 1;
      else {
        const row = { ...d, n: 1 };
        seen.set(key, row);
        out.push(row);
      }
    }
    return out;
  }, [fixes, slideOf, templateSlide]);
  if (rows.length === 0) return null;
  return (
    <Collapsible title="Исправлено автоматически" hint={plural(fixes.length, "правка", "правки", "правок")} defaultOpen={false} keepMounted={false}>
      {/* full-bleed rows in the card's 24px body; the last row's padding is part of the card's bottom */}
      <ol className="-mx-6 -mb-3 divide-y divide-zinc-100">
        {rows.map((r, idx) => (
          <li key={idx} className="flex items-start gap-3 px-6 py-3 text-footnote">
            <SlideTag slide={r.slide} onShow={onShow} />
            <span className="min-w-0 max-w-[680px] flex-1 text-zinc-900">
              {r.title}
              {r.extra && <span className="text-zinc-500">: {r.extra}</span>}
              {r.n > 1 && <span className="tabular-nums text-zinc-500"> ×{r.n}</span>}
            </span>
          </li>
        ))}
      </ol>
    </Collapsible>
  );
}

type LoadState = { status: "idle" | "loading" | "error" | "ready"; checks: CheckSpec[]; error: string | null };

/** The check registry is static for a running server: fetched once per page load. */
let checksCache: CheckSpec[] | null = null;

export function ChecksReference({ total }: { total?: number }) {
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

  // the list fades in only when it replaces the spinner (a cached list is simply there when the section opens)
  const fetched = useRef(false);
  if (state.status === "loading") fetched.current = true;
  const groups = useMemo(() => {
    const map = new Map<string, CheckSpec[]>();
    for (const c of state.checks) map.set(c.category, [...(map.get(c.category) ?? []), c]);
    return [...map.entries()].map(([category, list]) => ({ category, list: [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.title.localeCompare(b.title, "ru")) }));
  }, [state.checks]);

  return (
    <Collapsible
      title="Что проверяется"
      hint={total ? plural(total, "проверка", "проверки", "проверок") : undefined}
      open={open}
      onOpenChange={setOpen}
      keepMounted={false}
    >
      {state.status === "loading" && <div className="flex justify-center py-6"><Spinner showLabel label="Загружаю список" /></div>}
      {state.status === "error" && (
        <Notice tone="danger" title="Список проверок не загрузился" action={<Button variant="white" size="sm" icon={RefreshCw} onClick={() => setAttempt((n) => n + 1)}>Повторить</Button>}>
          {state.error}
        </Notice>
      )}
      {state.status === "ready" && (
        <div className={fetched.current ? "animate-fade" : undefined}>
          {groups.map(({ category, list }) => (
          <section key={category} className="pt-4 first:pt-0">
            <h4 className="mb-1 text-footnote font-semibold text-zinc-900">{categoryLabel(category)}</h4>
            <ul>
              {list.map((c) => (
                <li key={c.id} className="flex items-center gap-3 py-1 text-footnote">
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", c.severity === "error" ? "bg-red-500" : c.severity === "warn" ? "bg-amber-500" : "bg-accent")} aria-hidden />
                  <span className="min-w-0 flex-1 text-zinc-700">
                    {c.title}
                    {c.kind === "model" && <span className="text-zinc-500"> · моделью</span>}
                  </span>
                  <span className="shrink-0 text-zinc-500">{SEVERITY_LABEL[c.severity].toLowerCase()}</span>
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
