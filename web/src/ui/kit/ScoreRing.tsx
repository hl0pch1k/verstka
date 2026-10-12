/** Длина окружности кольца: r = 19, 2π·19 ≈ 119.38. */
const LEN = 119.38;

/** Кольцо оценки 44 px (R-aside): белая дорожка и синяя дуга — доля оценки от окружности, обводка 4, круглый конец,
 *  начало сверху; число в центре — Unbounded 13/20. */
export function ScoreRing({ score, size = 44 }: { score: number; size?: 44 }) {
  const s = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  return (
    <span style={{ position: "relative", display: "inline-block", width: size, height: size, flex: "none" }}>
      <svg width={size} height={size} viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r="19" fill="none" stroke="#FFFFFF" strokeWidth="4" />
        <circle cx="22" cy="22" r="19" fill="none" stroke="#2563EB" strokeWidth="4" strokeLinecap="round"
          strokeDasharray={`${((s * LEN) / 100).toFixed(2)} ${LEN}`} transform="rotate(-90 22 22)" />
      </svg>
      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#0B1220" }}>
        <span className="p2-sr">Оценка </span>{Math.round(s)}
      </span>
    </span>
  );
}
