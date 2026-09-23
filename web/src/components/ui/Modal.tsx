import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";

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

export function Modal({ open, onClose, title, description, footer, size = "md", dismissible = true, flush = false, className, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const { mounted, leaving } = usePresence(open, 150);
  // while the exit animation plays the caller may already have dropped the content: show the last one
  const last = useRef({ title, description, footer, children });
  if (open) last.current = { title, description, footer, children };
  const view = open ? { title, description, footer, children } : last.current;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();
    // capture phase: Esc closes only the modal, not the drawer it was opened from
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dismissible) {
        e.stopPropagation();
        closeRef.current();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open, dismissible]);

  if (!mounted) return null;

  return createPortal(
    <div className={cn("fixed inset-0 z-[90] flex items-center justify-center p-8", leaving && "pointer-events-none")}>
      <div className={cn("absolute inset-0 bg-ink/50 backdrop-blur-[3px]", leaving ? "animate-fade-out" : "animate-fade")} onClick={dismissible ? onClose : undefined} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn("relative flex max-h-full w-full flex-col overflow-hidden rounded-3xl bg-white shadow-pop outline-none", leaving ? "animate-zoom-out" : "animate-zoom-in", WIDTH[size], className)}
      >
        {(view.title || dismissible) && (
          <header className="flex shrink-0 items-start gap-4 px-7 pb-3 pt-6">
            <div className="min-w-0 flex-1">
              {view.title && <h2 className="text-xl font-semibold leading-7 text-zinc-900">{view.title}</h2>}
              {view.description && <p className="mt-1 text-sm leading-5 text-zinc-500">{view.description}</p>}
            </div>
            {dismissible && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть"
                className="-mr-2 flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full bg-zinc-100 text-zinc-500 transition-colors hover:bg-zinc-200 hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </header>
        )}
        <div className={cn("scroll-thin min-h-0 flex-1 overflow-y-auto", !flush && "px-7 pb-6 pt-2")}>{view.children}</div>
        {view.footer && <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-zinc-100 px-7 py-4">{view.footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
