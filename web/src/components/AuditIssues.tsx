// Quality check: remarks grouped by slide. A remark reads as a sentence — what is wrong, what to do, whether it can
// be fixed automatically; the check id stays in a tooltip for those who want it.
import { ArrowUpRight, Check } from "lucide-react";
import { cn, SEVERITY_LABEL } from "../lib/utils";
import type { Issue, Severity } from "../types";
import { actionLabel, isFixable, SEVERITIES, slideLabel, type SlideGroup } from "./AuditHelpers";

const DOT: Record<Severity, string> = { error: "bg-red-500", warn: "bg-amber-400", info: "bg-sky-400" };
const TEXT: Record<Severity, string> = { error: "text-red-700", warn: "text-amber-700", info: "text-sky-700" };

/** One remark: severity, message, advice and the automatic fix. Shared by the quality tab and «почему слайд такой». */
export function IssueLine({ issue, checked, disabled, onCheck, highlighted, onHover }: {
  issue: Issue;
  checked?: boolean;
  disabled?: boolean;
  onCheck?(on: boolean): void;
  highlighted?: boolean;
  onHover?(on: boolean): void;
}) {
  const fixable = isFixable(issue);
  const selectable = fixable && !!onCheck;
  return (
    <li
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      className={cn("flex gap-3 px-5 py-3.5 transition-colors", checked ? "bg-accent-50/70" : highlighted ? "bg-zinc-50" : "")}
      title={`Проверка: ${issue.check_id}`}
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
            "mt-0.5 flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50",
            checked ? "bg-accent text-white" : "bg-white shadow-[inset_0_0_0_1.5px_#C9CDD2] hover:shadow-[inset_0_0_0_1.5px_#0077FF]",
          )}
        >
          {checked && <Check className="h-3.5 w-3.5 animate-pop" strokeWidth={3} aria-hidden />}
        </button>
      ) : (
        <span className={cn("mt-[7px] h-2 w-2 shrink-0 rounded-full", DOT[issue.severity])} aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-[14px] leading-5 text-zinc-900">
          <span className={cn("mr-1.5 text-[13px] font-semibold", TEXT[issue.severity])}>{SEVERITY_LABEL[issue.severity]}.</span>
          {issue.message}
        </p>
        {issue.suggestion && <p className="mt-1 text-[13px] leading-5 text-zinc-500">{issue.suggestion}</p>}
        {(fixable || issue.kind === "model") && (
          <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs font-medium">
            {fixable && <span className="text-accent-700">Исправится автоматически: {actionLabel(issue.autofix?.action)}</span>}
            {issue.kind === "model" && <span className="text-zinc-500">Замечание открытой модели по картинке слайда</span>}
          </p>
        )}
      </div>
    </li>
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
}

export function SlideIssueGroup({ group, headline, current, selected, disabled, onShow, onSelect }: GroupProps) {
  const deck = group.slide === 0;
  return (
    <section className={cn("overflow-hidden rounded-2xl bg-white transition-shadow", current ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card")}>
      <header className="flex items-center gap-3 px-5 pb-2 pt-4">
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold text-zinc-900">{slideLabel(group.slide)}</p>
          {headline && <p className="truncate text-[13px] text-zinc-500">{headline}</p>}
        </div>
        <span className="flex shrink-0 items-center gap-2 text-xs font-medium text-zinc-500">
          {SEVERITIES.filter((s) => group.counts[s] > 0).map((s) => (
            <span key={s} className="flex items-center gap-1" title={SEVERITY_LABEL[s]}>
              <span className={cn("h-2 w-2 rounded-full", DOT[s])} aria-hidden />
              {group.counts[s]}
            </span>
          ))}
        </span>
        {!deck && (
          <button type="button" onClick={onShow} className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-full px-2.5 py-1.5 text-[13px] font-semibold text-accent-700 transition-colors hover:bg-accent-50">
            На слайде <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </header>
      <ul className="divide-y divide-zinc-100 pb-1">
        {group.issues.map((issue) => (
          <IssueLine key={issue.id} issue={issue} checked={selected.has(issue.id)} disabled={disabled} onCheck={(on) => onSelect(issue.id, on)} />
        ))}
      </ul>
    </section>
  );
}
