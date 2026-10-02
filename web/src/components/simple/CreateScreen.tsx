// The first screen, a product page in one column: a badge, the big title with the brand gradient and one line on what
// the agent does; the composer (the field, examples that type themselves into it while it is empty, the toolbar with
// the template, a file, the sample, the slide count, «Настройки» and «Создать»); the line on the model; and the gallery
// of templates below. Once «Создать» has scrolled away a bar floats at the bottom with the template, the count and the
// same button. The draft survives reloads. Motion: the hero rises in a 40 ms cascade on first load, «Настройки» unfold
// inside the composer, the floating bar rises in and fades out, and the whole page glides aside when the helper docks.
import { useEffect, useRef, useState, type ChangeEvent, type FocusEvent, type FormEvent, type KeyboardEvent } from "react";
import { ArrowRight, ChevronDown, FileText, LayoutTemplate, Minus, Paperclip, PenLine, Plus, SlidersHorizontal, Sparkles } from "lucide-react";
import { MOTION, smoothScroll, stagger, useFlip, usePresence } from "../../lib/motion";
import { modelIndicator } from "../../lib/modelText";
import { errText } from "../../lib/narrate";
import { templateTitle } from "../../lib/plain";
import { cn, LS, plural, storage } from "../../lib/utils";
import { writerModeOf } from "../../lib/writerMode";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { BRIEF_MIN, BRIEF_MIN_TOPIC, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle } from "../NewGenerationFormParts";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { Composer } from "./Composer";
import { ModelStatus } from "./ModelStatus";
import { TemplateActions, TemplatePicker, useTemplateDrop } from "./TemplatePicker";
import { TypewriterHint } from "./Typewriter";

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Number.isFinite(n) ? Math.round(n) : SLIDES_DEFAULT));
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;
// the topic line only when the server writes a text by a topic itself (writer mode); else the text is the deck
const PLACEHOLDER_WRITER = "Тема — например, «История VK»: текст напишет агент.\nИли ваш текст с тезисами и цифрами — соберу строго по нему.";
const PLACEHOLDER = "Ваш текст: о чём презентация, тезисы и цифры — соберу строго по нему.\nМожно по слайдам: «Слайд 3. Расходы. Нужна круговая диаграмма».";

// A text that dictates its slides, by the backend's rules (planning/brief_structure.py, compile.py `_order`, agent.py
// `_is_cover`): «Слайд 1 … Слайд 5» headings in ascending order (or «1. … 3.» headings with lines under each, in a text
// that speaks of slides) give a slide each, plus a cover unless the first one is a cover or the text's own «на N
// слайдов» leaves no room for it; without headings «на 8 слайдов», «10 слайдов» give N.
const SPEC_HEAD = /^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*(\d{1,2})\s*(?:\*\*)?\s*(?:[.:)—–-]\s*|\s+|$)(.*?)\s*(?:\*\*)?\s*$/i;
const NUM_HEAD = /^\s*(?:#{1,6}\s*)?(\d{1,2})[.)]\s+(\S.{0,90})$/;
const COUNT = /(?:на|из|ровно|не более|не больше|максимум|до|в)\s+(\d{1,2})\s+слайд|(\d{1,2})\s+слайд(?:ов|а)(?![а-яё])|(\d{1,2})\s+slides?\b/i;
const COVER = /титул|обложк|заглавн|cover|title/i;
const TITLE_LINE = /^\s*(?:[—–\-•*]\s*)?(?:название|подзаголовок|заголовок|title|subtitle)\s*[:—–]/im;
const TABLE_LINE = /^\s*\|.*\|\s*$/m;

const words = (s: string) => s.split(/\s+/).filter(Boolean).length;

interface Head { at: number; n: number; title: string }

function specHeads(lines: string[], text: string): Head[] {
  const heads: Head[] = [];
  lines.forEach((line, at) => {
    const m = SPEC_HEAD.exec(line);
    if (m && words(m[2]) <= 14) heads.push({ at, n: Number(m[1]), title: m[2] });
  });
  if (heads.length >= 2 && heads.every((h, i) => i === 0 || h.n > heads[i - 1].n)) return heads;
  if (!/слайд|slide/i.test(text)) return [];
  const nums: Head[] = [];
  lines.forEach((line, at) => {
    const m = NUM_HEAD.exec(line);
    if (m && words(m[2]) <= 10 && !/[;,]\s*$/.test(m[2])) nums.push({ at, n: Number(m[1]), title: m[2] });
  });
  if (nums.length < 3 || nums.some((h, i) => h.n !== i + 1)) return [];
  const ends = [...nums.slice(1).map((h) => h.at), lines.length];
  return nums.every((h, i) => lines.slice(h.at + 1, ends[i]).some((l) => l.trim())) ? nums : [];
}

function dictatedSlides(text: string): number | null {
  const lines = text.split("\n");
  const c = COUNT.exec(text);
  const hard = c ? Number(c[1] ?? c[2] ?? c[3]) || null : null;
  const heads = specHeads(lines, text);
  if (heads.length === 0) return hard;
  // the first head is the cover when its title says so, or when it describes a title and a subtitle (not a table)
  const first = lines.slice(heads[0].at + 1, heads.length > 1 ? heads[1].at : lines.length).join("\n");
  const cover = COVER.test(heads[0].title) || (TITLE_LINE.test(first) && !TABLE_LINE.test(first));
  return heads.length + (!cover && (hard === null || heads.length < hard) ? 1 : 0);
}

interface Draft { brief: string; audience: string; purpose: string; slides: number }

function loadDraft(): Draft {
  try {
    const d = JSON.parse(storage.get(LS.brief) ?? "null") as Partial<Draft> | null;
    return {
      brief: typeof d?.brief === "string" ? d.brief : "",
      audience: typeof d?.audience === "string" ? d.audience : "",
      purpose: PURPOSES.some((p) => p.value === d?.purpose) ? (d?.purpose as string) : "product",
      slides: clampSlides(Number(d?.slides ?? SLIDES_DEFAULT)),
    };
  } catch {
    return { brief: "", audience: "", purpose: "product", slides: SLIDES_DEFAULT };
  }
}

// what a text for a deck looks like: the examples type themselves into the empty field (module constants: the
// typewriter restarts on a new array)
const EXAMPLES = [
  "Итоги квартала: выручка 1,2 млрд ₽ (+18 %), три ключевых проекта и планы на IV квартал",
  "Запуск продукта: проблема клиентов, решение, рынок 40 млрд ₽ и план на год",
  "Слайд 1. Титул. Слайд 2. Цели на 2027 год. Слайд 3. Бюджет — круговая диаграмма",
  "Стратегия продаж: воронка, конверсия 12 % → 18 %, найм пяти менеджеров",
];
const TOPIC_EXAMPLES = ["История VK — от социальной сети до экосистемы", ...EXAMPLES];

/** A template's cover in a small frame (the composer's chip, the floating bar). */
function MiniCover({ t, className }: { t: TemplateListItem | undefined; className?: string }) {
  const [broken, setBroken] = useState(false);
  return (
    <span className={cn("relative block shrink-0 overflow-hidden bg-zinc-100 ring-1 ring-inset ring-zinc-900/[0.06]", className)} aria-hidden>
      {t?.cover_url && !broken ? (
        <img src={t.cover_url} alt="" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-zinc-400"><LayoutTemplate className="h-3.5 w-3.5" /></span>
      )}
    </span>
  );
}

export function CreateScreen() {
  const { health, healthError, modelStatus, strategies, templates, templateId, activeJob, startGeneration, toast, agentOpen, composerText, takeComposerText } = useApp();
  // a server with a model in its config whose every link is off builds without one: the switches say so too
  const modelsConfigured = (health?.models_configured ?? false) && modelStatus?.state !== "off";
  const drop = useTemplateDrop();

  const [draft] = useState(loadDraft);
  const [brief, setBrief] = useState(draft.brief);
  const [audience, setAudience] = useState(draft.audience);
  const [purpose, setPurpose] = useState(draft.purpose);
  const [slides, setSlides] = useState(draft.slides);
  // what the person is typing into the count (an empty field stays empty until they leave it)
  const [slidesDraft, setSlidesDraft] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [useModels, setUseModels] = useState(modelsConfigured);
  const [auditModels, setAuditModels] = useState(false);
  const [more, setMore] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [focused, setFocused] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const floatRef = useRef<HTMLDivElement>(null);
  const galleryRef = useRef<HTMLElement>(null);
  const purposeRef = useRef<HTMLDivElement>(null);
  // the helper docks (or leaves) in one reflow: the centred page glides the 180px instead of jumping
  const pageRef = useRef<HTMLDivElement>(null);
  useFlip(pageRef, agentOpen);
  // the last input was the pointer (a click moves the focus itself; only the keyboard's focus is scrolled clear)
  const byPointer = useRef(false);
  useEffect(() => {
    const pointer = () => void (byPointer.current = true);
    const key = () => void (byPointer.current = false);
    window.addEventListener("pointerdown", pointer, true);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("pointerdown", pointer, true);
      window.removeEventListener("keydown", key, true);
    };
  }, []);
  // what is missing shakes once when «Создать» is pressed: the gallery (no template) or the composer (the text)
  const [shaking, setShaking] = useState<"gallery" | "composer" | null>(null);
  useEffect(() => {
    if (!shaking) return;
    const t = window.setTimeout(() => setShaking(null), 420);
    return () => window.clearTimeout(t);
  }, [shaking]);
  // the hero cascades in once, on the first load (a later return to this screen comes through the view transition)
  const [intro] = useState(() => performance.now() < 4000);

  useEffect(() => {
    const t = window.setTimeout(() => storage.set(LS.brief, JSON.stringify({ brief, audience, purpose, slides } satisfies Draft)), 300);
    return () => window.clearTimeout(t);
  }, [brief, audience, purpose, slides]);

  // «Изменить» on the agent's text (the result's sheet, the plan): the text replaces the draft once, the field takes the
  // focus and comes into view
  useEffect(() => {
    if (composerText === null) return;
    setBrief(composerText);
    setShowErrors(false);
    takeComposerText();
    requestAnimationFrame(() => {
      const el = briefRef.current;
      if (!el) return;
      el.focus({ preventScroll: true });
      el.setSelectionRange(0, 0);
      el.scrollTop = 0;
      el.scrollIntoView({ block: "center", behavior: smoothScroll() });
    });
  }, [composerText, takeComposerText]);

  // «Создать» has scrolled away (the gallery is in view): the bar floats at the bottom
  const [away, setAway] = useState(false);
  useEffect(() => {
    const el = toolbarRef.current;
    const root = el?.closest("main");
    if (!el || !root) return;
    const io = new IntersectionObserver(([e]) => setAway(!e.isIntersecting && e.boundingClientRect.bottom <= (e.rootBounds?.top ?? 0) + 1), { root, threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const float = usePresence(away, MOTION.fast);

  // a text that dictates its slides fixes the count: the stepper shows it, locked, and the request sends that number
  // (the backend builds the text's slides whatever the count, and the count keeps a closing slide out)
  const dictated = dictatedSlides(brief);
  const byText = dictated !== null;
  const stepSlides = (delta: number) => {
    setSlidesDraft(null);
    setSlides((n) => clampSlides(n + delta));
  };
  const count = dictated ?? clampSlides(slides);

  const strategiesTouched = useRef(false);
  const modelsTouched = useRef(false);
  useEffect(() => {
    if (!strategiesTouched.current) setSelected(strategies.map((s) => s.name));
  }, [strategies]);
  useEffect(() => {
    if (!modelsTouched.current) setUseModels(modelsConfigured);
  }, [modelsConfigured]);

  const chosen = templates.find((t) => t.template_id === templateId);
  const chosenName = chosen ? templateTitle(chosen.source_file, chosen.template_id) : null;
  const briefLen = brief.trim().length;
  // a topic-only text is enough only when the server writes the text itself (writer mode); otherwise the text is the deck
  const briefMin = health?.writer ? BRIEF_MIN_TOPIC : BRIEF_MIN;
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const problem = healthError
    ? "Нет связи с сервером"
    : !templateId
      ? "Выберите или загрузите шаблон"
      : briefLen === 0
        ? "Напишите, о чём презентация"
        : briefLen < briefMin
          ? "Текст слишком короткий"
          : selected.length === 0
            ? "Выберите хотя бы один вариант оформления"
            : null;
  const busy = submitting || jobRunning;
  // the server being out of reach is the one problem then: the text is not marked
  const briefInvalid = showErrors && !healthError && !!templateId && briefLen < briefMin;
  // a short text is said once, by its own counter in the field (turned red); the status line keeps every other problem
  const shortInvalid = briefInvalid && briefLen > 0;
  const barProblem = showErrors && !shortInvalid ? problem : null;
  // a topic without material: the agent writes the text first (the server decides; this only says it). Not for a text
  // about the person's own project («наш», «мы»), and not when no model can answer
  const writer = writerModeOf(brief);
  const modelsOn = useModels && modelsConfigured;
  const writerLine = !!health?.writer && !!writer.mode && !writer.privateHint && briefLen >= briefMin && modelsOn && !modelIndicator(modelStatus, modelsOn) && !healthError && !barProblem;
  const writerPresence = usePresence(writerLine, MOTION.fast);
  // the examples type themselves into an empty field nobody is typing in
  const hinting = briefLen === 0 && !focused && !busy;

  const fillSample = () => {
    setBrief(SAMPLE_BRIEF);
    if (!audience.trim()) setAudience(SAMPLE_AUDIENCE);
    setPurpose("feature");
    setShowErrors(false);
    briefRef.current?.focus();
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/\.(md|txt|markdown)$/i.test(file.name)) return toast("error", "Нужен текстовый файл .txt или .md");
    if (file.size > MAX_BRIEF_BYTES) return toast("error", "Файл больше 2 МБ");
    try {
      const text = (await file.text()).replace(/\r\n/g, "\n").trim();
      if (!text) return toast("error", `Файл «${file.name}» пустой`);
      setBrief(text);
    } catch (err) {
      toast("error", `Не удалось прочитать «${file.name}»: ${errText(err)}`);
    }
  };

  const toGallery = () => galleryRef.current?.scrollIntoView({ block: "start", behavior: smoothScroll() });

  // a control reached with the keyboard never hides under the floating bar: the page scrolls it clear (a click needs no
  // help — the person sees what they click)
  const keepClearOfBar = (e: FocusEvent<HTMLFormElement>) => {
    const el = e.target as HTMLElement;
    if (floatRef.current?.contains(el) || byPointer.current) return;
    scrollClearOfBar(el);
  };
  const scrollClearOfBar = (el: HTMLElement) => {
    const main = el.closest("main");
    if (!main) return;
    // a hidden checkbox inside a card (a strategy option): the card is what the person sees focused
    const seen = el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio") ? (el.closest("label") ?? el) : el;
    requestAnimationFrame(() => {
      const bar = floatRef.current;
      if (!bar || document.activeElement !== el) return;
      const t = seen.getBoundingClientRect();
      const b = bar.getBoundingClientRect();
      // never past the element's own top (a tall text field stays readable from its first line)
      const by = Math.min(t.bottom - b.top + 16, t.top - main.getBoundingClientRect().top - 16);
      if (t.bottom > b.top - 8 && by > 0) main.scrollBy({ top: by, behavior: smoothScroll() });
    });
  };

  // «Тип презентации» is one radio group: one Tab stop, the arrows move and choose
  const onPurposeKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = PURPOSES.length;
    const i = Math.max(0, PURPOSES.findIndex((p) => p.value === purpose));
    const next = { ArrowRight: (i + 1) % n, ArrowDown: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    setPurpose(PURPOSES[next].value);
    purposeRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (problem || busy || !templateId) {
      if (busy || healthError) return;
      if (!templateId) {
        setShaking("gallery");
        toGallery();
      } else {
        if (briefLen < briefMin) {
          setShaking("composer");
          const el = briefRef.current;
          if (el) {
            el.focus({ preventScroll: true });
            el.closest("[data-composer]")?.scrollIntoView({ block: "nearest", behavior: smoothScroll() });
          }
        } else if (selected.length === 0) {
          setShaking("composer");
          setMore(true);
        }
      }
      return;
    }
    setSubmitting(true);
    try {
      await startGeneration({
        template_id: templateId,
        brief: brief.trim(),
        audience: audience.trim() || null,
        purpose,
        slides: count,
        strategies: strategies.length ? strategies.map((s) => s.name).filter((n) => selected.includes(n)) : selected,
        use_models: useModels && modelsConfigured,
        audit_models: auditModels && modelsConfigured,
        autofix: true,
        exports: ["pdf", "html"],
      });
    } finally {
      setSubmitting(false);
    }
  };

  const rise = (i: number) => (intro ? { className: "animate-rise", style: stagger(i) } : { className: undefined, style: undefined });

  const stepper = (
    <div className="flex shrink-0 items-center gap-2">
      <div
        className="inline-flex h-10 items-center rounded-full bg-zinc-100 transition-shadow duration-150 has-[input:focus]:shadow-selected"
        title={byText ? "Число слайдов задано в тексте" : undefined}
      >
        <Button variant="ghost" shape="circle" size="md" icon={Minus} aria-label="Меньше слайдов" disabled={busy || byText || slides <= SLIDES_MIN} onClick={() => stepSlides(-1)} />
        <input
          id="slides"
          type="number"
          inputMode="numeric"
          aria-label="Число слайдов"
          min={SLIDES_MIN}
          max={SLIDES_MAX}
          value={byText ? String(dictated) : (slidesDraft ?? String(slides))}
          readOnly={byText}
          disabled={busy}
          onChange={(e) => {
            if (byText) return;
            const raw = e.target.value;
            setSlidesDraft(raw);
            const n = Number(raw);
            if (raw && Number.isFinite(n)) setSlides(n);
          }}
          onBlur={() => {
            setSlidesDraft(null);
            setSlides((n) => clampSlides(n));
          }}
          className="w-8 bg-transparent text-center text-body font-semibold tabular-nums text-zinc-900 outline-none [appearance:textfield] disabled:opacity-40 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        <Button variant="ghost" shape="circle" size="md" icon={Plus} aria-label="Больше слайдов" disabled={busy || byText || slides >= SLIDES_MAX} onClick={() => stepSlides(1)} />
      </div>
      <span className="w-[66px] text-footnote text-zinc-500" aria-hidden>
        {byText ? "по тексту" : plural(count, "слайд", "слайда", "слайдов").replace(/^\d+\s/, "")}
      </span>
    </div>
  );

  const field = (
    <div className="flex gap-3 px-6 pt-6">
      <Sparkles className="mt-[3px] h-5 w-5 shrink-0 text-[#3858FF]" aria-hidden />
      <div className="relative min-w-0 flex-1">
        <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
        <textarea
          ref={briefRef}
          id="brief"
          aria-label="О чём презентация"
          aria-invalid={briefInvalid || undefined}
          aria-describedby={briefLen > 0 && briefLen < briefMin ? "brief-count" : undefined}
          value={brief}
          disabled={busy}
          rows={4}
          onChange={(e) => setBrief(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={health?.writer ? PLACEHOLDER_WRITER : PLACEHOLDER}
          className={cn(
            "scroll-thin block max-h-[40vh] min-h-[104px] w-full resize-none bg-transparent pb-2 text-title3 leading-[26px] text-zinc-900 outline-none disabled:opacity-60 [field-sizing:content]",
            hinting ? "placeholder:text-transparent" : "placeholder:text-zinc-400",
          )}
        />
        {/* the examples type themselves over the empty field (the real placeholder stays for screen readers) */}
        <TypewriterHint lines={health?.writer ? TOPIC_EXAMPLES : EXAMPLES} active={hinting} className="absolute inset-x-0 top-0 text-title3 leading-[26px] text-zinc-400" />
        {briefLen > 0 && briefLen < briefMin && (
          <span
            id="brief-count"
            className={cn(
              "pointer-events-none absolute bottom-0 right-0 text-caption font-semibold tabular-nums transition-colors duration-150 animate-fade",
              shortInvalid ? "text-red-600" : "text-amber-700",
            )}
          >
            ещё {briefMin - briefLen}
          </span>
        )}
        {/* read out once when «Создать» finds the text short (the counter itself changes with every key) */}
        {shortInvalid && <span role="alert" className="sr-only">Текст слишком короткий</span>}
      </div>
    </div>
  );

  const toolbar = (
    <>
      <button
        type="button"
        onClick={toGallery}
        disabled={busy}
        title={chosenName ? `Шаблон «${chosenName}» — выбрать другой` : "Выбрать шаблон"}
        className="tap-soft group inline-flex h-10 max-w-[260px] shrink-0 cursor-pointer items-center gap-2 rounded-full bg-zinc-100 pl-1.5 pr-3 text-footnote font-semibold text-zinc-800 hover:bg-zinc-200/70 active:bg-zinc-200 disabled:pointer-events-none disabled:opacity-40"
      >
        <MiniCover t={chosen} className="h-7 w-12 rounded-full" />
        <span className="min-w-0 truncate">{chosenName ?? "Выберите шаблон"}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-zinc-500 transition-transform duration-150 group-hover:translate-y-px" aria-hidden />
      </button>
      <Button size="md" variant="ghost" icon={Paperclip} disabled={busy} onClick={() => fileRef.current?.click()} title="Текст из файла .txt или .md">
        Файл
      </Button>
      {briefLen === 0 && (
        <Button size="md" variant="ghost" icon={FileText} disabled={busy} onClick={fillSample} className="animate-fade">
          Пример
        </Button>
      )}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {stepper}
        <Button variant="ghost" shape="circle" size="md" icon={SlidersHorizontal} aria-label="Настройки" title="Настройки" aria-expanded={more} aria-controls="create-settings" onClick={() => setMore(!more)} />
        <Button type="submit" variant="brand" shape="pill" size="lg" iconRight={ArrowRight} loading={busy}>
          Создать
        </Button>
      </div>
    </>
  );

  const settings = (
    <div className="space-y-6">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-6">
        <div>
          <label htmlFor="audience" className="mb-2 block text-footnote font-semibold text-zinc-700">Аудитория</label>
          <input id="audience" type="text" value={audience} disabled={busy} onChange={(e) => setAudience(e.target.value)} placeholder="Руководство, инвесторы, команда" className={INPUT_CLS} />
        </div>
        <div>
          <p id="purpose-label" className="mb-2 text-footnote font-semibold text-zinc-700">Тип презентации</p>
          <div ref={purposeRef} className="flex flex-wrap gap-2" role="radiogroup" aria-labelledby="purpose-label" onKeyDown={onPurposeKey}>
            {PURPOSES.map((p) => (
              <Chip
                key={p.value}
                surface="tinted"
                role="radio"
                aria-checked={purpose === p.value}
                tabIndex={purpose === p.value ? 0 : -1}
                selected={purpose === p.value}
                disabled={busy}
                onClick={() => setPurpose(p.value)}
              >
                {p.label}
              </Chip>
            ))}
          </div>
        </div>
      </div>
      {strategies.length > 0 && (
        <div>
          <p className="mb-2 text-footnote font-semibold text-zinc-700">Варианты оформления</p>
          <div className="grid grid-cols-3 gap-3">
            {strategies.map((s) => (
              <StrategyOption
                key={s.name}
                strategy={s}
                checked={selected.includes(s.name)}
                disabled={busy}
                onChange={(on) => {
                  strategiesTouched.current = true;
                  setSelected((cur) => (on ? Array.from(new Set([...cur, s.name])) : cur.filter((x) => x !== s.name)));
                }}
              />
            ))}
          </div>
        </div>
      )}
      {/* the first switch lines up with the first strategy card; the second takes the rest of the row */}
      <div className="grid grid-cols-3 gap-3">
        <Toggle
          label="Тексты пишет модель"
          title={modelsConfigured ? undefined : "Модель не подключена"}
          checked={useModels && modelsConfigured}
          disabled={busy || !modelsConfigured}
          onChange={(v) => {
            modelsTouched.current = true;
            setUseModels(v);
          }}
        />
        <div className="col-span-2">
          <Toggle
            label="Проверка слайдов моделью зрения"
            title={modelsConfigured ? undefined : "Модель не подключена"}
            checked={auditModels && modelsConfigured}
            disabled={busy || !modelsConfigured}
            onChange={(v) => {
              modelsTouched.current = true;
              setAuditModels(v);
            }}
          />
        </div>
      </div>
    </div>
  );

  return (
    <form onSubmit={(e) => void onSubmit(e)} onFocus={keepClearOfBar} noValidate>
      {/* the bottom padding lets the last row of templates scroll clear of the floating bar */}
      <div ref={pageRef} className="mx-auto max-w-[1184px] px-8 pb-28 pt-12 [@media(max-height:760px)]:pt-7">
        <div className="mx-auto flex max-w-[880px] flex-col items-center text-center">
          <span {...rise(0)} className={cn("inline-flex h-8 items-center gap-2 rounded-full bg-white px-3 text-footnote font-semibold text-zinc-700 shadow-card", rise(0).className)}>
            <span className="h-2 w-2 rounded-full bg-brand" aria-hidden />
            Открытые модели · строго по вашему шаблону
          </span>
          <h1 {...rise(1)} className={cn("mt-5 text-hero font-bold text-zinc-900 [@media(max-height:760px)]:text-[52px] [@media(max-height:760px)]:leading-[56px]", rise(1).className)}>
            Презентация в стиле
            <br />
            <span className="text-brand">вашего шаблона</span>
          </h1>
          <p {...rise(2)} className={cn("mt-4 max-w-[640px] text-title3 leading-[26px] text-zinc-500 [text-wrap:balance]", rise(2).className)}>
            {health?.writer ? "Вставьте текст или просто тему" : "Вставьте текст с тезисами и цифрами"} — агент продумает слайды, соберёт их из макетов вашего шаблона и сверит каждое число. Три варианта в PowerPoint за 5 минут.
          </p>
        </div>

        <div data-composer className="mx-auto mt-8 max-w-[880px] [@media(max-height:760px)]:mt-6">
          <Composer
            {...rise(3)}
            className={rise(3).className}
            field={field}
            toolbar={toolbar}
            toolbarRef={toolbarRef}
            settings={settings}
            settingsOpen={more}
            settingsId="create-settings"
            invalid={briefInvalid}
            shake={shaking === "composer"}
          />
          {/* the problem, the model line and the writer's line share one spot: one cross-fades into the other */}
          <div className="mt-3 grid h-6 items-center justify-items-center [&>*]:col-start-1 [&>*]:row-start-1">
            {barProblem && (
              <p key={barProblem} role="alert" className="truncate text-footnote font-semibold text-red-600 animate-fade [animation-duration:150ms]" title={barProblem}>{barProblem}</p>
            )}
            <ModelStatus enabled={useModels && modelsConfigured} hidden={!!barProblem} className="min-w-0" />
            {writerPresence.mounted && (
              <span
                className={cn("inline-flex min-w-0 items-center gap-2 text-footnote text-zinc-500", writerPresence.leaving ? "animate-fade-out" : "animate-fade", "[animation-duration:150ms]")}
                role="status"
                aria-hidden={writerPresence.leaving || undefined}
              >
                <PenLine className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="truncate">Текст напишет агент</span>
              </span>
            )}
          </div>
        </div>

        <section
          ref={galleryRef}
          id="templates"
          {...drop}
          aria-labelledby="templates-title"
          className={cn("mt-14 scroll-mt-6", shaking === "gallery" ? "animate-shake" : rise(4).className)}
          style={shaking === "gallery" ? undefined : rise(4).style}
        >
          <div className="mb-5">
            <div className="flex h-10 items-center gap-4">
              <h2 id="templates-title" className="min-w-0 flex-1 truncate text-title1 font-bold text-zinc-900">Шаблон оформления</h2>
              <div className="-mr-4 flex shrink-0 items-center gap-2">
                <TemplateActions />
              </div>
            </div>
            <p className="mt-1 text-body text-zinc-500">Слайды собираются из макетов шаблона: его шрифты, цвета и сетка.</p>
          </div>
          <TemplatePicker />
        </section>
      </div>

      {/* the bar that floats once «Создать» has scrolled away: the very end of the scrolled content, of no height, stuck
          24px above the window's edge (at the end of a short page too) */}
      <div className="pointer-events-none sticky bottom-6 z-20 h-0">
        {float.mounted && (
          <div
            ref={floatRef}
            className={cn(
              "pointer-events-auto absolute bottom-0 left-1/2 flex h-16 -translate-x-1/2 items-center gap-3 rounded-full bg-white/90 py-2 pl-2 pr-2 shadow-float backdrop-blur-xl",
              float.leaving ? "animate-fade-out" : "animate-float-in",
            )}
            aria-hidden={float.leaving || undefined}
          >
            <MiniCover t={chosen} className="h-12 w-[84px] rounded-full" />
            <span className="max-w-[260px] min-w-0">
              <span className="block truncate text-footnote font-semibold text-zinc-900">{chosenName ? `Шаблон «${chosenName}»` : "Шаблон не выбран"}</span>
              <span className="block text-caption text-zinc-500">{plural(count, "слайд", "слайда", "слайдов")}{byText ? " — по тексту" : ""}</span>
            </span>
            <Button type="submit" variant="brand" shape="pill" size="lg" iconRight={ArrowRight} loading={busy} className="ml-3">
              Создать презентацию
            </Button>
          </div>
        )}
      </div>
    </form>
  );
}
