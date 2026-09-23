import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

/** Top of every step: an eyebrow (step number), a large title, one line of context and the step's actions. */
export function PageHeader({ eyebrow, title, subtitle, actions, className }: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-end justify-between gap-6", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="mb-1.5 text-[13px] font-semibold text-accent">{eyebrow}</p>}
        <h1 className="line-clamp-2 text-[28px] font-bold leading-9 tracking-tight text-zinc-900">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-[15px] leading-6 text-zinc-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
