import { cn, scoreTone } from "../../lib/utils";

const STROKE: Record<ReturnType<typeof scoreTone>, string> = {
  success: "#22A447",
  warn: "#F2A600",
  error: "#E64646",
  neutral: "#99A2AD",
};

/** Audit score as a ring with the number inside (0–100). */
export function ScoreRing({ score, size = 44, stroke = 4, className, label = true }: { score: number | null; size?: number; stroke?: number; className?: string; label?: boolean }) {
  const tone = scoreTone(score);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const frac = score === null ? 0 : Math.min(1, Math.max(0, score / 100));
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }} title={score === null ? "Аудит не запускался" : `Оценка аудита ${Math.round(score)} из 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#E1E3E6" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={STROKE[tone]}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - frac)}
          style={{ transition: "stroke-dashoffset 600ms cubic-bezier(0.2, 0.8, 0.2, 1)" }}
        />
      </svg>
      {label && (
        <span className="absolute font-bold tabular-nums text-zinc-900" style={{ fontSize: Math.max(11, Math.round(size * 0.3)) }}>
          {score === null ? "—" : Math.round(score)}
        </span>
      )}
    </span>
  );
}
