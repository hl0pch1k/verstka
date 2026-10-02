// The examples that type themselves into an empty composer, the way a person would: a line types in (about 35 ms a
// character, a little uneven), holds for 2.2 s, erases faster and the next one starts. Only while `active` (an empty
// field without the focus: a person who is thinking is not distracted); with reduced motion the first example stands
// still, without a caret. aria-hidden: the field's own placeholder speaks to screen readers.
import { useEffect, useState } from "react";
import { useReducedMotion } from "../../lib/motion";
import { cn } from "../../lib/utils";

const TYPE_MS = 32;
const HOLD_MS = 2200;
const ERASE_MS = 16;
const GAP_MS = 420;

/** `lines` must keep its identity between renders (a module constant): a new array restarts the typing. */
export function TypewriterHint({ lines, active, className }: { lines: string[]; active: boolean; className?: string }) {
  const reduced = useReducedMotion();
  const [st, setSt] = useState({ i: 0, len: 0, erasing: false });
  useEffect(() => {
    if (!active || reduced || lines.length === 0) return;
    const line = lines[st.i % lines.length];
    let ms: number;
    let next: typeof st;
    if (!st.erasing && st.len < line.length) {
      // a steady hand is a machine's: every character a few ms off the beat, a pause after a word or a comma
      const ch = line[st.len];
      ms = TYPE_MS + ((st.len * 37) % 23) + (ch === " " || ch === "," ? 40 : 0);
      next = { ...st, len: st.len + 1 };
    } else if (!st.erasing) {
      ms = HOLD_MS;
      next = { ...st, erasing: true };
    } else if (st.len > 0) {
      ms = ERASE_MS;
      next = { ...st, len: st.len - 1 };
    } else {
      ms = GAP_MS;
      next = { i: (st.i + 1) % lines.length, len: 0, erasing: false };
    }
    const t = window.setTimeout(() => setSt(next), ms);
    return () => window.clearTimeout(t);
  }, [st, active, reduced, lines]);
  if (!active || lines.length === 0) return null;
  const text = reduced ? lines[0] : lines[st.i % lines.length].slice(0, st.len);
  return (
    <span aria-hidden className={cn("pointer-events-none select-none", className)}>
      {text}
      {!reduced && <span className="ml-0.5 inline-block h-[1.15em] w-[2px] translate-y-[0.22em] animate-caret rounded-full bg-accent" />}
    </span>
  );
}
