// «История»: popover with recent generations for the top bar. Click on a row opens that generation.
import { useEffect, useRef, useState } from "react";
import { ChevronDown, History, Layers } from "lucide-react";
import { cn, fmtDate, plural, scoreTone } from "../lib/utils";
import type { GenerationMeta } from "../types";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Spinner } from "./ui/Spinner";

/** Best audit score across the variants of a generation (from the list summary). */
export function bestScore(g: GenerationMeta): number | null {
  const scores = Object.values(g.summary ?? {})
    .map((s) => s.score)
    .filter((s): s is number => typeof s === "number" && Number.isFinite(s));
  return scores.length ? Math.max(...scores) : null;
}

const STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  running: { label: "выполняется", tone: "info" },
  queued: { label: "в очереди", tone: "info" },
  failed: { label: "ошибка", tone: "error" },
};

interface Props {
  generations: GenerationMeta[];
  currentId: string | null;
  onSelect(id: string): Promise<void> | void;
}

export function TopBarGenerations({ generations, currentId, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const list = [...generations].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)).slice(0, 12);

  const pick = async (id: string) => {
    setBusy(id);
    try {
      await onSelect(id);
    } finally {
      setBusy(null);
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 text-[13px] font-medium text-zinc-800 shadow-sm transition-colors",
          "hover:border-zinc-300 hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
          open && "border-zinc-300 bg-zinc-50",
        )}
      >
        <History className="h-4 w-4 text-zinc-500" aria-hidden />
        История
        {generations.length > 0 && (
          <Badge size="sm" tone="neutral">
            {generations.length}
          </Badge>
        )}
        <ChevronDown className={cn("h-3.5 w-3.5 text-zinc-400 transition-transform", open && "rotate-180")} aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Недавние генерации"
          className="absolute right-0 top-full z-40 mt-1.5 w-[440px] overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-pop animate-fade-in"
        >
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Недавние генерации</span>
            <span className="text-xs text-zinc-400">{plural(generations.length, "запуск", "запуска", "запусков")}</span>
          </div>
          {list.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-8 text-center">
              <Layers className="h-5 w-5 text-zinc-400" aria-hidden />
              <p className="text-[13px] font-medium text-zinc-700">Генераций пока нет</p>
              <p className="text-xs text-zinc-500">Опишите бриф в форме «Новая презентация» — первый запуск появится здесь.</p>
            </div>
          ) : (
            <ul className="scroll-thin max-h-[420px] overflow-y-auto py-1">
              {list.map((g) => {
                const score = bestScore(g);
                const status = g.status ? STATUS[g.status] : undefined;
                const current = g.id === currentId;
                return (
                  <li key={g.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={current}
                      disabled={busy !== null}
                      onClick={() => void pick(g.id)}
                      className={cn(
                        "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-zinc-50 focus:outline-none focus-visible:bg-zinc-50 disabled:cursor-wait",
                        current && "bg-accent-50/60 hover:bg-accent-50",
                      )}
                    >
                      <span className="w-[86px] shrink-0 text-xs tabular-nums text-zinc-500">{fmtDate(g.created_at)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-zinc-900">{g.template_file ?? g.template_id}</span>
                        <span className="block truncate text-xs text-zinc-500">
                          {plural(g.strategies.length, "вариант", "варианта", "вариантов")}
                          {g.slides ? ` · ${plural(g.slides, "слайд", "слайда", "слайдов")}` : ""}
                          {g.purpose ? ` · ${g.purpose}` : ""}
                        </span>
                      </span>
                      {busy === g.id ? (
                        <Spinner size={14} />
                      ) : status ? (
                        <Badge size="sm" tone={status.tone} dot>
                          {status.label}
                        </Badge>
                      ) : (
                        <Badge size="sm" tone={scoreTone(score)}>
                          {score === null ? "без аудита" : `${Math.round(score)} / 100`}
                        </Badge>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
