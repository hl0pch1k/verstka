import { useCountUp } from "../../lib/motion";
import { cn, scoreTone } from "../../lib/utils";

const STROKE: Record<ReturnType<typeof scoreTone>, string> = {
  success: "#10B981",
  warn: "#F59E0B",
  error: "#EF4444",
  neutral: "#C9CDD2",
};

/** Audit score as a ring with the plain number inside (0–100). The number moves from the last shown value, so a variant
 *  switch never drains the ring; the tooltip carries the formula. `tone` overrides the colour the score gives (a deck
 *  with errors is red whatever its score, so the ring never reads green next to a red verdict). */
export function ScoreRing({ score, size = 44, stroke = 4, className, label = true, tone: toneOverride }: { score: number | null; size?: number; stroke?: number; className?: string; label?: boolean; tone?: ReturnType<typeof scoreTone> }) {
  const tone = toneOverride ?? scoreTone(score);
  const shown = useCountUp(score);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const frac = shown === null ? 0 : Math.min(1, Math.max(0, shown / 100));
  const title = score === null ? "Проверка не запускалась" : `Оценка качества ${Math.round(score)} из 100 · 100 − 10 за ошибку − 3 за предупреждение`;
  return (
    <span
      role="img"
      aria-label={score === null ? "Оценка качества: нет" : `Оценка качества ${Math.round(score)} из 100`}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      title={title}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#F0F2F5" strokeWidth={stroke} />
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
        <span className="absolute font-bold tabular-nums text-zinc-900" style={{ fontSize: Math.max(12, Math.round(size * 0.32)) }} aria-hidden>
          {shown === null ? "—" : Math.round(shown)}
        </span>
      )}
    </span>
  );
}
