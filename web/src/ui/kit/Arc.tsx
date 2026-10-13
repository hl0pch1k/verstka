/** Дуга загрузки досок R-fixing и R-picture (бледное кольцо и синяя четверть, линия 2.5 — как на доске), крутится по
 *  кругу (`gh-spin`): ход исправления, «Вернуть как было», замена изображения, миниатюра исправляемого слайда. */
export function Arc({ size = 16 }: { size?: number }) {
  return (
    <svg className="gh-spin" width={size} height={size} viewBox="0 0 24 24" fill="none" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true" style={{ flex: "none" }}>
      <circle cx="12" cy="12" r="8" stroke="rgba(37,99,235,.14)" />
      <path d="M12 4a8 8 0 0 1 8 8" stroke="#2563EB" />
    </svg>
  );
}
