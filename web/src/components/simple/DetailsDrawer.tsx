// The details drawer: a quiet reading room from the right with everything an expert (or a jury) wants to see, out of
// the way of a person who only needs the deck — quality, why a slide looks so, the agent's work, the plan, the
// template and the files. One variant menu in the header serves every tab; the helper, when open, stays beside it.
import { useEffect, useLayoutEffect, useRef, useState, type ComponentType, type KeyboardEvent } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import { MOTION, usePresence } from "../../lib/motion";
import { cn, scoreTone, TONE_TEXT } from "../../lib/utils";
import { useApp } from "../../store";
import type { DetailKey } from "../../types";
import { AuditPanel } from "../AuditPanel";
import { ExportPanel } from "../ExportPanel";
import { PlanPanel } from "../PlanPanel";
import { RunPanel } from "../RunPanel";
import { TemplateDetails } from "../TemplatePanel";
import { Button } from "../ui/Button";
import { tabId, Tabs } from "../ui/Tabs";
import { variantScore } from "../VariantsHelpers";
import { AgentLog } from "./AgentPanel";
import { WhySlide } from "./WhySlide";

function Tech() {
  return (
    <div className="space-y-4">
      <ExportPanel />
      <RunPanel />
    </div>
  );
}

const TABS: Array<{ key: DetailKey; label: string; view: ComponentType; needsDeck: boolean; perVariant: boolean }> = [
  { key: "quality", label: "Качество", view: AuditPanel, needsDeck: true, perVariant: true },
  { key: "why", label: "Почему так", view: WhySlide, needsDeck: true, perVariant: true },
  { key: "agent", label: "Агент", view: AgentLog, needsDeck: true, perVariant: true },
  { key: "plan", label: "План", view: PlanPanel, needsDeck: true, perVariant: true },
  { key: "template", label: "Шаблон", view: TemplateDetails, needsDeck: false, perVariant: false },
  { key: "tech", label: "Файлы", view: Tech, needsDeck: true, perVariant: true },
];

/** «Структурный ⌄»: the variant every tab of the drawer shows; the menu lists the variants with their scores. */
function VariantMenu() {
  const { generation, activeStrategy, setActiveStrategy, strategyTitle } = useApp();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const { mounted, leaving } = usePresence(open, MOTION.fast);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    // the checked item takes the focus, so the arrows and Esc work at once
    const raf = requestAnimationFrame(() => menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus());
    return () => {
      document.removeEventListener("mousedown", onDown);
      cancelAnimationFrame(raf);
    };
  }, [open]);

  if (!generation || generation.variants.length < 2) return null;
  const active = activeStrategy ?? generation.variants[0].strategy;

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])];
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    // a closed menu leaves every key to the drawer (Esc on the trigger closes the drawer)
    if (!open) return;
    if (e.key === "Escape") {
      // the menu is the topmost layer: Esc closes it, not the drawer
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if (e.key === "Tab") {
      close(false);
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) && items.length) {
      e.preventDefault();
      e.stopPropagation();
      const next = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      items[next]?.focus();
    }
  };

  return (
    <div ref={box} className="relative" onKeyDown={onKey}>
      <Button ref={trigger} variant="ghost" size="md" iconRight={ChevronDown} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {strategyTitle(active)}
      </Button>
      {mounted && (
        <div
          ref={menu}
          role="menu"
          aria-label="Вариант оформления"
          className={cn("absolute right-0 top-full z-10 mt-2 w-60 origin-top-right rounded-2xl bg-white p-1 shadow-pop", leaving ? "pointer-events-none animate-drop-out" : "animate-drop-in")}
        >
          {generation.variants.map((v, i) => {
            const score = variantScore(v, generation.summary?.[v.strategy]?.score);
            const checked = v.strategy === active;
            return (
              <button
                key={v.strategy}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                tabIndex={checked ? 0 : -1}
                onClick={() => {
                  setActiveStrategy(v.strategy);
                  close(true);
                }}
                className={cn(
                  // the item that holds the focus is marked like a hovered one: the arrows show which item Enter picks
                  "flex h-10 w-full cursor-pointer items-center gap-2 rounded-xl px-3 text-left text-body transition-colors duration-150 hover:bg-zinc-100 focus:bg-zinc-100 focus-visible:outline-offset-[-2px]",
                  checked ? "font-semibold text-zinc-900" : "text-zinc-700",
                )}
              >
                <span className="w-4 shrink-0 text-footnote font-normal tabular-nums text-zinc-500">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{strategyTitle(v.strategy)}</span>
                {score !== null && <span className={cn("shrink-0 text-footnote font-semibold tabular-nums", TONE_TEXT[scoreTone(score)])}>{Math.round(score)}</span>}
                <span className="flex w-4 shrink-0 justify-end" aria-hidden>
                  {checked && <Check className="h-4 w-4 text-accent" strokeWidth={2.5} />}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** What the Tab key may land on inside a layer: shown, enabled and in the tab order. */
const FOCUSABLE = 'a[href],button,select,input,textarea,summary,[tabindex],[contenteditable="true"]';
function focusables(roots: HTMLElement[]): HTMLElement[] {
  return roots.flatMap((r) =>
    [...r.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled && el.checkVisibility?.({ checkVisibilityCSS: true, visibilityProperty: true } as CheckVisibilityOptions) !== false,
    ),
  );
}

/** The drawer's tab ids (`drawer-tab-quality`…) and the one panel they switch. */
const TABS_ID = "drawer";
const PANEL_ID = "drawer-panel";

/** The keys the result screen turns into slide steps (← → Home End): under the drawer they stay in the drawer, except
 *  on «Почему так», which walks the slides it explains. */
const SLIDE_KEYS = ["ArrowLeft", "ArrowRight", "Home", "End"];

export function DetailsDrawer() {
  const { detail, setDetail, screen, generation, agentOpen } = useApp();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const helperBeside = useRef(agentOpen);
  helperBeside.current = agentOpen;
  const shownTab = useRef<DetailKey | null>(null);
  const hasDeck = screen === "result" && !!generation && generation.variants.length > 0;
  const tabs = TABS.filter((t) => hasDeck || !t.needsDeck);
  const current = tabs.find((t) => t.key === detail) ?? null;
  // the closing drawer keeps showing its last tab while it slides out
  const { mounted, leaving } = usePresence(!!current, MOTION.fast);
  const last = useRef(current);
  if (current) last.current = current;
  const shown = current ?? last.current;
  shownTab.current = shown?.key ?? null;

  useEffect(() => {
    if (!current) return;
    // the control that opened the drawer gets the focus back when it closes
    opener.current = document.activeElement as HTMLElement | null;
    // a person typing to the helper beside the drawer keeps the focus in the chat
    if (!(document.activeElement as HTMLElement | null)?.closest?.("#helper")) closeRef.current?.focus();
    // a layer above the drawer (a modal opened from it, the lightbox) handles its own keys
    const onTop = () => {
      const layers = [...document.querySelectorAll('[aria-modal="true"]')].filter((l) => l !== dialog.current);
      return !layers.some((l) => dialog.current && dialog.current.compareDocumentPosition(l) & Node.DOCUMENT_POSITION_FOLLOWING);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (!onTop()) return;
      if (e.key !== "Tab" || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
      // the focus stays in the modal: the sheet and, when it is open beside it, the helper (sheet first, as seen)
      const helper = helperBeside.current ? document.getElementById("helper") : null;
      const roots = [sheet.current, helper].filter((r): r is HTMLElement => !!r);
      const list = focusables(roots);
      if (!list.length) return;
      const at = document.activeElement as HTMLElement | null;
      const inside = !!at && roots.some((r) => r.contains(at));
      const i = at ? list.indexOf(at) : -1;
      // an item outside the tab order inside the layer (the variant menu's items): the browser takes the next one
      if (inside && i < 0) return;
      e.preventDefault();
      const next = !inside ? (e.shiftKey ? list.length - 1 : 0) : (i + (e.shiftKey ? list.length - 1 : 1)) % list.length;
      list[next].focus();
    };
    // on the document: after the drawer's own controls (tabs, menu, palette, chips) had the key (a menu's Esc stops
    // there), before the listeners on the window — the result screen's slide keys and the helper's Esc, which sees the
    // key taken (Esc closes the topmost layer only: the drawer, not the helper beside it)
    const onDocKey = (e: globalThis.KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || !onTop()) return;
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        setDetail(null);
      } else if (SLIDE_KEYS.includes(e.key) && shownTab.current !== "why") e.stopPropagation();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("keydown", onDocKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("keydown", onDocKey);
      const o = opener.current;
      opener.current = null;
      if (o?.isConnected && o !== document.body && !(document.activeElement as HTMLElement | null)?.closest?.("#helper")) o.focus({ preventScroll: true });
    };
    // the focus moves to the close button when the drawer opens, not on every tab switch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!current, setDetail]);

  // every tab opens at its top (the scroller is shared by the tabs)
  const shownKey = shown?.key;
  useLayoutEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
  }, [shownKey]);

  if (!mounted || !shown) return null;
  const View = shown.view;
  const title = tabs.length > 1 ? shown.label : "Разбор шаблона";
  return (
    // the helper open beside the drawer belongs to the same modal layer: the Tab key cycles through both, and aria-owns
    // puts the helper inside the dialog for a screen reader (aria-modal would hide it otherwise)
    <div ref={dialog} className={cn("fixed inset-0 z-50", leaving && "pointer-events-none")} role="dialog" aria-modal="true" aria-owns={agentOpen ? "helper" : undefined} aria-label={title}>
      <div className={cn("absolute inset-0 bg-ink/40 backdrop-blur-[2px]", leaving ? "animate-fade-out" : "animate-fade")} onClick={() => setDetail(null)} aria-hidden />
      <div
        ref={sheet}
        className={cn(
          "absolute inset-y-0 flex flex-col bg-canvas shadow-pop transition-[right] duration-300",
          agentOpen ? "right-[360px] w-[min(800px,calc(100vw-360px-48px))]" : "right-0 w-[min(800px,94vw)]",
          leaving ? "animate-slide-out-right" : "animate-slide-in-right",
        )}
      >
        {/* above the content's sticky rows (the «Почему так» nav): the variant menu opens over them */}
        <header className="relative z-20 flex h-14 shrink-0 items-stretch gap-4 border-b border-zinc-200/70 bg-white px-6">
          {tabs.length > 1 ? (
            // the tabs have ids and point at the panel, the panel names its tab (aria-labelledby); the keyboard ring is
            // the primitive's own 40px pill
            <Tabs variant="underline" aria-label="Разделы" value={shown.key} onChange={setDetail} items={tabs.map((t) => ({ key: t.key, label: t.label }))} idPrefix={TABS_ID} panelId={PANEL_ID} />
          ) : (
            <h2 className="self-center text-title2 font-bold text-zinc-900">Разбор шаблона</h2>
          )}
          <div className="ml-auto flex items-center gap-4 self-center">
            {shown.perVariant && <VariantMenu />}
            {/* the same quiet close as the helper's header beside it: a ghost circle on the white bar */}
            <Button ref={closeRef} variant="ghost" shape="circle" size="md" icon={X} aria-label="Закрыть" onClick={() => setDetail(null)} />
          </div>
        </header>
        <div ref={scroller} className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-6">
          <div key={shown.key} {...(tabs.length > 1 ? { role: "tabpanel", id: PANEL_ID, "aria-labelledby": tabId(TABS_ID, shown.key) } : {})} className="animate-fade-in">
            <View />
          </div>
        </div>
      </div>
    </div>
  );
}
