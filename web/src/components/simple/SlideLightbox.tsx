// The slide on the whole screen — the way it will look on a projector. It grows out of the slide on the stage and
// shrinks back into it; ← and → turn the slides (a short push toward the travel, never a black frame), Esc closes.
// Only «3 / 6» on top: the slide speaks for itself; its headline is the dialog's name for screen readers. With the
// «Замечания» switch on, the remarks' frames and numbers are drawn read-only (their titles in native tooltips).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, ImageOff, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { EASE, flipFromRect, usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import { RemarksLayer, SlideImage } from "../VariantsSlidePreview";
import type { StageRemark } from "../VariantsHelpers";

interface Props {
  open: boolean;
  src: string | null;
  slide: number; // 1-based
  total: number;
  headline: string;
  aspect: number;
  remarks?: StageRemark[];
  showRemarks?: boolean;
  onSelect(n: number): void;
  onClose(): void;
}

const CLOSE_MS = 220;
const stageRect = () => document.querySelector<HTMLElement>("[data-stage-frame]")?.getBoundingClientRect() ?? null;

/** An arrow at the screen's edge (x = 24 / W − 24, the same edges as «3 / 6» and ×), out of the slide's flow, so it
 *  never moves between window sizes. The name is clean for screen readers; the key is in the tooltip. */
function NavButton({ icon: Icon, label, keyHint, side, disabled, className, onClick }: { icon: LucideIcon; label: string; keyHint: string; side: "left" | "right"; disabled: boolean; className?: string; onClick(): void }) {
  return (
    <div className={cn("pointer-events-none absolute inset-y-0 flex items-center pb-16", side === "left" ? "left-6" : "right-6", className)}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        title={`${label} (${keyHint})`}
        className="tap pointer-events-auto flex h-12 w-12 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/10 text-white/80 hover:bg-white/20 hover:text-white focus-visible:outline-white disabled:pointer-events-none disabled:opacity-0"
      >
        <Icon className="h-5 w-5" aria-hidden />
      </button>
    </div>
  );
}

export function SlideLightbox({ open, src, slide, total, headline, aspect, remarks = [], showRemarks = false, onSelect, onClose }: Props) {
  const { mounted, leaving } = usePresence(open, CLOSE_MS);
  const rootRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const live = useRef({ slide, total, onSelect, onClose });
  live.current = { slide, total, onSelect, onClose };
  const [failed, setFailed] = useState<string | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  // the direction of travel between two slides: the next one pushes in from that side
  const prev = useRef(slide);
  const dir = (Math.sign(slide - prev.current) as -1 | 0 | 1) || 0;
  useEffect(() => {
    prev.current = slide;
  }, [slide]);

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

  // it grows out of the stage slide on open and shrinks back into it on close (transform only)
  const zoomed = useRef<"none" | "in" | "out">("none");
  useLayoutEffect(() => {
    const el = frameRef.current;
    if (!mounted || !el) {
      zoomed.current = "none";
      return;
    }
    if (open && zoomed.current !== "in") {
      zoomed.current = "in";
      const r = stageRect();
      if (r) flipFromRect(el, r, { duration: 300, easing: EASE.glide });
    } else if (leaving && zoomed.current !== "out") {
      zoomed.current = "out";
      const r = stageRect();
      if (r) flipFromRect(el, r, { duration: CLOSE_MS, easing: EASE.in, reverse: true });
    }
  }, [mounted, open, leaving]);

  // the frame's size: the remarks' pins are placed in it
  useLayoutEffect(() => {
    const el = frameRef.current;
    if (!mounted || !el) return;
    const run = () => setSize((s) => (s.w === el.offsetWidth && s.h === el.offsetHeight ? s : { w: el.offsetWidth, h: el.offsetHeight }));
    run();
    const ro = new ResizeObserver(run);
    ro.observe(el);
    return () => ro.disconnect();
  }, [mounted]);

  const [shownSrc, setShownSrc] = useState<string | null>(null);
  if (!mounted) return null;
  const broken = !src || failed === src;
  const withStage = !!stageRect();
  // «3 / 6», × and the arrows land just after the slide and leave first
  const chrome = leaving ? "animate-fade-out [animation-duration:100ms]" : "animate-fade [animation-delay:120ms]";

  return createPortal(
    <div
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Слайд ${slide} из ${total}${headline ? `: ${headline}` : ""}`}
      className={cn("fixed inset-0 z-[95] flex flex-col text-white", leaving && "pointer-events-none")}
    >
      <div aria-hidden className={cn("absolute inset-0 bg-[#0F1012]", leaving ? "animate-fade-out rm-fade-out [animation-duration:200ms]" : "animate-fade rm-fade")} />
      <div className={cn("relative flex h-16 shrink-0 items-center justify-between px-6", chrome)}>
        <p className="text-footnote tabular-nums" aria-live="polite">
          <span key={slide} className="inline-block animate-fade-in font-semibold text-white">{slide}</span>
          <span className="text-white/60"> / {total}</span>
        </p>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Закрыть"
          title="Закрыть (Esc)"
          className="tap flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/10 text-white/80 hover:bg-white/20 hover:text-white focus-visible:outline-white"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>
      {/* a click on the dark field around the slide closes, like in every photo viewer */}
      {/* px-24 = 24 + the 48px arrow + 24: the slide never runs under an arrow (the width below keeps the same 192px) */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-24 pb-16" onClick={(e) => e.target === e.currentTarget && onClose()}>
        <NavButton icon={ChevronLeft} label="Предыдущий слайд" keyHint="←" side="left" className={chrome} disabled={slide <= 1} onClick={() => onSelect(slide - 1)} />
        <div
          ref={frameRef}
          data-lb-frame
          className={cn(
            "relative overflow-hidden rounded-lg bg-white/5 shadow-[0_30px_90px_rgba(0,0,0,0.55)]",
            !withStage && (leaving ? "animate-zoom-out" : "animate-zoom-in"),
          )}
          style={{ aspectRatio: String(aspect), width: `min(calc(100vw - 192px), calc((100vh - 128px) * ${aspect.toFixed(4)}))` }}
        >
          {!broken && (
            <SlideImage
              src={src}
              alt={`Слайд ${slide}${headline ? `: ${headline}` : ""}`}
              dir={dir}
              dark
              onError={setFailed}
              onShown={setShownSrc}
            />
          )}
          {broken && (
            <div className="absolute inset-0 flex animate-fade flex-col items-center justify-center gap-2 text-white/60">
              <ImageOff className="h-6 w-6" aria-hidden />
              <span className="text-footnote">Превью не сохранилось</span>
            </div>
          )}
          {showRemarks && !broken && shownSrc === src && remarks.length > 0 && !leaving && (
            <RemarksLayer key={src ?? ""} remarks={remarks} size={size} readOnly spotlight={false} />
          )}
        </div>
        <NavButton icon={ChevronRight} label="Следующий слайд" keyHint="→" side="right" className={chrome} disabled={slide >= total} onClick={() => onSelect(slide + 1)} />
      </div>
    </div>,
    document.body,
  );
}
