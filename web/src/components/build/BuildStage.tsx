// «Сцена Verstka»: the dark stage of a build, in the template's own proportions — the place where the slide will appear
// once the deck is ready (the stage then turns into it). Two soft glows breathe behind a fine grid of dots while the work
// runs; a mono kicker says the step and the role, a timer counts against the five minutes; the phase's title is set big
// (its words rise one by one, the old ones leave upwards); under it the agent's newest line types itself; on the right
// the sketch of the slide it speaks of draws itself; the brand-gradient bar with a glowing head and the percent close it.
// Sizes follow the stage's width (a size container): the same composition at 1280 and at 1920.
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { MOTION, useReducedMotion } from "../../lib/motion";
import type { StageLine } from "../../lib/jobState";
import type { Sketch } from "../../lib/stage";
import { cn } from "../../lib/utils";
import { CountUp } from "../ui/CountUp";
import { Blueprint, type BlueprintMode } from "./Blueprint";

/** How long a phase's title stays before the next one may replace it: a fast build (no model: a dozen seconds) still
 *  reads as a sequence of steps, and words that rise are never replaced before they have landed. */
const TITLE_DWELL_MS = 1100;

/** The phase's words, big: the new ones rise word by word (40 ms apart, at most six steps) while the old ones leave
 *  upwards in the same spot. The live region is the heading itself (the leaving words are hidden from it). */
function StageTitle({ text: wanted }: { text: string }) {
  // the title on show changes at most once per TITLE_DWELL_MS, to the newest wish (a burst of phases skips ahead)
  const [text, setText] = useState(wanted);
  const since = useRef(performance.now());
  useEffect(() => {
    if (wanted === text) return;
    const t = window.setTimeout(() => {
      since.current = performance.now();
      setText(wanted);
    }, Math.max(0, TITLE_DWELL_MS - (performance.now() - since.current)));
    return () => window.clearTimeout(t);
  }, [wanted, text]);
  const [cur, setCur] = useState({ text, k: 0 });
  const [prev, setPrev] = useState<{ text: string; k: number } | null>(null);
  if (text !== cur.text) {
    // derived in render: the words on screen become the leaving layer
    setPrev({ text: cur.text, k: cur.k });
    setCur({ text, k: cur.k + 1 });
  }
  useEffect(() => {
    if (!prev) return;
    const t = window.setTimeout(() => setPrev(null), MOTION.base);
    return () => window.clearTimeout(t);
  }, [prev]);
  const words = cur.text.split(" ");
  return (
    <h2 className="grid font-display font-bold leading-[1.02] tracking-[-0.035em] text-white [font-size:clamp(26px,5.3cqw,66px)] [text-wrap:balance] [&>*]:col-start-1 [&>*]:row-start-1" aria-live="polite">
      {prev && (
        <span key={`p${prev.k}`} aria-hidden className="animate-word-out">
          {prev.text}
        </span>
      )}
      <span key={cur.k}>
        {words.map((w, i) => (
          <span key={i}>
            <span className={cn("inline-block", cur.k > 0 && "animate-word-rise")} style={cur.k > 0 ? { animationDelay: `${(prev ? 90 : 0) + Math.min(i, 6) * 40}ms` } : undefined}>
              {w}
            </span>
            {i < words.length - 1 ? " " : ""}
          </span>
        ))}
      </span>
    </h2>
  );
}

/** How long a line stays before the next one may replace it: a burst of the designer's lines reads as a sequence. */
const DWELL_MS = 900;
/** Typing: 12 ms a character, a long line within 0.7 s. */
const CHAR_MS = 12;
const TYPE_MAX_MS = 700;

/** The agent's newest line, typing itself in mono; a line stays at least 0.9 s (a burst skips to its newest line). */
function NowLine({ line }: { line: StageLine | null }) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<StageLine | null>(line);
  const since = useRef(performance.now());
  useEffect(() => {
    if (!line || line.n === shown?.n) return;
    const wait = Math.max(0, DWELL_MS - (performance.now() - since.current));
    const t = window.setTimeout(() => {
      since.current = performance.now();
      setShown(line);
    }, wait);
    return () => window.clearTimeout(t);
  }, [line, shown?.n]);
  const [len, setLen] = useState(0);
  useEffect(() => {
    if (!shown) return;
    if (reduced) return void setLen(shown.text.length);
    setLen(0);
    const start = performance.now();
    const per = Math.min(CHAR_MS, TYPE_MAX_MS / Math.max(1, shown.text.length));
    let raf = 0;
    const tick = () => {
      const n = Math.min(shown.text.length, Math.floor((performance.now() - start) / per));
      setLen(n);
      if (n < shown.text.length) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // a new line (its number), not a new object of the same line
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown?.n, reduced]);
  if (!shown) return <p className="min-h-[4.65em] [font-size:clamp(12px,1.4cqw,16px)]" />;
  const prefix = shown.slide && !/слайд/i.test(shown.text) ? `Слайд ${shown.slide} · ` : "";
  const typing = len < shown.text.length;
  return (
    <p className="line-clamp-3 min-h-[4.65em] font-mono leading-[1.55] text-white/70 [font-size:clamp(12px,1.4cqw,16px)]" title={shown.text}>
      {prefix && <span className="text-[#8FB4FF]">{prefix}</span>}
      {shown.text.slice(0, len)}
      {/* the caret blinks only while the line types */}
      <span className={cn("ml-0.5 inline-block h-[1.1em] w-[0.5ch] translate-y-[0.18em] bg-[#8FB4FF]", typing ? "opacity-100" : "animate-caret")} aria-hidden />
    </p>
  );
}

function StageProgress({ value, queued }: { value: number; queued: boolean }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div className="flex items-center gap-[2cqw]">
      <div className="relative h-[max(6px,0.55cqw)] flex-1">
        {/* a dark track with a hairline: the part still to go never reads as filled over the violet glow */}
        <div className="absolute inset-0 overflow-hidden rounded-full bg-black/40 ring-1 ring-inset ring-white/10">
          {queued ? (
            <div className="absolute inset-y-0 left-0 w-[30%] animate-sweep rounded-full bg-brand" />
          ) : (
            <div className="absolute inset-0 rounded-full bg-brand transition-transform duration-600 ease-glide" style={{ transform: `translateX(${pct - 100}%)` }} />
          )}
        </div>
        {/* the glowing head rides on the bar's end */}
        {!queued && pct > 0 && (
          <span
            aria-hidden
            className="absolute top-1/2 h-[260%] w-[max(10px,1cqw)] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#8A6CFF] blur-[6px] transition-[left] duration-600 ease-glide"
            style={{ left: `${pct}%` }}
          />
        )}
      </div>
      <span className="w-[4.2ch] shrink-0 text-right font-mono font-medium tabular-nums text-white [font-size:clamp(12px,1.35cqw,16px)]">
        {queued ? "—" : <CountUp value={pct} ms={MOTION.data} format={(n) => `${Math.round(n)}%`} />}
      </span>
    </div>
  );
}

export interface BuildStageProps {
  kicker: string;
  title: string;
  line: StageLine | null;
  sketch: Sketch | null;
  mode: BlueprintMode;
  progress: number;
  queued: boolean;
  /** «1:42 / 5:00» */
  timer: string;
  aspect: number;
  running: boolean;
  className?: string;
  style?: CSSProperties;
}

export function BuildStage({ kicker, title, line, sketch, mode, progress, queued, timer, aspect, running, className, style }: BuildStageProps) {
  return (
    <section
      aria-label="Сцена сборки"
      className={cn("relative isolate overflow-hidden rounded-[20px] bg-stage text-white shadow-[0_30px_70px_-34px_rgba(11,13,18,0.7)]", className)}
      style={{ aspectRatio: String(aspect), containerType: "size", ...style }}
    >
      {/* the two glows breathe out of phase while the work runs; the dots fade towards the edges */}
      <div aria-hidden className={cn("pointer-events-none absolute -left-[12%] -top-[38%] -z-10 h-[95%] w-[62%] rounded-full bg-[#0066F5] opacity-45 blur-[90px]", running && "animate-stage-glow")} />
      <div aria-hidden className={cn("pointer-events-none absolute -bottom-[42%] -right-[8%] -z-10 h-[95%] w-[58%] rounded-full bg-[#6A4DFF] opacity-40 blur-[100px]", running && "animate-stage-glow [animation-delay:-3.5s]")} />
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 [background-image:radial-gradient(rgba(255,255,255,0.075)_1px,transparent_1.2px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_50%_45%,#000_25%,transparent_78%)]" />
      <div className="flex h-full flex-col px-[4.6cqw] pb-[3.8cqw] pt-[3.6cqw]">
        <div className="flex items-center justify-between gap-4 font-mono font-medium uppercase tracking-[0.14em] [font-size:clamp(11px,1.05cqw,13px)]">
          <span className="truncate text-white/80">
            <span className="text-[#9DBBFF]">///</span> {kicker}
          </span>
          <span className="shrink-0 tabular-nums tracking-normal text-white/70">{timer}</span>
        </div>
        <div className="flex min-h-0 flex-1 items-center gap-[4.5cqw]">
          <div className="min-w-0 flex-[1.12]">
            <StageTitle text={title} />
            <div className="mt-[2.2cqw]">
              <NowLine line={line} />
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <Blueprint sketch={sketch} mode={mode} aspect={aspect} running={running} />
          </div>
        </div>
        <StageProgress value={progress} queued={queued} />
      </div>
    </section>
  );
}
