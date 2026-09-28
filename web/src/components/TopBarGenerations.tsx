// «Мои презентации»: the recent decks by day — cover, title, time, template, slides and the best quality score; a click
// reopens one. One Tab stop for the whole list (roving tabindex: ↑/↓/Home/End walk it); leaving it closes the popover.
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { AlertCircle, History, Layers, Loader2 } from "lucide-react";
import { MOTION, usePresence } from "../lib/motion";
import { templateTitle } from "../lib/plain";
import { cn, fmtDay, fmtTime, plural, scoreTone, TONE_TEXT } from "../lib/utils";
import type { GenerationMeta } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

const LIMIT = 50;

/** Best audit score across the variants of a generation (from the list summary). A topic whose text was never written
 *  (the model failed: a skeleton) has none: «100» would read as a success. */
function bestScore(g: GenerationMeta): number | null {
  if (g.writer && g.writer.status !== "written" && g.planner?.planned_by === "skeleton") return null;
  const scores = Object.values(g.summary ?? {})
    .map((s) => s.score)
    .filter((s): s is number => typeof s === "number" && Number.isFinite(s));
  return scores.length ? Math.max(...scores) : null;
}

/** «10 слайдов» or «8–10 слайдов» — what was built (the variants may differ), else what was asked for. */
function slidesText(g: GenerationMeta): string | null {
  const built = Object.values(g.summary ?? {})
    .map((s) => s.n_slides)
    .filter((n): n is number => typeof n === "number" && n > 0);
  if (built.length === 0) return g.slides ? plural(g.slides, "слайд", "слайда", "слайдов") : null;
  const lo = Math.min(...built);
  const hi = Math.max(...built);
  return lo === hi ? plural(hi, "слайд", "слайда", "слайдов") : `${lo}–${plural(hi, "слайд", "слайда", "слайдов")}`;
}

/** The deck title; older runs without one fall back to the first line of the text. */
const titleOf = (g: GenerationMeta) =>
  g.title?.trim() ||
  g.brief
    ?.split("\n")
    .map((l) => l.replace(/^#+\s*/, "").replace(/\*\*/g, "").trim())
    .find(Boolean)
    ?.slice(0, 120) ||
  (g.template_file ?? g.template_id).replace(/\.(?:pptx|potx|pptm|potm|ppsx|ppsm|thmx|ppt|pot|pps|odp|otp)$/i, "");

function Cover({ g, busy }: { g: GenerationMeta; busy: boolean }) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const running = g.status === "running" || g.status === "queued";
  const failed = g.status === "failed";
  const src = g.strategies[0] ? `/api/generations/${g.id}/${g.strategies[0]}/slides/slide-001.jpg` : null;
  return (
    <span className="relative flex aspect-video w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-zinc-100 ring-1 ring-zinc-900/[0.08]">
      {running ? (
        <Loader2 className="h-4 w-4 animate-spin text-zinc-400" aria-hidden />
      ) : failed ? (
        <AlertCircle className="h-4 w-4 text-zinc-400" aria-hidden />
      ) : src && !broken ? (
        <img
          ref={(el) => {
            if (el?.complete && el.naturalWidth > 0 && !loaded) setLoaded(true);
          }}
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setBroken(true)}
          className={cn("h-full w-full object-cover transition-opacity duration-200 ease-out", loaded ? "opacity-100" : "opacity-0")}
        />
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
  const busyRef = useRef<string | null>(null);
  const [rovId, setRovId] = useState<string | null>(null); // the one row in the Tab order
  const [atEnd, setAtEnd] = useState(true);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { mounted, leaving } = usePresence(open, MOTION.fast);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    // Esc closes the popover only (the helper behind it stays)
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
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
  const pickable = (g: GenerationMeta) => g.status !== "running" && g.status !== "queued";
  // the roving stop: the row last walked to, else the open deck, else the newest one that can be opened
  const tabId =
    (rovId && list.some((g) => g.id === rovId && pickable(g)) ? rovId : null) ??
    (currentId && list.some((g) => g.id === currentId && pickable(g)) ? currentId : null) ??
    list.find(pickable)?.id ??
    null;
  // day groups in order: «Сегодня», «Вчера», «24 сент.»
  const groups: Array<{ day: string; items: GenerationMeta[] }> = [];
  for (const g of list) {
    const day = fmtDay(g.created_at) || "Раньше";
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(g);
    else groups.push({ day, items: [g] });
  }

  // the bottom fade shows only while there is more below
  const measure = () => {
    const el = listRef.current;
    if (el) setAtEnd(el.scrollHeight - el.scrollTop - el.clientHeight < 8);
  };
  useEffect(() => {
    if (mounted) window.requestAnimationFrame(measure);
  }, [mounted, list.length]);

  const pick = async (id: string) => {
    busyRef.current = id;
    setBusy(id);
    try {
      await onSelect(id);
    } finally {
      busyRef.current = null;
      setBusy(null);
      setOpen(false);
      triggerRef.current?.focus(); // the picked row unmounts: the focus goes back to where the popover came from
    }
  };

  // ↑/↓ walk the rows, Home/End jump to the ends
  const onListKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const rows = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("button[data-row]:not(:disabled)") ?? [])];
    if (rows.length === 0) return;
    const at = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? rows.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const row = rows[(next + rows.length) % rows.length];
    setRovId(row.dataset.id ?? null);
    row.focus();
  };

  return (
    <div
      ref={rootRef}
      className="relative"
      onBlur={(e) => {
        // Tab (or a click) out of the trigger and the list closes the popover; a deck that is loading keeps it open
        if (open && busyRef.current === null && !rootRef.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <Button
        ref={triggerRef}
        variant="ghost"
        size="md"
        icon={History}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key !== "ArrowDown") return;
          e.preventDefault();
          setOpen(true);
          window.requestAnimationFrame(() => listRef.current?.querySelector<HTMLButtonElement>('button[data-row][tabindex="0"]')?.focus());
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        Мои презентации
      </Button>

      {mounted && (
        <div
          role="dialog"
          aria-label="Мои презентации"
          tabIndex={-1} // a click on a day label keeps the focus inside, so the popover stays open
          className={cn(
            // 20px under the 40px trigger = 8px under the 64px header
            "absolute right-0 top-[calc(100%+20px)] z-40 w-[440px] origin-top-right overflow-hidden rounded-2xl bg-white text-zinc-900 shadow-pop outline-none",
            leaving ? "pointer-events-none animate-drop-out rm-fade-out" : "animate-drop-in rm-fade",
          )}
        >
          {list.length === 0 ? (
            <div className="flex flex-col items-center px-6 py-8 text-center">
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-100">
                <Layers className="h-6 w-6 text-zinc-500" aria-hidden />
              </span>
              <p className="text-body font-semibold text-zinc-900">Пока пусто</p>
            </div>
          ) : (
            <div
              ref={listRef}
              onKeyDown={onListKey}
              onScroll={measure}
              className={cn(
                "scroll-thin max-h-[min(560px,calc(100vh-96px))] overflow-y-auto pb-2",
                !atEnd && "[mask-image:linear-gradient(to_bottom,#000_calc(100%-24px),transparent)]",
              )}
            >
              {groups.map((grp) => (
                <section key={grp.day} aria-label={grp.day}>
                  <h3 className="sticky top-0 z-[1] bg-white px-4 pb-1 pt-3 font-sans text-caption font-semibold text-zinc-500">{grp.day}</h3>
                  <ul>
                    {grp.items.map((g) => {
                      const score = bestScore(g);
                      const current = g.id === currentId;
                      const running = g.status === "running" || g.status === "queued";
                      const failed = g.status === "failed";
                      const title = titleOf(g);
                      const meta = [fmtTime(g.created_at), g.template_file ? templateTitle(g.template_file) : null, slidesText(g)].filter(Boolean).join(" · ");
                      return (
                        <li key={g.id}>
                          <button
                            type="button"
                            data-row
                            data-id={g.id}
                            tabIndex={g.id === tabId ? 0 : -1}
                            onFocus={() => setRovId(g.id)}
                            aria-current={current || undefined}
                            disabled={busy !== null || running}
                            onClick={() => void pick(g.id)}
                            title={`${title}\n${meta}`}
                            className={cn(
                              "tap-soft mx-2 flex min-h-[72px] w-[calc(100%-16px)] cursor-pointer items-start gap-3 rounded-xl p-2 text-left focus-visible:outline-offset-[-2px] disabled:cursor-default",
                              current ? "bg-accent-50" : "hover:bg-zinc-100",
                              busy !== null && busy !== g.id && "opacity-60",
                            )}
                          >
                            <Cover g={g} busy={busy === g.id} />
                            <span className="min-w-0 flex-1">
                              <span className="line-clamp-2 text-body font-semibold text-zinc-900">{title}</span>
                              <span className="block truncate text-caption text-zinc-500">{meta}</span>
                            </span>
                            {running ? (
                              <Badge size="sm" tone="accent" dot>собирается</Badge>
                            ) : failed ? (
                              <Badge size="sm" tone="error">не удалось</Badge>
                            ) : score !== null ? (
                              <span className={cn("shrink-0 text-footnote font-semibold tabular-nums", TONE_TEXT[scoreTone(score)])} title="Лучшая оценка качества среди вариантов">
                                {Math.round(score)}
                              </span>
                            ) : null}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
