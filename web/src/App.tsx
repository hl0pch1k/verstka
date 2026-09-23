import { useEffect } from "react";
import { WifiOff } from "lucide-react";
import { Header } from "./components/shell/Header";
import { CreateScreen } from "./components/simple/CreateScreen";
import { DetailsDrawer } from "./components/simple/DetailsDrawer";
import { HelperChat } from "./components/simple/HelperChat";
import { ResultScreen } from "./components/simple/ResultScreen";
import { Toasts } from "./components/ui/Toasts";
import { useApp } from "./store";

// Two screens a person understands without a manual — «Создать» and «Результат» — plus the «Подробнее» drawer
// for the expert views and the helper chat in the corner.
export default function App() {
  const { healthError, screen, generation, activeJob } = useApp();
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
        <div role="alert" className="flex shrink-0 items-center justify-center gap-2.5 bg-red-600 px-6 py-2 text-[13px] text-white">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-semibold">Нет связи с сервером.</span>
          <span className="text-red-100">
            Запустите <code className="rounded-md bg-red-700/60 px-1.5 py-0.5 font-mono text-xs text-white">verstka serve</code> — страница переподключится сама.
          </span>
        </div>
      )}
      <main key={screen} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <div className="px-10 py-8 animate-fade-in">{screen === "create" ? <CreateScreen /> : <ResultScreen />}</div>
      </main>
      <DetailsDrawer />
      <HelperChat />
      <Toasts />
    </div>
  );
}
