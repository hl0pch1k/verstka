// A storyboard card's sketch of a planned slide: a light wireframe in the slide's proportions, in the form the designer
// chose — the slide's headline as its title, then the body: columns, a pie, a line, a table, cards, rows. It is drawn
// in the template's own strong colour (`--sk`, `--sk-soft` on a parent: lib/stage sketchInk), so the storyboard
// already looks like the deck. `live`: the slide was planned while the reader watched — the sketch draws itself once
// (bars grow from the baseline, rules run out from their start, the line draws); a card shown later (another variant,
// a page opened mid-build) is finished at once. Sizes follow the card's width (the card is an inline-size container).
// Decorative (aria-hidden): the card's caption and the agent's column say the same in words.
import { createContext, useContext, type CSSProperties, type ReactNode } from "react";
import type { Sketch, SketchKind } from "../../lib/stage";
import { cn } from "../../lib/utils";

const INK = "bg-[color:var(--sk)]";
const SOFT = "bg-[color:var(--sk-soft)]";
const GREY = "bg-zinc-200";
const GREY_SOFT = "bg-zinc-100";
const RULE = "bg-zinc-300";

type Grow = "x" | "y" | "top" | "fade";

const GROW: Record<Grow, string> = {
  x: "origin-left animate-grow-x",
  y: "origin-bottom animate-grow-y",
  top: "origin-top animate-grow-y",
  fade: "animate-fade",
};

/** The sketch is drawn while the reader watches (its pieces grow in turn) or shown finished. */
const Live = createContext(false);

/** A piece of the drawing, placed in % of the card; live, each grows in its turn (50 ms apart, from 120 ms). */
function Box({ x, y, w, h, className, grow = "x", i = 0 }: { x: number; y: number; w: number; h: number; className?: string; grow?: Grow; i?: number }) {
  const live = useContext(Live);
  return (
    <span
      className={cn("absolute rounded-[2px]", className, live && GROW[grow])}
      style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%`, ...(live ? { animationDelay: `${120 + i * 50}ms` } : null) }}
    />
  );
}

const at = (live: boolean, i: number, from = 120, step = 50): CSSProperties | undefined => (live ? { animationDelay: `${from + i * step}ms` } : undefined);

/** Up to three figures of the headline («32%», «12 дней», «225 000 ₽») for a slide of big numbers: the sketch never
 *  makes figures up — a missing one is a bold bar. */
function figuresOf(headline: string | null): string[] {
  const found = (headline ?? "").match(/[−-]?\d[\d   ]*(?:[.,]\d+)?\s?(?:%|₽|млн|млрд|тыс\.?|м²|×)?/g) ?? [];
  return found.map((s) => s.replace(/[\s  ]+$/, "").trim()).filter((s) => s.length > 0 && s.length <= 8).slice(0, 3);
}

/** The slide's own title, top left, as on a slide of the template. */
function Title({ text, live }: { text: string; live: boolean }) {
  return (
    <p className={cn("absolute left-[7%] right-[9%] top-[8%] line-clamp-2 font-semibold leading-[1.25] text-zinc-800 [font-size:max(8px,5cqw)]", live && "animate-fade")}>
      {text}
    </p>
  );
}

function Body({ kind, headline, live }: { kind: SketchKind; headline: string; live: boolean }): ReactNode {
  switch (kind) {
    case "cover":
      return (
        <>
          <p className={cn("absolute left-[7%] right-[16%] top-[27%] line-clamp-3 font-bold leading-[1.12] text-zinc-900 [font-size:max(9px,7cqw)]", live && "animate-fade")}>{headline}</p>
          <Box x={7} y={76} w={34} h={3.4} className={GREY} i={2} />
          <Box x={7} y={84} w={12} h={3} className={INK} i={3} />
        </>
      );
    case "section":
    case "closing":
      return (
        <>
          <Box x={7} y={33} w={10} h={3.2} className={INK} i={0} />
          <p className={cn("absolute left-[7%] right-[14%] top-[42%] line-clamp-2 font-bold leading-[1.15] text-zinc-900 [font-size:max(9px,6.4cqw)]", live && "animate-fade")}>{headline}</p>
        </>
      );
    case "quote":
      return (
        <>
          <span className={cn("absolute left-[7%] top-[14%] font-bold leading-none text-[color:var(--sk)] [font-size:max(18px,13cqw)]", live && "animate-fade")}>“</span>
          <p className={cn("absolute left-[18%] right-[10%] top-[38%] line-clamp-3 font-medium leading-[1.3] text-zinc-800 [font-size:max(8px,5cqw)]", live && "animate-fade")} style={at(live, 1)}>{headline}</p>
          <Box x={18} y={82} w={14} h={2.6} className={INK} i={4} />
        </>
      );
    case "bars":
      return (
        <>
          <Title text={headline} live={live} />
          {[0.42, 0.64, 0.5, 0.88, 0.6].map((f, i) => (
            <Box key={i} x={12 + i * 16} y={88 - f * 44} w={10} h={f * 44} className={i === 3 ? INK : SOFT} grow="y" i={i} />
          ))}
          <Box x={8} y={88} w={84} h={0.9} className={RULE} i={0} />
        </>
      );
    case "hbars":
      return (
        <>
          <Title text={headline} live={live} />
          <Box x={8} y={41} w={0.7} h={47} className={RULE} grow="top" />
          {[62, 46, 78, 34].map((w, i) => (
            <Box key={i} x={8.7} y={44 + i * 11} w={w} h={7} className={i === 2 ? INK : SOFT} i={i} />
          ))}
        </>
      );
    case "pie":
      return (
        <>
          <Title text={headline} live={live} />
          <svg viewBox="0 0 100 100" className="absolute left-[9%] top-[39%] h-[50%]" style={{ aspectRatio: "1" }} aria-hidden>
            {[
              { len: 46, off: 0, color: "var(--sk)" },
              { len: 30, off: 46, color: "var(--sk-soft)" },
              { len: 24, off: 76, color: "#E3E4E7" },
            ].map((s, i) => (
              <circle
                key={i}
                cx="50"
                cy="50"
                r="34"
                fill="none"
                stroke={s.color}
                strokeWidth="22"
                pathLength={100}
                strokeDasharray={`${s.len} ${100 - s.len}`}
                strokeDashoffset={-s.off}
                transform="rotate(-90 50 50)"
                className={live ? "animate-fade" : undefined}
                style={at(live, i, 140, 80)}
              />
            ))}
          </svg>
          {["var(--sk)", "var(--sk-soft)", "#E3E4E7"].map((c, i) => (
            <span key={i} className={cn("absolute flex items-center gap-[6%]", live && "animate-fade")} style={{ left: "50%", top: `${47 + i * 12}%`, width: "36%", height: "5%", ...at(live, i, 300, 70) }}>
              <span className="h-full shrink-0 rounded-full" style={{ aspectRatio: "1", background: c }} />
              <span className={cn("h-[70%] flex-1 rounded-[2px]", GREY)} />
            </span>
          ))}
        </>
      );
    case "line":
      return (
        <>
          <Title text={headline} live={live} />
          <svg viewBox="0 0 250 100" preserveAspectRatio="none" className="absolute left-[8%] top-[42%] h-[44%] w-[84%] overflow-visible" aria-hidden>
            <path d="M0 100 L0 74 L50 62 L100 66 L150 40 L200 46 L250 12 L250 100 Z" fill="var(--sk)" fillOpacity="0.08" className={live ? "animate-fade" : undefined} style={at(live, 0, 520)} />
            <path d="M0 88 L50 84 L100 79 L150 74 L200 70 L250 60" fill="none" stroke="#C9D0D9" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" pathLength={100} strokeDasharray="100" className={live ? "animate-draw" : undefined} style={at(live, 0, 220)} />
            <path d="M0 74 L50 62 L100 66 L150 40 L200 46 L250 12" fill="none" stroke="var(--sk)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" pathLength={100} strokeDasharray="100" className={live ? "animate-draw" : undefined} style={at(live, 0, 120)} />
          </svg>
          <Box x={8} y={88} w={84} h={0.9} className={RULE} i={0} />
        </>
      );
    case "table":
      return (
        <>
          <Title text={headline} live={live} />
          <Box x={7} y={40} w={86} h={9} className={SOFT} i={0} />
          {[49, 59, 69, 79, 89].map((y, i) => (
            <Box key={`r${i}`} x={7} y={y} w={86} h={0.8} className={GREY} i={i + 1} />
          ))}
          {[33, 55, 74].map((x, i) => (
            <Box key={`c${i}`} x={x} y={40} w={0.6} h={49.8} className={GREY} grow="top" i={i + 2} />
          ))}
        </>
      );
    case "numbers": {
      const figures = figuresOf(headline);
      return (
        <>
          <Title text={headline} live={live} />
          {[0, 1, 2].map((i) => (
            <span key={i} className={cn("absolute flex flex-col gap-[9%]", live && "animate-fade-in")} style={{ left: `${7 + i * 30}%`, top: "44%", width: "26%", height: "42%", ...at(live, i, 140, 80) }}>
              {figures[i] ? (
                <span className={cn("truncate font-bold leading-none [font-size:max(9px,6.4cqw)]", i === 0 ? "text-[color:var(--sk)]" : "text-zinc-800")}>{figures[i]}</span>
              ) : (
                <span className={cn("block h-[26%] w-[70%] rounded-[2px]", i === 0 ? INK : "bg-zinc-300")} />
              )}
              <span className={cn("block h-[11%] w-[86%] rounded-[2px]", GREY)} />
              <span className={cn("block h-[11%] w-[58%] rounded-[2px]", GREY_SOFT)} />
            </span>
          ))}
        </>
      );
    }
    case "cards":
      return (
        <>
          <Title text={headline} live={live} />
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={cn("absolute flex flex-col gap-[10%] rounded-[6%] bg-zinc-50 p-[5%] shadow-[inset_0_0_0_1px_#E3E4E7]", live && "animate-fade-in")}
              style={{ left: `${7 + i * 29.5}%`, top: "40%", width: "26.5%", height: "48%", ...at(live, i, 140, 80) }}
            >
              <span className={cn("block h-[20%] shrink-0 rounded-full", INK)} style={{ aspectRatio: "1" }} />
              <span className="mt-auto block h-[10%] w-[82%] rounded-[2px] bg-zinc-300" />
              <span className={cn("block h-[10%] w-[60%] rounded-[2px]", GREY)} />
            </span>
          ))}
        </>
      );
    case "list":
    case "agenda":
      return (
        <>
          <Title text={headline} live={live} />
          {[72, 60, 78, 52].map((w, i) => (
            <span key={i} className={cn("absolute flex items-center gap-[3%]", live && "animate-fade-in")} style={{ left: "7%", top: `${42 + i * 12}%`, width: `${w}%`, height: "6%", ...at(live, i, 140, 70) }}>
              {kind === "agenda" ? (
                <span className="w-[6%] shrink-0 font-semibold leading-none text-[color:var(--sk)] [font-size:max(7px,4cqw)]">{i + 1}</span>
              ) : (
                <span className={cn("block h-[64%] shrink-0 rounded-full", INK)} style={{ aspectRatio: "1" }} />
              )}
              <span className={cn("block h-full flex-1 rounded-[2px]", GREY)} />
            </span>
          ))}
        </>
      );
    case "timeline":
      return (
        <>
          <Title text={headline} live={live} />
          <Box x={7} y={63} w={86} h={0.9} className={RULE} i={0} />
          {[0, 1, 2, 3].map((i) => (
            <span key={i}>
              <span
                className={cn("absolute rounded-full shadow-[0_0_0_2px_var(--sk-soft)]", INK, live && "animate-pop")}
                style={{ left: `${11 + i * 24}%`, top: "60.6%", width: "3.4%", aspectRatio: "1", ...at(live, i, 240, 80) }}
              />
              <Box x={7 + i * 24} y={i % 2 ? 71 : 44} w={15} h={4.6} className="bg-zinc-300" i={i + 2} />
              <Box x={7 + i * 24} y={i % 2 ? 79 : 52} w={10} h={3.6} className={GREY} i={i + 3} />
            </span>
          ))}
        </>
      );
    case "compare":
      return (
        <>
          <Title text={headline} live={live} />
          {[0, 1].map((c) => (
            <span key={c}>
              <Box x={7 + c * 45} y={41} w={38} h={7} className={c === 0 ? INK : "bg-zinc-300"} i={c} />
              {[34, 27, 31].map((w, r) => (
                <Box key={r} x={7 + c * 45} y={55 + r * 11} w={w} h={4.6} className={GREY} i={2 + c * 3 + r} />
              ))}
            </span>
          ))}
          <Box x={49.7} y={40} w={0.6} h={48} className={GREY} grow="top" i={1} />
        </>
      );
    case "image":
      return (
        <>
          <Title text={headline} live={live} />
          <span className={cn("absolute left-[7%] top-[40%] h-[48%] w-[40%] overflow-hidden rounded-[4%]", SOFT, live && "animate-fade")} style={at(live, 0)}>
            <svg viewBox="0 0 40 24" preserveAspectRatio="xMidYMax slice" className="absolute inset-0 h-full w-full" aria-hidden>
              <circle cx="30" cy="7" r="2.6" fill="var(--sk)" fillOpacity="0.55" />
              <path d="M0 24 L12 11 L21 19 L27 14 L40 24 Z" fill="var(--sk)" fillOpacity="0.4" />
            </svg>
          </span>
          <Box x={52} y={42} w={36} h={6} className="bg-zinc-300" i={1} />
          {[34, 30, 22].map((w, i) => (
            <Box key={i} x={52} y={55 + i * 10} w={w} h={4.4} className={GREY} i={i + 2} />
          ))}
        </>
      );
    default:
      return (
        <>
          <Title text={headline} live={live} />
          {[84, 78, 88, 62, 72].map((w, i) => (
            <Box key={i} x={7} y={42 + i * 9.4} w={w} h={4.4} className={GREY} i={i} />
          ))}
        </>
      );
  }
}

export function SlideSketch({ sketch, live }: { sketch: Sketch; live: boolean }) {
  return (
    <div aria-hidden className="absolute inset-0">
      <Live.Provider value={live}>
        <Body kind={sketch.kind} headline={sketch.headline ?? "Слайд без заголовка"} live={live} />
      </Live.Provider>
    </div>
  );
}
