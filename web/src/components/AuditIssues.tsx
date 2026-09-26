// Quality check: remarks grouped by slide. A remark reads as a sentence — what is wrong, what to do, whether it can
// be fixed automatically. Motion: a remark being fixed dims while the job runs, and a remark (or a whole slide's group)
// that a fix removed folds away (300 ms glide) instead of vanishing, so the list below glides up.
import { useEffect, useState } from "react";
import { ArrowUpRight, Check } from "lucide-react";
import { MOTION, prefersReducedMotion } from "../lib/motion";
import { cn, SEVERITY_LABEL } from "../lib/utils";
import type { Issue, Severity } from "../types";
import { actionLabel, isFixable, SEVERITY_RANK, slideLabel, type SlideGroup } from "./AuditHelpers";
import { Button } from "./ui/Button";
import { Collapse } from "./ui/Collapse";

/** A remark as a person reads it: the colour codes of a contrast note stay in the check's data, not in the sentence
 *  («(#FFFFFF на #0077FF, нужно 4,5:1)» → «(нужно 4,5:1)»). */
export const plainIssue = (text: string) =>
  text
    .replace(/\s*\(#[0-9a-f]{3,8}\s+на\s+#[0-9a-f]{3,8}(?:,\s*([^)]*))?\)/gi, (_m, rest?: string) => (rest ? ` (${rest})` : ""))
    .replace(/(\d)\.(\d):1/g, "$1,$2:1");

const capitalFirst = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

/** A list whose items fold away when they leave (a fixed remark, a slide with no remarks left): an item that just left
 *  stays in its place, marked `leaving`, for the length of the fold (300 ms), then goes. A list that is swapped whole
 *  (another variant) is keyed by its owner instead. */
export function useLeaving<T>(items: T[], id: (t: T) => string, order: (a: T, b: T) => number): Array<{ item: T; leaving: boolean }> {
  // derived during render (React's «state from the previous render» pattern): the item that left is still in the very
  // commit that drops it from `items`, so its fold continues on the same element instead of a remount
  // compared by ids, not by identity: a list rebuilt with the same items is no change (and never a render loop)
  const sig = items.map(id).join("\u0000");
  const [prev, setPrev] = useState({ sig, items });
  const [gone, setGone] = useState<Map<string, T>>(() => new Map());
  if (sig !== prev.sig) {
    const now = new Set(items.map(id));
    const left = prev.items.filter((t) => !now.has(id(t)));
    setPrev({ sig, items });
    if (left.length && !prefersReducedMotion()) setGone((cur) => new Map([...cur, ...left.map((t) => [id(t), t] as const)]));
  }
  // the folded ones go once the fold has played (a later departure restarts the wait: they are folded already)
  useEffect(() => {
    if (!gone.size) return;
    const t = window.setTimeout(() => setGone(new Map()), MOTION.slow);
    return () => window.clearTimeout(t);
  }, [gone]);
  const now = new Set(items.map(id));
  return [
    ...items.map((item) => ({ item, leaving: false })),
    ...[...gone.values()].filter((t) => !now.has(id(t))).map((item) => ({ item, leaving: true })),
  ].sort((a, b) => order(a.item, b.item));
}

const DOT: Record<Severity, string> = { error: "bg-red-500", warn: "bg-amber-500", info: "bg-accent" };
const TEXT: Record<Severity, string> = { error: "text-red-600", warn: "text-amber-700", info: "text-accent-700" };

/** One remark: severity, message, advice and the automatic fix. Shared by the quality tab and «Почему так». */
export function IssueLine({ issue, checked, disabled, onCheck, highlighted, onHover, dim, className }: {
  issue: Issue;
  checked?: boolean;
  disabled?: boolean;
  onCheck?(on: boolean): void;
  highlighted?: boolean;
  onHover?(on: boolean): void;
  /** The remark is being fixed right now: it steps back (no pulse) until the job ends. */
  dim?: boolean;
  className?: string;
}) {
  const fixable = isFixable(issue);
  const selectable = fixable && !!onCheck;
  return (
    <div
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      className={cn(
        "flex gap-3 px-6 py-3 [transition:background-color_150ms_var(--ease-std),opacity_200ms_var(--ease-std)]",
        checked ? "bg-accent-50" : highlighted ? "bg-zinc-50" : "",
        dim && "opacity-60",
        className,
      )}
    >
      {selectable ? (
        <button
          type="button"
          role="checkbox"
          aria-checked={!!checked}
          aria-label="Отметить для исправления"
          disabled={disabled}
          onClick={() => onCheck?.(!checked)}
          className={cn(
            "tap flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded disabled:cursor-not-allowed disabled:opacity-40",
            checked ? "bg-accent-fill text-white" : "bg-white ring-2 ring-inset ring-zinc-300 hover:ring-accent",
          )}
        >
          {checked && <Check className="h-3.5 w-3.5 animate-pop" strokeWidth={2.5} aria-hidden />}
        </button>
      ) : (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center" aria-hidden>
          <span className={cn("h-2 w-2 rounded-full", DOT[issue.severity])} />
        </span>
      )}
      <div className="min-w-0 max-w-[680px] flex-1">
        <p className="text-body text-zinc-900">
          <span className={cn("mr-2 text-footnote font-semibold", TEXT[issue.severity])}>{SEVERITY_LABEL[issue.severity]}</span>
          {plainIssue(issue.message)}
        </p>
        {issue.suggestion && <p className="mt-1 text-footnote text-zinc-500">{issue.suggestion}</p>}
        {(fixable || issue.kind === "model") && (
          <p className="mt-1 flex flex-wrap gap-x-3 text-footnote">
            {fixable && <span className="text-accent-700">Можно исправить автоматически: {actionLabel(issue.autofix?.action)}</span>}
            {issue.kind === "model" && <span className="text-zinc-500">Замечание модели</span>}
          </p>
        )}
      </div>
    </div>
  );
}

interface GroupProps {
  group: SlideGroup;
  headline: string | null;
  current: boolean;
  selected: Set<string>;
  disabled: boolean;
  onShow(): void;
  onSelect(id: string, on: boolean): void;
  /** The remarks a running fix is working on (they dim). */
  fixing?(issue: Issue): boolean;
}

const byRank = (a: Issue, b: Issue) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.check_id.localeCompare(b.check_id);

export function SlideIssueGroup({ group, headline, current, selected, disabled, onShow, onSelect, fixing }: GroupProps) {
  const deck = group.slide === 0;
  const rows = useLeaving(group.issues, (i) => i.id, byRank);
  return (
    <section className={cn("overflow-hidden rounded-2xl bg-white pb-3 transition-shadow duration-150", current ? "shadow-selected" : "shadow-card")}>
      <header className="flex items-center gap-3 px-6 pb-2 pt-6">
        <div className="min-w-0 flex-1">
          <h3 className="text-title3 font-semibold text-zinc-900">{slideLabel(group.slide)}</h3>
          {headline && (
            <p className="mt-0.5 truncate text-footnote text-zinc-500" title={headline}>
              {headline}
            </p>
          )}
        </div>
        {!deck && (
          <Button variant="ghost" size="sm" iconRight={ArrowUpRight} onClick={onShow}>
            На слайде
          </Button>
        )}
      </header>
      {/* a fixed remark folds away (its divider with it); the ones below glide up */}
      <ul>
        {rows.map(({ item: issue, leaving }, i) => (
          <li key={issue.id}>
            <Collapse open={!leaving}>
              <IssueLine
                issue={issue}
                checked={selected.has(issue.id)}
                disabled={disabled || leaving}
                dim={leaving || fixing?.(issue)}
                onCheck={(on) => onSelect(issue.id, on)}
                className={i > 0 ? "border-t border-zinc-100" : undefined}
              />
            </Collapse>
          </li>
        ))}
      </ul>
    </section>
  );
}

const TAG = "inline-flex h-5 min-w-[72px] shrink-0 items-center justify-center rounded-lg px-2 text-caption font-semibold tabular-nums";

/** «Слайд 3» (opens the slide) or «Все» for the whole deck: the first column of the quality lists. */
export function SlideTag({ slide, onShow }: { slide: number | null; onShow?(slide: number): void }) {
  if (!slide) {
    return (
      <span className={cn(TAG, "bg-zinc-100 text-zinc-600")} title="Все слайды">
        Все
      </span>
    );
  }
  return onShow ? (
    <button type="button" onClick={() => onShow(slide)} title="Показать на слайде" className={cn(TAG, "tap cursor-pointer bg-accent-50 text-accent-700 hover:bg-accent-100")}>
      Слайд {slide}
    </button>
  ) : (
    <span className={cn(TAG, "bg-zinc-100 text-zinc-600")}>Слайд {slide}</span>
  );
}

/** The folded notes of the rules: one row per note, the slide first. */
export function MinorNotes({ issues, onShow }: { issues: Issue[]; onShow(slide: number): void }) {
  return (
    <ul className="-mx-6 -mb-3 divide-y divide-zinc-100">
      {issues.map((i) => (
        <li key={i.id} className="flex items-start gap-3 px-6 py-3 text-footnote">
          <SlideTag slide={i.slide > 0 ? i.slide : null} onShow={onShow} />
          <span className="min-w-0 max-w-[680px] flex-1 text-zinc-700">{capitalFirst(plainIssue(i.message))}</span>
        </li>
      ))}
    </ul>
  );
}
