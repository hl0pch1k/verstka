import { useId, useState, type ReactNode } from "react";
import { MOTION, usePresence } from "../../lib/motion";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

export interface CollapsibleProps {
  title: ReactNode;
  /** A count or a short label after the title (shown in both states) — never a sentence. */
  hint?: ReactNode;
  /** Extra header content on the right (badges, buttons); clicks inside do not toggle the section. */
  right?: ReactNode;
  /** Controlled state. Omit to let the component manage itself (see `defaultOpen`). */
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** "card" — white bordered card; "plain" — borderless row for nesting inside cards. */
  variant?: "card" | "plain";
  /** Keep children mounted while collapsed (default) so that form state survives. */
  keepMounted?: boolean;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

export function Collapsible({
  title, hint, right, open: controlled, defaultOpen = false, onOpenChange, variant = "card", keepMounted = true, className, bodyClassName, children,
}: CollapsibleProps) {
  const [inner, setInner] = useState(defaultOpen);
  const open = controlled ?? inner;
  const bodyId = useId();
  const card = variant === "card";
  // without keepMounted the content still stays for the collapse (300 ms), so it folds away instead of vanishing first
  const presence = usePresence(open, MOTION.slow);

  const toggle = () => {
    if (controlled === undefined) setInner(!open);
    onOpenChange?.(!open);
  };

  return (
    <section className={cn(card && "rounded-2xl bg-white shadow-card", className)}>
      <div className={cn("flex items-center gap-3", card ? "px-6" : "px-0")}>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={bodyId}
          className={cn(
            "group flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left",
            // card: the toggle spans the card's header edge to edge, so the inset focus ring traces the card itself
            card
              ? cn("h-16 -ml-6 pl-6 focus-visible:outline-offset-[-2px]", right ? "pr-0" : "-mr-6 pr-6", open ? "rounded-t-2xl" : "rounded-2xl")
              : "h-10 -mx-2 rounded-xl px-2",
          )}
        >
          <span className={cn("truncate font-semibold text-zinc-900", card ? "text-title3" : "text-body")}>{title}</span>
          {hint && <span className="min-w-0 flex-1 truncate text-footnote font-normal text-zinc-500">{hint}</span>}
          <ChevronDown
            className={cn("ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-[transform,color] duration-300 ease-glide group-hover:text-zinc-700", open && "rotate-180")}
            aria-hidden
          />
        </button>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </div>
      <div className={cn("grid transition-[grid-template-rows] duration-300 ease-glide", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div
          id={bodyId}
          className={cn("min-h-0 overflow-hidden", open ? "opacity-100" : "opacity-0")}
          // Hidden content must leave the tab order, but only after the collapse has played. The content fades in
          // 200 ms after 60 ms (the rows open first) and out in 150 ms.
          style={{
            visibility: open ? "visible" : "hidden",
            transition: open
              ? "visibility 0s linear 0s, opacity 200ms var(--ease-out) 60ms"
              : `visibility 0s linear ${MOTION.slow}ms, opacity 150ms var(--ease-in) 0s`,
          }}
        >
          {(keepMounted || presence.mounted) && <div className={cn(card ? "px-6 pb-6 pt-0" : "pb-3 pt-1", bodyClassName)}>{children}</div>}
        </div>
      </div>
    </section>
  );
}
