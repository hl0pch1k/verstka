// Presentational pieces of the helper's feed: message bubbles, the typing indicator and the inline job status.
import { memo, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cn, fmtTime } from "../lib/utils";
import type { ActiveJob } from "../store";
import type { ChatMessage } from "../types";
import { Progress } from "./ui/Progress";

const BUBBLE = "min-w-0 break-words rounded-2xl px-4 py-2 text-body leading-6 [text-wrap:pretty]";

/** Russian typesetting for the assistant's prose: «900 000», «слайд 5», «6 категорий», «во вкладке», «из текста» and
 *  «— вывод» never break across lines: a one- or two-letter word never ends a line. */
function typeset(text: string): string {
  return text
    .replace(/(\d) (?=\d{3}(?!\d))/g, "$1 ")
    .replace(/(слайд\S*) (\d)/gi, "$1 $2")
    .replace(/(\d) (?=[а-яё%₽])/gi, "$1 ")
    .replace(/(?<=^|[\s(«])(в|во|и|к|ко|с|со|на|не|но|по|о|об|у|за|из|от|до|а|я) /gi, "$1 ")
    .replace(/ ([—–]) /g, " $1 ");
}

/** The assistant's text as paragraphs: «• » lines hang, so a list reads as a list; a blank line is a gap. */
function Paragraphs({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let gap = false;
  typeset(text)
    .split("\n")
    .forEach((raw, i) => {
      const line = raw.trimEnd();
      if (!line.trim()) return void (gap = out.length > 0);
      const bullet = /^\s*[•·-]\s+/.exec(line);
      out.push(
        <p key={i} className={cn(bullet && "pl-4 -indent-4", gap && "mt-2")}>
          {bullet ? (
            <>
              <span className="inline-block w-4 indent-0" aria-hidden>
                •
              </span>
              {line.slice(bullet[0].length)}
            </>
          ) : (
            line
          )}
        </p>,
      );
      gap = false;
    });
  return <>{out}</>;
}

/** An assistant bubble: grey, from the left edge of the feed. */
export function AssistantBubble({ children, title, className }: { children: ReactNode; title?: string; className?: string }) {
  return (
    <div className={cn("flex animate-fade-in", className)}>
      <div title={title} className={cn(BUBBLE, "max-w-[92%] rounded-tl-lg bg-zinc-100 text-zinc-900")}>
        {typeof children === "string" ? <Paragraphs text={children} /> : children}
      </div>
    </div>
  );
}

/** Folds a long text by height: 6 lines for the person's own text, 10 for a reply; the toggle shows only when needed. */
function useFold(text: string, expanded: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [foldable, setFoldable] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    // re-measured on resize too: a reply that arrives while the helper is hidden measures 0 until it is shown
    const measure = () => el.clientHeight > 0 && setFoldable(el.scrollHeight > el.clientHeight + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, expanded]);
  return { ref, foldable };
}

export const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const isUser = message.role === "user";
  const { ref, foldable } = useFold(message.text, expanded);
  const time = fmtTime(message.ts) || undefined; // `ts` is unix seconds (store.pushMessage)
  const toggle = (foldable || expanded) && (
    <button
      type="button"
      onClick={() => setExpanded((v) => !v)}
      aria-expanded={expanded}
      className={cn(
        "mt-1 block cursor-pointer text-footnote font-semibold",
        isUser
          ? "text-white underline decoration-white/60 underline-offset-2 hover:decoration-white focus-visible:outline-white"
          : "text-accent-700 hover:underline",
      )}
    >
      {expanded ? "Свернуть" : "Показать полностью"}
    </button>
  );

  if (!isUser)
    return (
      <div data-msg={message.id} className="flex animate-fade-in">
        <div title={time} className={cn(BUBBLE, "max-w-[92%] rounded-tl-lg bg-zinc-100 text-zinc-900")}>
          <div ref={ref} className={cn(!expanded && "line-clamp-[10]")}>
            <Paragraphs text={message.text} />
          </div>
          {toggle}
        </div>
      </div>
    );
  return (
    <div data-msg={message.id} className="flex animate-fade-in justify-end">
      <div title={time} className={cn(BUBBLE, "ml-auto max-w-[85%] rounded-br-lg bg-accent-fill text-white")}>
        <div ref={ref} className={cn("whitespace-pre-wrap", !expanded && "line-clamp-6")}>
          {message.text}
        </div>
        {toggle}
      </div>
    </div>
  );
});

/** Three dots in an assistant bubble while /api/chat is in flight. */
export function TypingIndicator() {
  return (
    <div role="status" aria-label="Помощник печатает" className="flex animate-fade-in">
      <div className="flex h-10 items-center gap-1 rounded-2xl rounded-tl-lg bg-zinc-100 px-4">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-2 w-2 animate-bounce rounded-full bg-zinc-400" style={{ animationDelay: `${i * 140}ms`, animationDuration: "900ms" }} />
        ))}
      </div>
    </div>
  );
}

/** An edit, a fix or a template analysis at work: its label, a bar and the share done. */
export function JobBubble({ job }: { job: ActiveJob }) {
  const failed = job.status === "failed";
  const done = job.status === "done";
  const pct = Math.round(job.progress * 100);
  // queued, or started with nothing done yet: the bar runs indeterminate, so a «0%» beside it would contradict it
  const waiting = !failed && !done && (job.status === "queued" || pct === 0);
  return (
    <div role="status" aria-live="polite" className="w-[92%] animate-fade-in">
      <div className={cn("rounded-2xl rounded-tl-lg px-4 py-3", failed ? "bg-red-50" : done ? "bg-emerald-50" : "bg-accent-50")}>
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-footnote font-semibold text-zinc-900" title={job.label}>{job.label}</span>
          {!failed && !waiting && <span className="shrink-0 text-caption tabular-nums text-zinc-500">{pct}%</span>}
        </div>
        <Progress className="mt-2" value={failed ? 1 : job.progress} tone={failed ? "error" : done ? "success" : "accent"} size="sm" indeterminate={waiting} />
      </div>
    </div>
  );
}
