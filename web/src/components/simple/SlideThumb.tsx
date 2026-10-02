// A slide thumbnail's two parts, shared by the deck's rail and the build's rail: the picture that never paints blank
// (a new address replaces it only once decoded) and the count of the slide's remarks (or a spinner while the agent
// fixes the slide).
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { decodeImage, MOTION, usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import type { Severity } from "../../types";

const BADGE: Record<Severity, string> = {
  error: "bg-red-600 text-white",
  warn: "bg-amber-500 text-amber-950",
  info: "bg-zinc-500 text-white",
};

/** A thumb's picture. A new address (the deck reloaded after a fix or an undo, another variant) replaces the picture on
 *  screen only once it is decoded: the old one stays until then, so the thumb never paints blank. A thumb whose picture
 *  never loaded (lazy, off screen) takes the new address at once. */
export function ThumbImg({ url, onBroken }: { url: string; onBroken(url: string): void }) {
  const [shown, setShown] = useState(url);
  const loaded = useRef(false);
  useEffect(() => {
    if (url === shown) return;
    if (!loaded.current) return void setShown(url);
    let live = true;
    const swap = () => live && setShown(url);
    decodeImage(url).then(swap, swap);
    return () => {
      live = false;
    };
  }, [url, shown]);
  return (
    <img
      src={shown}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      onLoad={() => (loaded.current = true)}
      onError={() => onBroken(shown)}
      className="block h-full w-full object-cover"
    />
  );
}

/** The count of a thumb's remarks (the worst severity's colour); it pops in, re-pops when the count changes and pops
 *  out when the remarks are gone. The slide the agent is fixing shows a spinner instead. */
export function ThumbBadge({ count, sev, fixing, delay }: { count: number; sev: Severity | null; fixing: boolean; delay: number }) {
  const show = fixing || (count > 0 && !!sev);
  const { mounted, leaving } = usePresence(show, MOTION.fast);
  const last = useRef({ count, sev, fixing });
  if (show) last.current = { count, sev, fixing };
  if (!mounted) return null;
  const s = last.current;
  if (s.fixing)
    return (
      <span aria-hidden className={cn("absolute right-1 top-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-white shadow-raise", leaving ? "animate-pop-out" : "animate-pop")}>
        <Loader2 className="h-3 w-3 animate-spin text-accent" />
      </span>
    );
  return (
    <span
      key={s.count}
      aria-hidden
      className={cn(
        "absolute right-1 top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-caption font-semibold leading-4 tabular-nums ring-2 ring-white",
        BADGE[s.sev ?? "info"],
        leaving ? "animate-pop-out" : "animate-pop",
      )}
      style={leaving ? undefined : { animationDelay: `${delay}ms` }}
    >
      {s.count}
    </span>
  );
}
