// The first screen: ① choose a template, ② say what the deck is about, one button. Everything else (purpose,
// variants of layout, the model) waits behind «Дополнительные настройки». The draft survives reloads.
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, FileText, Minus, Paperclip, Plus, Presentation, ShieldCheck, Unlock } from "lucide-react";
import { errText } from "../../lib/narrate";
import { cn, LS, plural, storage } from "../../lib/utils";
import { useApp } from "../../store";
import { BRIEF_MIN, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle } from "../NewGenerationFormParts";
import { Button } from "../ui/Button";
import { TemplatePicker } from "./TemplatePicker";

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Number.isFinite(n) ? Math.round(n) : SLIDES_DEFAULT));
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;

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

function Step({ n, title, hint, done, delay, shake, children }: { n: number; title: string; hint: string; done: boolean; delay: number; shake: boolean; children: ReactNode }) {
  // the card rises once; later a shake must not replay the entrance (a changed animation-name restarts it)
  const [entered, setEntered] = useState(false);
  return (
    <section
      onAnimationEnd={(e) => e.target === e.currentTarget && setEntered(true)}
      className={cn("rounded-3xl bg-white p-7 shadow-card", shake ? "animate-shake" : !entered && "animate-rise")}
      style={shake || entered ? undefined : { animationDelay: `${delay}ms` }}
    >
      <div className="mb-5 flex items-start gap-4">
        <span
          className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[15px] font-bold transition-colors duration-300", done ? "bg-accent text-white" : "bg-accent-50 text-accent")}
          aria-label={done ? `Шаг ${n} готов` : `Шаг ${n}`}
        >
          {done ? <Check key="done" className="h-[18px] w-[18px] animate-pop" strokeWidth={3} aria-hidden /> : n}
        </span>
        <div>
          <h2 className="text-xl font-bold tracking-tight text-zinc-900">{title}</h2>
          <p className="mt-0.5 text-sm text-zinc-500">{hint}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export function CreateScreen() {
  const { health, healthError, strategies, templateId, manifestLoading, activeJob, startGeneration, toast } = useApp();
  const modelsConfigured = health?.models_configured ?? false;

  const [draft] = useState(loadDraft);
  const [brief, setBrief] = useState(draft.brief);
  const [audience, setAudience] = useState(draft.audience);
  const [purpose, setPurpose] = useState(draft.purpose);
  const [slides, setSlides] = useState(draft.slides);
  const [selected, setSelected] = useState<string[]>([]);
  const [useModels, setUseModels] = useState(modelsConfigured);
  const [auditModels, setAuditModels] = useState(false);
  const [more, setMore] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);
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
    ? "Нет связи с сервером — подождите, интерфейс переподключится сам"
    : !templateId
      ? "Выберите или загрузите шаблон"
      : briefLen === 0
        ? "Напишите, о чём презентация"
        : briefLen < BRIEF_MIN
          ? `Текст слишком короткий: нужно хотя бы ${BRIEF_MIN} символов`
          : selected.length === 0
            ? "Выберите хотя бы один вариант оформления"
            : null;
  const busy = submitting || jobRunning;

  const fillSample = () => {
    setBrief(SAMPLE_BRIEF);
    if (!audience.trim()) setAudience(SAMPLE_AUDIENCE);
    setPurpose("feature");
    setShowErrors(false);
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
      toast("info", `Текст из «${file.name}» вставлен`);
    } catch (err) {
      toast("error", `Не удалось прочитать «${file.name}»: ${errText(err)}`);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (problem || busy || !templateId) {
      if (busy || healthError) return;
      if (!templateId) setShaking(1);
      else {
        setShaking(2);
        if (briefLen < BRIEF_MIN) briefRef.current?.focus();
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
        slides: clampSlides(slides),
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
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="mx-auto max-w-[980px] space-y-6 pb-10">
      <div className="animate-rise pb-2 pt-4 text-center">
        <h1 className="text-[40px] font-bold leading-[48px] tracking-tight text-zinc-900">Презентация в стиле вашего шаблона</h1>
        <p className="mx-auto mt-3 max-w-2xl text-[17px] leading-7 text-zinc-500">
          Выберите фирменный шаблон и напишите, о чём рассказать. Verstka соберёт три варианта — их можно скачать и править в PowerPoint.
        </p>
        <ul className="mt-5 flex flex-wrap items-center justify-center gap-2 text-[13px] font-medium text-zinc-600">
          {[
            { icon: Presentation, text: "Редактируемый PowerPoint, не картинки" },
            { icon: ShieldCheck, text: "Проверка качества каждого слайда" },
            { icon: Unlock, text: "Только открытые модели" },
          ].map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-1.5 rounded-full bg-white/80 px-3 py-1.5 shadow-card">
              <Icon className="h-3.5 w-3.5 text-accent" aria-hidden />
              {text}
            </li>
          ))}
        </ul>
      </div>

      <Step n={1} title="Выберите шаблон" hint="Фирменный шаблон PowerPoint — по нему будут оформлены слайды" done={!!templateId && !manifestLoading} delay={60} shake={shaking === 1}>
        <TemplatePicker />
        {showErrors && !templateId && !healthError && (
          <p role="alert" className="mt-3 text-[13px] font-medium text-red-600 animate-fade">Выберите шаблон или загрузите свой .pptx</p>
        )}
      </Step>

      <Step n={2} title="О чём презентация" hint="Тезисы, цифры и таблицы — всё попадёт на слайды, заголовки станут выводами" done={briefLen >= BRIEF_MIN} delay={120} shake={shaking === 2}>
        <textarea
          ref={briefRef}
          id="brief"
          aria-label="О чём презентация"
          value={brief}
          disabled={busy}
          onChange={(e) => setBrief(e.target.value)}
          placeholder={"Например: итоги пилота «Умные сводки» за квартал.\n\nПроблема: сотрудники тратят 47 минут в день на чтение чатов.\nРезультаты: время сократилось до 29 минут, NPS 64.\nПросим: бюджет 14,5 млн ₽ на масштабирование."}
          className={cn(
            "scroll-thin block min-h-[260px] w-full resize-y rounded-2xl border-0 bg-zinc-100 px-5 py-4 text-[15px] leading-7 text-zinc-900 placeholder:text-zinc-500 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none disabled:opacity-60",
            showErrors && templateId && briefLen < BRIEF_MIN && "shadow-[0_0_0_2px_#F87171]",
          )}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {briefLen === 0 && <Button size="sm" variant="tonal" icon={FileText} disabled={busy} onClick={fillSample} className="animate-fade">Вставить пример</Button>}
          <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
          <Button size="sm" variant="ghost" icon={Paperclip} disabled={busy} onClick={() => fileRef.current?.click()}>Загрузить из файла</Button>
          {showErrors && templateId && briefLen < BRIEF_MIN ? (
            <span role="alert" className="ml-auto text-xs font-medium text-red-600 animate-fade">
              {briefLen === 0 ? "Напишите, о чём рассказать, — или вставьте пример" : `Пока ${plural(briefLen, "символ", "символа", "символов")} — нужно хотя бы ${BRIEF_MIN}`}
            </span>
          ) : (
            <span className={cn("ml-auto text-xs tabular-nums", briefLen > 0 && briefLen < BRIEF_MIN ? "text-amber-600" : "text-zinc-400")}>
              {briefLen > 0 ? plural(briefLen, "символ", "символа", "символов").replace(/^\d+/, briefLen.toLocaleString("ru-RU")) : ""}
            </span>
          )}
        </div>

        <div className="mt-6 grid grid-cols-[auto_minmax(0,1fr)] items-end gap-6 border-t border-zinc-100 pt-6">
          <div>
            <label htmlFor="slides" className="mb-2 block text-[13px] font-semibold text-zinc-700">Сколько слайдов</label>
            <div className="flex items-center gap-2">
              <Button icon={Minus} aria-label="Меньше слайдов" disabled={busy || slides <= SLIDES_MIN} onClick={() => setSlides((n) => clampSlides(n - 1))} className="h-11 w-11 rounded-full" />
              <input
                id="slides"
                type="number"
                min={SLIDES_MIN}
                max={SLIDES_MAX}
                value={slides}
                disabled={busy}
                onChange={(e) => setSlides(Number(e.target.value))}
                onBlur={() => setSlides((n) => clampSlides(n))}
                className="h-11 w-16 rounded-xl border-0 bg-zinc-100 text-center text-lg font-bold tabular-nums text-zinc-900 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <Button icon={Plus} aria-label="Больше слайдов" disabled={busy || slides >= SLIDES_MAX} onClick={() => setSlides((n) => clampSlides(n + 1))} className="h-11 w-11 rounded-full" />
            </div>
          </div>
          <div>
            <label htmlFor="audience" className="mb-2 block text-[13px] font-semibold text-zinc-700">Для кого <span className="font-normal text-zinc-400">— необязательно</span></label>
            <input id="audience" type="text" value={audience} disabled={busy} onChange={(e) => setAudience(e.target.value)} placeholder="Например: руководство, инвесторы, команда" className={INPUT_CLS} />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setMore(!more)}
          aria-expanded={more}
          className="mt-6 inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold text-zinc-600 hover:text-zinc-900"
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", more && "rotate-180")} aria-hidden />
          Дополнительные настройки
        </button>
        {/* the settings unfold smoothly; while folded they leave the tab order once the animation has played */}
        <div className={cn("grid transition-[grid-template-rows] duration-300 ease-out", more ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
          <div className="min-h-0 overflow-hidden" style={{ visibility: more ? "visible" : "hidden", transition: `visibility 0s linear ${more ? "0s" : "300ms"}` }}>
          <div className="mt-4 space-y-6 rounded-2xl bg-zinc-50 p-5">
            <div>
              <p className="mb-2 text-[13px] font-semibold text-zinc-700">Тип презентации</p>
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Тип презентации">
                {PURPOSES.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    role="radio"
                    aria-checked={purpose === p.value}
                    disabled={busy}
                    onClick={() => setPurpose(p.value)}
                    className={cn(
                      "h-9 cursor-pointer rounded-full px-3.5 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
                      purpose === p.value ? "bg-zinc-900 text-white" : "bg-white text-zinc-700 shadow-card hover:bg-zinc-100",
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            {strategies.length > 0 && (
              <div>
                <p className="mb-1 text-[13px] font-semibold text-zinc-700">Варианты оформления</p>
                <p className="mb-3 text-xs text-zinc-500">По умолчанию собираются все три — потом выберете лучший.</p>
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
            <div className="grid grid-cols-2 gap-6">
              <Toggle
                label="Писать тексты открытой моделью"
                hint={modelsConfigured ? "Точнее формулировки, но дольше. Без модели работает быстрый встроенный планировщик" : "Модель не подключена — работает встроенный планировщик"}
                checked={useModels && modelsConfigured}
                disabled={busy || !modelsConfigured}
                onChange={(v) => {
                  modelsTouched.current = true;
                  setUseModels(v);
                }}
              />
              <Toggle
                label="Проверять слайды моделью по картинке"
                hint={modelsConfigured ? "Дополнительная проверка смысла и читаемости; дольше" : "Недоступно без подключённой модели"}
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
      </Step>

      <div className="flex animate-rise flex-col items-center gap-3 pt-2" style={{ animationDelay: "180ms" }}>
        <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} loading={busy} className="h-14 rounded-2xl px-10 text-[17px] transition-[background-color,transform,box-shadow] hover:-translate-y-px hover:shadow-raise">
          Создать презентацию
        </Button>
        <p className={cn("text-sm", showErrors && problem ? "font-semibold text-red-600" : "text-zinc-500")} role={showErrors && problem ? "alert" : undefined}>
          {showErrors && problem
            ? problem
            : `${plural(selected.length || 3, "вариант", "варианта", "вариантов")} по ${plural(clampSlides(slides), "слайду", "слайда", "слайдов")} · ${useModels && modelsConfigured ? "с моделью — до 5 минут" : "обычно меньше минуты"}`}
        </p>
      </div>
    </form>
  );
}
