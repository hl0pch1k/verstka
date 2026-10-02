// The right column of a build: the agent's steps as a short checklist (done, at work, waiting; what each came to) and,
// under it, everything the agent has said, as a log in mono — the time since the start, who spoke (in the colour of
// the step), the slide, the words. New lines fade up; the log follows them unless the reader has scrolled up to read.
// The log is not a live region (the stage's title announces the steps; the lines would drown a screen reader).
import { useLayoutEffect, useRef } from "react";
import { Check, Loader2, Minus } from "lucide-react";
import type { PhaseKey, TimelineRow } from "../../lib/agent";
import { smoothScroll } from "../../lib/motion";
import type { LogLine } from "../../lib/stage";
import { cn } from "../../lib/utils";

// each role's colour on white (≥ 4.5:1)
const ROLE_TONE: Record<PhaseKey, string> = {
  writer: "text-pink-700",
  analyst: "text-accent-700",
  architect: "text-cyan-700",
  designer: "text-[#5B3FD9]",
  critic: "text-amber-700",
  revise: "text-emerald-700",
  layout: "text-zinc-600",
  check: "text-zinc-600",
};

function StepIcon({ status }: { status: TimelineRow["status"] }) {
  return (
    <span
      className={cn(
        "flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors duration-300",
        status === "done" && "bg-accent-fill text-white",
        status === "active" && "text-accent",
        (status === "pending" || status === "skipped") && "text-zinc-300",
      )}
      aria-hidden
    >
      {status === "done" ? (
        <Check key="d" className="h-3 w-3 animate-pop" strokeWidth={3} />
      ) : status === "active" ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : status === "skipped" ? (
        <Minus className="h-3.5 w-3.5 text-zinc-400" strokeWidth={2.5} />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
      )}
    </span>
  );
}

const STATUS_WORD: Record<TimelineRow["status"], string> = { done: "готово", active: "сейчас", pending: "впереди", skipped: "пропущен" };

export function AgentLog({ rows, lines, running, className }: { rows: TimelineRow[]; lines: LogLine[]; running: boolean; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  // the lines there when the log mounts come in with the page; later ones fade up
  const known = useRef<Set<string> | null>(null);
  if (known.current === null) known.current = new Set(lines.map((l) => l.key));
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);
  useLayoutEffect(() => {
    const el = box.current;
    if (el && stick.current && el.scrollHeight > el.clientHeight) el.scrollTo({ top: el.scrollHeight, behavior: smoothScroll() });
  }, [lines.length]);
  return (
    <aside aria-label="Работа агента" className={cn("flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-card", className)}>
      <div className="flex shrink-0 items-center gap-2 px-4 pb-2 pt-4">
        <h2 className="text-title3 font-semibold text-zinc-900">Агент</h2>
        {running && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-caption font-semibold text-accent-700">
            <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-accent" aria-hidden />
            работает
          </span>
        )}
      </div>
      <ol className="shrink-0 space-y-1 px-4 pb-3">
        {rows.map((r) => (
          <li key={r.key} className="flex h-7 items-center gap-2.5">
            <StepIcon status={r.status} />
            <span className={cn("shrink-0 text-footnote font-semibold transition-colors duration-150", r.status === "pending" ? "text-zinc-500" : "text-zinc-900")}>{r.title}</span>
            <span className="sr-only">: {STATUS_WORD[r.status]}</span>
            {(r.note || r.status === "active") && (
              <span key={r.note ?? r.hint} className="min-w-0 flex-1 animate-fade truncate text-right text-caption text-zinc-500" title={r.note ?? r.hint}>
                {r.note ?? r.hint}
              </span>
            )}
          </li>
        ))}
      </ol>
      <div className="mx-4 h-px shrink-0 bg-zinc-900/[0.07]" aria-hidden />
      <div ref={box} className="scroll-thin relative min-h-0 flex-1 overflow-y-auto [mask-image:linear-gradient(to_bottom,transparent,#000_16px)]">
        <ol className="space-y-2.5 px-4 pb-4 pt-4 font-mono text-[12px] leading-[18px]" aria-live="off">
          {lines.length === 0 && <li className="text-zinc-400">Агент ещё не сказал ни слова…</li>}
          {lines.map((l) => (
            <li key={l.key} className={cn("flex gap-2", !known.current?.has(l.key) && "animate-fade-in")}>
              <span className="w-[4ch] shrink-0 tabular-nums text-zinc-400">{l.time ?? ""}</span>
              <span className="min-w-0 flex-1 text-zinc-700 [overflow-wrap:anywhere]">
                <span className={cn("mr-1.5 font-semibold uppercase tracking-[0.06em]", ROLE_TONE[l.phase])}>{l.role}</span>
                {l.slide !== null && <span className="mr-1.5 text-zinc-500">сл.{l.slide}</span>}
                {l.text}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </aside>
  );
}
