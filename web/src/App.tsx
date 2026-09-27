import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { WifiOff } from "lucide-react";
import { Header } from "./components/shell/Header";
import { CreateScreen } from "./components/simple/CreateScreen";
import { DetailsDrawer } from "./components/simple/DetailsDrawer";
import { HelperChat } from "./components/simple/HelperChat";
import { ResultScreen } from "./components/simple/ResultScreen";
import { Toasts } from "./components/ui/Toasts";
import { supportsViewTransitions, useReducedMotion, viewTransition } from "./lib/motion";
import { cn } from "./lib/utils";
import { useApp } from "./store";

// Two screens a person understands without a manual — «Создать» and «Результат» — plus the details drawer for the
// expert views and the helper docked on the right (the page reflows beside it). Each screen owns its container.
// A screen change (create ↔ result) plays as a View Transition: the old screen stays on screen for one commit, then the
// header holds still while the old page clears and the next one rises and fades in (a fade-through). One deck → another from the history swaps
// inside the store's own transition once the new deck has loaded (loadGeneration with `hold`); a reload on a deck opens
// on the result screen straight away (its skeleton, then the deck).
export default function App() {
  const { healthError, screen, generation, generationId, activeJob, agentOpen, detail } = useApp();
  // the same rule as DetailsDrawer: the deck tabs exist only on the result screen of a deck, the template tab always
  const drawerOpen = !!detail && (detail === "template" || (screen === "result" && !!generation && generation.variants.length > 0));
  const reduced = useReducedMotion();
  const viewKey = screen === "result" ? `result:${generationId ?? ""}` : "create";
  const want = useRef({ key: viewKey, screen });
  want.current = { key: viewKey, screen };
  const [shown, setShown] = useState(want.current);
  useLayoutEffect(() => {
    if (viewKey === shown.key) return;
    // another deck on the same screen: the result screen has already switched its content (it reads the deck from the
    // store), so there is no old view left to capture — and an empty transition would only block the next real one
    // (the build → deck hand-off that follows a new deck's id)
    if (want.current.screen === shown.screen) return setShown(want.current);
    // the callback reads the latest wish: a switch back before the transition started never lands on a stale screen.
    // Create and result share nothing but the header: a fade-through, the two pages never print over each other
    viewTransition(() => setShown(want.current), { through: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey]);
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  const deckTitle = generation?.variants[0]?.outline?.title;
  useEffect(() => {
    document.title = building
      ? `Готовлю презентацию ${Math.round((activeJob?.progress ?? 0) * 100)}% · Verstka`
      : screen === "result" && deckTitle ? `${deckTitle} · Verstka` : "Verstka — презентации в стиле вашего шаблона";
  }, [building, activeJob?.progress, screen, deckTitle]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header />
      {healthError && (
        <div role="alert" className="flex h-10 shrink-0 items-center justify-center gap-2 bg-red-600 px-8 text-footnote font-semibold text-white">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
          Нет связи с сервером — переподключаюсь…
        </div>
      )}
      {/* relative: the helper leaves the flow at once on close and slides out over the page's edge */}
      <div className="relative flex min-h-0 flex-1">
        {/* scroll padding: a control focused by Tab (or the caret of a long text) stops clear of the create screen's
            sticky action bar and of the build screen's sticky title bar */}
        <main key={shown.screen} data-follow className={cn("scroll-thin min-w-0 flex-1 overflow-y-auto scroll-pb-24", building && shown.screen === "result" && "scroll-pt-24")}>
          {/* without View Transitions (or with reduced motion) the new screen rises in by itself */}
          <div className={cn("h-full", (!supportsViewTransitions || reduced) && "animate-screen-in rm-fade")}>
            {shown.screen === "create" ? <CreateScreen /> : <ResultScreen />}
          </div>
        </main>
        <HelperChat />
      </div>
      <DetailsDrawer />
      {/* centred on what nothing docked covers: left of the helper and of an open drawer (its content is never covered) */}
      <Toasts helper={agentOpen} drawer={drawerOpen} />
    </div>
  );
}
