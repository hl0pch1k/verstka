// The first screen, a calm one-screen composer: ① choose a template, ② say what the deck is about, and a sticky bar
// with the slide count and the one «Создать презентацию». Everything else waits behind «Настройки». The draft
// survives reloads. Motion: the title, the two steps and the bar rise in a 40 ms cascade on first load, «Настройки»
// unfolds (rows glide, the content fades in after them), and the whole form glides aside when the helper docks.
import { useEffect, useRef, useState, type ChangeEvent, type FocusEvent, type FormEvent, type HTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, FileText, Minus, Paperclip, Plus, SlidersHorizontal } from "lucide-react";
import { smoothScroll, stagger, useFlip } from "../../lib/motion";
import { errText } from "../../lib/narrate";
import { cn, LS, storage } from "../../lib/utils";
import { useApp } from "../../store";
import { BRIEF_MIN, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle } from "../NewGenerationFormParts";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { ModelStatus } from "./ModelStatus";
import { TemplateActions, TemplatePicker, useTemplateDrop } from "./TemplatePicker";

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Number.isFinite(n) ? Math.round(n) : SLIDES_DEFAULT));
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;
const PLACEHOLDER =
  "Например: итоги пилота «Умные сводки» за квартал.\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты: время сократилось до 29 минут, NPS 64. Просим: бюджет 14,5 млн ₽ на масштабирование.";

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

/** `true` at once, `false` only once it has held for `ms`: switching templates reloads the template's analysis for a
 *  moment, and the step's check must not blink off and pop back in for that. */
function useHeldTrue(value: boolean, ms: number): boolean {
  const [held, setHeld] = useState(value);
  useEffect(() => {
    if (value) return void setHeld(true);
    const t = window.setTimeout(() => setHeld(false), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return value || held;
}

function Step({ n, title, done, actions, order, shake, zone, children }: {
  n: number;
  title: string;
  done: boolean;
  actions?: ReactNode;
  /** Place in the entrance cascade (40 ms steps). */
  order: number;
  shake: boolean;
  zone?: HTMLAttributes<HTMLElement>;
  children: ReactNode;
}) {
  // the card rises once; later a shake must not replay the entrance (a changed animation-name restarts it)
  const [entered, setEntered] = useState(false);
  return (
    <section
      {...zone}
      aria-labelledby={`step-${n}`}
      onAnimationEnd={(e) => e.target === e.currentTarget && setEntered(true)}
      className={cn("rounded-2xl bg-white p-6 shadow-card [@media(max-height:760px)]:py-5", shake ? "animate-shake" : !entered && "animate-rise")}
      style={shake || entered ? undefined : stagger(order)}
    >
      <div className="mb-4 flex h-9 items-center gap-3 [@media(max-height:760px)]:mb-3">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-body font-bold transition-colors duration-300",
            done ? "bg-accent-fill text-white" : "bg-accent-50 text-accent-700",
          )}
        >
          <span className="sr-only">{done ? `Шаг ${n} готов` : `Шаг ${n}`}</span>
          {done ? <Check key="done" className="h-4 w-4 animate-pop" strokeWidth={2.5} aria-hidden /> : <span aria-hidden>{n}</span>}
        </span>
        <h2 id={`step-${n}`} className="text-title2 font-bold text-zinc-900">{title}</h2>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function CreateScreen() {
  const { health, healthError, modelStatus, strategies, templateId, manifestLoading, activeJob, startGeneration, toast, agentOpen } = useApp();
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
  const fileRef = useRef<HTMLInputElement>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const purposeRef = useRef<HTMLDivElement>(null);
  // a template chosen and read; a switch to another template keeps the check unless its analysis takes a while
  const templateDone = useHeldTrue(!!templateId && !manifestLoading, 400) && !!templateId;
  // the helper docks (or leaves) in one reflow: the centred form glides the 180px instead of jumping
  const formRef = useRef<HTMLDivElement>(null);
  useFlip(formRef, agentOpen);
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
  // the step that is missing something shakes once when «Создать» is pressed
  const [shaking, setShaking] = useState<1 | 2 | null>(null);
  useEffect(() => {
    if (!shaking) return;
    const t = window.setTimeout(() => setShaking(null), 420);
    return () => window.clearTimeout(t);
  }, [shaking]);

  useEffect(() => {
    const t = window.setTimeout(() => storage.set(LS.brief, JSON.stringify({ brief, audience, purpose, slides } satisfies Draft)), 300);
    return () => window.clearTimeout(t);
  }, [brief, audience, purpose, slides]);

  // a text that dictates its slides fixes the count: the stepper shows it, locked, and the request sends that number
  // (the backend builds the text's slides whatever the count, and the count keeps a closing slide out)
  const dictated = dictatedSlides(brief);
  const byText = dictated !== null;
  const stepSlides = (delta: number) => {
    setSlidesDraft(null);
    setSlides((n) => clampSlides(n + delta));
  };

  const strategiesTouched = useRef(false);
  const modelsTouched = useRef(false);
  useEffect(() => {
    if (!strategiesTouched.current) setSelected(strategies.map((s) => s.name));
  }, [strategies]);
  useEffect(() => {
    if (!modelsTouched.current) setUseModels(modelsConfigured);
  }, [modelsConfigured]);

  const briefLen = brief.trim().length;
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const problem = healthError
    ? "Нет связи с сервером"
    : !templateId
      ? "Выберите или загрузите шаблон"
      : briefLen === 0
        ? "Напишите, о чём презентация"
        : briefLen < BRIEF_MIN
          ? "Текст слишком короткий"
          : selected.length === 0
            ? "Выберите хотя бы один вариант оформления"
            : null;
  const busy = submitting || jobRunning;
  // the server being out of reach is the one problem then: the text is not marked
  const briefInvalid = showErrors && !healthError && !!templateId && briefLen < BRIEF_MIN;
  // a short text is said once, by its own counter in the field (turned red); the bar keeps every other problem
  const shortInvalid = briefInvalid && briefLen > 0;
  const barProblem = showErrors && !shortInvalid ? problem : null;

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

  // a control reached with the keyboard never hides under the stuck bar: the page scrolls it clear (a click needs no
  // help — the person sees what they click)
  const keepClearOfBar = (e: FocusEvent<HTMLFormElement>) => {
    const el = e.target as HTMLElement;
    if (barRef.current?.contains(el) || byPointer.current) return;
    scrollClearOfBar(el);
  };
  const scrollClearOfBar = (el: HTMLElement) => {
    const main = el.closest("main");
    if (!main) return;
    // a hidden checkbox inside a card (a strategy option): the card is what the person sees focused
    const seen = el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio") ? (el.closest("label") ?? el) : el;
    requestAnimationFrame(() => {
      const bar = barRef.current;
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
      if (!templateId) setShaking(1);
      else {
        setShaking(2);
        if (briefLen < BRIEF_MIN && briefRef.current) {
          briefRef.current.focus();
          // the marked field comes clear of the bar after a click too (after a key, the focus handler has done it)
          if (byPointer.current) scrollClearOfBar(briefRef.current);
        }
        else if (selected.length === 0) setMore(true);
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
        slides: dictated ?? clampSlides(slides),
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

  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      onFocus={keepClearOfBar}
      noValidate
      className="px-8 pt-6 [@media(max-height:760px)]:pt-3"
    >
      {/* a short window (1280×720) tightens the rhythm by 48px, so «Настройки» clears the sticky bar on first load */}
      <div ref={formRef} className="mx-auto max-w-[980px]">
        <h1 className="mb-6 [@media(max-height:760px)]:mb-4 animate-rise text-center text-display font-bold tracking-tight text-zinc-900">Презентация в стиле вашего шаблона</h1>

        <Step n={1} title="Выберите шаблон" done={templateDone} actions={<TemplateActions />} order={1} shake={shaking === 1} zone={drop}>
          <TemplatePicker />
        </Step>

        <div className="mt-4 [@media(max-height:760px)]:mt-3">
          <Step
            n={2}
            title="О чём презентация"
            done={briefLen >= BRIEF_MIN}
            order={2}
            shake={shaking === 2}
            actions={
              <>
                {briefLen === 0 && (
                  <Button size="sm" variant="ghost" icon={FileText} disabled={busy} onClick={fillSample} className="animate-fade">
                    Пример
                  </Button>
                )}
                <Button size="sm" variant="ghost" icon={Paperclip} disabled={busy} onClick={() => fileRef.current?.click()} title="Текст из файла .txt или .md" className="-mr-3">
                  Файл
                </Button>
              </>
            }
          >
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
            <div
              className={cn(
                "relative rounded-xl bg-zinc-100 transition-[background-color,box-shadow] duration-150 has-[textarea:focus]:bg-white",
                briefInvalid ? "shadow-danger" : "has-[textarea:focus]:shadow-selected",
              )}
            >
              <textarea
                ref={briefRef}
                id="brief"
                aria-label="О чём презентация"
                aria-invalid={briefInvalid || undefined}
                aria-describedby={briefLen > 0 && briefLen < BRIEF_MIN ? "brief-count" : undefined}
                value={brief}
                disabled={busy}
                rows={3}
                onChange={(e) => setBrief(e.target.value)}
                placeholder={PLACEHOLDER}
                className="scroll-thin block max-h-[50vh] min-h-24 w-full resize-none scroll-py-3 bg-transparent px-4 py-3 text-body leading-6 text-zinc-900 outline-none placeholder:text-zinc-500 disabled:opacity-60 [field-sizing:content]"
              />
              {briefLen > 0 && briefLen < BRIEF_MIN && (
                <span
                  id="brief-count"
                  className={cn(
                    "pointer-events-none absolute bottom-2 right-4 text-caption font-semibold tabular-nums transition-colors duration-150 animate-fade",
                    shortInvalid ? "text-red-600" : "text-amber-700",
                  )}
                >
                  ещё {BRIEF_MIN - briefLen}
                </span>
              )}
              {/* read out once when «Создать» finds the text short (the counter itself changes with every key) */}
              {shortInvalid && <span role="alert" className="sr-only">Текст слишком короткий</span>}
            </div>

            <Button size="sm" variant="ghost" icon={SlidersHorizontal} aria-expanded={more} aria-controls="create-settings" onClick={() => setMore(!more)} className="-ml-3 mt-4 [@media(max-height:760px)]:mt-3">
              Настройки
              <ChevronDown className={cn("h-4 w-4 shrink-0 text-zinc-500 transition-transform duration-300 ease-glide", more && "rotate-180")} aria-hidden />
            </Button>
            {/* the settings unfold smoothly (the rows glide open, the panel fades in just after them, and fades out first
                on the way back); while folded they leave the tab order once the animation has played */}
            <div className={cn("grid transition-[grid-template-rows] duration-300 ease-glide", more ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
              <div id="create-settings" className="min-h-0 overflow-hidden" style={{ visibility: more ? "visible" : "hidden", transition: `visibility 0s linear ${more ? "0s" : "300ms"}` }}>
                <div className={cn("mt-4 space-y-6 rounded-xl bg-zinc-50 p-6 transition-opacity", more ? "opacity-100 delay-[60ms] duration-200 ease-out" : "opacity-0 duration-150 ease-in")}>
                  <div>
                    <label htmlFor="audience" className="mb-2 block text-footnote font-semibold text-zinc-700">Аудитория</label>
                    <input id="audience" type="text" value={audience} disabled={busy} onChange={(e) => setAudience(e.target.value)} placeholder="Руководство, инвесторы, команда" className={cn(INPUT_CLS, "max-w-[420px]")} />
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
              </div>
            </div>
          </Step>
        </div>

        {/* the stuck bar floats 16px over the window edge; the strip under it is painted, so nothing scrolls through.
            Its controls are always in view: the page's bottom scroll padding (kept for the form above it) must not nudge
            the page when one of them takes the focus */}
        <div className="sticky bottom-0 z-10 mt-4 pb-4 [background:linear-gradient(to_top,theme(colors.canvas)_16px,transparent_16px)] [&_button]:-scroll-mb-24 [&_input]:-scroll-mb-24">
          <div ref={barRef} className="flex h-[72px] animate-rise items-center gap-4 rounded-2xl bg-white/90 px-6 shadow-pop backdrop-blur" style={stagger(3)}>
            <div className="flex shrink-0 items-center gap-3">
              <label htmlFor="slides" className="text-footnote text-zinc-500">Слайдов</label>
              <div
                className="inline-flex h-10 items-center rounded-full bg-zinc-100 transition-shadow duration-150 has-[input:focus]:shadow-selected"
                title={byText ? "Число слайдов задано в тексте" : undefined}
              >
                <Button variant="ghost" shape="circle" size="md" icon={Minus} aria-label="Меньше слайдов" disabled={busy || byText || slides <= SLIDES_MIN} onClick={() => stepSlides(-1)} />
                <input
                  id="slides"
                  type="number"
                  inputMode="numeric"
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
                  className="w-10 bg-transparent text-center text-title3 font-semibold tabular-nums text-zinc-900 outline-none [appearance:textfield] disabled:opacity-40 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                />
                <Button variant="ghost" shape="circle" size="md" icon={Plus} aria-label="Больше слайдов" disabled={busy || byText || slides >= SLIDES_MAX} onClick={() => stepSlides(1)} />
              </div>
              {byText && <span className="text-caption text-zinc-500 animate-fade">по тексту</span>}
            </div>
            {/* the problem and the model line share one spot: one cross-fades into the other (150 ms), nothing moves */}
            <div className="grid min-w-0 flex-1 items-center [&>*]:col-start-1 [&>*]:row-start-1">
              {barProblem && (
                <p key={barProblem} role="alert" className="truncate text-footnote font-semibold text-red-600 animate-fade [animation-duration:150ms]" title={barProblem}>{barProblem}</p>
              )}
              <ModelStatus enabled={useModels && modelsConfigured} hidden={!!barProblem} className="min-w-0" />
            </div>
            <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} loading={busy}>
              Создать презентацию
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}
