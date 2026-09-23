// The assistant as every site's support chat: a round button in the corner, a chat window above it.
import { useEffect, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import { Chat } from "../Chat";

export function HelperChat() {
  const { agentOpen, setAgentOpen, messages } = useApp();
  // replies that arrived while the window was closed light a counter on the button
  const replies = messages.filter((m) => m.role === "assistant").length;
  const [seen, setSeen] = useState(replies);
  useEffect(() => {
    if (agentOpen) setSeen(replies);
  }, [agentOpen, replies]);
  const unread = agentOpen ? 0 : Math.max(0, replies - seen);
  const { mounted, leaving } = usePresence(agentOpen, 150);

  return (
    <>
      <div
        aria-label="Помощник Verstka"
        // the chat stays mounted while hidden: a half-written message survives closing the window
        className={cn(
          "fixed bottom-24 right-6 z-40 h-[min(640px,calc(100vh-128px))] w-[400px] origin-bottom-right flex-col overflow-hidden rounded-3xl bg-white shadow-pop",
          mounted ? "flex" : "hidden",
          mounted && (leaving ? "animate-scale-out" : "animate-scale-in"),
        )}
      >
        <Chat onClose={() => setAgentOpen(false)} />
      </div>
      <button
        type="button"
        onClick={() => setAgentOpen(!agentOpen)}
        aria-expanded={agentOpen}
        className={cn(
          "fixed bottom-6 right-6 z-40 flex h-14 cursor-pointer items-center gap-2.5 rounded-full pl-4 pr-5 text-[15px] font-semibold text-white shadow-glow transition-all duration-200 hover:scale-[1.03] focus:outline-none focus-visible:ring-4 focus-visible:ring-accent/30",
          agentOpen ? "bg-zinc-900" : "bg-accent",
        )}
      >
        <span key={agentOpen ? "x" : "chat"} className="animate-pop">
          {agentOpen ? <X className="h-5 w-5" aria-hidden /> : <MessageCircle className="h-5 w-5" aria-hidden />}
        </span>
        {agentOpen ? "Закрыть" : "Помощник"}
        {unread > 0 && (
          <span key={unread} className="absolute -right-1 -top-1 flex h-6 min-w-6 animate-pop items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-bold ring-2 ring-canvas">{unread}</span>
        )}
      </button>
    </>
  );
}
