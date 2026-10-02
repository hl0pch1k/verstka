// The variants of a build under the stage, one chip each: the name, where it is («продумываю слайды» → «вёрстка 4 из
// 12» → «готово») and a thin bar. The chip on show is ringed: its rail is the one on the left (the critic, the revision
// and the layout are each variant's own). One radio group: one Tab stop, the arrows move and choose.
import { useRef, type KeyboardEvent } from "react";
import { Check } from "lucide-react";
import { cn } from "../../lib/utils";
import { variantHint } from "../../lib/plain";
import { Progress } from "../ui/Progress";

export interface ChipState { text: string; done: boolean; frac: number; indeterminate?: boolean }

export function VariantChips({ names, states, value, onChange, titleOf, className }: {
  names: string[];
  states: Record<string, ChipState>;
  value: string;
  onChange(name: string): void;
  titleOf(name: string): string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = names.length;
    const i = Math.max(0, names.indexOf(value));
    const next = { ArrowRight: (i + 1) % n, ArrowDown: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    onChange(names[next]);
    ref.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
  };
  return (
    <div ref={ref} role="radiogroup" aria-label="Вариант, чьи слайды показаны" onKeyDown={onKey} className={cn("grid shrink-0 gap-3", className)} style={{ gridTemplateColumns: `repeat(${names.length}, minmax(0, 1fr))` }}>
      {names.map((name, i) => {
        const st = states[name] ?? { text: "в очереди", done: false, frac: 0, indeterminate: true };
        const on = name === value;
        return (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(name)}
            title={variantHint(name)}
            className={cn("tap-soft relative flex h-[60px] min-w-0 cursor-pointer flex-col rounded-2xl bg-white px-4 pt-2.5 text-left", on ? "shadow-selected" : "shadow-card hover:shadow-raise")}
          >
            <span className="flex w-full items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-footnote font-semibold text-zinc-900">{titleOf(name)}</span>
              {st.done && (
                <span className="flex h-4 w-4 shrink-0 animate-pop items-center justify-center rounded-full bg-accent-fill text-white" aria-hidden>
                  <Check className="h-2.5 w-2.5" strokeWidth={3} />
                </span>
              )}
            </span>
            {/* «продумываю слайды» → «вёрстка 4 из 12» → «готово»: each status cross-fades in */}
            <span key={st.text} className="block w-full animate-fade truncate text-caption text-zinc-500">{st.text}</span>
            {/* staggered, so the sweeps never move in lockstep */}
            <Progress size="xs" value={st.frac} indeterminate={st.indeterminate} delayMs={i * 200} className="absolute inset-x-4 bottom-2" />
          </button>
        );
      })}
    </div>
  );
}
