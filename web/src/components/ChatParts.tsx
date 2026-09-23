// Presentational pieces of the chat feed: message bubbles, the typing indicator and the inline job status.
import { memo, useState } from "react";
import { Sparkles } from "lucide-react";
import { cn } from "../lib/utils";
import type { ActiveJob } from "../store";
import type { ChatMessage } from "../types";
import { Progress } from "./ui/Progress";

const COLLAPSE_AFTER = 640; // long briefs are folded so the feed stays readable

/** `ts` is unix seconds (see store.pushMessage). */
function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function AgentAvatar({ hidden = false }: { hidden?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-white",
        hidden && "invisible",
      )}
    >
      <Sparkles className="h-3.5 w-3.5" strokeWidth={2.25} />
    </span>
  );
}

export interface MessageBubbleProps {
  message: ChatMessage;
  /** First message in a run of the same author: shows the avatar and adds a larger gap above. */
  first: boolean;
}

export const MessageBubble = memo(function MessageBubble({ message, first }: MessageBubbleProps) {
  const [expanded, setExpanded] = useState(false);
  const isUser = message.role === "user";
  const foldable = isUser && message.text.length > COLLAPSE_AFTER;
  const text = foldable && !expanded ? `${message.text.slice(0, COLLAPSE_AFTER).trimEnd()}…` : message.text;
  const time = fmtTime(message.ts);

  if (isUser) {
    return (
      <div className={cn("flex animate-fade-in flex-col items-end", first ? "mt-4" : "mt-1.5")}>
        <div className="max-w-[86%] whitespace-pre-wrap break-words rounded-[18px] rounded-br-md bg-accent-100 px-3.5 py-2.5 text-[13px] leading-5 text-zinc-900">
          {text}
          {foldable && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1.5 block cursor-pointer text-xs font-semibold text-accent-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              {expanded ? "Свернуть" : `Показать полностью · ${message.text.length.toLocaleString("ru-RU")} зн.`}
            </button>
          )}
        </div>
        {time && <span className="mt-1 pr-1 text-[11px] tabular-nums text-zinc-400">{time}</span>}
      </div>
    );
  }

  return (
    <div className={cn("flex animate-fade-in items-start gap-2", first ? "mt-4" : "mt-1.5")}>
      <AgentAvatar hidden={!first} />
      <div className="flex min-w-0 max-w-[86%] flex-col items-start">
        <div className="whitespace-pre-wrap break-words rounded-[18px] rounded-tl-md bg-zinc-100 px-3.5 py-2.5 text-[13px] leading-5 text-zinc-900">
          {text}
        </div>
        {time && <span className="mt-1 pl-1 text-[11px] tabular-nums text-zinc-400">{time}</span>}
      </div>
    </div>
  );
});

/** Three bouncing dots in an assistant bubble — shown while /api/chat is in flight. */
export function TypingIndicator({ first }: { first: boolean }) {
  return (
    <div role="status" aria-label="Агент печатает" className={cn("flex animate-fade-in items-start gap-2", first ? "mt-4" : "mt-1.5")}>
      <AgentAvatar hidden={!first} />
      <div className="flex h-10 items-center gap-1 rounded-[18px] rounded-tl-md bg-zinc-100 px-4">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400" style={{ animationDelay: `${i * 140}ms`, animationDuration: "900ms" }} />
        ))}
      </div>
    </div>
  );
}

/** Compact mirror of the global job bar, so the conversation itself shows that the agent is working. */
export function JobBubble({ job }: { job: ActiveJob }) {
  const failed = job.status === "failed";
  const done = job.status === "done";
  return (
    <div role="status" aria-live="polite" className="mt-4 flex animate-fade-in items-start gap-2">
      <AgentAvatar />
      <div className={cn("min-w-0 flex-1 rounded-[18px] rounded-tl-md px-3.5 py-3", failed ? "bg-red-50" : done ? "bg-emerald-50" : "bg-accent-50")}>
        <div className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-zinc-900">{job.label}</span>
          {!failed && <span className="shrink-0 text-xs font-medium tabular-nums text-zinc-500">{Math.round(job.progress * 100)}%</span>}
        </div>
        <Progress className="mt-2" value={failed ? 1 : job.progress} tone={failed ? "error" : done ? "success" : "accent"} size="sm" indeterminate={job.status === "queued"} />
        {job.message && <p className={cn("mt-1.5 truncate text-xs", failed ? "text-red-600" : "text-zinc-500")}>{job.message}</p>}
      </div>
    </div>
  );
}
