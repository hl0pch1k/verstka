// The slide on the whole screen — the way it will look on a projector. ← and → turn the slides, Esc closes.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, ImageOff, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";

interface Props {
  open: boolean;
  src: string | null;
  slide: number; // 1-based
  total: number;
  headline: string;
  aspect: number;
  onSelect(n: number): void;
  onClose(): void;
}

function NavButton({ icon: Icon, label, disabled, onClick }: { icon: LucideIcon; label: string; disabled: boolean; onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="flex h-12 w-12 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/10 text-white/80 transition-[background-color,color,opacity,transform] duration-150 hover:bg-white/20 hover:text-white active:scale-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60 disabled:pointer-events-none disabled:opacity-0"
    >
      <Icon className="h-6 w-6" aria-hidden />
    </button>
  );
}

export function SlideLightbox({ open, src, slide, total, headline, aspect, onSelect, onClose }: Props) {
  const { mounted, leaving } = usePresence(open, 160);
  const rootRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const live = useRef({ slide, total, onSelect, onClose });
  live.current = { slide, total, onSelect, onClose };
  // the previous slide stays under the next one until it has loaded: turning never flashes black
  const [shown, setShown] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus({ preventScroll: true });
    // capture phase: the deck's own ←/→ handler must not turn the slide a second time
    const onKey = (e: KeyboardEvent) => {
      const s = live.current;
      if (e.key === "Tab") {
        const nodes = [...(rootRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? [])];
        if (nodes.length === 0) return;
        const at = nodes.indexOf(document.activeElement as HTMLElement);
        nodes[e.shiftKey ? (at <= 0 ? nodes.length - 1 : at - 1) : at === nodes.length - 1 ? 0 : at + 1].focus();
      } else if (e.key === "Escape") s.onClose();
      else if (e.key === "ArrowRight" || e.key === "PageDown") s.slide < s.total && s.onSelect(s.slide + 1);
      else if (e.key === "ArrowLeft" || e.key === "PageUp") s.slide > 1 && s.onSelect(s.slide - 1);
      else if (e.key === "Home") s.onSelect(1);
      else if (e.key === "End") s.onSelect(s.total);
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = overflow;
      previous?.focus?.({ preventScroll: true });
    };
  }, [open]);

  if (!mounted) return null;
  const broken = !src || failed === src;
  const loading = !broken && shown !== src;

  return createPortal(
    <div
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Слайд ${slide} из ${total}`}
      className={cn("fixed inset-0 z-[95] flex flex-col bg-[#0F1012] text-white", leaving ? "pointer-events-none animate-fade-out" : "animate-fade")}
    >
      <div className="flex h-16 shrink-0 items-center gap-4 pl-8 pr-5">
        <p className="min-w-0 flex-1 truncate text-[15px]">
          <span className="font-semibold tabular-nums text-white">{slide}</span>
          <span className="tabular-nums text-white/40"> / {total}</span>
          {headline && <span className="ml-4 text-white/70">{headline}</span>}
        </p>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Закрыть"
          title="Закрыть (Esc)"
          className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>
      {/* a click on the dark field around the slide closes, like in every photo viewer */}
      <div className="flex min-h-0 flex-1 items-center justify-center gap-6 px-6 pb-14" onClick={(e) => e.target === e.currentTarget && onClose()}>
        <NavButton icon={ChevronLeft} label="Предыдущий слайд (←)" disabled={slide <= 1} onClick={() => onSelect(slide - 1)} />
        <div
          className={cn("relative overflow-hidden rounded-lg bg-white/5 shadow-[0_30px_90px_rgba(0,0,0,0.55)]", !leaving && "animate-zoom-in")}
          style={{ aspectRatio: String(aspect), width: `min(calc(100vw - 192px), calc((100vh - 136px) * ${aspect.toFixed(4)}))` }}
        >
          {loading && shown && <img src={shown} alt="" aria-hidden draggable={false} className="absolute inset-0 h-full w-full object-contain" />}
          {!broken && (
            <img
              key={src}
              src={src ?? undefined}
              alt={`Слайд ${slide}${headline ? `: ${headline}` : ""}`}
              draggable={false}
              decoding="async"
              onLoad={() => setShown(src)}
              onError={() => setFailed(src)}
              className={cn("absolute inset-0 h-full w-full object-contain transition-opacity duration-200 ease-out", loading ? "opacity-0" : "opacity-100")}
            />
          )}
          {broken && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/50">
              <ImageOff className="h-7 w-7" aria-hidden />
              <span className="text-sm">Превью слайда не сохранилось</span>
            </div>
          )}
        </div>
        <NavButton icon={ChevronRight} label="Следующий слайд (→)" disabled={slide >= total} onClick={() => onSelect(slide + 1)} />
      </div>
    </div>,
    document.body,
  );
}
