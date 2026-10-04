import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { MOTION, usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import { Button } from "./Button";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  /** Bottom bar, usually buttons aligned to the right. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** Close on backdrop click / Escape (default true). Disable while a request is in flight. */
  dismissible?: boolean;
  /** Remove body paddings (full-bleed previews, tables). */
  flush?: boolean;
  className?: string;
  children: ReactNode;
}

const WIDTH = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-6xl" } as const;

/** The dialogs open now, oldest first: Esc and Tab belong to the top one (a confirmation over a template's window
 *  closes alone), and the page scrolls again only when the last one has closed. */
const stack: object[] = [];
let pageOverflow = "";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Tab and Shift+Tab go round the dialog's own controls, never into the page behind it. */
function keepFocusIn(e: KeyboardEvent, panel: HTMLElement | null) {
  if (!panel) return;
  const items = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
  const active = document.activeElement;
  if (items.length === 0) {
    e.preventDefault();
    panel.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  if (!panel.contains(active)) {
    e.preventDefault();
    (e.shiftKey ? last : first).focus();
  } else if (e.shiftKey && (active === first || active === panel)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}

export function Modal({ open, onClose, title, description, footer, size = "md", dismissible = true, flush = false, className, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // read when Esc comes: a request in flight («Удаляю…») toggles it without re-running the dialog's effect (which would
  // send the focus behind the dialog and back)
  const dismissRef = useRef(dismissible);
  dismissRef.current = dismissible;
  const id = useId();
  const { mounted, leaving } = usePresence(open, MOTION.fast);
  // while the exit animation plays the caller may already have dropped the content: show the last one
  const last = useRef({ title, description, footer, children });
  if (open) last.current = { title, description, footer, children };
  const view = open ? { title, description, footer, children } : last.current;

  useEffect(() => {
    if (!open) return;
    const me = {};
    if (stack.length === 0) pageOverflow = document.body.style.overflow;
    stack.push(me);
    document.body.style.overflow = "hidden";
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    // capture phase: Esc closes only the top dialog, not the drawer it was opened from; a field that takes Esc back
    // itself (an inline rename: [data-own-escape]) keeps the window open
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== me) return;
      if (e.key === "Tab") return keepFocusIn(e, panelRef.current);
      if (e.key !== "Escape" || !dismissRef.current || (e.target instanceof Element && e.target.closest("[data-own-escape]"))) return;
      e.stopPropagation();
      closeRef.current();
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      stack.splice(stack.indexOf(me), 1);
      if (stack.length === 0) document.body.style.overflow = pageOverflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!mounted) return null;

  return createPortal(
    <div className={cn("fixed inset-0 z-[90] flex items-center justify-center p-8", leaving && "pointer-events-none")}>
      {/* VK's overlay: plain black at 40 %, no blur */}
      <div className={cn("absolute inset-0 bg-black/40", leaving ? "animate-fade-out rm-fade-out" : "animate-fade rm-fade")} onClick={dismissible ? onClose : undefined} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={view.title ? `${id}-title` : undefined}
        aria-describedby={view.description ? `${id}-desc` : undefined}
        tabIndex={-1}
        className={cn("relative flex max-h-full w-full origin-center flex-col overflow-hidden rounded-3xl bg-white shadow-pop outline-none", leaving ? "animate-zoom-out rm-fade-out" : "animate-zoom-in rm-fade", WIDTH[size], className)}
      >
        {(view.title || dismissible) && (
          <header className="flex shrink-0 items-start gap-4 px-6 pb-2 pt-6">
            <div className="min-w-0 flex-1 self-center">
              {view.title && <h2 id={`${id}-title`} className="text-title2 font-semibold text-zinc-900">{view.title}</h2>}
              {view.description && <p id={`${id}-desc`} className="mt-0.5 text-footnote text-zinc-500">{view.description}</p>}
            </div>
            {/* one close look on every white surface (drawer, helper, modal): a ghost circle */}
            {dismissible && <Button variant="ghost" shape="circle" size="md" icon={X} aria-label="Закрыть" onClick={onClose} />}
          </header>
        )}
        <div className={cn("scroll-thin min-h-0 flex-1 overflow-y-auto", !flush && "px-6 pb-6 pt-2")}>{view.children}</div>
        {view.footer && <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-zinc-100 px-6 py-4">{view.footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
