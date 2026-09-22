// «Аудит»: issues grouped by slide — an accordion per slide with selectable, fixable issue rows.
import { ChevronDown, Eye, Wand2 } from "lucide-react";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { Issue, Severity } from "../types";
import { actionLabel, isFixable, KIND_SHORT, SEVERITIES, SEVERITY_TONE, slideLabel, type SlideGroup } from "./AuditHelpers";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

interface GroupProps {
  group: SlideGroup;
  headline: string | null;
  open: boolean;
  current: boolean;
  selected: Set<string>;
  disabled: boolean;
  onToggle(): void;
  onPick(): void;
  onShow(): void;
  onSelect(id: string, on: boolean): void;
  onSelectGroup(on: boolean): void;
}

export function SlideIssueGroup({ group, headline, open, current, selected, disabled, onToggle, onPick, onShow, onSelect, onSelectGroup }: GroupProps) {
  const fixableIds = group.issues.filter(isFixable).map((i) => i.id);
  const pickedHere = fixableIds.filter((id) => selected.has(id)).length;
  const allPicked = fixableIds.length > 0 && pickedHere === fixableIds.length;
  const deck = group.slide === 0;

  return (
    <section className={cn("rounded-xl border bg-white shadow-card transition-colors", current ? "border-accent ring-1 ring-accent/30" : "border-zinc-200")}>
      <div className="flex min-h-[48px] items-center gap-2 pl-3 pr-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? "Свернуть" : "Развернуть"}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform duration-200", open && "rotate-180")} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => {
            onPick();
            if (!open) onToggle();
          }}
          title={deck ? "Замечания ко всей колоде" : "Выбрать слайд"}
          className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md py-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
        >
          <span className={cn("shrink-0 text-sm font-semibold", current ? "text-accent-700" : "text-zinc-900")}>{slideLabel(group.slide)}</span>
          {headline && <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-500">{headline}</span>}
        </button>
        <div className="flex shrink-0 items-center gap-1.5">
          {SEVERITIES.filter((s) => group.counts[s] > 0).map((s) => (
            <Badge key={s} tone={SEVERITY_TONE[s]} size="sm" dot title={`${SEVERITY_LABEL[s]}: ${group.counts[s]}`}>
              {group.counts[s]}
            </Badge>
          ))}
          {fixableIds.length > 0 && (
            <label className="ml-1 flex cursor-pointer select-none items-center gap-1.5 text-xs text-zinc-500" title="Отметить все исправимые замечания слайда">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-zinc-300 accent-accent focus:ring-accent/30"
                checked={allPicked}
                disabled={disabled}
                onChange={(e) => onSelectGroup(e.target.checked)}
              />
              {plural(fixableIds.length, "исправимое", "исправимых", "исправимых")}
            </label>
          )}
          {!deck && (
            <Button size="sm" variant="ghost" icon={Eye} onClick={onShow} className="ml-1">
              Показать на слайде
            </Button>
          )}
        </div>
      </div>
      {open && (
        <ul className="divide-y divide-zinc-100 border-t border-zinc-100">
          {group.issues.map((issue) => (
            <IssueRow key={issue.id} issue={issue} checked={selected.has(issue.id)} disabled={disabled} onCheck={(on) => onSelect(issue.id, on)} />
          ))}
        </ul>
      )}
    </section>
  );
}

interface RowProps {
  issue: Issue;
  checked: boolean;
  disabled: boolean;
  onCheck(on: boolean): void;
}

const ROW_ACCENT: Record<Severity, string> = { error: "bg-red-500", warn: "bg-amber-500", info: "bg-sky-500" };

export function IssueRow({ issue, checked, disabled, onCheck }: RowProps) {
  const fixable = isFixable(issue);
  const control = fixable ? (
    <input
      type="checkbox"
      aria-label="Выбрать для исправления"
      className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-accent focus:ring-accent/30"
      checked={checked}
      disabled={disabled}
      onChange={(e) => onCheck(e.target.checked)}
    />
  ) : (
    <span className="mt-0.5 block h-4 w-4" aria-hidden />
  );

  return (
    <li className={cn("relative flex gap-3 px-4 py-3 transition-colors", checked && "bg-accent-50/60")}>
      <span className={cn("absolute inset-y-2 left-0 w-0.5 rounded-r", ROW_ACCENT[issue.severity])} aria-hidden />
      <div className="shrink-0 pl-1">{control}</div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={SEVERITY_TONE[issue.severity]} size="sm">
            {SEVERITY_LABEL[issue.severity]}
          </Badge>
          <Badge tone={issue.kind === "model" ? "accent" : "neutral"} size="sm" title={issue.kind === "model" ? "Проверка моделью (LLM/VLM)" : "Детерминированная проверка"}>
            {KIND_SHORT[issue.kind]}
          </Badge>
          <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600">{issue.check_id}</code>
          {issue.element_ids.length > 0 && (
            <span className="text-[11px] text-zinc-400" title={issue.element_ids.join(", ")}>
              {plural(issue.element_ids.length, "элемент", "элемента", "элементов")}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[13px] leading-5 text-zinc-900">{issue.message}</p>
        {issue.suggestion && (
          <p className="mt-1 text-[13px] leading-5 text-zinc-600">
            <span className="font-medium text-zinc-500">Рекомендация: </span>
            {issue.suggestion}
          </p>
        )}
        {issue.autofix && (
          <p className={cn("mt-1.5 flex items-start gap-1.5 text-xs leading-4", fixable ? "text-accent-700" : "text-zinc-400")}>
            <Wand2 className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              <span className="font-medium">{fixable ? "Автоисправление" : "Автоисправление недоступно"}</span>
              {fixable && ` · ${actionLabel(issue.autofix.action)}`}
              {issue.autofix.description && ` — ${issue.autofix.description}`}
            </span>
          </p>
        )}
      </div>
    </li>
  );
}
