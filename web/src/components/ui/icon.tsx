import { isValidElement, type ReactElement } from "react";
import type { LucideIcon } from "lucide-react";

/** An icon prop accepts either a lucide component (`icon={Upload}`) or a ready element (`icon={<Upload />}`). */
export type IconProp = LucideIcon | ReactElement;

export function renderIcon(icon: IconProp | null | undefined, className?: string, strokeWidth = 2) {
  if (!icon) return null;
  if (isValidElement(icon)) return icon;
  const Cmp = icon as LucideIcon;
  return <Cmp className={className} strokeWidth={strokeWidth} aria-hidden />;
}
