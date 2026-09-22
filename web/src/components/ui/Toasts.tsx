// Global toast stack. State lives in a tiny module-level store so that any code (the app store, plain
// helpers) can call `pushToast` without re-rendering the whole tree. Mount <Toasts/> exactly once.
import { useSyncExternalStore } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn, uid } from "../../lib/utils";

export type ToastKind = "error" | "success" | "info";
export interface ToastItem { id: string; kind: ToastKind; text: string }

const MAX_VISIBLE = 4;
const TTL_MS: Record<ToastKind, number> = { error: 7000, success: 3500, info: 4500 };

let items: ToastItem[] = [];
const listeners = new Set<() => void>();
const timers = new Map<string, number>();

function emit(next: ToastItem[]) {
  items = next;
  listeners.forEach((l) => l());
}

export function dismissToast(id: string) {
  const t = timers.get(id);
  if (t !== undefined) {
    window.clearTimeout(t);
    timers.delete(id);
  }
  if (items.some((i) => i.id === id)) emit(items.filter((i) => i.id !== id));
}

export function pushToast(kind: ToastKind, text: string): string {
  // The same message fired twice in a row (e.g. two panels reporting one failure) is shown once.
  const dup = items.find((i) => i.kind === kind && i.text === text);
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

const STYLE: Record<ToastKind, { icon: typeof Info; iconCls: string; bar: string }> = {
  error: { icon: AlertCircle, iconCls: "text-red-500", bar: "bg-red-500" },
  success: { icon: CheckCircle2, iconCls: "text-emerald-500", bar: "bg-emerald-500" },
  info: { icon: Info, iconCls: "text-accent", bar: "bg-accent" },
};

export function Toasts() {
  const list = useSyncExternalStore(subscribe, snapshot, snapshot);
  if (list.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-[380px] flex-col gap-2" aria-live="polite">
      {list.map((t) => {
        const s = STYLE[t.kind];
        const Icon = s.icon;
        return (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className="pointer-events-auto relative flex items-start gap-3 overflow-hidden rounded-xl border border-zinc-200 bg-white py-3 pl-4 pr-2.5 shadow-pop animate-fade-in"
          >
            <span className={cn("absolute inset-y-0 left-0 w-1", s.bar)} aria-hidden />
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", s.iconCls)} aria-hidden />
            <p className="min-w-0 flex-1 whitespace-pre-line break-words text-[13px] leading-5 text-zinc-800">{t.text}</p>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Закрыть уведомление"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
