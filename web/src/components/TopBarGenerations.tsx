// «Мои презентации»: the recent decks with their cover, a plain date and the quality score; a click reopens one.
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { AlertCircle, ChevronDown, History, Layers, Loader2 } from "lucide-react";
import { usePresence } from "../lib/motion";
import { cn, fmtWhen, plural, scoreTone } from "../lib/utils";
import type { GenerationMeta } from "../types";
import { Badge } from "./ui/Badge";

const LIMIT = 12;

/** Best audit score across the variants of a generation (from the list summary). */
function bestScore(g: GenerationMeta): number | null {
  const scores = Object.values(g.summary ?? {})
    .map((s) => s.score)
    .filter((s): s is number => typeof s === "number" && Number.isFinite(s));
  return scores.length ? Math.max(...scores) : null;
}

const titleOf = (g: GenerationMeta) =>
  g.brief
    ?.split("\n")
    .map((l) => l.replace(/^#+\s*/, "").trim())
    .find(Boolean)
    ?.slice(0, 80) || (g.template_file ?? g.template_id).replace(/\.pptx$/i, "");

function Cover({ g, busy }: { g: GenerationMeta; busy: boolean }) {
  const [broken, setBroken] = useState(false);
  const running = g.status === "running" || g.status === "queued";
  const failed = g.status === "failed";
  const src = g.strategies[0] ? `/api/generations/${g.id}/${g.strategies[0]}/slides/slide-001.jpg` : null;
  return (
    <span className="relative flex aspect-video w-[92px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-zinc-100 shadow-inner-line">
      {running ? (
        <Loader2 className="h-4 w-4 animate-spin text-zinc-400" aria-hidden />
      ) : failed ? (
        <AlertCircle className="h-4 w-4 text-zinc-400" aria-hidden />
      ) : src && !broken ? (
        <img src={src} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} className="h-full w-full object-cover" />
      ) : (
        <Layers className="h-4 w-4 text-zinc-400" aria-hidden />
      )}
      {busy && (
        <span className="absolute inset-0 flex items-center justify-center bg-white/70 animate-fade">
          <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden />
        </span>
      )}
    </span>
  );
}

interface Props {
  generations: GenerationMeta[];
  currentId: string | null;
  onSelect(id: string): Promise<void> | void;
}

export function TopBarGenerations({ generations, currentId, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const { mounted, leaving } = usePresence(open, 140);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const list = [...generations].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)).slice(0, LIMIT);

  const pick = async (id: string) => {
    setBusy(id);
    try {
      await onSelect(id);
    } finally {
      setBusy(null);
      setOpen(false);
    }
  };

  // ↑/↓ walk the rows, Home/End jump to the ends
  const onListKey = (e: ReactKeyboardEvent<HTMLUListElement>) => {
    const rows = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("[role=option]") ?? [])];
    if (rows.length === 0) return;
    const at = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? rows.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    rows[(next + rows.length) % rows.length].focus();
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key !== "ArrowDown") return;
          e.preventDefault();
          setOpen(true);
          window.requestAnimationFrame(() => listRef.current?.querySelector<HTMLButtonElement>("[role=option]")?.focus());
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "inline-flex h-10 cursor-pointer items-center gap-2 rounded-full bg-zinc-100 pl-3.5 pr-3 text-[14px] font-semibold text-zinc-800 transition-colors hover:bg-zinc-200/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
          open && "bg-zinc-200/80",
        )}
      >
        <History className="h-4 w-4 text-zinc-500" aria-hidden />
        Мои презентации
        {generations.length > 0 && <span className="min-w-[20px] rounded-full bg-white px-1.5 text-center text-[11px] font-bold leading-5 tabular-nums text-zinc-600">{generations.length}</span>}
        <ChevronDown className={cn("h-4 w-4 text-zinc-400 transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>

      {mounted && (
        <div
          className={cn(
            "absolute right-0 top-full z-40 mt-2 w-[480px] origin-top-right overflow-hidden rounded-2xl bg-white text-zinc-900 shadow-pop",
            leaving ? "pointer-events-none animate-drop-out" : "animate-drop-in",
          )}
        >
          <div className="flex items-baseline justify-between px-5 pb-2 pt-4">
            <span className="font-display text-[16px] font-semibold text-zinc-900">Мои презентации</span>
            {generations.length > 0 && <span className="text-xs text-zinc-400">{plural(generations.length, "презентация", "презентации", "презентаций")}</span>}
          </div>
          {list.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 px-6 pb-9 pt-6 text-center">
              <span className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-zinc-100">
                <Layers className="h-5 w-5 text-zinc-400" aria-hidden />
              </span>
              <p className="text-[14px] font-semibold text-zinc-800">Здесь пока пусто</p>
              <p className="text-[13px] text-zinc-500">Созданные презентации появятся в этом списке.</p>
            </div>
          ) : (
            <ul ref={listRef} role="listbox" aria-label="Мои презентации" onKeyDown={onListKey} className="scroll-thin max-h-[min(460px,calc(100vh-140px))] space-y-0.5 overflow-y-auto px-2 pb-2">
              {list.map((g) => {
                const score = bestScore(g);
                const current = g.id === currentId;
                const running = g.status === "running" || g.status === "queued";
                const failed = g.status === "failed";
                const slides = g.slides ?? Object.values(g.summary ?? {})[0]?.n_slides;
                return (
                  <li key={g.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={current}
                      disabled={busy !== null || running}
                      onClick={() => void pick(g.id)}
                      className={cn(
                        "flex w-full cursor-pointer items-center gap-3.5 rounded-xl p-2 pr-3 text-left transition-colors focus:outline-none focus-visible:bg-zinc-100 disabled:cursor-default",
                        current ? "bg-accent-50" : "hover:bg-zinc-100",
                        busy !== null && busy !== g.id && "opacity-60",
                      )}
                    >
                      <Cover g={g} busy={busy === g.id} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-semibold text-zinc-900" title={titleOf(g)}>{titleOf(g)}</span>
                        <span className="mt-0.5 block truncate text-xs text-zinc-500">
                          {[fmtWhen(g.created_at), plural(g.strategies.length, "вариант", "варианта", "вариантов"), slides ? plural(slides, "слайд", "слайда", "слайдов") : null].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      {running ? (
                        <Badge size="sm" tone="info" dot>собирается</Badge>
                      ) : failed ? (
                        <Badge size="sm" tone="error">не удалось</Badge>
                      ) : score !== null ? (
                        <Badge size="sm" tone={scoreTone(score)} title="Лучшая оценка качества среди вариантов">{Math.round(score)}/100</Badge>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {generations.length > LIMIT && <p className="border-t border-zinc-100 px-5 py-2.5 text-xs text-zinc-400">Показаны последние {LIMIT} из {generations.length}</p>}
        </div>
      )}
    </div>
  );
}
