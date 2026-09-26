// The second screen: the deck as a fixed-height workspace (no page scroll). A title bar with the downloads, then the
// stage — the variant switch, the slide as large as the window allows, the thumbnails — and a narrow aside with the
// quality, the designer's reasoning, the agent and the ways into the drawer.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Download, FileText, FolderDown, ImageOff, LayoutTemplate, ListTree, PenLine, RotateCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { plainWords, variantsNote } from "../../lib/agent";
import { deckNotice } from "../../lib/modelText";
import { figuresLine } from "../../lib/narrate";
import { fileSafe, templateTitle, variantHint } from "../../lib/plain";
import { cn, fmtWhen, plural, storage } from "../../lib/utils";
import { useApp } from "../../store";
import type { DetailKey, Generation, Issue, Variant } from "../../types";
import { isMinor } from "../AuditHelpers";
import { BuildScreen } from "../BuildScreen";
import { Button, LinkButton } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Notice } from "../ui/Notice";
import { ScoreRing } from "../ui/ScoreRing";
import { Segmented } from "../ui/Segmented";
import { issuesBySlide, KEY_ISSUES, variantRev, variantScore, withRev } from "../VariantsHelpers";
import { SlideControls, VariantsSlidePreview } from "../VariantsSlidePreview";
import { AgentCard } from "./AgentPanel";
import { useRetryIn } from "./ModelStatus";
import { SlideLightbox } from "./SlideLightbox";
import { SlideStrip } from "./SlideStrip";

const NO_ISSUES: Issue[] = [];
/** The screen's container, shared with the build screen and the header row: the edges line up across screens. The left
 *  margin follows the window, not the main column, so the docked helper never moves the title off the logo's edge. */
const ROOT = "ml-[max(0px,calc((100vw-1600px)/2))] mr-auto flex h-full min-h-[600px] max-w-[1600px] flex-col gap-4 px-8 py-6";
const CARD = "group block w-full shrink-0 cursor-pointer rounded-2xl bg-white p-4 text-left shadow-card transition-colors duration-150 hover:bg-zinc-50 active:bg-zinc-100";
/** The stage around the well: p-4 twice, the 40px header, the 72px strip and two 12px gaps. */
const STAGE_CHROME = 168;
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

function CardChevron() {
  return <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />;
}

function DrawerLink({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-xl bg-white text-footnote font-semibold text-zinc-800 shadow-card transition-colors duration-150 hover:bg-zinc-50 active:bg-zinc-100"
    >
      <Icon className="h-4 w-4 shrink-0 text-zinc-500" aria-hidden />
      {label}
    </button>
  );
}

/** The quality card: the ring, one verdict and the figures checked against the text. Warnings get their own meta
 *  line: «1 предупреждение» (the word the remark tags and the drawer use) does not fit beside the verdict in 180px. */
function QualityCard({ variant, score, errors, onOpen }: { variant: Variant; score: number | null; errors: number | null; onOpen(): void }) {
  const warnings = variant.audit?.summary.warnings ?? 0;
  const figs = figuresLine(variant.audit?.summary.figures);
  const verdict = errors === null ? "Не проверено" : errors > 0 ? plural(errors, "ошибка", "ошибки", "ошибок") : "Ошибок нет";
  const warned = warnings > 0 ? plural(warnings, "предупреждение", "предупреждения", "предупреждений") : null;
  const second = figs ?? (errors ? { text: "Можно исправить автоматически", tone: "ok" as const, title: undefined } : null);
  return (
    <button type="button" onClick={onOpen} aria-label={`Качество: ${verdict}${warned ? ` · ${warned}` : ""}`} className={CARD}>
      <span className="flex items-center gap-3">
        {/* an error turns the ring red whatever the score («90» with one error would be green beside «1 ошибка») */}
        <ScoreRing score={score} size={44} stroke={4} tone={errors ? "error" : undefined} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1">
            <span className={cn("min-w-0 flex-1 text-body font-semibold", errors ? "text-red-600" : "text-zinc-900")}>{verdict}</span>
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

function Deck({ generation }: { generation: Generation }) {
  const { activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, strategies, manifest, setScreen, detail, setDetail, health, modelStatus, refreshModelStatus, startGeneration, activeJob, generations, agentOpen } = useApp();
  const variant = activeVariant ?? generation.variants[0];
  const total = slidesOf(variant);
  const empty = total === 0;
  const rev = variantRev(variant);
  const issueMap = useMemo(() => issuesBySlide(variant.audit, onStage), [variant.audit]);
  const slideIssues = issueMap.get(selectedSlide) ?? NO_ISSUES;
  const [showIssues, setShowIssues] = useState(() => storage.get(KEY_ISSUES) === "1");
  const [highlightId, setHighlightId] = useState<string | null>(null);
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

  // warm the cache with the neighbours: ← and → show the next slide at once
  useEffect(() => {
    for (const n of [selectedSlide + 1, selectedSlide - 1]) {
      const url = variant.slides[n - 1];
      if (url) new Image().src = withRev(url, rev);
    }
  }, [selectedSlide, variant, rev]);

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
  const hasChip = !empty && slideIssues.length > 0;
  // any slide of any variant with a remark: the header keeps room for the chip on every slide, so it never shifts
  const anyRemarks = useMemo(() => generation.variants.some((v) => (v.audit?.issues ?? []).some((i) => i.slide >= 1 && onStage(i))), [generation.variants]);

  // The stage header spans the slide's width: the switch starts at the slide's left edge, ⤢ ends at its right edge. It
  // never lets the switch and the controls overlap. From the natural widths (remembered while each part is shown in
  // full, so the choice never flips back and forth): 0 all in full; 1 «Замечания» shows only its icon and count; 2 the
  // switch also drops « · N сл.» (the count moves to the segment's tooltip). A slide narrower than the tightest header
  // (1280×720 with remarks in the deck) gets a header that much wider, centred on it, the same on every slide.
  const header = useRef<HTMLDivElement>(null);
  const [squeeze, setSqueeze] = useState(0);
  const [hdrMin, setHdrMin] = useState(0);
  // until the chip has been shown: its full width and its icon-and-count width with a one-digit count
  const natural = useRef({ seg: 0, segTight: 0, chip: 132, chipIcon: 56 });
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
      } else if (seg) n.segTight = seg.offsetWidth;
      if (chip) {
        if (squeeze < 1) n.chip = chip.offsetWidth;
        else n.chipIcon = chip.offsetWidth;
      }
      const fixedW = fixed ? fixed.offsetWidth + 8 : 0;
      setHdrMin((seg ? n.segTight : 0) + fixedW + (fixed && anyRemarks ? n.chipIcon + 8 : 0));
      if (!seg) return setSqueeze(0);
      // a deck with remarks keeps the chip's room on the slides without one: the switch looks the same on every slide
      const room = h.clientWidth - fixedW - (chip || anyRemarks ? 8 : 0);
      if (!chip) return setSqueeze(n.seg + (anyRemarks ? n.chipIcon : 0) <= room ? 0 : 2);
      setSqueeze(n.seg + n.chip <= room ? 0 : n.seg + n.chipIcon <= room ? 1 : 2);
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
  }, [squeeze, hasChip, anyRemarks, countsDiffer, variant.strategy, generation.variants.length]);
  const headerW = box.frame > 0 ? Math.max(box.frame, hdrMin) : undefined;

  // «Структурный, оценка 100» for a screen reader, when every variant has its score
  const scored = generation.variants.every((v) => variantScore(v, generation.summary?.[v.strategy]?.score) !== null);
  const segments = generation.variants.map((v, i) => {
    const s = variantScore(v, generation.summary?.[v.strategy]?.score);
    const n = counts[i];
    const showCount = n === 0 || (countsDiffer && squeeze < 2);
    const hint = variantHint(v.strategy, strategies.find((x) => x.name === v.strategy)?.description);
    return {
      key: v.strategy,
      label: strategyTitle(v.strategy),
      meta: (
        <>
          {/* an error colours the score: the ring may still read «90» */}
          {s !== null && <span className={(errorsOf(v) ?? 0) > 0 ? "text-red-700" : scoreText(s)}>{Math.round(s)}</span>}
          {showCount && (
            <span data-count={n === 0 ? undefined : ""} className={n === 0 ? "text-red-700" : "text-zinc-500"}>
              {s !== null ? " · " : ""}
              {n} сл.
            </span>
          )}
        </>
      ),
      title: countsDiffer && !showCount ? `${hint} · ${plural(n, "слайд", "слайда", "слайдов")}` : hint,
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

  // «Почему так» gets every line the aside has left (the reasoning is what a person reads here), the links follow it:
  // one tight group, the space under it stays canvas and nothing scrolls
  const aside = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [whyLines, setWhyLines] = useState(4);
  useLayoutEffect(() => {
    const room = aside.current;
    const el = list.current;
    if (!room || !el) return;
    const run = () => {
      const kids = [...el.children] as HTMLElement[];
      const used = kids.filter((k) => !k.hasAttribute("data-why")).reduce((sum, k) => sum + k.offsetHeight, 0) + 12 * (kids.length - 1);
      const free = room.clientHeight - used - 68; // the why card without its text: p-4 twice, the 24px title, mt-3
      setWhyLines(Math.max(1, Math.min(12, Math.floor(free / 20))));
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(room);
    for (const k of el.children) if (!k.hasAttribute("data-why")) ro.observe(k);
    return () => ro.disconnect();
  }, [agentOpen, variant, !!why]);

  // a width-bound slide (a wide window) caps the workspace at the slide's height: no bands above and below the slide
  const capH = !empty && box.well > 0 ? Math.ceil(box.well / aspect) + STAGE_CHROME : undefined;

  return (
    <div className={ROOT}>
      <div className="flex h-14 shrink-0 items-center gap-6">
        <div ref={titleBox} className="relative min-w-0 flex-1">
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

      {notice && (
        <Notice
          className="shrink-0 animate-fade"
          tone="warn"
          title={noticeTitle}
          action={
            notice.retry || notice.rewrite ? (
              <>
                {notice.retry && (
                  // a disabled button shows no tooltip: the wrapper carries it while the model is overloaded
                  <span title={retryWaits ? "Модель перегружена — попробуйте через минуту" : undefined}>
                    <Button size="sm" variant="white" icon={RotateCcw} loading={submitting} disabled={jobRunning || retryWaits} onClick={() => void rebuild()} title={retryWaits ? undefined : "Собрать ту же презентацию заново"}>
                      Собрать ещё раз
                    </Button>
                  </span>
                )}
                {notice.rewrite && <Button size="sm" variant="white" icon={PenLine} onClick={() => setScreen("create")}>Дописать текст</Button>}
              </>
            ) : null
          }
        >
          {noticeBody && <span className="line-clamp-2" title={noticeFull}>{noticeBody}</span>}
        </Notice>
      )}

      <div className={cn("grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-4", agentOpen ? "grid-cols-1" : "grid-cols-[minmax(0,1fr)_288px]")} style={{ maxHeight: capH }}>
        <section aria-label="Просмотр слайдов" className="flex min-h-0 min-w-0 flex-col gap-3 rounded-2xl bg-white p-4 shadow-card">
          <div ref={header} className="mx-auto flex h-10 w-full shrink-0 items-center gap-2" style={{ maxWidth: headerW }}>
            {generation.variants.length > 1 && (
              <div className="shrink-0" title={note ?? undefined}>
                <Segmented ariaLabel="Вариант оформления" metaLabel={scored ? "оценка" : undefined} items={segments} value={variant.strategy} onChange={setActiveStrategy} />
              </div>
            )}
            {!empty && (
              <SlideControls
                slide={selectedSlide}
                total={total}
                issues={slideIssues}
                showIssues={showIssues}
                canZoom={!!src}
                compact={squeeze > 0}
                onToggleIssues={(v) => {
                  setShowIssues(v);
                  storage.set(KEY_ISSUES, v ? "1" : "0");
                }}
                onSelect={setSelectedSlide}
                onZoom={() => setZoom(true)}
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
                issues={slideIssues}
                aspect={aspect}
                showIssues={showIssues}
                highlightId={highlightId}
                onHighlight={setHighlightId}
                onAspect={setNaturalAspect}
                onBox={(frame, well) => setBox((b) => (b.frame === frame && b.well === well ? b : { frame, well }))}
                onZoom={() => setZoom(true)}
                onOpenIssues={() => open("quality")}
              />
              <SlideStrip variant={variant} rev={rev} total={total} selected={selectedSlide} aspect={aspect} frameWidth={box.frame} issueMap={issueMap} onSelect={setSelectedSlide} />
              <SlideLightbox open={zoom} src={src} slide={selectedSlide} total={total} headline={headline} aspect={aspect} onSelect={setSelectedSlide} onClose={() => setZoom(false)} />
            </>
          )}
        </section>

        {!agentOpen && (
          <aside ref={aside} aria-label="О презентации" className="flex min-h-0 flex-col">
            {/* the cards that change per slide come last, so turning the slides never moves the others; the list scrolls
                only in a window too short for it (the p-1 keeps the focus rings and shadows unclipped) */}
            <div ref={list} className="scroll-thin -m-1 flex min-h-0 flex-col gap-3 overflow-y-auto p-1">
              <QualityCard variant={variant} score={score} errors={errors} onOpen={() => open("quality")} />
              <AgentCard variant={variant} onOpen={() => open("agent")} />
              {why && (
                <button type="button" data-why onClick={() => open("why")} className={CARD}>
                  <span className="flex items-center gap-2">
                    <span className="text-title3 font-semibold text-zinc-900">Почему так</span>
                    <CardChevron />
                  </span>
                  <span className="mt-3 line-clamp-4 text-footnote text-zinc-700 [text-wrap:pretty]" style={{ WebkitLineClamp: whyLines }} title={why}>
                    {why}
                  </span>
                </button>
              )}
              <div className="grid shrink-0 grid-cols-3 gap-2">
                <DrawerLink icon={ListTree} label="План" onClick={() => open("plan")} />
                <DrawerLink icon={LayoutTemplate} label="Шаблон" onClick={() => open("template")} />
                <DrawerLink icon={FolderDown} label="Файлы" onClick={() => open("tech")} />
              </div>
            </div>
          </aside>
        )}
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

export function ResultScreen() {
  const { generation, generationLoading, activeJob, setScreen } = useApp();
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  if (building && activeJob) return <BuildScreen job={activeJob} />;
  if (!generation) {
    if (generationLoading) return <DeckSkeleton />;
    return (
      <div className="flex h-full items-center justify-center px-8 py-6">
        <EmptyState
          icon={FileText}
          title="Здесь появится презентация"
          action={<Button variant="primary" size="lg" onClick={() => setScreen("create")}>Создать презентацию</Button>}
        />
      </div>
    );
  }
  if (generation.variants.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-8 py-6">
        <EmptyState
          icon={FileText}
          title="Не получилось собрать презентацию"
          hint="Измените текст и соберите заново"
          action={<Button variant="primary" size="lg" onClick={() => setScreen("create")}>Вернуться к тексту</Button>}
        />
      </div>
    );
  }
  // one Deck per generation: its measured widths and the natural aspect of the slides start afresh with another deck
  return <Deck key={generation.id} generation={generation} />;
}
