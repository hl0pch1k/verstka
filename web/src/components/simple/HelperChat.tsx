// The helper as a docked right sidebar under the header: the page reflows beside it, so nothing is ever covered.
// It stays mounted while closed (a half-written message survives), Esc closes it when it is the topmost layer and a
// build start closes it (flows.ts / ChatActions). Over the details drawer it rises above the dim and up to the top
// edge of the window, side by side with the sheet.
// Motion: it docks in one reflow and slides in from the right (300 ms glide), its content landing 60 ms later; on close it
// leaves the flow at once (absolute over the page's right edge) and slides out in 200 ms, so the page reflows once, at
// the start, and the screens glide their main block (FLIP) instead of jumping twice.
import { useEffect, useRef } from "react";
import { usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import { Chat } from "../Chat";

export function HelperChat() {
  const { agentOpen, setAgentOpen, detail } = useApp();
  const { mounted, leaving } = usePresence(agentOpen, 200);
  const ref = useRef<HTMLElement>(null);

  // Esc closes the helper only when no modal layer (drawer, lightbox, modal) is open — those handle Esc themselves
  useEffect(() => {
    if (!agentOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      if ((e.target as HTMLElement | null)?.closest?.('[role="menu"],[role="listbox"]')) return;
      setAgentOpen(false);
      document.getElementById("helper-toggle")?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [agentOpen, setAgentOpen]);

  // on open the composer takes the focus
  useEffect(() => {
    if (!agentOpen) return;
    const raf = window.requestAnimationFrame(() => ref.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(raf);
  }, [agentOpen]);

  return (
    <aside
      ref={ref}
      id="helper"
      aria-label="Помощник"
      className={cn(
        "vt-helper z-20 w-[360px] shrink-0 flex-col border-l border-zinc-200/70 bg-white",
        mounted ? "flex" : "hidden",
        !mounted || !leaving ? "relative" : "absolute inset-y-0 right-0",
        mounted && (leaving ? "pointer-events-none animate-sheet-out rm-fade-out" : "animate-sheet-in rm-fade"),
        // beside the drawer: above its dim and pulled up over the header, so both 56px headers share y = 0
        detail && mounted && "z-[60] -mt-16",
      )}
    >
      <div className={cn("flex min-h-0 flex-1 flex-col", mounted && !leaving && "animate-fade [animation-delay:60ms]")}>
        <Chat
          onClose={() => {
            setAgentOpen(false);
            document.getElementById("helper-toggle")?.focus();
          }}
        />
      </div>
    </aside>
  );
}
