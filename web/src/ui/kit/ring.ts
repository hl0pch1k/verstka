/** Длина окружности кольца оценки: r = 19, 2π·19 ≈ 119.38 (R-aside, V2 `ringDash`). */
export const RING_LEN = 119.38;

/** `stroke-dasharray` дуги: доля оценки от окружности, оценка зажата в 0…100 («106.25 119.38» для 89). Оценка 0 (и не
 *  число) — дуги нет, null: штрих нулевой длины с круглым концом браузер рисует точкой на дорожке. */
export function ringDash(score: number): string | null {
  const s = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  return s > 0 ? `${((s * RING_LEN) / 100).toFixed(2)} ${RING_LEN}` : null;
}
