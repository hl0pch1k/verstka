import { useEffect, useRef, type ReactNode } from "react";
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

export function Modal({ open, onClose, title, description, footer, size = "md", dismissible = true, flush = false, className, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const { mounted, leaving } = usePresence(open, MOTION.fast);
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
      <div className={cn("absolute inset-0 bg-ink/50 backdrop-blur-[3px]", leaving ? "animate-fade-out rm-fade-out" : "animate-fade rm-fade")} onClick={dismissible ? onClose : undefined} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn("relative flex max-h-full w-full origin-center flex-col overflow-hidden rounded-3xl bg-white shadow-pop outline-none", leaving ? "animate-zoom-out rm-fade-out" : "animate-zoom-in rm-fade", WIDTH[size], className)}
      >
        {(view.title || dismissible) && (
          <header className="flex shrink-0 items-start gap-4 px-6 pb-2 pt-6">
            <div className="min-w-0 flex-1 self-center">
              {view.title && <h2 className="text-title2 font-semibold text-zinc-900">{view.title}</h2>}
              {view.description && <p className="mt-0.5 text-footnote text-zinc-500">{view.description}</p>}
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
