// The stage's sketch of the slide the agent speaks of: a wireframe in the slide's own proportions that draws itself in
// the form the designer chose — columns grow, a pie turns, a line runs, a table rules itself, cards and rows land. The
// slide's number and headline sit on top. Before the first slide is planned (the author, the analyst) the sketch is a
// page being read: lines of text under a highlight that runs down; while the deck is checked, checks pop over it.
// Decorative (aria-hidden): the stage's own line says the same in words. Keyed by the slide and its form, so each new
// sketch draws itself once; reduced motion shows it finished.
import type { CSSProperties, ReactNode } from "react";
import { Check } from "lucide-react";
import type { Sketch } from "../../lib/stage";
import { cn } from "../../lib/utils";

export type BlueprintMode = "read" | "sketch" | "check";

const INK = "bg-white/[0.16]";
const INK_SOFT = "bg-white/[0.09]";
const ACCENT = "bg-[#4D7CFF]";

/** A block of the wireframe, placed in % of the sketch. */
function Box({ x, y, w, h, className, style, children }: { x: number; y: number; w: number; h: number; className?: string; style?: CSSProperties; children?: ReactNode }) {
  return (
    <span className={cn("absolute rounded-[3px]", className)} style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%`, ...style }}>
      {children}
    </span>
  );
}

const delay = (i: number, step = 60, from = 40): CSSProperties => ({ animationDelay: `${from + i * step}ms` });

/** Up to three numbers of the headline («35%», «225 000 ₽»), for the sketch of a slide of big numbers. */
function numbersOf(headline: string | null): string[] {
  const found = (headline ?? "").match(/\d[\d  ]*(?:[.,]\d+)?\s?(?:%|₽|млн|млрд|тыс\.?|м²)?/g) ?? [];
  const clean = found.map((s) => s.replace(/[  ]+$/, "").trim()).filter((s) => s.length <= 9);
  return [...clean, "72%", "1,2", "×3"].slice(0, 3);
}

function Drawing({ kind, headline }: { kind: Sketch["kind"]; headline: string | null }) {
  switch (kind) {
    case "cover":
      return (
        <>
          <Box x={8} y={36} w={68} h={10} className={cn("origin-left animate-grow-x", "bg-white/70")} style={delay(0)} />
          <Box x={8} y={50} w={50} h={10} className={cn("origin-left animate-grow-x", "bg-white/70")} style={delay(1)} />
          <Box x={8} y={66} w={36} h={4} className={cn("origin-left animate-grow-x", INK)} style={delay(2)} />
          <Box x={8} y={86} w={16} h={3} className={cn("origin-left animate-grow-x", ACCENT)} style={delay(3)} />
        </>
      );
    case "bars":
      return (
        <>
          {[42, 64, 50, 86, 58].map((h, i) => (
            <Box key={i} x={12 + i * 16} y={86 - h * 0.62} w={10} h={h * 0.62} className={cn("origin-bottom animate-grow-y", i === 3 ? ACCENT : INK)} style={delay(i)} />
          ))}
          <Box x={8} y={86.5} w={84} h={0.8} className={cn("origin-left animate-grow-x", "bg-white/30")} style={delay(0, 0, 60)} />
        </>
      );
    case "hbars":
      return (
        <>
          {[70, 52, 84, 38].map((w, i) => (
            <Box key={i} x={10} y={30 + i * 15} w={w * 0.82} h={8} className={cn("origin-left animate-grow-x", i === 2 ? ACCENT : INK)} style={delay(i)} />
          ))}
          <Box x={9.4} y={26} w={0.8} h={62} className={cn("origin-top animate-grow-y", "bg-white/30")} style={delay(0, 0, 60)} />
        </>
      );
    case "pie":
      return (
        <>
          <svg viewBox="0 0 100 100" className="absolute left-[9%] top-[30%] h-[60%]" style={{ aspectRatio: "1" }} aria-hidden>
            <circle cx="50" cy="50" r="36" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="18" />
            {[
              { len: 46, off: 0, color: "#4D7CFF" },
              { len: 30, off: 46, color: "#8A6CFF" },
              { len: 24, off: 76, color: "rgba(255,255,255,0.45)" },
            ].map((s, i) => (
              <circle
                key={i}
                cx="50"
                cy="50"
                r="36"
                fill="none"
                stroke={s.color}
                strokeWidth="18"
                pathLength={100}
                strokeDasharray={`${s.len} ${100 - s.len}`}
                strokeDashoffset={-s.off}
                transform="rotate(-90 50 50)"
                className="animate-fade"
                style={{ animationDelay: `${150 + i * 140}ms`, animationDuration: "500ms" }}
              />
            ))}
          </svg>
          {["#4D7CFF", "#8A6CFF", "rgba(255,255,255,0.45)"].map((c, i) => (
            <span key={i} className="absolute flex animate-fade-in items-center gap-[6%]" style={{ left: "58%", top: `${38 + i * 15}%`, width: "34%", height: "6%", ...delay(i, 90, 300) }}>
              <span className="h-full shrink-0 rounded-full" style={{ aspectRatio: "1", background: c }} />
              <span className="h-[60%] flex-1 rounded-[3px] bg-white/[0.16]" />
            </span>
          ))}
        </>
      );
    case "line":
      return (
        <svg viewBox="0 0 250 100" className="absolute left-[8%] top-[30%] h-[58%] w-[84%] overflow-visible" aria-hidden>
          <defs>
            <linearGradient id="bp-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#4D7CFF" stopOpacity="0.32" />
              <stop offset="1" stopColor="#4D7CFF" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d="M0 100 L0 82 L45 68 L90 73 L135 46 L180 53 L250 18 L250 100 Z" fill="url(#bp-area)" className="animate-fade" style={{ animationDelay: "600ms", animationDuration: "600ms" }} />
          <path d="M0 92 L45 87 L90 83 L135 77 L180 74 L250 63" fill="none" stroke="rgba(255,255,255,0.38)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" pathLength={100} strokeDasharray="100" className="animate-draw" style={{ ["--len" as string]: "100", animationDelay: "260ms" }} />
          <path d="M0 82 L45 68 L90 73 L135 46 L180 53 L250 18" fill="none" stroke="#7AA2FF" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" pathLength={100} strokeDasharray="100" className="animate-draw" style={{ ["--len" as string]: "100", animationDelay: "120ms" }} />
          {[[135, 46], [250, 18]].map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="5" fill="#0B0D12" stroke="#7AA2FF" strokeWidth="2.5" className="animate-pop" style={{ animationDelay: `${700 + i * 120}ms`, transformBox: "fill-box", transformOrigin: "center" }} />
          ))}
        </svg>
      );
    case "table":
      return (
        <>
          <Box x={8} y={28} w={84} h={12} className={cn("origin-left animate-grow-x", "bg-white/[0.14]")} style={delay(0)} />
          {[40, 52, 64, 76, 88].map((y, i) => (
            <Box key={`r${i}`} x={8} y={y} w={84} h={0.7} className={cn("origin-left animate-grow-x", "bg-white/25")} style={delay(i + 1)} />
          ))}
          {[36, 57, 76].map((x, i) => (
            <Box key={`c${i}`} x={x} y={28} w={0.7} h={60} className={cn("origin-top animate-grow-y", "bg-white/20")} style={delay(i, 80, 300)} />
          ))}
        </>
      );
    case "numbers": {
      const nums = numbersOf(headline);
      return (
        <>
          {nums.map((n, i) => (
            <span key={i} className="absolute flex animate-fade-in flex-col gap-[10%]" style={{ left: `${8 + i * 30}%`, top: "36%", width: "26%", height: "46%", ...delay(i, 110) }}>
              <span className={cn("truncate font-display font-bold leading-none", i === 0 ? "text-[#7AA2FF]" : "text-white/85")} style={{ fontSize: "clamp(12px, 2.4cqw, 30px)" }}>{n}</span>
              <span className={cn("block h-[9%] w-[80%] rounded-[3px]", INK)} />
              <span className={cn("block h-[9%] w-[55%] rounded-[3px]", INK_SOFT)} />
            </span>
          ))}
        </>
      );
    }
    case "cards":
      return (
        <>
          {[0, 1, 2].map((i) => (
            <span key={i} className="absolute flex animate-fill-in flex-col gap-[9%] rounded-[6px] border border-white/10 bg-white/[0.06] p-[3%]" style={{ left: `${8 + i * 29}%`, top: "32%", width: "26%", height: "54%", ...delay(i, 90) }}>
              <span className={cn("block h-[22%] rounded-full", ACCENT)} style={{ aspectRatio: "1" }} />
              <span className={cn("block h-[11%] w-[85%] rounded-[3px]", "bg-white/40")} />
              <span className={cn("block h-[9%] w-[70%] rounded-[3px]", INK)} />
              <span className={cn("block h-[9%] w-[50%] rounded-[3px]", INK_SOFT)} />
            </span>
          ))}
        </>
      );
    case "list":
    case "agenda":
      return (
        <>
          {[78, 64, 82, 56].map((w, i) => (
            <span key={i} className="absolute flex animate-slide-in-l items-center gap-[3%]" style={{ left: "8%", top: `${32 + i * 14}%`, width: `${w}%`, height: "7%", ...delay(i, 80) }}>
              {kind === "agenda" ? (
                <span className="font-mono font-semibold leading-none text-[#7AA2FF]" style={{ fontSize: "clamp(9px, 1.2cqw, 15px)" }}>{`0${i + 1}`}</span>
              ) : (
                <span className={cn("block h-[70%] shrink-0 rounded-full", ACCENT)} style={{ aspectRatio: "1" }} />
              )}
              <span className={cn("block h-full flex-1 rounded-[3px]", i === 0 ? "bg-white/40" : INK)} />
            </span>
          ))}
        </>
      );
    case "timeline":
      return (
        <>
          <Box x={8} y={58} w={84} h={0.9} className={cn("origin-left animate-grow-x", "bg-white/30")} style={delay(0, 0, 80)} />
          {[0, 1, 2, 3].map((i) => (
            <span key={i}>
              <span className="absolute animate-pop rounded-full bg-[#4D7CFF] ring-[3px] ring-[#4D7CFF]/25" style={{ left: `${12 + i * 24}%`, top: "55.5%", width: "3.2%", aspectRatio: "1", ...delay(i, 120, 260) }} />
              <Box x={8 + i * 24} y={i % 2 ? 66 : 40} w={14} h={5} className={cn("origin-left animate-grow-x", INK)} style={delay(i, 120, 320)} />
              <Box x={8 + i * 24} y={i % 2 ? 74 : 48} w={10} h={4} className={cn("origin-left animate-grow-x", INK_SOFT)} style={delay(i, 120, 360)} />
            </span>
          ))}
        </>
      );
    case "compare":
      return (
        <>
          {[0, 1].map((c) => (
            <span key={c}>
              <Box x={8 + c * 45} y={30} w={39} h={9} className={cn("origin-left animate-grow-x", c === 0 ? ACCENT : "bg-white/40")} style={delay(c)} />
              {[0, 1, 2].map((r) => (
                <Box key={r} x={8 + c * 45} y={46 + r * 13} w={[34, 28, 31][r]} h={6} className={cn("origin-left animate-grow-x", INK)} style={delay(c * 3 + r, 60, 220)} />
              ))}
            </span>
          ))}
          <Box x={49.6} y={28} w={0.8} h={62} className={cn("origin-top animate-grow-y", "bg-white/20")} style={delay(0, 0, 100)} />
        </>
      );
    case "quote":
      return (
        <>
          <span className="absolute left-[8%] top-[18%] animate-fade-in font-display font-bold leading-none text-[#7AA2FF]" style={{ fontSize: "clamp(28px, 7cqw, 84px)" }}>“</span>
          <Box x={18} y={44} w={70} h={7} className={cn("origin-left animate-grow-x", "bg-white/45")} style={delay(0, 0, 200)} />
          <Box x={18} y={56} w={56} h={7} className={cn("origin-left animate-grow-x", "bg-white/45")} style={delay(1, 80, 200)} />
          <Box x={18} y={74} w={22} h={4} className={cn("origin-left animate-grow-x", ACCENT)} style={delay(2, 80, 200)} />
        </>
      );
    case "image":
      return (
        <>
          <span className="absolute left-[8%] top-[28%] h-[60%] w-[40%] animate-fill-in overflow-hidden rounded-[6px] bg-white/[0.08]">
            <svg viewBox="0 0 40 30" className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMax slice" aria-hidden>
              <circle cx="29" cy="9" r="3.4" fill="#7AA2FF" opacity="0.8" />
              <path d="M0 30 L13 15 L22 24 L28 18 L40 30 Z" fill="rgba(255,255,255,0.22)" />
            </svg>
          </span>
          <Box x={54} y={34} w={36} h={8} className={cn("origin-left animate-grow-x", "bg-white/45")} style={delay(0, 0, 200)} />
          {[0, 1, 2].map((i) => <Box key={i} x={54} y={50 + i * 11} w={[34, 30, 22][i]} h={5} className={cn("origin-left animate-grow-x", INK)} style={delay(i, 70, 300)} />)}
        </>
      );
    case "section":
      return (
        <>
          <span className="absolute left-[8%] top-[30%] animate-fade-in font-display font-bold leading-none text-[#7AA2FF]" style={{ fontSize: "clamp(22px, 5cqw, 60px)" }}>02</span>
          <Box x={8} y={62} w={56} h={9} className={cn("origin-left animate-grow-x", "bg-white/60")} style={delay(0, 0, 220)} />
          <Box x={8} y={76} w={30} h={4} className={cn("origin-left animate-grow-x", INK)} style={delay(1, 80, 220)} />
        </>
      );
    default:
      return (
        <>
          {[84, 78, 88, 64, 72].map((w, i) => (
            <Box key={i} x={8} y={34 + i * 11} w={w} h={5} className={cn("origin-left animate-grow-x", INK)} style={delay(i, 70)} />
          ))}
        </>
      );
  }
}

/** The page being read: lines of a text under a highlight that runs down it (only while the work runs). */
function Reading({ running }: { running: boolean }) {
  return (
    <>
      {[62, 88, 80, 92, 54, 86, 76, 90, 48].map((w, i) => (
        <Box key={i} x={8} y={14 + i * 8.6} w={w * 0.84} h={3.6} className={cn("animate-fade-in", i % 4 === 0 ? "bg-white/30" : INK)} style={delay(i, 50, 0)} />
      ))}
      {running && <span className="absolute inset-x-0 top-0 h-[18%] animate-scan-down bg-gradient-to-b from-transparent via-[#4D7CFF]/25 to-transparent" />}
    </>
  );
}

export function Blueprint({ sketch, mode, aspect, running }: { sketch: Sketch | null; mode: BlueprintMode; aspect: number; running: boolean }) {
  const reading = mode === "read" || !sketch;
  const key = reading ? "read" : `${sketch.slide}-${sketch.kind}`;
  return (
    <div aria-hidden className="relative w-full overflow-hidden rounded-[1.4cqw] border border-white/[0.14] bg-white/[0.035] shadow-[0_20px_50px_-24px_rgba(0,0,0,0.6)]" style={{ aspectRatio: String(aspect) }}>
      {/* the slide's number and headline on top (the sketch's own title bar) */}
      {!reading && (
        <div key={`h-${key}`} className="absolute inset-x-[8%] top-[8%] flex animate-fade-in items-baseline gap-[3%]">
          <span className="shrink-0 font-mono font-semibold uppercase tracking-[0.12em] text-[#9DBBFF]" style={{ fontSize: "clamp(11px, 0.95cqw, 13px)" }}>{String(sketch.slide).padStart(2, "0")}</span>
          <span className="line-clamp-2 min-w-0 font-semibold leading-[1.25] text-white/90" style={{ fontSize: "clamp(11px, 1.2cqw, 15px)" }}>{sketch.headline ?? "Слайд без заголовка"}</span>
        </div>
      )}
      <div key={key} className="absolute inset-0">
        {reading ? <Reading running={running} /> : <Drawing kind={sketch.kind} headline={sketch.headline} />}
      </div>
      {mode === "check" && !reading && (
        <div className="absolute inset-0">
          {[
            { x: 84, y: 30 },
            { x: 48, y: 52 },
            { x: 84, y: 74 },
          ].map((p, i) => (
            <span key={i} className="absolute flex animate-pop items-center justify-center rounded-full bg-emerald-500 text-white shadow-[0_0_0_4px_rgba(16,185,129,0.25)]" style={{ left: `${p.x}%`, top: `${p.y}%`, width: "7%", aspectRatio: "1", ...delay(i, 220, 200) }}>
              <Check className="h-[60%] w-[60%]" strokeWidth={3} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
