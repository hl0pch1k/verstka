import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
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

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dismissible) {
        e.stopPropagation();
        closeRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open, dismissible]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-8">
      <div className="absolute inset-0 bg-zinc-900/40 backdrop-blur-[2px] animate-fade-in" onClick={dismissible ? onClose : undefined} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn("relative flex max-h-full w-full flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-pop outline-none animate-fade-in", WIDTH[size], className)}
      >
        {(title || dismissible) && (
          <header className="flex shrink-0 items-start gap-4 border-b border-zinc-100 px-6 py-4">
            <div className="min-w-0 flex-1">
              {title && <h2 className="text-base font-semibold leading-6 text-zinc-900">{title}</h2>}
              {description && <p className="mt-0.5 text-[13px] leading-5 text-zinc-500">{description}</p>}
            </div>
            {dismissible && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть"
                className="-mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </header>
        )}
        <div className={cn("scroll-thin min-h-0 flex-1 overflow-y-auto", !flush && "px-6 py-5")}>{children}</div>
        {footer && <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-zinc-100 bg-zinc-50/60 px-6 py-3.5">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
