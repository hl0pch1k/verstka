// Мелочи модуля ds (boards/V2.dc.html версии 105, `dsData().I`): иконки файлов данных и брендбука (сетка 24, круглые
// концы, толщина по размеру — как kit/Icon) и двухцветная дуга хода `ds-spin` (кольцо 14 % и синяя четверть).
import { strokeFor } from "../kit/Icon";
import type { SourceKind } from "../../types";

export const DS_ICON = {
  tbl: "M6.5 4.5h11a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2z M4.5 9.5h15 M4.5 14.5h15 M10 9.5v10",
  json: "M9 4.5H8a2 2 0 0 0-2 2v3a2.5 2.5 0 0 1-2 2.5 2.5 2.5 0 0 1 2 2.5v3a2 2 0 0 0 2 2h1 M15 4.5h1a2 2 0 0 1 2 2v3a2.5 2.5 0 0 0 2 2.5 2.5 2.5 0 0 0-2 2.5v3a2 2 0 0 1-2 2h-1",
  txt: "M13.5 3.5h-6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8.5z M13.5 3.5v3a2 2 0 0 0 2 2h3 M9 13h6 M9 16.5h4",
  file: "M13.5 3.5h-6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8.5z M13.5 3.5v3a2 2 0 0 0 2 2h3",
  chart: "M4.5 4.5v13a2 2 0 0 0 2 2h13 M8 15l3.5-3.5 3 3 5-5.5",
  folder: "M4 17.5v-11a2 2 0 0 1 2-2h3.6l2 2.5H18a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z",
  frame: "M8 3.5v17 M16 3.5v17 M3.5 8h17 M3.5 16h17",
  book: "M5.5 19V6a2.5 2.5 0 0 1 2.5-2.5h10.5v13H8A2.5 2.5 0 0 0 5.5 19z M5.5 19A1.5 1.5 0 0 0 7 20.5h11.5v-4",
  upload: "M12 14.5V4 M7.5 8.5L12 4l4.5 4.5 M4.5 15.5v2A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5v-2",
  target: "M12 3.5a8.5 8.5 0 1 1 0 17a8.5 8.5 0 0 1 0-17z M12 8a4 4 0 1 1 0 8a4 4 0 0 1 0-8z M12 12h.01",
  warn: "M10.27 4.75a2 2 0 0 1 3.46 0l7.02 12.25A2 2 0 0 1 19.02 20H4.98a2 2 0 0 1-1.73-3z M12 9.5v4 M12 16.8h.01",
  info: "M12 3.5a8.5 8.5 0 1 1 0 17a8.5 8.5 0 0 1 0-17z M12 11v5 M12 7.8h.01",
  x: "M6.5 6.5l11 11 M17.5 6.5l-11 11",
} as const;
export type DsIconName = keyof typeof DS_ICON;

export function DsIcon({ name, size = 16, color, style }: { name: DsIconName; size?: number; color?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color ?? "currentColor"} strokeWidth={strokeFor(size)}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>
      <path d={DS_ICON[name]} />
    </svg>
  );
}

/** Значок файла данных по формату: таблица, JSON, текст. */
export const fileIcon = (kind: SourceKind | null): DsIconName => (kind === "json" ? "json" : kind === "text" ? "txt" : "tbl");

/** Дуга хода модуля ds: 16 px (2.25) в строках, 12 px (2.5) в карточке. */
export function DsSpin({ size = 16 }: { size?: number }) {
  return (
    <svg className="ds-spin" width={size} height={size} viewBox="0 0 24 24" fill="none" strokeWidth={strokeFor(size)} strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="8" stroke="rgba(37,99,235,.14)" />
      <path d="M12 4a8 8 0 0 1 8 8" stroke="#2563EB" />
    </svg>
  );
}
