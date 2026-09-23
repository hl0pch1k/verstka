import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

export interface CollapsibleProps {
  title: ReactNode;
  /** Secondary text after the title (shown in both states). */
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
          className={cn("group flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left focus:outline-none", card ? "h-[60px]" : "h-10")}
        >
          <span className="truncate text-[15px] font-semibold text-zinc-900">{title}</span>
          {hint && <span className="min-w-0 flex-1 truncate text-[13px] font-normal text-zinc-500">{hint}</span>}
          <ChevronDown
            className={cn("ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-transform duration-200 group-hover:text-zinc-700 group-focus-visible:text-accent", open && "rotate-180")}
            aria-hidden
          />
        </button>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </div>
      <div className={cn("grid transition-[grid-template-rows] duration-200 ease-out", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div
          id={bodyId}
          className="min-h-0 overflow-hidden"
          // Hidden content must leave the tab order, but only after the collapse animation has played.
          style={{ visibility: open ? "visible" : "hidden", transition: `visibility 0s linear ${open ? "0s" : "200ms"}` }}
        >
          {(open || keepMounted) && <div className={cn(card ? "px-6 pb-5 pt-1" : "pb-3 pt-1", bodyClassName)}>{children}</div>}
        </div>
      </div>
    </section>
  );
}
