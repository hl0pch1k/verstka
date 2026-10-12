// Линейная иконка «Слоёв»: сетка 24, круглые концы, без подложки. Толщина по размеру — правило эталона:
// 2.5 при 12 px и меньше, 2.25 при 14–16 px, 2 от 18 px.
import { ICONS, type IconName } from "./icons";

export type { IconName } from "./icons";
export const strokeFor = (size: number) => (size <= 12 ? 2.5 : size <= 16 ? 2.25 : 2);

export function Icon({ name, size = 18, className, label }: { name: IconName; size?: number; className?: string; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeFor(size)}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined} aria-label={label}>
      <path d={ICONS[name]} />
    </svg>
  );
}
