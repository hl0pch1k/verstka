// The second screen: the deck as a fixed-height workspace (no page scroll). A title bar with the downloads, then the
// stage — the variant switch, the slide as large as the window allows, the thumbnails — and a narrow aside with the
// quality, the designer's reasoning, the agent and the ways into the drawer. The «Замечания» switch turns the aside into
// the remarks workspace: the remarks are numbered on the slide and in the list, and «Исправить слайд» lets the agent
// fix them on that slide only.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { ChevronRight, Download, FileText, FolderDown, ImageOff, LayoutTemplate, ListTree, PenLine, RotateCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { plainWords, variantsNote } from "../../lib/agent";
import { deckNotice } from "../../lib/modelText";
import { figuresLine } from "../../lib/narrate";
import { fileSafe, templateTitle, variantHint } from "../../lib/plain";
import { decodeImage, EASE, MOTION, prefersReducedMotion, useFlip, usePresence, viewTransition } from "../../lib/motion";
import { cn, fmtWhen, plural, storage } from "../../lib/utils";
import { useApp } from "../../store";
import type { DetailKey, Generation, Issue, Variant } from "../../types";
import { isMinor } from "../AuditHelpers";
import { BuildScreen } from "../BuildScreen";
import { Button, LinkButton } from "../ui/Button";
import { Collapse } from "../ui/Collapse";
import { EmptyState } from "../ui/EmptyState";
import { Notice } from "../ui/Notice";
import { ScoreRing } from "../ui/ScoreRing";
import { Segmented } from "../ui/Segmented";
import { issuesBySlide, KEY_ISSUES, nextFlagged, remarkTone, stageRemarks, variantRev, variantScore, withRev } from "../VariantsHelpers";
import { SlideControls, VariantsSlidePreview } from "../VariantsSlidePreview";
import { AgentCard } from "./AgentPanel";
import { useRetryIn } from "./ModelStatus";
import { RemarksPanel, useCheckTitles } from "./RemarksPanel";
import { SlideLightbox } from "./SlideLightbox";
import { SlideStrip } from "./SlideStrip";
import { useSlideFix, type FixRun } from "./useSlideFix";

const NO_ISSUES: Issue[] = [];
/** The screen's container, shared with the build screen and the header row: the edges line up across screens. The left
 *  margin follows the window, not the main column, so the docked helper never moves the title off the logo's edge. */
const ROOT = "ml-[max(0px,calc((100vw-1600px)/2))] mr-auto flex h-full min-h-[600px] max-w-[1600px] flex-col gap-4 px-8 py-6";
const CARD = "tap-soft group block w-full shrink-0 cursor-pointer rounded-2xl bg-white p-4 text-left shadow-card hover:bg-zinc-50 active:bg-zinc-100";
/** The aside's cards rise one after another when the aside appears (the deck opens, the helper closes, the remarks
 *  mode ends); the quality card carries its own rise, it stays through the remarks mode. */
const ASIDE_STAGGER = "[&>*:not(:first-child)]:animate-rise [&>*:nth-child(2)]:[animation-delay:40ms] [&>*:nth-child(3)]:[animation-delay:80ms] [&>*:nth-child(n+4)]:[animation-delay:120ms]";
/** The cards that already rose in under the leaving remarks panel take its place: their rise and fades finish at once
 *  for a moment (a finished animation never replays when the override goes). */
const CARDS_SETTLE = "[&>*]:![animation-duration:0s] [&>*]:![animation-delay:0s] [&_.animate-fade]:![animation-duration:0s]";
/** The stage around the well: p-4 twice, the 40px header, the 72px strip and two 12px gaps. */
const STAGE_CHROME = 168;
/** The same inside the stage's padding (the stage's content box: the header, the strip and the two gaps). */
const STAGE_INNER = STAGE_CHROME - 32;
/** The aside column and the gap before it. */
const ASIDE_W = 288 + 16;
/** The H1 steps down the type scale before it truncates: title1, then title2 on one line, then title2 on two lines (the
 *  meta goes to the tooltip). With the helper open it stays on one line: the bar never reflows on that toggle. */
const TITLE_FIT = ["truncate text-title1", "truncate text-title2", "line-clamp-2 text-title2 [text-wrap:balance]"] as const;
/** The remarks the stage shows: errors, warnings and the model's flags. Minor notes stay in the drawer's «Мелкие заметки». */
const onStage = (i: Issue) => !isMinor(i);

/** The deck notice speaks of «модель», never a backend name; one-line titles end without a period, and the provider's
 *  retry pause is not a person's business (copy rules 3, 4 and 6). */
function plainNotice(text: string, labels: string[]): string {
  let t = text;
  for (const l of labels) t = t.split(`модель ${l}`).join("модель").split(`Модель ${l}`).join("Модель").split(l).join("Модель");
  return t
    .split(/(?<=[.!?…])\s+/)
    .filter((s) => !/пауз|через\s+\d/i.test(s))
    .join(" ")
    .trim();
}

const isEditable = (el: EventTarget | null) => {
  const t = el as HTMLElement | null;
  if (!t || typeof t.closest !== "function") return false;
  return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || !!t.closest('[role="tablist"], [role="dialog"], [role="radiogroup"], [role="menu"]');
};
function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
/** A score is plain «100»; colour only flags a problem (shades that keep 4.5:1 on the grey segmented track). */
const scoreText = (s: number) => (s >= 90 ? "text-zinc-500" : s >= 70 ? "text-amber-800" : "text-red-700");
/** The real slide count of a variant: 0 when it has none (slideCount() never says 0). */
const slidesOf = (v: Variant) => v.slides.length || v.outline?.slides.length || v.plan?.slides.length || 0;

/** The «Почему так» card: its white surface is a layer of its own, so a change of the text's height glides (below). */
const WHY_CARD = "tap-soft group relative isolate block w-full shrink-0 cursor-pointer rounded-2xl p-4 text-left";

/** When `key` changes, the element's `[data-surface]` layer glides from the element's old height to its new one (a scaleY
 *  FLIP from the top; the text on it cross-fades by itself), so a card whose text got shorter or longer never snaps. */
function useSurfaceGlide(ref: RefObject<HTMLElement>, key: unknown) {
  const lastKey = useRef(key);
  const before = useRef<number | null>(null);
  if (key !== lastKey.current && ref.current && before.current === null) before.current = ref.current.offsetHeight;
  useLayoutEffect(() => {
    const el = ref.current;
    const was = before.current;
    const changed = lastKey.current !== key;
    lastKey.current = key;
    before.current = null;
    if (!el || was === null || !changed || prefersReducedMotion()) return;
    const now = el.offsetHeight;
    if (!now || !was || Math.abs(now - was) < 1) return;
    el.querySelector<HTMLElement>("[data-surface]")?.animate([{ transform: `scaleY(${was / now})` }, { transform: "none" }], { duration: MOTION.slow, easing: EASE.glide });
  });
}

/** The aside column glides with the slide when the helper docks or leaves (translate only, from where it visibly was).
 *  A start beyond the right edge of the page's scroll column would be clipped away — for a few frames the column would
 *  be missing, then wipe in from that edge — so the start is clamped to that edge and the column fades in on the way. */
function useAsideGlide(ref: RefObject<HTMLElement>, key: unknown) {
  const lastKey = useRef(key);
  const before = useRef<DOMRect | null>(null);
  if (key !== lastKey.current && ref.current && !before.current) before.current = ref.current.getBoundingClientRect();
  useLayoutEffect(() => {
    const el = ref.current;
    const was = before.current;
    const changed = lastKey.current !== key;
    lastKey.current = key;
    before.current = null;
    if (!el || !was || !changed || prefersReducedMotion()) return;
    el.getAnimations().forEach((a) => (a.id === "aside-glide" || a.id === "aside-fade") && a.cancel());
    const now = el.getBoundingClientRect();
    if (now.width === 0 || was.width === 0) return;
    let dx = was.left - now.left;
    const dy = was.top - now.top;
    const edge = el.closest("main")?.getBoundingClientRect().right ?? document.documentElement.clientWidth;
    const clipped = dx > 0 && now.right + dx > edge + 0.5;
    if (clipped) dx = Math.max(0, edge - now.right);
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      const a = el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: MOTION.slow, easing: EASE.glide });
      a.id = "aside-glide";
    }
    if (clipped) {
      const f = el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: MOTION.base, easing: EASE.out });
      f.id = "aside-fade";
    }
  });
}

function CardChevron() {
  return <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-transform duration-150 ease-out group-hover:translate-x-0.5" aria-hidden />;
}

function DrawerLink({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="tap inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-xl bg-white text-footnote font-semibold text-zinc-800 shadow-card hover:bg-zinc-50 active:bg-zinc-100"
    >
      <Icon className="h-4 w-4 shrink-0 text-zinc-500" aria-hidden />
      {label}
    </button>
  );
}

/** The quality card: the ring, one verdict and the figures checked against the text. Warnings get their own meta
 *  line: «1 предупреждение» (the word the remark tags and the drawer use) does not fit beside the verdict in 180px. */
function QualityCard({ variant, score, errors, onOpen, className }: { variant: Variant; score: number | null; errors: number | null; onOpen(): void; className?: string }) {
  const warnings = variant.audit?.summary.warnings ?? 0;
  const figs = figuresLine(variant.audit?.summary.figures);
  const verdict = errors === null ? "Не проверено" : errors > 0 ? plural(errors, "ошибка", "ошибки", "ошибок") : "Ошибок нет";
  const warned = warnings > 0 ? plural(warnings, "предупреждение", "предупреждения", "предупреждений") : null;
  const second = figs ?? (errors ? { text: "Можно исправить автоматически", tone: "ok" as const, title: undefined } : null);
  return (
    <button type="button" onClick={onOpen} aria-label={`Качество: ${verdict}${warned ? ` · ${warned}` : ""}`} className={cn(CARD, className)}>
      <span className="flex items-center gap-3">
        {/* an error turns the ring red whatever the score («90» with one error would be green beside «1 ошибка») */}
        <ScoreRing score={score} size={44} stroke={4} tone={errors ? "error" : undefined} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1">
            <span key={verdict} className={cn("min-w-0 flex-1 animate-fade text-body font-semibold transition-colors duration-150", errors ? "text-red-600" : "text-zinc-900")}>{verdict}</span>
            <CardChevron />
          </span>
          {warned && <span className="mt-0.5 block text-footnote text-zinc-500">{warned}</span>}
          {second && (
            <span className={cn("block text-footnote", !warned && "mt-0.5", second.tone === "warn" ? "text-amber-700" : "text-zinc-500")} title={second.title}>
              {second.text}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

/** A deck that mounts inside a View Transition (the build hands over, the create screen opens a deck): the transition is
 *  its entrance, so for its length the deck's own fades and rises finish at once (a second fade inside the fading-in
 *  snapshot reads as a washed-out page). */
const QUIET_ENTER = "[&_.animate-fade]:![animation-duration:0s] [&_.animate-rise]:![animation-duration:0s] [&_.animate-rise]:![animation-delay:0s] [&_.animate-fade-in]:![animation-duration:0s] [&_.animate-fade-in]:![animation-delay:0s]";
const inViewTransition = () => {
  try {
    return document.documentElement.matches(":active-view-transition");
  } catch {
    return false; // a browser without the pseudo-class has no View Transitions either
  }
};

function Deck({ generation }: { generation: Generation }) {
  const { activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, strategies, manifest, setScreen, detail, setDetail, health, modelStatus, refreshModelStatus, startGeneration, activeJob, generations, agentOpen } = useApp();
  const variant = activeVariant ?? generation.variants[0];
  const total = slidesOf(variant);
  const empty = total === 0;
  const rev = variantRev(variant);
  const issueMap = useMemo(() => issuesBySlide(variant.audit, onStage), [variant.audit]);
  const slideIssues = issueMap.get(selectedSlide) ?? NO_ISSUES;
  const [showIssues, setShowIssues] = useState(() => storage.get(KEY_ISSUES) === "1");
  const [naturalAspect, setNaturalAspect] = useState<number | null>(null);
  const [zoom, setZoom] = useState(false);
  // the slide frame and the well it sits in: the thumbnails line up with the frame, and a width-bound slide caps the stage
  const [box, setBox] = useState({ frame: 0, well: 0 });
  const templateLoaded = !!manifest && manifest.template_id === generation.template_id;
  const aspect = naturalAspect ?? (templateLoaded && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9);

  useEffect(() => {
    if (empty) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || isEditable(e.target)) return;
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      const jump = e.key === "Home" ? 1 : e.key === "End" ? total : 0;
      if (!step && !jump) return;
      e.preventDefault();
      setSelectedSlide(jump || selectedSlide + step);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedSlide, total, empty, setSelectedSlide]);

  // warm the cache with the neighbours: ← and → show the next slide at once (decoded, so it never paints blank)
  useEffect(() => {
    for (const n of [selectedSlide + 1, selectedSlide - 1]) {
      const url = variant.slides[n - 1];
      if (url) void decodeImage(withRev(url, rev)).catch(() => {});
    }
  }, [selectedSlide, variant, rev]);

  // how the next image comes in: a push toward the travel (slides), a cross-fade (variants), a reveal (an edit or a fix)
  const prevView = useRef({ slide: selectedSlide, strategy: variant.strategy, rev });
  const pv = prevView.current;
  const slideDir: -1 | 0 | 1 = pv.strategy === variant.strategy && pv.slide !== selectedSlide ? (Math.sign(selectedSlide - pv.slide) as -1 | 1) : 0;
  const slideMode = pv.strategy === variant.strategy && pv.slide === selectedSlide && pv.rev !== rev ? "reveal" : "turn";
  useEffect(() => {
    prevView.current = { slide: selectedSlide, strategy: variant.strategy, rev };
  });

  const outlineSlide = variant.outline?.slides[selectedSlide - 1] ?? null;
  const headline = outlineSlide?.headline ?? "";
  // why the designer chose this form (Agent v2): as many lines as the aside has room for, the whole story in «Почему так».
  // The same words as the drawer's tab: plainWords (plainTerms plus the slide kinds) reads «Форма «две колонки»…»
  const whyRaw = empty ? null : variant.design?.find((d) => d.index === selectedSlide)?.rationale ?? outlineSlide?.rationale ?? null;
  const why = whyRaw?.trim() ? cap(plainWords(whyRaw).trim()) : null;
  const raw = variant.slides[selectedSlide - 1];
  const src = raw ? withRev(raw, rev) : null;
  const score = variantScore(variant, generation.summary?.[variant.strategy]?.score);
  const errorsOf = (v: Variant) => v.audit?.summary.errors ?? generation.summary?.[v.strategy]?.errors ?? null;
  const errors = errorsOf(variant);
  const pptx = variant.files["deck.pptx"] ?? null;
  const pdf = variant.files["deck.pdf"] ?? null;
  const title = variant.outline?.title || "Презентация";
  const variantName = strategyTitle(variant.strategy);
  const variantIdx = generation.variants.findIndex((v) => v.strategy === variant.strategy) + 1;
  const fileBase = `${fileSafe(title)} — ${variantName}`;
  const meta = [templateTitle(generation.template_file), fmtWhen(generation.created_at)].filter(Boolean).join(" · ");

  // the drawer gives the focus back to the card that opened it: Tab goes on from the same place in the aside
  const opener = useRef<HTMLElement | null>(null);
  const open = (d: DetailKey) => {
    const el = document.activeElement as HTMLElement | null;
    opener.current = el && el !== document.body ? el : null;
    setDetail(d);
  };
  useEffect(() => {
    if (detail !== null) return;
    const el = opener.current;
    opener.current = null;
    if (el?.isConnected) el.focus({ preventScroll: true });
  }, [detail]);

  // The H1 fits instead of truncating: 28px, then 20, then two lines of 20 (the meta line moves into the tooltip, so the
  // bar stays 56px and the slide never moves). A hidden probe gives the 28px width of the title.
  const titleBox = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const [fit, setFit] = useState(0);
  useLayoutEffect(() => {
    const boxEl = titleBox.current;
    const pr = probe.current;
    if (!boxEl || !pr) return;
    const run = () => {
      // fractional widths: a title 0.2px wider than its box must step down, not end in «…»
      const w = pr.getBoundingClientRect().width;
      const cw = boxEl.getBoundingClientRect().width;
      if (!w || !cw) return;
      setFit(w <= cw ? 0 : (w * 20) / 28 <= cw ? 1 : 2);
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(boxEl);
    ro.observe(pr);
    void document.fonts?.ready.then(run);
    return () => ro.disconnect();
  }, [title]);
  // the helper open: one line (truncated, the full title in the tooltip) and the meta stays
  const titleStep = agentOpen ? Math.min(fit, 1) : fit;

  // the variant switch: «Структурный 100»; the slide count only when the variants differ in it
  const counts = generation.variants.map((v) => slidesOf(v));
  const countsDiffer = new Set(counts).size > 1;
  const note = useMemo(() => generation.variants.map((v) => variantsNote(v)).find(Boolean) ?? null, [generation.variants]);
  // any slide of any variant with a remark: the switch keeps its room on every slide and variant, so the header never
  // shifts; it shows only on a variant that has remarks (a clean variant, «Ошибок нет», has nothing to switch on)
  const anyRemarks = useMemo(() => generation.variants.some((v) => (v.audit?.issues ?? []).some((i) => i.slide >= 1 && onStage(i))), [generation.variants]);
  const variantStage = useMemo(() => [...issueMap.entries()].filter(([n]) => n >= 1).flatMap(([, l]) => l), [issueMap]);
  const variantHas = variantStage.length > 0;
  // the mode stays on after a fix cleared the variant (its success is still on screen) and across a switch to a clean
  // variant, until the person turns it off; a stored "1" on a clean variant shows nothing
  const sticky = useRef(false);
  if (!showIssues) sticky.current = false;
  else if (variantHas) sticky.current = true;
  const remarksOn = !empty && showIssues && (variantHas || sticky.current);
  const switchRoom = !empty && (anyRemarks || remarksOn);
  const switchShown = variantHas || remarksOn;
  const titles = useCheckTitles();
  const titleOf = useCallback((id: string) => titles[id], [titles]);
  const remarks = useMemo(() => stageRemarks(slideIssues, titleOf), [slideIssues, titleOf]);
  const deckRemarks = issueMap.get(0)?.length ?? 0;
  const nextSlide = useMemo(() => nextFlagged(new Map([...issueMap].filter(([n]) => n >= 1)), selectedSlide, total), [issueMap, selectedSlide, total]);

  // the list and the slide point at each other: hover/focus (active), a frame clicked (picked), a row clicked (ping)
  const [activeIds, setActiveIds] = useState<string[]>([]);
  const [picked, setPicked] = useState<{ id: string; k: number } | null>(null);
  const [ping, setPing] = useState<{ id: string; k: number } | null>(null);
  useEffect(() => {
    setActiveIds([]);
    setPicked(null);
    setPing(null);
  }, [selectedSlide, variant.strategy]);
  const onActive = useCallback((ids: string[] | null) => setActiveIds((cur) => (ids === null ? (cur.length ? [] : cur) : ids)), []);
  const onPick = useCallback((id: string) => setPicked((p) => ({ id, k: (p?.k ?? 0) + 1 })), []);
  const onPing = useCallback((id: string) => setPing((p) => ({ id, k: (p?.k ?? 0) + 1 })), []);

  // the wishes stay per slide until a fix with them has been applied
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  // «Исправить слайд»: one run per deck; its outcome goes to a toast when the panel does not show it
  const view = useRef({ remarksOn, strategy: variant.strategy, slide: selectedSlide, detail });
  view.current = { remarksOn, strategy: variant.strategy, slide: selectedSlide, detail };
  const fix = useSlideFix(generation.id, (r: FixRun) => view.current.remarksOn && view.current.detail === null && r.strategy === view.current.strategy && r.slide === view.current.slide);
  const run = fix.run;
  const runHere = !!run && run.strategy === variant.strategy && run.slide === selectedSlide;
  const runWorking = !!run && (run.phase === "submitting" || run.phase === "running" || run.phase === "undoing");
  // the thumb keeps its spinner until the reloaded deck is in: it then pops straight out (never back to the count of
  // the remark just fixed)
  const runBusy = runWorking || (!!run && run.phase === "done" && !!run.result?.applied && !run.synced);
  const fixingLabel = !runHere
    ? null
    : run.phase === "submitting" || run.phase === "running" || (run.phase === "done" && !run.revealed)
      ? "Агент исправляет слайд"
      : run.phase === "undoing" || (run.phase === "undone" && !run.revealed)
        ? "Возвращаю как было"
        : null;
  const fixingIds = useMemo(() => (runHere && runWorking ? run.requested.map((r) => r.issue.id) : []), [runHere, runWorking, run]);
  const resolved = useMemo(() => {
    if (!runHere || run.phase !== "done" || !run.result?.applied || !run.revealed) return null;
    const fixed = new Set(run.result.fixed);
    return { key: String(run.at), marks: run.requested.filter((r) => fixed.has(r.issue.id)).map((r) => ({ n: r.n, box: r.boxes[0] ?? null })) };
  }, [runHere, run]);
  // the scan stops once a new image of the slide is on screen: the one shown when the job started does not count
  const shownImg = useRef<string | null>(null);
  const startImg = useRef<string | null>(null);
  useEffect(() => {
    if (run && (run.phase === "submitting" || run.phase === "undoing")) startImg.current = shownImg.current;
  }, [run?.phase]);
  const revealIfNew = () => {
    if (runHere && !run.revealed && (run.phase === "done" || run.phase === "undone") && shownImg.current !== startImg.current) fix.reveal();
  };
  useEffect(revealIfNew, [run?.phase, run?.revealed, runHere]);
  // after an applied fix the wishes of that slide have done their work
  useEffect(() => {
    if (run?.phase !== "done" || !run.result?.applied) return;
    const key = `${run.strategy}/${run.slide}`;
    setDrafts((d) => (d[key] ? { ...d, [key]: "" } : d));
  }, [run?.phase, run?.result, run?.strategy, run?.slide]);
  // a fallback, should the image never change
  useEffect(() => {
    if (!run || run.revealed || (run.phase !== "done" && run.phase !== "undone")) return;
    const t = window.setTimeout(fix.reveal, 4000);
    return () => window.clearTimeout(t);
  }, [run, fix.reveal]);
  // a settled run: seen on its slide it ends 1.5s after the person moves on; told elsewhere (banner) it ends after 8s
  useEffect(() => {
    if (!run || (run.phase !== "done" && run.phase !== "failed")) return;
    if (runHere && remarksOn) {
      if (!run.seen) fix.seen();
      return;
    }
    const t = window.setTimeout(fix.dismiss, run.seen ? 1500 : 8000);
    return () => window.clearTimeout(t);
  }, [run, runHere, remarksOn, fix.seen, fix.dismiss]);
  const showRun = () => {
    if (!run) return;
    if (run.strategy !== variant.strategy) {
      setActiveStrategy(run.strategy);
      requestAnimationFrame(() => setSelectedSlide(run.slide));
    } else setSelectedSlide(run.slide);
  };
  const draftKey = `${variant.strategy}/${selectedSlide}`;
  const canWish = generation.use_models !== false && health?.models_configured !== false;

  // The stage header spans the slide's width: the switch starts at the slide's left edge, ⤢ ends at its right edge. It
  // never lets the switch and the controls overlap. From the natural widths (remembered while each part is shown in
  // full, so the choice never flips back and forth): 0 all in full; 1 «Замечания» shows only its track and count; 2 the
  // variant switch also drops « · N сл.» (the count moves to the segment's tooltip). A slide narrower than that header
  // gets a header that much wider, centred on it, the same on every slide. Only a stage narrower still (the helper and
  // the remarks column both open at 1280) goes further: 3 the scores and ⤢ go (the slide itself opens full screen),
  // 4 the «3 / 10» too (the thumbnails show the slide).
  const header = useRef<HTMLDivElement>(null);
  const [squeeze, setSqueeze] = useState(0);
  const [hdrMin, setHdrMin] = useState(0);
  // until the switch has been shown: its full width and its track-and-count width with a one-digit count
  const natural = useRef({ seg: 0, segTight: 0, segBare: 0, chip: 148, chipIcon: 72, fixed: 0 });
  useLayoutEffect(() => {
    const h = header.current;
    if (!h) return;
    const run = () => {
      const seg = h.querySelector<HTMLElement>('[role="radiogroup"]');
      const chip = h.querySelector<HTMLElement>("[data-remarks]");
      const fixed = h.querySelector<HTMLElement>("[data-fixed]");
      const n = natural.current;
      if (seg && squeeze < 2) {
        n.seg = seg.offsetWidth;
        n.segTight = n.seg - [...seg.querySelectorAll<HTMLElement>("[data-count]")].reduce((sum, c) => sum + c.offsetWidth, 0);
      } else if (seg && squeeze < 3) n.segTight = seg.offsetWidth;
      // without the scores: each «77» and the 8px before it go
      if (seg && squeeze < 3) n.segBare = n.segTight - [...seg.querySelectorAll<HTMLElement>("[data-score]")].reduce((sum, c) => sum + c.offsetWidth + 8, 0);
      if (chip) {
        if (squeeze < 1) n.chip = chip.offsetWidth;
        else n.chipIcon = chip.offsetWidth;
      }
      if (fixed && squeeze < 3) n.fixed = fixed.offsetWidth;
      const fixedW = fixed ? n.fixed + 8 : 0;
      const icon = chip || anyRemarks ? n.chipIcon + 8 : 0;
      setHdrMin((seg ? n.segTight : 0) + fixedW + (fixed ? icon : 0));
      if (!seg) return setSqueeze(0);
      // a deck with remarks keeps the switch's room on every slide: the header looks the same throughout
      const room = h.clientWidth - fixedW - (chip || anyRemarks ? 8 : 0);
      let level = !chip
        ? n.seg + icon - 8 <= room ? 0 : 2
        : n.seg + n.chip <= room ? 0 : n.seg + n.chipIcon <= room ? 1 : 2;
      // the stage's own width (the header may grow up to it)
      const stage = h.parentElement ? h.parentElement.clientWidth - 32 : h.clientWidth;
      if (level === 2 && n.segTight + icon + fixedW > stage + 0.5) level = n.segBare + icon + fixedW - 44 <= stage + 0.5 ? 3 : 4;
      setSqueeze(level);
    };
    run();
    // the parts too: the web font arriving narrows the switch while the header keeps its width
    const ro = new ResizeObserver(run);
    ro.observe(h);
    h.querySelectorAll('[role="radiogroup"], [data-remarks], [data-fixed]').forEach((el) => ro.observe(el));
    let live = true;
    void document.fonts?.ready.then(() => live && run());
    return () => {
      live = false;
      ro.disconnect();
    };
  }, [squeeze, switchRoom, anyRemarks, countsDiffer, variant.strategy, generation.variants.length]);
  // the slide's width in CSS (the stage is a size container): right in the very commit that changes the layout, so a
  // helper or remarks toggle never shows the header at its old width for a frame
  const headerW = `max(${hdrMin}px, min(100cqw, (100cqh - ${STAGE_INNER}px) * ${aspect.toFixed(4)}))`;

  // «Структурный, оценка 100» for a screen reader, when every variant has its score
  const scored = generation.variants.every((v) => variantScore(v, generation.summary?.[v.strategy]?.score) !== null);
  const segments = generation.variants.map((v, i) => {
    const s = variantScore(v, generation.summary?.[v.strategy]?.score);
    const n = counts[i];
    const showCount = n === 0 || (countsDiffer && squeeze < 2);
    const showScore = s !== null && squeeze < 3;
    const hint = variantHint(v.strategy, strategies.find((x) => x.name === v.strategy)?.description);
    const hintScored = s !== null && !showScore ? `${hint} · оценка ${Math.round(s)}` : hint;
    return {
      key: v.strategy,
      label: strategyTitle(v.strategy),
      meta: !showScore && !showCount ? undefined : (
        <>
          {/* an error colours the score: the ring may still read «90» */}
          {showScore && <span data-score="" className={(errorsOf(v) ?? 0) > 0 ? "text-red-700" : scoreText(s)}>{Math.round(s)}</span>}
          {showCount && (
            <span data-count={n === 0 ? undefined : ""} className={n === 0 ? "text-red-700" : "text-zinc-500"}>
              {showScore ? " · " : ""}
              {n} сл.
            </span>
          )}
        </>
      ),
      title: countsDiffer && !showCount ? `${hintScored} · ${plural(n, "слайд", "слайда", "слайдов")}` : hintScored,
    };
  });

  // the newest deck built with the model: the live model state is about the same failure
  const latest = useMemo(() => {
    if (!generations.some((x) => x.id === generation.id)) return false;
    const t = generation.created_at ?? 0;
    return !generations.some((x) => x.id !== generation.id && x.use_models && x.status === "done" && (x.created_at ?? 0) > t);
  }, [generations, generation.id, generation.created_at]);
  // every model was marked paused a moment ago: a new build before the pause is over would get the same answer
  const retryIn = useRetryIn(modelStatus);
  // why the deck is thin, when it is: the model did not plan it (and why), a topic without theses, or a short text.
  // The rebuild button and the advice beside it follow the live model state, so they never disagree
  const notice = deckNotice(generation, variant, total, { status: modelStatus, latest, retryIn });
  const failed = !!generation.use_models && generation.planner?.by_model === false;
  useEffect(() => {
    if (failed) void refreshModelStatus();
  }, [failed, generation.id, refreshModelStatus]);
  const recheckIn = modelStatus?.state === "down" && modelStatus.retry_in ? Math.min(modelStatus.retry_in + 2, 600) : 0;
  useEffect(() => {
    if (!failed || !recheckIn) return;
    const t = window.setTimeout(() => void refreshModelStatus(), recheckIn * 1000);
    return () => window.clearTimeout(t);
  }, [failed, recheckIn, refreshModelStatus]);
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  // one rebuild at a time: a double click must not start two generations (each spends model requests)
  const inFlight = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const rebuild = async () => {
    if (inFlight.current) return;
    if (!generation.brief || !health?.models_configured) return setScreen("create");
    inFlight.current = true;
    setSubmitting(true);
    try {
      // the same inputs as the deck on screen, only the model gets another chance
      await startGeneration({
        template_id: generation.template_id,
        brief: generation.brief,
        audience: generation.audience ?? null,
        purpose: generation.purpose ?? null,
        slides: generation.slides ?? null,
        language: generation.language,
        extra_instructions: generation.extra_instructions ?? null,
        strategies: generation.strategies,
        use_models: true,
        audit_models: generation.audit_models ?? false,
        autofix: generation.autofix ?? true,
        exports: generation.exports ?? ["pdf", "html"],
      });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };
  const modelLabels = [generation.planner?.tried_label, generation.planner?.model_label].filter((x): x is string => !!x && x.length > 1);
  const noticeTitle = notice ? plainNotice(notice.title, modelLabels).replace(/\.\s*$/, "") : "";
  const noticeHelp = notice?.help ? plainNotice(cap(notice.help), modelLabels) : "";
  const noticeBasis = notice ? plainNotice(notice.basis, modelLabels) : "";
  const noticeBody = noticeHelp || noticeBasis;
  const noticeFull = [noticeBasis, noticeHelp].filter(Boolean).join(" ");
  const retryWaits = !!notice && notice.retryWait > 0;

  // the aside: the remarks workspace while the switch is on (with the helper open too), else the cards (helper closed).
  // The panel and the cards cross-fade (below). A hidden aside stays mounted (display: none): the quality ring keeps
  // its score instead of drawing from 0 again, and the cards still rise when it shows (a shown element restarts its
  // CSS animations)
  const panel = usePresence(remarksOn, MOTION.fast);
  const asideShown = remarksOn || panel.mounted || !agentOpen;
  const withPanel = panel.mounted;
  // the mode turns on with the helper closed: the cards fade out under the rising panel (never an empty column)
  const cards = usePresence(!remarksOn, MOTION.fast);
  const cardsLeaving = cards.leaving && withPanel && !agentOpen;
  // the mode turns off with the helper closed: the cards rise in under the fading panel (a still copy), then the live
  // cards take their place without a second entrance — the column is never empty either way
  const cardsArriving = panel.leaving && !agentOpen;
  const [wasArriving, setWasArriving] = useState(false);
  const [cardsSettle, setCardsSettle] = useState(false);
  if (cardsArriving !== wasArriving) {
    // derived in render (state, not a ref: the same under StrictMode's double render): the panel has just gone
    setWasArriving(cardsArriving);
    if (!cardsArriving && !withPanel) setCardsSettle(true);
  }
  useEffect(() => {
    if (!cardsSettle) return;
    const t = window.setTimeout(() => setCardsSettle(false), 500);
    return () => window.clearTimeout(t);
  }, [cardsSettle]);

  // «Почему так» gets every line the aside has left (the reasoning is what a person reads here), the links follow it:
  // one tight group, the space under it stays canvas and nothing scrolls
  const aside = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [whyLines, setWhyLines] = useState(4);
  useLayoutEffect(() => {
    const room = aside.current;
    const el = list.current;
    if (!room || !el || withPanel) return;
    const run = () => {
      const kids = ([...el.children] as HTMLElement[]).filter((k) => k.offsetHeight > 0 || k.hasAttribute("data-why"));
      const used = kids.filter((k) => !k.hasAttribute("data-why")).reduce((sum, k) => sum + k.offsetHeight, 0) + 12 * (kids.length - 1);
      const free = room.clientHeight - used - 68; // the why card without its text: p-4 twice, the 24px title, mt-3
      setWhyLines(Math.max(1, Math.min(12, Math.floor(free / 20))));
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(room);
    for (const k of el.children) if (!k.hasAttribute("data-why")) ro.observe(k);
    return () => ro.disconnect();
  }, [agentOpen, variant, !!why, withPanel, asideShown]);

  // a width-bound slide (a wide window, the helper open) caps the workspace at the slide's height: no bands above and
  // below the slide. In CSS from the deck's own width (a container): a measured width would be one commit late after
  // the helper or the remarks column toggles, and the slide would jump a second time in the middle of its glide. Not
  // while the helper and the remarks workspace are both open: the list gets the column's full height (it is not cut
  // while the page has room below), and the stage keeps its height through both toggles (only the slide glides)
  const capH = empty ? undefined : `calc((100cqw - ${asideShown ? ASIDE_W : 0}px - 32px) / ${aspect.toFixed(4)} + ${STAGE_CHROME}px)`;

  // the helper docks or the aside comes and goes: the page reflows once, the slide glides between its two sizes (a
  // translate + uniform scale, 300ms) and the thumbnails re-flow under a short fade instead of jumping
  const frameRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const layoutKey = `${agentOpen ? 1 : 0}${asideShown ? 1 : 0}`;
  useFlip(frameRef, layoutKey, { scale: true });
  // the header follows the slide's edges: its two ends glide with it
  const segRef = useRef<HTMLDivElement>(null);
  const ctrlRef = useRef<HTMLDivElement>(null);
  useFlip(segRef, layoutKey);
  useFlip(ctrlRef, layoutKey);
  // the remarks column stays through a helper toggle: it glides to its new place with the slide instead of teleporting
  useAsideGlide(aside, layoutKey);
  // the aside's cards change height with the slide (the reasoning) and the variant (the agent's summary): the cards
  // below glide to their new places and the «Почему так» surface glides to its new height
  const whyKey = `${variant.strategy}/${selectedSlide}/${rev}`;
  const agentBox = useRef<HTMLDivElement>(null);
  const whyBox = useRef<HTMLButtonElement>(null);
  const linksBox = useRef<HTMLDivElement>(null);
  useFlip(agentBox, variant.strategy);
  useFlip(whyBox, whyKey);
  useSurfaceGlide(whyBox, whyKey);
  useFlip(linksBox, whyKey);
  const firstLayout = useRef(true);
  const stageRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (firstLayout.current) {
      firstLayout.current = false;
      return;
    }
    if (prefersReducedMotion()) return;
    stripRef.current?.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 100, easing: EASE.inOut, fill: "backwards" });
    // the stage card stops clipping while the slide and the header glide from their old boxes: a slide that shrinks
    // into a narrower card is never cropped by it (it keeps its own rounded ring), the column arriving beside it paints
    // over it
    const stage = stageRef.current;
    if (!stage) return;
    stage.style.overflow = "visible";
    const t = window.setTimeout(() => (stage.style.overflow = ""), MOTION.slow + 20);
    return () => {
      window.clearTimeout(t);
      stage.style.overflow = "";
    };
  }, [layoutKey]);

  // the notice keeps its last words while it collapses
  const lastNotice = useRef(notice);
  if (notice) lastNotice.current = notice;
  const shownNotice = notice ?? lastNotice.current;

  // the aside's cards below the quality card; `live: false` is the still copy that fades out under the remarks panel
  const asideCards = (live: boolean) => (
    <>
      {/* empty:hidden: the card renders nothing for a deck the agent did not plan */}
      <div ref={live ? agentBox : undefined} className="shrink-0 empty:hidden">
        <AgentCard variant={variant} onOpen={() => open("agent")} />
      </div>
      {why && (
        <button ref={live ? whyBox : undefined} type="button" data-why={live ? "" : undefined} onClick={() => open("why")} className={WHY_CARD}>
          <span data-surface aria-hidden className="absolute inset-0 -z-10 origin-top rounded-2xl bg-white shadow-card transition-colors duration-150 group-hover:bg-zinc-50 group-active:bg-zinc-100" />
          <span className="flex items-center gap-2">
            <span className="text-title3 font-semibold text-zinc-900">Почему так</span>
            <CardChevron />
          </span>
          {/* the reasoning cross-fades per slide and variant; the card itself stays */}
          <span key={`${variant.strategy}/${selectedSlide}/${rev}`} className="mt-3 line-clamp-4 animate-fade text-footnote text-zinc-700 [text-wrap:pretty]" style={{ WebkitLineClamp: whyLines }} title={why}>
            {why}
          </span>
        </button>
      )}
      <div ref={live ? linksBox : undefined} className="grid shrink-0 grid-cols-3 gap-2">
        <DrawerLink icon={ListTree} label="План" onClick={() => open("plan")} />
        <DrawerLink icon={LayoutTemplate} label="Шаблон" onClick={() => open("template")} />
        <DrawerLink icon={FolderDown} label="Файлы" onClick={() => open("tech")} />
      </div>
    </>
  );

  const toggleRemarks = (v: boolean) => {
    setShowIssues(v);
    storage.set(KEY_ISSUES, v ? "1" : "0");
  };

  // mounted inside a View Transition: it is the entrance for its length (then the usual motion applies; a finished
  // animation never replays when the override goes)
  const [quiet, setQuiet] = useState(inViewTransition);
  useEffect(() => {
    if (!quiet) return;
    const t = window.setTimeout(() => setQuiet(false), 700);
    return () => window.clearTimeout(t);
  }, [quiet]);

  return (
    <div className={cn(ROOT, quiet && QUIET_ENTER)} style={{ containerType: "inline-size" }}>
      <div className="flex h-14 shrink-0 items-center gap-6">
        {/* vt-title: the build screen's «Готовлю презентацию» cross-fades in place into this title */}
        <div ref={titleBox} className="vt-title relative min-w-0 flex-1">
          <div aria-hidden className="pointer-events-none invisible absolute inset-0 overflow-hidden">
            <span ref={probe} className="absolute left-0 top-0 whitespace-nowrap font-display text-title1 font-bold tracking-tight">{title}</span>
          </div>
          <h1 className={cn(TITLE_FIT[titleStep], "font-bold tracking-tight text-zinc-900")} title={titleStep === 2 ? `${title}\n${meta}` : title}>
            {title}
          </h1>
          {titleStep < 2 && <p className="truncate text-footnote text-zinc-500" title={meta}>{meta}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {agentOpen ? (
            <Button variant="white" size="lg" icon={PenLine} aria-label="Изменить" title="Изменить текст или шаблон" onClick={() => setScreen("create")} />
          ) : (
            <Button variant="white" size="lg" icon={PenLine} onClick={() => setScreen("create")}>Изменить</Button>
          )}
          {/* the helper open: both secondary actions keep only their icons, the title keeps its room */}
          {pdf &&
            (agentOpen ? (
              <LinkButton variant="white" size="lg" icon={FileText} href={pdf} download={`${fileBase}.pdf`} aria-label="Скачать PDF" title="Скачать PDF" />
            ) : (
              <LinkButton variant="white" size="lg" icon={FileText} href={pdf} download={`${fileBase}.pdf`}>PDF</LinkButton>
            ))}
          {pptx && (
            <LinkButton variant="primary" size="lg" icon={Download} href={pptx} download={`${fileBase}.pptx`} title={`Вариант ${variantIdx} · ${variantName}`}>
              Скачать PowerPoint
            </LinkButton>
          )}
        </div>
      </div>

      {/* a notice that appears on the live screen grows in: the stage shrinks smoothly instead of jumping */}
      {/* the gap below the notice folds with it: it sits inside the clipped box, the -mb-4 takes back the column's gap */}
      <Collapse open={!!notice} className="-mb-4">
        <div className="pb-4">
          {shownNotice && (
            <Notice
              className="shrink-0"
              tone="warn"
              title={noticeTitle}
              action={
                shownNotice.retry || shownNotice.rewrite ? (
                  <>
                    {shownNotice.retry && (
                      // a disabled button shows no tooltip: the wrapper carries it while the model is overloaded
                      <span title={retryWaits ? "Модель перегружена — попробуйте через минуту" : undefined}>
                        <Button size="sm" variant="white" icon={RotateCcw} loading={submitting} disabled={jobRunning || retryWaits} onClick={() => void rebuild()} title={retryWaits ? undefined : "Собрать ту же презентацию заново"}>
                          Собрать ещё раз
                        </Button>
                      </span>
                    )}
                    {shownNotice.rewrite && <Button size="sm" variant="white" icon={PenLine} onClick={() => setScreen("create")}>Дописать текст</Button>}
                  </>
                ) : null
              }
            >
              {noticeBody && <span className="line-clamp-2" title={noticeFull}>{noticeBody}</span>}
            </Notice>
          )}
        </div>
      </Collapse>

      <div className={cn("grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-4", asideShown ? "grid-cols-[minmax(0,1fr)_288px]" : "grid-cols-1")} style={{ maxHeight: withPanel && agentOpen ? undefined : capH }}>
        {/* overflow-hidden at rest; while the slide glides between two sizes the card lets it show in full (above) */}
        <section ref={stageRef} aria-label="Просмотр слайдов" className="flex min-h-0 min-w-0 animate-fade flex-col gap-3 overflow-hidden rounded-2xl bg-white p-4 shadow-card" style={{ containerType: "size" }}>
          <div ref={header} className="mx-auto flex h-10 w-full shrink-0 items-center gap-2" style={{ maxWidth: headerW }}>
            {generation.variants.length > 1 && (
              <div ref={segRef} className="shrink-0" title={note ?? undefined}>
                <Segmented ariaLabel="Вариант оформления" metaLabel={scored ? "оценка" : undefined} items={segments} value={variant.strategy} onChange={setActiveStrategy} />
              </div>
            )}
            {!empty && (
              <SlideControls
                slide={selectedSlide}
                total={total}
                canZoom={!!src}
                compact={squeeze > 0}
                tight={squeeze >= 3 ? (squeeze >= 4 ? 2 : 1) : 0}
                rootRef={ctrlRef}
                onSelect={setSelectedSlide}
                onZoom={() => setZoom(true)}
                remarks={{ show: switchRoom, hidden: !switchShown, visible: remarksOn, count: variantStage.length, tone: remarkTone(variantStage), onToggle: toggleRemarks }}
              />
            )}
          </div>
          {empty ? (
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <EmptyState compact icon={ImageOff} title="В этом варианте нет слайдов" />
            </div>
          ) : (
            <>
              <VariantsSlidePreview
                src={src}
                slide={selectedSlide}
                headline={headline}
                aspect={aspect}
                onAspect={setNaturalAspect}
                onBox={(frame, well) => setBox((b) => (b.frame === frame && b.well === well ? b : { frame, well }))}
                onZoom={() => setZoom(true)}
                dir={slideDir}
                mode={slideMode}
                remarks={remarks}
                showRemarks={remarksOn}
                activeIds={activeIds}
                onActive={onActive}
                onPick={onPick}
                ping={ping}
                fixing={fixingLabel}
                fixingIds={fixingIds}
                resolved={resolved}
                onReady={(s) => {
                  shownImg.current = s;
                  revealIfNew();
                }}
                frameRef={frameRef}
              />
              <div ref={stripRef} className="flex shrink-0 flex-col">
                <SlideStrip
                  variant={variant}
                  rev={rev}
                  total={total}
                  selected={selectedSlide}
                  aspect={aspect}
                  frameWidth={box.frame}
                  issueMap={issueMap}
                  showRemarks={remarksOn}
                  fixingSlide={run && runBusy && run.strategy === variant.strategy ? run.slide : null}
                  onSelect={setSelectedSlide}
                />
              </div>
              <SlideLightbox open={zoom} src={src} slide={selectedSlide} total={total} headline={headline} aspect={aspect} remarks={remarks} showRemarks={remarksOn} onSelect={setSelectedSlide} onClose={() => setZoom(false)} />
            </>
          )}
        </section>

        <aside ref={aside} aria-label="О презентации" className={cn("vt-aside min-h-0 flex-col", asideShown ? "flex" : "hidden")}>
          {/* the cards that change per slide come last, so turning the slides never moves the others; the list scrolls
              only in a window too short for it (the p-1 keeps the focus rings and shadows unclipped) */}
          <div ref={list} className={cn("scroll-thin -m-1 flex min-h-0 flex-col gap-3 p-1", withPanel ? "flex-1 overflow-hidden" : cn("overflow-y-auto", ASIDE_STAGGER, cardsSettle && CARDS_SETTLE))}>
            <QualityCard variant={variant} score={score} errors={errors} onOpen={() => open("quality")} className="animate-rise" />
            {withPanel ? (
              <div className="relative flex min-h-0 flex-1 flex-col">
                {cardsLeaving && (
                  <div aria-hidden {...({ inert: "" } as Record<string, string>)} className="pointer-events-none absolute inset-x-0 top-0 flex animate-fade-out flex-col gap-3 rm-fade-out [&_*]:!animate-none">
                    {asideCards(false)}
                  </div>
                )}
                {cardsArriving && (
                  <div aria-hidden {...({ inert: "" } as Record<string, string>)} className="pointer-events-none absolute inset-x-0 top-0 flex animate-rise flex-col gap-3 [animation-duration:120ms] [&_*]:!animate-none">
                    {asideCards(false)}
                  </div>
                )}
                <RemarksPanel
                  slide={selectedSlide}
                  strategy={variant.strategy}
                  remarks={remarks}
                  deckRemarks={deckRemarks}
                  nextSlide={nextSlide}
                  activeIds={activeIds}
                  onActive={onActive}
                  picked={picked}
                  onPing={onPing}
                  onGoto={setSelectedSlide}
                  onShowRun={showRun}
                  onOpenQuality={() => open("quality")}
                  fix={fix}
                  edits={variant.edits ?? []}
                  canWish={canWish}
                  busy={jobRunning}
                  wishes={drafts[draftKey] ?? ""}
                  onWishes={(v) => setDrafts((d) => ({ ...d, [draftKey]: v }))}
                  enter={agentOpen ? "slide" : "rise"}
                  leaving={panel.leaving}
                />
              </div>
            ) : (
              asideCards(true)
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

/** Mirrors the deck's layout block for block, so nothing jumps when the deck arrives. */
function DeckSkeleton() {
  return (
    <div className={ROOT} aria-busy aria-label="Загрузка презентации">
      <div className="flex h-14 shrink-0 items-center gap-6">
        <div className="min-w-0 flex-1">
          <div className="skeleton h-8 w-1/2" />
          <div className="skeleton mt-2 h-4 w-[30%]" />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="skeleton h-12 w-32 rounded-xl" />
          <div className="skeleton h-12 w-24 rounded-xl" />
          <div className="skeleton h-12 w-56 rounded-xl" />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_288px] grid-rows-[minmax(0,1fr)] gap-4">
        <div className="flex min-h-0 flex-col gap-3 rounded-2xl bg-white p-4 shadow-card">
          <div className="flex h-10 shrink-0 items-center justify-between">
            <div className="skeleton h-10 w-[400px] rounded-xl" />
            <div className="skeleton h-10 w-40 rounded-xl" />
          </div>
          <div className="skeleton min-h-0 flex-1 rounded-xl" />
          <div className="skeleton h-[72px] shrink-0 rounded-lg" />
        </div>
        <div className="flex min-h-0 flex-col gap-3">
          <div className="skeleton h-[76px] shrink-0 rounded-2xl" />
          <div className="skeleton h-[200px] shrink-0 rounded-2xl" />
          <div className="skeleton h-36 shrink-0 rounded-2xl" />
          <div className="skeleton h-10 shrink-0 rounded-xl" />
        </div>
      </div>
    </div>
  );
}

/** How long the finished build screen may wait for its deck (the list, the deck, the first slide) before it hands over
 *  anyway (the skeleton then covers the rest). */
const HANDOFF_WAIT = 4000;

export function ResultScreen() {
  const { generation, generationLoading, activeJob, activeVariant, setScreen } = useApp();
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  // build → result inside a View Transition: the build screen stays until the new deck is loaded and its first slide
  // decoded, so the transition goes from the build straight to the finished deck — never through an empty screen, a
  // skeleton or a slide still fading in («Готовлю презентацию» cross-fades into the title, the status column into the
  // aside)
  const [shownBuilding, setShownBuilding] = useState(building);
  const lastJob = useRef(activeJob);
  if (activeJob && activeJob.kind === "generate") lastJob.current = activeJob;
  // the deck on screen when the build started: the build's own deck is another one
  const startId = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (building) startId.current = generation?.id ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building]);
  const handing = shownBuilding && !building;
  const built = handing && lastJob.current?.status === "done";
  const fresh = built && !!generation && !generationLoading && generation.id !== startId.current;
  const [waitedOut, setWaitedOut] = useState(false);
  const [decodedFor, setDecodedFor] = useState<string | null>(null);
  useEffect(() => {
    if (!handing) return void setWaitedOut(false);
    const t = window.setTimeout(() => setWaitedOut(true), HANDOFF_WAIT);
    return () => window.clearTimeout(t);
  }, [handing]);
  // the first slide the deck will show, decoded before the transition captures the deck
  const firstSrc = useMemo(() => {
    if (!fresh || !generation) return null;
    const v = (activeVariant && generation.variants.includes(activeVariant) ? activeVariant : null) ?? generation.variants[0];
    const raw = v?.slides[0];
    return raw ? withRev(raw, variantRev(v)) : null;
  }, [fresh, generation, activeVariant]);
  useEffect(() => {
    if (!fresh || !generation) return;
    const id = generation.id;
    let alive = true;
    const go = () => alive && setDecodedFor(id);
    const t = window.setTimeout(go, 800);
    (firstSrc ? decodeImage(firstSrc) : Promise.resolve()).then(go, go);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [fresh, generation, firstSrc]);
  useLayoutEffect(() => {
    if (building === shownBuilding) return;
    if (building) return viewTransition(() => setShownBuilding(true));
    // a failed build hands over at once; a finished one once its deck is ready (or after the wait)
    if (built && !waitedOut && !(fresh && decodedFor === generation?.id)) return;
    viewTransition(() => setShownBuilding(false));
  }, [building, shownBuilding, built, fresh, decodedFor, generation?.id, waitedOut]);
  // skeleton → deck as a true cross-fade: the deck renders under the skeleton, which fades out over it
  const skel = usePresence(!generation && generationLoading, MOTION.fast);

  if (shownBuilding && lastJob.current) return <BuildScreen job={lastJob.current} />;
  let body: JSX.Element | null;
  if (generation && generation.variants.length > 0) {
    // one Deck per generation: its measured widths and the natural aspect of the slides start afresh with another deck
    body = <Deck key={generation.id} generation={generation} />;
  } else if (generation) {
    body = (
      <div className="flex h-full items-center justify-center px-8 py-6">
        <EmptyState
          icon={FileText}
          title="Не получилось собрать презентацию"
          hint="Измените текст и соберите заново"
          action={<Button variant="primary" size="lg" onClick={() => setScreen("create")}>Вернуться к тексту</Button>}
        />
      </div>
    );
  } else if (!skel.mounted) {
    body = (
      <div className="flex h-full items-center justify-center px-8 py-6">
        <EmptyState
          icon={FileText}
          title="Здесь появится презентация"
          action={<Button variant="primary" size="lg" onClick={() => setScreen("create")}>Создать презентацию</Button>}
        />
      </div>
    );
  } else body = null;
  return (
    <div className="relative h-full">
      {body}
      {skel.mounted && (
        <div className={cn("absolute inset-0 z-10 bg-canvas", skel.leaving && "pointer-events-none animate-fade-out rm-fade-out")}>
          <DeckSkeleton />
        </div>
      )}
    </div>
  );
}
