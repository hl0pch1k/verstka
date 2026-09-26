import { useEffect } from "react";
import { WifiOff } from "lucide-react";
import { Header } from "./components/shell/Header";
import { CreateScreen } from "./components/simple/CreateScreen";
import { DetailsDrawer } from "./components/simple/DetailsDrawer";
import { HelperChat } from "./components/simple/HelperChat";
import { ResultScreen } from "./components/simple/ResultScreen";
import { Toasts } from "./components/ui/Toasts";
import { cn } from "./lib/utils";
import { useApp } from "./store";

// Two screens a person understands without a manual — «Создать» and «Результат» — plus the details drawer for the
// expert views and the helper docked on the right (the page reflows beside it). Each screen owns its container.
export default function App() {
  const { healthError, screen, generation, activeJob, agentOpen } = useApp();
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
      <div className="flex min-h-0 flex-1">
        {/* scroll padding: a control focused by Tab (or the caret of a long text) stops clear of the create screen's
            sticky action bar and of the build screen's sticky title bar */}
        <main key={screen} data-follow className={cn("scroll-thin min-w-0 flex-1 overflow-y-auto scroll-pb-24", building && screen === "result" && "scroll-pt-24")}>
          <div className="h-full animate-fade-in">{screen === "create" ? <CreateScreen /> : <ResultScreen />}</div>
        </main>
        <HelperChat />
      </div>
      <DetailsDrawer />
      {/* centred on the content: the docked helper takes 360px on the right */}
      <Toasts insetRight={agentOpen ? 360 : 0} />
    </div>
  );
}
