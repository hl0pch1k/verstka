import { useCountUp } from "../../lib/motion";
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
  const shown = useCountUp(score); // the ring fills and the number counts up when the score appears
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const frac = shown === null ? 0 : Math.min(1, Math.max(0, shown / 100));
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }} title={score === null ? "Проверка не запускалась" : `Оценка качества ${Math.round(score)} из 100`}>
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
        />
      </svg>
      {label && (
        <span className="absolute font-bold tabular-nums text-zinc-900" style={{ fontSize: Math.max(11, Math.round(size * 0.3)) }}>
          {shown === null ? "—" : Math.round(shown)}
        </span>
      )}
    </span>
  );
}
