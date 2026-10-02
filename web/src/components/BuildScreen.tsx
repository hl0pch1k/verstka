// While a presentation is being built: «сцена Verstka». The page has the deck's own frame — the title bar, then the
// rail on the left, the stage in the middle, a 288px column on the right — so that when the build ends every block
// turns into its counterpart of the deck (View Transitions: the title, the rail of sketches → the thumbnails, the dark
// stage → the slide, the agent's column → the aside). On the stage the phase is set big, the agent's newest line types
// itself and the slide it speaks of is sketched; the rail fills in slide by slide as the designer thinks them through
// (then the real previews fade in); the right column shows how the agent thinks, step by step; the variants' chips
// under the stage choose whose rail is shown. A narrow page (the helper docked) drops the log column.
// Entered through a View Transition (create → build, deck → build), the transition's page rise is the only entrance:
// the blocks do not rise again inside the fading-in page, and they take their view-transition names only once it has
// ended (from the create page, which has nothing to morph from, the whole page rises as one piece).
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { buildTimeline, laterPhase, phaseOfStep, type PhaseKey } from "../lib/agent";
import type { VariantProgress } from "../lib/jobText";
import { templateTitle } from "../lib/plain";
import { clock, railSlides, ROLE, STAGE_TITLE, type Sketch } from "../lib/stage";
import { stagger } from "../lib/motion";
import { cn, fmtWhen } from "../lib/utils";
import { useApp, type ActiveJob } from "../store";
import { AgentLog } from "./build/AgentLog";
import { BuildStage } from "./build/BuildStage";
import { StageRail } from "./build/StageRail";
import { VariantChips, type ChipState } from "./build/VariantChips";

const PROMISE_MS = 5 * 60 * 1000; // the five-minute promise
/** The variants' chips under the stage (VariantChips). */
const CHIPS_H = 60;

/** A variant's chip: determinate once the pipeline reports its layout, indeterminate while the agent works on it. */
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

/** The one-off entrances of what the page shows at mount (a status, a step's check, a tile's pop). */
const ENTRANCES = new Set(["fade", "fade-in", "rise", "pop", "fill-in", "tile-pulse", "word-rise"]);

/** How the build page came in. `quiet`: it mounted inside a View Transition, which is its entrance. `title` / `names`:
 *  the title block and the other blocks carry their view-transition names, which the hand-off to the deck needs.
 *  Entering through a transition they get them once it has ended, so the page rises as one piece, with one exception:
 *  a deck's title (read at the first render, while the page being left is still in the DOM) cross-fades in place into
 *  «Готовлю презентацию». The deck's other blocks do not morph into the build's: they fade out with the deck. */
function useEntrance(): { quiet: boolean; title: boolean; names: boolean } {
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
  return { quiet, title: settled || fromTitle, names: settled };
}

const slideUrl = (gid: string, variant: string, n: number) => `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(variant)}/slides/slide-${String(n).padStart(3, "0")}.jpg`;

/** The variant's rendered previews, once the build has rendered them (around 86 %): the first slide is probed every 3 s
 *  until it loads, then the rest are fetched; a slide that is not there yet is tried again with the next probe. */
function useSlidePreviews(gid: string | null | undefined, variant: string, count: number, enabled: boolean): Record<number, string> {
  const [found, setFound] = useState<Record<string, string>>({});
  const foundRef = useRef(found);
  foundRef.current = found;
  useEffect(() => {
    if (!gid || !enabled || count <= 0) return;
    let alive = true;
    let timer = 0;
    const load = (n: number) =>
      new Promise<boolean>((resolve) => {
        const key = `${variant}/${n}`;
        if (foundRef.current[key]) return resolve(true);
        const url = slideUrl(gid, variant, n);
        const img = new Image();
        img.onload = () => {
          if (alive) setFound((m) => (m[key] ? m : { ...m, [key]: url }));
          resolve(true);
        };
        img.onerror = () => resolve(false);
        img.src = url;
      });
    const round = async () => {
      if (!(await load(1)) || !alive) return void (timer = window.setTimeout(round, 3000));
      const got = await Promise.all(Array.from({ length: count - 1 }, (_, i) => load(i + 2)));
      if (alive && got.some((ok) => !ok)) timer = window.setTimeout(round, 3000);
    };
    void round();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [gid, variant, count, enabled]);
  return useMemo(() => {
    const out: Record<number, string> = {};
    for (const [key, url] of Object.entries(found)) {
      const [v, n] = [key.slice(0, key.lastIndexOf("/")), Number(key.slice(key.lastIndexOf("/") + 1))];
      if (v === variant) out[n] = url;
    }
    return out;
  }, [found, variant]);
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

  // «VK Tech · сегодня, 18:14»: the same meta line the result shows under its title once the deck is ready
  const tid = job.template ?? templateId;
  const tpl = templates.find((t) => t.template_id === tid);
  const file = tpl?.source_file ?? (manifest?.template_id === tid ? manifest?.source_file : null);
  const meta = [file ? templateTitle(file) : "", fmtWhen(job.startedAt / 1000)].filter(Boolean).join(" · ");
  // the stage has the slides' proportions: it turns into the first slide when the deck is ready
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect : manifest?.template_id === tid && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;

  const names = job.items?.length ? job.items : strategies.map((s) => s.name);
  const message = job.message;
  // saving the files means every variant has been laid out and checked
  const exporting = /^сохраняю файлы/i.test(message);
  const elapsed = Date.now() - job.startedAt;
  const queued = job.status === "queued";

  // the variants are laid out one after another: the check of the first must not end «Вёрстка» for the others
  const laying = !exporting && names.some((n) => (job.variants?.[n]?.frac ?? 0) < 0.75);
  const phase: PhaseKey | null = job.phase === "check" && laying ? "layout" : job.phase ?? null;

  const variantOf = (name: string): VariantState => {
    if (exporting) return { ...job.variants?.[name], text: "готово", done: true, frac: 1 };
    const st = job.variants?.[name];
    if (st && st.text !== "план готов") return st;
    // before the pipeline reports: where the agent is with this variant (shared lines count for every variant);
    // a variant waiting behind another at the critic is with the critic too
    let own: PhaseKey | null = null;
    for (const e of job.agent ?? []) if (e.variant == null || e.variant === name) own = laterPhase(own, phaseOfStep(e.step));
    const jobAt = phase && (phase === "critic" || phase === "revise" || phase === "layout" || phase === "check") ? "critic" : phase;
    const at = laterPhase(own, jobAt);
    if (st || at === "layout" || at === "check") return { ...st, text: "в очереди на вёрстку", done: false, frac: 0 };
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
  const stepRow = rows[Math.min(step, rows.length) - 1];
  const kicker = queued || !stepRow ? "в очереди" : `шаг ${Math.min(step, rows.length)} из ${rows.length} · ${ROLE[stepRow.key]}`;
  const title = STAGE_TITLE[queued ? "queued" : phase ?? "queued"];

  // the variant whose rail is shown: the first one until the person picks another
  const [picked, setPicked] = useState<string | null>(null);
  const shown = picked && names.includes(picked) ? picked : names[0] ?? "";
  const own = job.variants?.[shown];
  const laid = exporting ? own?.of ?? 0 : own?.laid ?? 0;
  const count = own?.of ?? job.slides ?? 0;
  const rail = useMemo(() => railSlides(job.agent ?? [], shown, count, laid, own?.of !== undefined), [job.agent, shown, count, laid, own?.of]);
  // the slide the stage speaks of: the newest line's (when it is about this variant), else the newest sketched one
  const line = job.line ?? null;
  const lineSlide = line?.slide && (line.variant == null || line.variant === shown) ? line.slide : null;
  const lastSketched = [...rail].reverse().find((s) => s.sketch)?.n ?? null;
  const focus = lineSlide ?? lastSketched;
  const sketch: Sketch | null = (focus ? rail[focus - 1]?.sketch : null) ?? null;
  const mode = !sketch || phase === "writer" || phase === "analyst" || phase === "architect" ? "read" : phase === "check" ? "check" : "sketch";
  const previews = useSlidePreviews(job.generation, shown, rail.length, job.progress >= 0.86 || phase === "check" || exporting);

  const chips = useMemo(() => {
    const out: Record<string, ChipState> = {};
    for (const n of names) out[n] = variantOf(n);
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [names, job.variants, job.agent, phase, exporting]);
  const timer = elapsed <= PROMISE_MS ? `${clock(elapsed / 1000)} / ${clock(PROMISE_MS / 1000)}` : clock(elapsed / 1000);

  return (
    // left edge = the header's container edge, also while the helper narrows `main` (identical to mx-auto otherwise)
    <div ref={rootRef} className="build-root ml-[max(0px,calc((100vw-1600px)/2))] mr-auto flex h-full min-h-[600px] max-w-[1600px] flex-col gap-4 px-8 py-6">
      {/* laid out like the result's title bar (H1 + meta line), so the title stays put when the deck replaces the build */}
      <div className="flex h-14 shrink-0 items-center">
        {/* vt-title: «Готовлю презентацию» cross-fades in place into the deck's title when the build ends */}
        <div className={cn("min-w-0 flex-1", vt.title && "vt-title")}>
          <h1 className="truncate text-title1 font-bold tracking-tight text-zinc-900">Готовлю презентацию</h1>
          {meta && <p className="truncate text-footnote text-zinc-500" title={meta}>{meta}</p>}
        </div>
      </div>

      {/* the workspace is no taller than the stage and its chips (the slides' proportions): no bands above and below the
          stage, the columns beside it end with it — the deck's own workspace is capped the same way */}
      <div
        className="build-grid grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-4"
        style={{ maxHeight: `calc((100cqw - var(--side)) / ${aspect.toFixed(4)} + ${names.length > 1 ? CHIPS_H + 12 : 0}px)` }}
      >
        <StageRail
          slides={rail}
          images={previews}
          focus={focus}
          aspect={aspect}
          className={cn(vt.names && "vt-rail", !vt.quiet && "animate-rise")}
        />
        <div className={cn("flex min-h-0 min-w-0 flex-col gap-3", !vt.quiet && "animate-rise")} style={vt.quiet ? undefined : stagger(1)}>
          {/* the stage: the largest box of the slides' proportions the column leaves (a size container) */}
          <div className="grid min-h-0 flex-1 place-items-center" style={{ containerType: "size" }}>
            <BuildStage
              kicker={kicker}
              title={title}
              line={line}
              sketch={sketch}
              mode={mode}
              progress={job.progress}
              queued={queued}
              timer={timer}
              aspect={aspect}
              running={!queued}
              className={cn(vt.names && "vt-stage")}
              style={{ width: `min(100cqw, calc(100cqh * ${aspect.toFixed(4)}))` }}
            />
          </div>
          {names.length > 1 && <VariantChips names={names} states={chips} value={shown} onChange={setPicked} titleOf={strategyTitle} />}
        </div>
        <AgentLog
          rows={rows}
          variantTitle={strategyTitle}
          running={!queued}
          className={cn("build-log", vt.names && "vt-aside", !vt.quiet && "animate-rise")}
        />
      </div>
    </div>
  );
}
