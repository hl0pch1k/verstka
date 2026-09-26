// Global toast stack. State lives in a tiny module-level store so that any code (the app store, plain
// helpers) can call `pushToast` without re-rendering the whole tree. Mount <Toasts/> exactly once.
import { useSyncExternalStore } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn, uid } from "../../lib/utils";

export type ToastKind = "error" | "success" | "info";
export interface ToastItem { id: string; kind: ToastKind; text: string; leaving?: boolean }

const MAX_VISIBLE = 4;
const TTL_MS: Record<ToastKind, number> = { error: 7000, success: 3500, info: 4500 };

let items: ToastItem[] = [];
const listeners = new Set<() => void>();
const timers = new Map<string, number>();

function emit(next: ToastItem[]) {
  items = next;
  listeners.forEach((l) => l());
}

const EXIT_MS = 150; // drop-out

export function dismissToast(id: string) {
  const t = timers.get(id);
  if (t !== undefined) {
    window.clearTimeout(t);
    timers.delete(id);
  }
  const item = items.find((i) => i.id === id);
  if (!item || item.leaving) return;
  // play the exit, then drop the item
  emit(items.map((i) => (i.id === id ? { ...i, leaving: true } : i)));
  window.setTimeout(() => emit(items.filter((i) => i.id !== id)), EXIT_MS);
}

export function pushToast(kind: ToastKind, text: string): string {
  // The same message fired twice in a row (e.g. two panels reporting one failure) is shown once.
  const dup = items.find((i) => i.kind === kind && i.text === text && !i.leaving);
  if (dup) return dup.id;
  const id = uid("t");
  const next = [...items, { id, kind, text }];
  next.slice(0, Math.max(0, next.length - MAX_VISIBLE)).forEach((old) => dismissTimerOnly(old.id));
  emit(next.slice(-MAX_VISIBLE));
  timers.set(id, window.setTimeout(() => dismissToast(id), TTL_MS[kind]));
  return id;
}

function dismissTimerOnly(id: string) {
  const t = timers.get(id);
  if (t !== undefined) window.clearTimeout(t);
  timers.delete(id);
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
const snapshot = () => items;

const STYLE: Record<ToastKind, { icon: typeof Info; iconCls: string }> = {
  error: { icon: AlertCircle, iconCls: "text-red-400" },
  success: { icon: CheckCircle2, iconCls: "text-emerald-400" },
  info: { icon: Info, iconCls: "text-accent-300" },
};

/** `insetRight`: the width docked on the right (the helper), so the stack centres on the content, not on the window. */
export function Toasts({ insetRight = 0 }: { insetRight?: number }) {
  const list = useSyncExternalStore(subscribe, snapshot, snapshot);
  if (list.length === 0) return null;
  return (
    <div
      className="pointer-events-none fixed top-20 z-[100] flex w-[420px] -translate-x-1/2 flex-col items-center gap-2"
      style={{ left: `calc(50% - ${insetRight / 2}px)` }}
      aria-live="polite"
    >
      {list.map((t) => {
        const s = STYLE[t.kind];
        const Icon = s.icon;
        return (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto relative flex w-full items-center gap-3 overflow-hidden rounded-2xl bg-ink py-3 pl-4 pr-2 text-white shadow-pop",
              t.leaving ? "animate-drop-out" : "animate-drop-in",
            )}
          >
            <span className="flex h-5 shrink-0 items-center self-start">
              <Icon className={cn("h-4 w-4", s.iconCls)} aria-hidden />
            </span>
            <p className="min-w-0 flex-1 whitespace-pre-line break-words text-footnote text-white/90">{t.text}</p>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Закрыть уведомление"
              className="-my-1 flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-white/60 transition-colors duration-150 hover:bg-white/10 hover:text-white focus-visible:outline-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
