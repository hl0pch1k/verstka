// The first screen: a new presentation in three steps, top to bottom — ① the template (the covers of the latest
// templates, every template in a window), ② the text (a large field; under it what the text holds: «В тексте:
// 6 слайдов, 14 чисел, 1 таблица»), ③ the parameters (folded into one line until opened: type, audience, slide count,
// variants, models — one three-column grid). A bar docked to the bottom of the window says in one line what will be
// built and holds «Создать презентацию», so the action is always in reach. The step to do now has its number in VK
// blue. The draft survives reloads. Motion only where something changes: a step that is missing something shakes once
// when «Создать» is pressed, the parameters unfold, a step's number turns into a check when the step gets done.
import { useEffect, useRef, useState, type ChangeEvent, type FocusEvent, type FormEvent, type HTMLAttributes, type ReactNode } from "react";
import { AlertCircle, ArrowRight, Check, ChevronDown, FileText, Minus, Paperclip, PenLine, Plus } from "lucide-react";
import { MOTION, smoothScroll, useFlip, usePresence } from "../../lib/motion";
import { modelIndicator } from "../../lib/modelText";
import { errText } from "../../lib/narrate";
import { tplLabel } from "../../lib/plain";
import { factsLine, textFacts } from "../../lib/textFacts";
import { cn, LS, plural, storage } from "../../lib/utils";
import { writerModeOf } from "../../lib/writerMode";
import { useApp } from "../../store";
import { BRIEF_MIN, BRIEF_MIN_TOPIC, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle } from "../NewGenerationFormParts";
import { Button } from "../ui/Button";
import { ModelStatus } from "./ModelStatus";
import { TemplatePicker, TemplateUploadButton, useTemplateDrop } from "./TemplatePicker";

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Number.isFinite(n) ? Math.round(n) : SLIDES_DEFAULT));
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;
// the topic line only when the server writes a text by a topic itself (writer mode); else the text is the deck
const PLACEHOLDER_WRITER = "Тема — например, «История VK»: текст напишет агент. Или ваш текст с тезисами и цифрами — слайды будут строго по нему…";
const PLACEHOLDER = "Тезисы, цифры и таблицы — слайды будут строго по ним. Можно по слайдам: «Слайд 3. Расходы. Нужна круговая диаграмма»…";

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

/** A step of the form: a white paper with its number and title and its own actions. The number says where the step
 *  is: done — a blue check on a light tint; the step to do now — white on VK blue; still ahead — grey. */
function Step({ n, title, done, current = false, actions, shake, zone, id, children }: {
  n: number;
  title: string;
  done: boolean;
  /** The step to do now (the first one not done): its number is filled. */
  current?: boolean;
  actions?: ReactNode;
  shake?: boolean;
  zone?: HTMLAttributes<HTMLElement>;
  id?: string;
  children?: ReactNode;
}) {
  // the check springs in when the step gets done while the person watches, not when the page opens with it done
  const was = useRef(done);
  const justDone = done && !was.current;
  if (!done) was.current = false;
  return (
    <section {...zone} id={id} aria-labelledby={`step-${n}`} className={cn("scroll-mt-6 rounded-2xl bg-white p-6 shadow-card", shake && "animate-shake")}>
      <div className="flex h-8 items-center gap-3">
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-footnote font-semibold tabular-nums transition-colors duration-200",
            done ? "bg-accent-50 text-accent-600" : current ? "bg-accent-fill text-white" : "bg-zinc-100 text-zinc-500",
          )}
        >
          <span className="sr-only">{done ? `Шаг ${n} готов` : current ? `Шаг ${n}, сейчас` : `Шаг ${n}`}</span>
          {done ? <Check key="done" className={cn("h-4 w-4", justDone && "animate-pop")} strokeWidth={2.75} aria-hidden /> : <span aria-hidden>{n}</span>}
        </span>
        <h2 id={`step-${n}`} className="text-title3 font-semibold text-zinc-900">{title}</h2>
        {actions && <div className="-mr-2 ml-auto flex min-w-0 items-center gap-1">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/** A − / + of the slide count: square, the field's own height, inside its frame (the frame clips the hover). */
function CountStep({ icon: Icon, label, disabled, onClick }: { icon: typeof Plus; label: string; disabled: boolean; onClick(): void }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="tap flex h-full w-10 shrink-0 cursor-pointer items-center justify-center text-zinc-700 hover:bg-zinc-900/[0.06] hover:text-zinc-900 active:bg-zinc-900/10 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
}

export function CreateScreen() {
  const { health, healthError, modelStatus, strategies, templates, templateId, manifestLoading, activeJob, startGeneration, toast, agentOpen, composerText, takeComposerText } = useApp();
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
  // a template chosen and read; a switch to another template keeps the check unless its analysis takes a while
  const templateDone = useHeldTrue(!!templateId && !manifestLoading, 400) && !!templateId;
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
  // the step that is missing something shakes once when «Создать» is pressed
  const [shaking, setShaking] = useState<1 | 2 | 3 | null>(null);
  useEffect(() => {
    if (!shaking) return;
    const t = window.setTimeout(() => setShaking(null), 420);
    return () => window.clearTimeout(t);
  }, [shaking]);

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

  // what the text holds: a text that dictates its slides fixes the count (the stepper shows it, locked, and the request
  // sends that number — the backend builds the text's slides whatever the count, and the count keeps a closing slide out)
  const facts = textFacts(brief);
  const dictated = facts.slides;
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
  const chosenName = chosen ? tplLabel(chosen) : null;
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
  // «Создать» spins only for its own work (sending, a deck being built); another job (a template being analysed) only
  // makes it unavailable for a moment
  const creating = submitting || (jobRunning && activeJob?.kind === "generate");
  // the server being out of reach is the one problem then: the text is not marked
  const briefInvalid = showErrors && !healthError && !!templateId && briefLen < briefMin;
  // a short text is said once, by its own counter under the field (turned red); the bar keeps every other problem
  const shortInvalid = briefInvalid && briefLen > 0;
  const barProblem = showErrors && !shortInvalid ? problem : null;
  // a topic without material: the agent writes the text first (the server decides; this only says it). Not for a text
  // about the person's own project («наш», «мы»), and not when no model can answer
  const writer = writerModeOf(brief);
  const modelsOn = useModels && modelsConfigured;
  const writerLine = !!health?.writer && !!writer.mode && !writer.privateHint && briefLen >= briefMin && modelsOn && !modelIndicator(modelStatus, modelsOn) && !healthError && !barProblem;
  const writerPresence = usePresence(writerLine, MOTION.fast);
  const variantsCount = strategies.length ? strategies.filter((s) => selected.includes(s.name)).length : selected.length;
  const purposeLabel = PURPOSES.find((p) => p.value === purpose)?.label ?? "";
  const slidesWord = plural(count, "слайд", "слайда", "слайдов");
  // the folded parameters in one line, in the order the bar says them: slides, variants, then the rest
  const paramsLine = [byText ? `${slidesWord} по тексту` : slidesWord, plural(variantsCount, "вариант", "варианта", "вариантов"), purposeLabel, modelsOn ? "тексты пишет модель" : "без модели"].join(" · ");
  // the bar's one line: what will be built
  const summary = [slidesWord, plural(variantsCount, "вариант", "варианта", "вариантов")].join(" · ");
  const seen = factsLine(facts);
  // «1 551 знак»: thousands apart, as the counters elsewhere
  const chars = (n: number) => plural(n, "знак", "знака", "знаков").replace(/^\d+/, n.toLocaleString("ru-RU"));
  const textDone = briefLen >= briefMin;

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

  // a control reached with the keyboard never hides under the bar: the page scrolls it clear (a click needs no help —
  // the person sees what they click)
  const keepClearOfBar = (e: FocusEvent<HTMLFormElement>) => {
    const el = e.target as HTMLElement;
    if (barRef.current?.contains(el) || byPointer.current) return;
    scrollClearOfBar(el);
  };
  const scrollClearOfBar = (el: HTMLElement) => {
    const main = el.closest("main");
    if (!main) return;
    // a hidden checkbox inside a card (a strategy option): the card is what the person sees focused
    const target = el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio") ? (el.closest("label") ?? el) : el;
    requestAnimationFrame(() => {
      const bar = barRef.current;
      if (!bar || document.activeElement !== el) return;
      const t = target.getBoundingClientRect();
      const b = bar.getBoundingClientRect();
      // never past the element's own top (a tall text field stays readable from its first line)
      const by = Math.min(t.bottom - b.top + 16, t.top - main.getBoundingClientRect().top - 16);
      if (t.bottom > b.top - 8 && by > 0) main.scrollBy({ top: by, behavior: smoothScroll() });
    });
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (problem || busy || !templateId) {
      if (busy || healthError) return;
      if (!templateId) {
        setShaking(1);
        document.getElementById("step-template")?.scrollIntoView({ block: "nearest", behavior: smoothScroll() });
      } else if (briefLen < briefMin) {
        setShaking(2);
        const el = briefRef.current;
        if (el) {
          el.focus({ preventScroll: true });
          document.getElementById("step-text")?.scrollIntoView({ block: "nearest", behavior: smoothScroll() });
        }
      } else if (selected.length === 0) {
        setShaking(3);
        setMore(true);
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

  return (
    <form onSubmit={(e) => void onSubmit(e)} onFocus={keepClearOfBar} noValidate className="flex min-h-full flex-col">
      <div ref={pageRef} className="mx-auto w-full max-w-[1120px] flex-1 px-8 pb-8 pt-6">
        <header className="mb-6">
          <h1 className="text-title1 font-semibold text-zinc-900">Новая презентация</h1>
          <p className="mt-1 text-body text-zinc-500">Шаблон задаёт оформление, текст — содержание. Агент соберёт три варианта и сверит каждое число с текстом.</p>
        </header>

        <div className="space-y-4">
          <Step id="step-template" n={1} title="Шаблон" done={templateDone} current={!templateDone} actions={<TemplateUploadButton />} shake={shaking === 1} zone={drop}>
            <div className="mt-5">
              <TemplatePicker />
            </div>
          </Step>

          <Step
            id="step-text"
            n={2}
            title="Текст"
            done={textDone}
            current={templateDone && !textDone}
            shake={shaking === 2}
            actions={
              <>
                <Button size="sm" variant="ghost" icon={Paperclip} disabled={busy} onClick={() => fileRef.current?.click()} title="Текст из файла .txt или .md">
                  Из файла
                </Button>
                {briefLen === 0 && (
                  <Button size="sm" variant="ghost" icon={FileText} disabled={busy} onClick={fillSample} className="animate-fade">
                    Пример
                  </Button>
                )}
              </>
            }
          >
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
            <div
              className={cn(
                "mt-5 rounded-lg border bg-white transition-[border-color,box-shadow] duration-150",
                briefInvalid
                  ? "border-red-500 shadow-[0_0_0_3px_rgba(242,55,65,0.12)]"
                  : "border-zinc-900/[0.12] hover:border-zinc-900/20 has-[textarea:focus]:border-accent has-[textarea:focus]:shadow-[0_0_0_3px_rgba(0,119,255,0.12)]",
              )}
            >
              <textarea
                ref={briefRef}
                id="brief"
                aria-label="Текст презентации"
                aria-invalid={briefInvalid || undefined}
                aria-describedby="brief-help"
                value={brief}
                disabled={busy}
                rows={6}
                onChange={(e) => setBrief(e.target.value)}
                placeholder={health?.writer ? PLACEHOLDER_WRITER : PLACEHOLDER}
                // as tall as its text (the page is the one scroller); a browser without field-sizing keeps six lines
                className="scroll-thin block min-h-[160px] w-full resize-none rounded-lg bg-transparent px-4 py-3 text-body leading-6 text-zinc-900 outline-none placeholder:text-zinc-400 disabled:opacity-60 [field-sizing:content]"
              />
            </div>
            {/* what the text holds (the agent will see the same) and its length */}
            <div id="brief-help" className="mt-2 flex min-h-5 items-start gap-4 text-footnote">
              <p className="min-w-0 flex-1 text-zinc-500">
                {briefLen === 0 ? "Вставьте готовый текст или загрузите .txt и .md" : seen ? `В тексте: ${seen}` : "Цифр и таблиц в тексте нет — слайды будут из формулировок"}
              </p>
              {briefLen > 0 && (
                <p className={cn("shrink-0 tabular-nums", briefLen < briefMin ? (shortInvalid ? "font-medium text-red-600" : "text-amber-700") : "text-zinc-500")}>
                  {briefLen < briefMin ? `ещё ${chars(briefMin - briefLen)}` : chars(briefLen)}
                </p>
              )}
            </div>
            {/* read out once when «Создать» finds the text short (the counter itself changes with every key) */}
            {shortInvalid && <span role="alert" className="sr-only">Текст слишком короткий</span>}
          </Step>

          <Step
            n={3}
            title="Параметры"
            done={false}
            current={templateDone && textDone}
            shake={shaking === 3}
            actions={
              <>
                {!more && <span className="mr-1 min-w-0 truncate text-footnote text-zinc-500">{paramsLine}</span>}
                <Button size="sm" variant="ghost" iconRight={<ChevronDown className={cn("transition-transform duration-200 ease-out", more && "rotate-180")} />} aria-expanded={more} aria-controls="create-settings" onClick={() => setMore(!more)}>
                  {more ? "Свернуть" : "Изменить"}
                </Button>
              </>
            }
          >
            {/* the parameters unfold (the rows glide open, the content fades in just after them, and fades out first on
                the way back); while folded they leave the tab order once the animation has played */}
            <div className={cn("grid transition-[grid-template-rows] duration-250 ease-glide", more ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
              <div id="create-settings" className="min-h-0 overflow-hidden" style={{ visibility: more ? "visible" : "hidden", transition: `visibility 0s linear ${more ? "0s" : "250ms"}` }}>
                <div className={cn("space-y-6 pt-5 transition-opacity", more ? "opacity-100 delay-[60ms] duration-200 ease-out" : "opacity-0 duration-150 ease-in")}>
                  {/* the rows share the panel's edges: the fields (the count only as wide as a count needs), the variants and the
                    switches */}
                  <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)_148px] gap-4">
                    <div>
                      <label htmlFor="purpose" className="mb-2 block text-footnote font-medium text-zinc-700">Тип презентации</label>
                      <div className="relative">
                        <select
                          id="purpose"
                          value={purpose}
                          disabled={busy}
                          onChange={(e) => setPurpose(e.target.value)}
                          className={cn(INPUT_CLS, "cursor-pointer appearance-none pr-10")}
                        >
                          {PURPOSES.map((p) => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" aria-hidden />
                      </div>
                    </div>
                    <div>
                      <label htmlFor="audience" className="mb-2 block text-footnote font-medium text-zinc-700">Аудитория</label>
                      <input id="audience" type="text" value={audience} disabled={busy} onChange={(e) => setAudience(e.target.value)} placeholder="Руководство, инвесторы, команда…" className={INPUT_CLS} />
                    </div>
                    <div>
                      <div className="mb-2 flex items-baseline justify-between gap-2">
                        <label htmlFor="slides" className="text-footnote font-medium text-zinc-700">Слайдов</label>
                        {byText && <span className="animate-fade text-caption text-zinc-500">задано в тексте</span>}
                      </div>
                      <div
                        className="flex h-10 items-stretch overflow-hidden rounded-lg border border-zinc-900/[0.12] bg-white transition-[border-color,box-shadow] duration-150 hover:border-zinc-900/20 has-[input:focus]:border-accent has-[input:focus]:shadow-[0_0_0_3px_rgba(0,119,255,0.12)]"
                        title={byText ? "Число слайдов задано в тексте" : undefined}
                      >
                        <CountStep icon={Minus} label="Меньше слайдов" disabled={busy || byText || slides <= SLIDES_MIN} onClick={() => stepSlides(-1)} />
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
                          className="min-w-0 flex-1 bg-transparent text-center text-body font-semibold tabular-nums text-zinc-900 outline-none [appearance:textfield] read-only:text-zinc-500 disabled:opacity-40 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                        />
                        <CountStep icon={Plus} label="Больше слайдов" disabled={busy || byText || slides >= SLIDES_MAX} onClick={() => stepSlides(1)} />
                      </div>
                    </div>
                  </div>
                  {strategies.length > 0 && (
                    <div>
                      <p className="mb-2 text-footnote font-medium text-zinc-700">Варианты оформления</p>
                      <div className="grid grid-cols-3 gap-4">
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
                  <div className="grid grid-cols-3 gap-4">
                    <Toggle
                      label="Модель пишет тексты слайдов"
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
                        label="Модель проверяет слайды по картинке"
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
      </div>

      {/* the bar docked to the bottom of the window, the page's width: what will be built in one line, the state of the
          request (a problem, the model, the writer) and the one action. Solid, with a hairline on top: the page scrolls
          under it, nothing shows through. Its controls are always in view: the page's bottom scroll padding (kept for the
          form above it) must not nudge the page when one of them takes the focus */}
      <div className="sticky bottom-0 z-10 bg-white shadow-[inset_0_1px_0_#E3E4E7] [&_button]:-scroll-mb-24 [&_input]:-scroll-mb-24">
        <div ref={barRef} className="mx-auto flex h-[72px] w-full max-w-[1120px] items-center gap-4 px-8">
          <p className="min-w-0 shrink truncate text-body text-zinc-500" title={chosenName ? `${chosenName} · ${summary}` : undefined}>
            <span className="font-medium text-zinc-900">{chosenName ?? "Шаблон не выбран"}</span>
            {chosenName && <span> · {summary}</span>}
          </p>
          {/* the problem, the model line and the writer's line share one spot: one cross-fades into the other */}
          <div className="grid min-w-0 flex-1 items-center justify-items-end [&>*]:col-start-1 [&>*]:row-start-1">
            {barProblem && (
              <p key={barProblem} role="alert" className="inline-flex min-w-0 items-center gap-1.5 text-footnote font-medium text-red-600 animate-fade [animation-duration:150ms]" title={barProblem}>
                <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
                <span className="truncate">{barProblem}</span>
              </p>
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
          <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} loading={creating} disabled={busy && !creating}>
            Создать презентацию
          </Button>
        </div>
      </div>
    </form>
  );
}
