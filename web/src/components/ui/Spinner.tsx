import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

export interface SpinnerProps {
  /** Pixel size of the icon (default 16). */
  size?: number;
  className?: string;
  /** Accessible label; also rendered next to the spinner when `showLabel` is set. */
  label?: string;
  showLabel?: boolean;
}

export function Spinner({ size = 16, className, label = "Загрузка", showLabel = false }: SpinnerProps) {
  return (
    <span role="status" aria-label={label} className={cn("inline-flex items-center gap-2 text-zinc-500", className)}>
      <Loader2 className="animate-spin" style={{ width: size, height: size }} strokeWidth={2.25} aria-hidden />
      {showLabel && <span className="text-[13px]">{label}…</span>}
    </span>
  );
}
