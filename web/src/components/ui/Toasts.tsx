// Global toast stack. State lives in a tiny module-level store so that any code (the app store, plain
// helpers) can call `pushToast` without re-rendering the whole tree. Mount <Toasts/> exactly once.
import { useSyncExternalStore } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { MOTION } from "../../lib/motion";
import { cn, uid } from "../../lib/utils";
import { Collapse } from "./Collapse";

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

// the card drops out in 150 ms while its row collapses in 300 ms, so the toasts below glide up instead of jumping
const EXIT_MS = MOTION.slow;

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
  emit(next);
  // the oldest over the limit leave with their exit (the rest glide up), never by a cut
  const staying = next.filter((i) => !i.leaving);
  staying.slice(0, Math.max(0, staying.length - MAX_VISIBLE)).forEach((old) => dismissToast(old.id));
  timers.set(id, window.setTimeout(() => dismissToast(id), TTL_MS[kind]));
  return id;
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

// the layers docked on the right (the same sizes as HelperChat and the DetailsDrawer sheet)
const HELPER_W = 360;
const TOAST_W = 420;
const GUTTER = 24;
const MIN_W = 304;

/** Where the stack sits (its centre x and width, px): centred on the part of the window nothing docked covers — left of
 *  the helper, and left of an open drawer (with the helper beside it) — so a toast never covers the sheet's content.
 *  When that strip is too narrow (the helper beside the drawer on a laptop screen) the stack moves into the helper
 *  column, under its header. */
export function toastPlace(vw: number, helper: boolean, drawer: boolean): { cx: number; w: number; top: number } {
  const sheet = !drawer ? 0 : helper ? Math.min(800, vw - HELPER_W - 48) : Math.min(800, vw * 0.94);
  const free = vw - sheet - (helper ? HELPER_W : 0);
  // beside the drawer the helper rises to the top edge: 16px under its 56px header, as the page's stack sits under 64px
  if (drawer && helper && free - GUTTER * 2 < MIN_W) return { cx: vw - HELPER_W / 2, w: HELPER_W - 32, top: 72 };
  return { cx: free / 2, w: Math.max(MIN_W, Math.min(TOAST_W, free - GUTTER * 2)), top: 80 };
}

const onResize = (l: () => void) => {
  window.addEventListener("resize", l);
  return () => window.removeEventListener("resize", l);
};
const viewportWidth = () => window.innerWidth;

/** `helper`: the helper is docked on the right; `drawer`: the details drawer is open (see toastPlace). */
export function Toasts({ helper = false, drawer = false }: { helper?: boolean; drawer?: boolean }) {
  const list = useSyncExternalStore(subscribe, snapshot, snapshot);
  const vw = useSyncExternalStore(onResize, viewportWidth, () => 1440);
  if (list.length === 0) return null;
  const { cx, w, top } = toastPlace(vw, helper, drawer);
  return (
    <div
      className="vt-toasts pointer-events-none fixed left-0 z-[100] flex flex-col items-center"
      // the stack glides with the helper and the drawer (transform, never `left`); anchored on its centre, so a width that
      // changes with the place never throws it sideways
      style={{ top: 0, width: w, transform: `translate(calc(${Math.round(cx)}px - 50%), ${top}px)`, transition: "transform 300ms var(--ease-glide)" }}
      aria-live="polite"
    >
      {list.map((t) => {
        const s = STYLE[t.kind];
        const Icon = s.icon;
        return (
          // new toasts join at the bottom (nothing below them moves), so they mount open and drop in with their shadow
          // unclipped; a leaving one collapses its row
          <Collapse key={t.id} open={!t.leaving} className="w-full" innerClassName="pb-2">
          <div
            role={t.kind === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto relative flex w-full origin-top items-center gap-3 overflow-hidden rounded-2xl bg-ink py-3 pl-4 pr-2 text-white shadow-pop",
              t.leaving ? "pointer-events-none animate-drop-out rm-fade-out" : "animate-drop-in rm-fade",
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
              className="tap -my-1 flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-white/60 hover:bg-white/10 hover:text-white focus-visible:outline-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          </Collapse>
        );
      })}
    </div>
  );
}
