import { useEffect, useState, type ReactNode } from "react";
import { MOTION, prefersReducedMotion, usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";

export interface CollapseProps {
  open: boolean;
  /** Mounted open: start collapsed and grow in (a notice, a field, a toast that appears on a live screen). */
  appear?: boolean;
  children: ReactNode;
  className?: string;
  /** Classes of a box around the children inside the clipped row (paddings that should fold away with the content go
   *  here: `pb-2`). */
  innerClassName?: string;
}

/** The one height primitive: content that appears or leaves pushes its neighbours smoothly instead of snapping
 *  (grid rows 0fr ↔ 1fr, 300 ms glide; the content fades in 200 ms after 60 ms and out in 150 ms). The children stay
 *  mounted while it collapses and unmount after. Settled open, the box stops clipping, so shadows and focus rings of the
 *  content show in full. */
export function Collapse({ open, appear = false, children, className, innerClassName }: CollapseProps) {
  const { mounted } = usePresence(open, MOTION.slow);
  const [expanded, setExpanded] = useState(open && !appear);
  const [settled, setSettled] = useState(open && !appear);

  useEffect(() => {
    if (!open) {
      setExpanded(false);
      setSettled(false);
      return;
    }
    if (prefersReducedMotion()) {
      setExpanded(true);
      setSettled(true);
      return;
    }
    // one painted frame at 0fr first, so the rows have something to transition from
    let r2 = 0;
    const r1 = requestAnimationFrame(() => {
      r2 = requestAnimationFrame(() => setExpanded(true));
    });
    return () => {
      cancelAnimationFrame(r1);
      cancelAnimationFrame(r2);
    };
  }, [open]);

  useEffect(() => {
    if (!expanded || settled) return;
    const t = window.setTimeout(() => setSettled(true), MOTION.slow);
    return () => window.clearTimeout(t);
  }, [expanded, settled]);

  if (!mounted) return null;
  return (
    <div className={cn("grid transition-[grid-template-rows] duration-300 ease-glide", expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]", className)} aria-hidden={!open || undefined}>
      <div
        className={cn(
          "min-h-0 transition-opacity",
          settled && expanded ? "overflow-visible" : "overflow-hidden",
          expanded ? "opacity-100 delay-[60ms] duration-200 ease-out" : "opacity-0 duration-150 ease-in",
        )}
      >
        {/* the paddings live inside the clipped row (a padding on the row itself is its minimum height at 0fr: the closed
            Collapse would keep that strip and snap it shut on unmount); always this box, so a class that comes and goes
            never remounts the children */}
        <div className={innerClassName}>{children}</div>
      </div>
    </div>
  );
}
