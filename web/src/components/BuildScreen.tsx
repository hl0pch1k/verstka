// While a presentation is being built. It mirrors the result screen's frame: the title bar (sticky, so the page keeps
// its name while it follows the newest line), the agent's work on the left (Аналитик → Дизайнер → Критик → Правка →
// Вёрстка → Проверка, lines only ever get added) and, on the right, a 288px column with the progress, the clock and
// the three variants, pinned right under the title bar so it never moves. Motion: the percent counts and the bars
// glide to each new value, the step label and a variant's status cross-fade when they change, and the title block and
// the right column carry view-transition names, so the deck's title and aside take their place when the build ends.
// Entered through a View Transition (create → build, deck → build), the transition's page rise is the only entrance:
// the cards do not rise again inside the fading-in page (a second fade there reads as a washed-out, double-exposed
// page), and from the create page, which has no title or aside to morph from, the whole page rises as one piece.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Check } from "lucide-react";
import { buildTimeline, laterPhase, phaseOfStep, type PhaseKey } from "../lib/agent";
import type { VariantProgress } from "../lib/jobText";
import { templateTitle, variantHint } from "../lib/plain";
import { stagger } from "../lib/motion";
import { cn, fmtWhen } from "../lib/utils";
import { useApp, type ActiveJob } from "../store";
import { AgentTimeline } from "./simple/AgentTimeline";
import { CountUp } from "./ui/CountUp";
import { Progress } from "./ui/Progress";

const PROMISE_MS = 5 * 60 * 1000; // the five-minute promise

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** A variant's row: determinate once the pipeline reports its layout, indeterminate while the agent works on it. */
interface VariantState extends VariantProgress { indeterminate?: boolean }

// what the agent is doing with a variant before the pipeline reports its layout (then: «в очереди на вёрстку»,
// «вёрстка 4 из 6», «проверка качества», «готово»)
const AGENT_STATUS: Partial<Record<PhaseKey, string>> = {
  writer: "пишу текст",
  analyst: "читаю текст",
  architect: "строю сюжет",
  designer: "продумываю слайды",
  critic: "проверяет критик",
  revise: "правка",
};

/** A View Transition is running (the page is being captured or animated). */
const inViewTransition = () => {
  try {
    return document.documentElement.matches(":active-view-transition");
  } catch {
    return false; // a browser without the pseudo-class has no View Transitions either
  }
};

/** The one-off entrances of what the page shows at mount (a status, the step label, the active step's spinner, a done
 *  step's check). */
const ENTRANCES = new Set(["fade", "fade-in", "rise", "pop"]);

/** How the build page came in. `quiet`: it mounted inside a View Transition, which is its entrance. `title` / `aside`:
 *  the title block and the status column carry their view-transition names, which the hand-off to the deck needs.
 *  Entering through a transition they get them once it has ended, so the page rises as one piece, with one exception:
 *  a deck's title (read at the first render, while the page being left is still in the DOM) cross-fades in place into
 *  «Готовлю презентацию». The deck's aside does not morph into the column: it is taller, and its lower cards would
 *  hang opaque below the shrinking box; it fades out with the deck instead. */
function useEntrance(): { quiet: boolean; title: boolean; aside: boolean } {
  const [quiet] = useState(inViewTransition);
  const [fromTitle] = useState(() => quiet && !!document.querySelector(".vt-title"));
  const [settled, setSettled] = useState(!quiet);
  useEffect(() => {
    if (settled) return;
    let raf = 0;
    const tick = () => (inViewTransition() ? (raf = requestAnimationFrame(tick)) : setSettled(true));
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [settled]);
  return { quiet, title: settled || fromTitle, aside: settled };
}

export function BuildScreen({ job }: { job: ActiveJob }) {
  const { strategies, strategyTitle, templates, templateId, manifest } = useApp();
  const vt = useEntrance();
  // inside the transition, the entrances of the page's content end at once (a later change still animates)
  const rootRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!vt.quiet) return;
    for (const a of rootRef.current?.getAnimations({ subtree: true }) ?? []) {
      const name = (a as Animation & { animationName?: string }).animationName;
      if (name && ENTRANCES.has(name)) a.finish();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // the interval only asks for a re-render; the clock is read at render time (throttled background tabs never lag)
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  // the fade under the title bar shows only once something has scrolled under it (at rest it would blur the card's edge)
  const barRef = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const box = barRef.current?.closest("[data-follow]") as HTMLElement | null;
    if (!box) return;
    const onScroll = () => setScrolled(box.scrollTop > 0);
    onScroll();
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => box.removeEventListener("scroll", onScroll);
  }, []);

  // «VK Tech · сегодня, 18:14»: the same meta line the result shows under its title once the deck is ready
  const tid = job.template ?? templateId;
  const file = templates.find((t) => t.template_id === tid)?.source_file ?? (manifest?.template_id === tid ? manifest?.source_file : null);
  const meta = [file ? templateTitle(file) : "", fmtWhen(job.startedAt / 1000)].filter(Boolean).join(" · ");

  const names = job.items?.length ? job.items : strategies.map((s) => s.name);
  const message = job.message;
  // saving the files means every variant has been laid out and checked
  const exporting = /^сохраняю файлы/i.test(message);
  const pct = Math.round(job.progress * 100);
  const elapsed = Date.now() - job.startedAt;

  // the variants are laid out one after another: the check of the first must not end «Вёрстка» for the others
  const laying = !exporting && names.some((n) => (job.variants?.[n]?.frac ?? 0) < 0.75);
  const phase: PhaseKey | null = job.phase === "check" && laying ? "layout" : job.phase ?? null;

  const variantOf = (name: string): VariantState => {
    if (exporting) return { text: "готово", done: true, frac: 1 };
    const st = job.variants?.[name];
    if (st && st.text !== "план готов") return st;
    // before the pipeline reports: where the agent is with this variant (shared lines count for every variant);
    // a variant waiting behind another at the critic is with the critic too
    let own: PhaseKey | null = null;
    for (const e of job.agent ?? []) if (e.variant == null || e.variant === name) own = laterPhase(own, phaseOfStep(e.step));
    const jobAt = phase && (phase === "critic" || phase === "revise" || phase === "layout" || phase === "check") ? "critic" : phase;
    const at = laterPhase(own, jobAt);
    if (st || at === "layout" || at === "check") return { text: "в очереди на вёрстку", done: false, frac: 0 };
    return { text: AGENT_STATUS[at ?? "analyst"] ?? "работаю…", done: false, frac: 0, indeterminate: true };
  };

  // the pipeline's own messages speak for the steps the agent does not narrate (laying out, checking)
  const layoutNote = useMemo(() => {
    const busy = names.map((n) => ({ n, st: job.variants?.[n] })).find(({ st }) => st && !st.done && /вёрстка/.test(st.text));
    return busy?.st ? `${strategyTitle(busy.n)}: ${busy.st.text}` : null;
  }, [names, job.variants, strategyTitle]);
  const checkNote = /проверка качества|исправляю замечания|сохраняю файлы/i.test(message) ? message : null;
  const rows = useMemo(() => {
    const notes: Partial<Record<PhaseKey, string | null>> = {
      layout: phase === "layout" ? layoutNote : null,
      check: phase === "check" ? checkNote : null,
    };
    // before Agent v2 the plan came in one piece: the designer row says so instead of listing slides
    if (!job.agent?.length && phase && phase !== "analyst") notes.designer = "план готов";
    return buildTimeline({ events: job.agent ?? [], phase, running: true, notes });
  }, [job.agent, phase, layoutNote, checkNote]);
  const activeIdx = rows.findIndex((r) => r.status === "active");
  const step = activeIdx >= 0 ? activeIdx + 1 : Math.max(1, rows.filter((r) => r.status === "done" || r.status === "skipped").length);
  const stepTitle = rows[Math.min(step, rows.length) - 1]?.title;
  const stepLabel = stepTitle ? `${stepTitle} · шаг ${Math.min(step, rows.length)} из ${rows.length}` : "В очереди";

  return (
    // left edge = the header's container edge, also while the helper narrows `main` (identical to mx-auto otherwise)
    <div ref={rootRef} className="ml-[max(0px,calc((100vw-1600px)/2))] mr-auto flex max-w-[1600px] flex-col gap-4 px-8 py-6">
      {/* the title bar stays: canvas behind it, a 16px fade under it, so lines slide away instead of being cut */}
      <div ref={barRef} className="sticky top-0 z-10 -mx-8 -mb-4 -mt-6 bg-canvas px-8 pb-4 pt-6">
        {/* laid out like the result's title bar (H1 + meta line), so the title stays put when the deck replaces the build */}
        <div className="flex h-14 items-center">
          {/* vt-title: «Готовлю презентацию» cross-fades in place into the deck's title when the build ends */}
          <div className={cn("min-w-0 flex-1", vt.title && "vt-title")}>
            <h1 className="truncate text-title1 font-bold tracking-tight text-zinc-900">Готовлю презентацию</h1>
            {meta && <p className="truncate text-footnote text-zinc-500" title={meta}>{meta}</p>}
          </div>
        </div>
        {/* rendered only while scrolled: a pseudo-element kept at opacity 0 still painted a white band over the card */}
        {scrolled && <div aria-hidden className="pointer-events-none absolute inset-x-0 top-full h-4 animate-fade bg-gradient-to-b from-canvas to-transparent" />}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_288px] items-start gap-4">
        {/* the active step's title pins right under the title bar (above its fade); lines never leave one word alone */}
        <section
          aria-label="Как работает агент"
          className={cn("min-w-0 rounded-2xl bg-white p-6 shadow-card [text-wrap:pretty]", !vt.quiet && "animate-rise")}
        >
          <h2 className="text-title3 font-semibold text-zinc-900">Как работает агент</h2>
          <AgentTimeline rows={rows} variantTitle={strategyTitle} follow pinClassName="top-24 z-[11]" className="mt-4" />
        </section>

        {/* vt-aside: the status column becomes the deck's aside (both are the 288px column on the right) */}
        <div className={cn("sticky top-24 z-10 flex flex-col gap-3", vt.aside && "vt-aside", !vt.quiet && "animate-rise")} style={vt.quiet ? undefined : stagger(1)}>
          <section aria-label="Ход сборки" className="rounded-2xl bg-white p-4 shadow-card">
            {/* the percent rolls to each new value (600 ms, the bar below glides with it); the sign stays put */}
            <p className="font-display text-display font-bold tracking-tight text-zinc-900">
              <CountUp value={pct} ms={600} />
              <span className="text-title1 text-zinc-500">%</span>
            </p>
            <Progress size="md" value={job.progress} indeterminate={job.status === "queued"} className="mt-3" />
            {/* the live region stays; the label inside cross-fades up 4px when the agent moves to the next step */}
            <p className="mt-3 text-footnote font-semibold text-zinc-900" aria-live="polite">
              <span key={stepLabel} className="block truncate animate-fade-in">{stepLabel}</span>
            </p>
            <p className="text-footnote tabular-nums text-zinc-500">
              {elapsed <= PROMISE_MS ? `${clock(elapsed)} / ${clock(PROMISE_MS)}` : clock(elapsed)}
            </p>
          </section>

          {names.length > 1 && (
            <section aria-label="Варианты" className="rounded-2xl bg-white p-2 shadow-card">
              {names.map((name, i) => {
                const st = variantOf(name);
                return (
                  <div key={name} className="p-2" title={variantHint(name)}>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-caption font-bold transition-colors duration-300",
                          st.done ? "bg-accent-fill text-white" : "bg-zinc-100 text-zinc-600",
                        )}
                        aria-hidden
                      >
                        {st.done ? <Check key="d" className="h-4 w-4 animate-pop" strokeWidth={2.5} /> : i + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-footnote font-semibold text-zinc-900">{strategyTitle(name)}</span>
                        {/* «продумываю слайды» → «вёрстка 4 из 6» → «готово»: each status cross-fades in */}
                        <span key={st.text} className="block truncate text-caption text-zinc-500 animate-fade">{st.text}</span>
                      </span>
                    </div>
                    <div className="ml-10 mt-2">
                      {/* staggered, so the three sweeps never move in lockstep */}
                      <Progress size="sm" value={st.frac} indeterminate={st.indeterminate} delayMs={i * 200} />
                    </div>
                  </div>
                );
              })}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
