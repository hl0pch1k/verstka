// Step 2 «Бриф»: the brief editor, audience and purpose, deck size, strategies and models → startGeneration().
// The draft is kept in localStorage: switching steps or reloading the page never loses a written brief.
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { FileText, Minus, Paperclip, Plus, SlidersHorizontal, Sparkles } from "lucide-react";
import { errText } from "../lib/narrate";
import { cn, LS, plural, storage } from "../lib/utils";
import { useApp } from "../store";
import {
  BRIEF_MIN, Field, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle,
} from "./NewGenerationFormParts";
import { Button } from "./ui/Button";
import { PageHeader } from "./ui/PageHeader";
import { Spinner } from "./ui/Spinner";

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

export function NewGenerationForm() {
  const { health, healthError, strategies, templateId, manifest, manifestLoading, activeJob, startGeneration, toast } = useApp();
  const modelsConfigured = health?.models_configured ?? false;

  const [draft] = useState(loadDraft);
  const [brief, setBrief] = useState(draft.brief);
  const [audience, setAudience] = useState(draft.audience);
  const [purpose, setPurpose] = useState(draft.purpose);
  const [slides, setSlides] = useState(draft.slides);
  const [selected, setSelected] = useState<string[]>([]);
  const [useModels, setUseModels] = useState(modelsConfigured);
  const [auditModels, setAuditModels] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = window.setTimeout(() => storage.set(LS.brief, JSON.stringify({ brief, audience, purpose, slides } satisfies Draft)), 300);
    return () => window.clearTimeout(t);
  }, [brief, audience, purpose, slides]);

  // Defaults follow the server until the user touches a control.
  const strategiesTouched = useRef(false);
  const modelsTouched = useRef(false);
  useEffect(() => {
    if (!strategiesTouched.current) setSelected(strategies.map((s) => s.name));
  }, [strategies]);
  useEffect(() => {
    if (!modelsTouched.current) setUseModels(modelsConfigured);
  }, [modelsConfigured]);

  const briefLen = brief.trim().length;
  const briefError = briefLen === 0 ? "Опишите, о чём презентация" : briefLen < BRIEF_MIN ? `Слишком коротко: нужно хотя бы ${BRIEF_MIN} символов` : null;
  const strategiesError = selected.length === 0 ? "Выберите хотя бы одну стратегию" : null;
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const noTemplate = !templateId;
  const valid = !briefError && !strategiesError && !noTemplate;
  const disabled = submitting || jobRunning;

  const blocker = useMemo(() => {
    if (healthError) return "API недоступен — дождитесь переподключения";
    if (noTemplate) return "Сначала загрузите или выберите шаблон .pptx";
    if (jobRunning) return `Дождитесь завершения: ${activeJob?.label}`;
    if (manifestLoading) return "Шаблон загружается…";
    return null;
  }, [healthError, noTemplate, jobRunning, activeJob?.label, manifestLoading]);

  const toggleStrategy = (name: string, on: boolean) => {
    strategiesTouched.current = true;
    setSelected((cur) => (on ? Array.from(new Set([...cur, name])) : cur.filter((s) => s !== name)));
  };

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
    if (!/\.(md|txt|markdown)$/i.test(file.name)) return toast("error", "Бриф должен быть файлом .md или .txt");
    if (file.size > MAX_BRIEF_BYTES) return toast("error", "Файл брифа больше 2 МБ");
    try {
      const text = (await file.text()).replace(/\r\n/g, "\n").trim();
      if (!text) return toast("error", `Файл «${file.name}» пустой`);
      // front matter (---\naudience: …\n---) is understood by the server; keep it as is
      setBrief(text);
      toast("info", `Бриф «${file.name}» загружен`);
    } catch (err) {
      toast("error", `Не удалось прочитать «${file.name}»: ${errText(err)}`);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (!valid || disabled || !templateId || healthError) return;
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

  const templateName = manifest?.source_file?.replace(/\.pptx$/i, "").replace(/_/g, " ");
  const summary = [
    templateName ? `шаблон «${templateName}»` : null,
    plural(selected.length, "вариант", "варианта", "вариантов"),
    plural(clampSlides(slides), "слайд", "слайда", "слайдов"),
    useModels && modelsConfigured ? "с моделью" : "без модели",
  ].filter(Boolean).join(" · ");

  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="pb-2">
      <PageHeader
        eyebrow="Шаг 2 из 5"
        title="О чём презентация"
        subtitle="Бриф в свободной форме: тезисы, цифры и таблицы в markdown. Факты попадут на слайды без искажений, заголовки станут выводами."
      />

      <div className="mt-8 grid grid-cols-[minmax(0,1fr)_380px] gap-6">
        <section className="flex min-w-0 flex-col rounded-3xl bg-white shadow-card">
          <div className="flex items-center gap-2 px-6 pb-2 pt-5">
            <label htmlFor="ng-brief" className="text-[17px] font-semibold text-zinc-900">
              Бриф<span className="ml-0.5 text-red-500" aria-hidden>*</span>
            </label>
            <span className={cn("ml-2 text-xs font-medium tabular-nums", briefLen >= BRIEF_MIN ? "text-zinc-400" : "text-amber-600")}>
              {briefLen.toLocaleString("ru-RU")} зн.{briefLen < BRIEF_MIN && ` · минимум ${BRIEF_MIN}`}
            </span>
            <span className="ml-auto flex items-center gap-1.5">
              <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
              <Button size="sm" variant="ghost" icon={Paperclip} disabled={disabled} onClick={() => fileRef.current?.click()}>Из файла</Button>
              <Button size="sm" variant="tonal" icon={FileText} disabled={disabled} onClick={fillSample}>Пример брифа</Button>
            </span>
          </div>
          <textarea
            id="ng-brief"
            value={brief}
            disabled={disabled}
            onChange={(e) => setBrief(e.target.value)}
            placeholder={"# Итоги пилота «Умные сводки»\n\n## Проблема\nСотрудники тратят 47 минут в день на чтение чатов…\n\n## Результаты\n| Метрика | До | После |\n|---|---|---|\n| Время, мин/день | 47 | 29 |"}
            className={cn(
              "scroll-thin mx-3 mb-3 min-h-[440px] flex-1 resize-y rounded-2xl border-0 bg-zinc-50 px-4 py-4 font-sans text-[15px] leading-7 text-zinc-900 placeholder:text-zinc-400 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none disabled:opacity-60",
              showErrors && briefError && "shadow-[0_0_0_2px_#FCA5A5]",
            )}
          />
          {showErrors && briefError && <p role="alert" className="px-6 pb-4 text-xs font-medium text-red-600">{briefError}</p>}
        </section>

        <div className="space-y-5">
          <section className="space-y-5 rounded-3xl bg-white p-6 shadow-card">
            <Field label="Аудитория" htmlFor="ng-audience" hint="Кому показываем — от этого зависят тон и глубина.">
              <input id="ng-audience" type="text" value={audience} disabled={disabled} onChange={(e) => setAudience(e.target.value)} placeholder="Продуктовый комитет, инвесторы…" className={INPUT_CLS} />
            </Field>
            <Field label="Цель">
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Цель презентации">
                {PURPOSES.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    role="radio"
                    aria-checked={purpose === p.value}
                    disabled={disabled}
                    onClick={() => setPurpose(p.value)}
                    className={cn(
                      "h-9 cursor-pointer rounded-full px-3.5 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
                      purpose === p.value ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200/70",
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </Field>
          </section>

          <section className="rounded-3xl bg-white p-6 shadow-card">
            <div className="flex items-center justify-between">
              <label htmlFor="ng-slides" className="text-[13px] font-semibold text-zinc-700">Слайдов</label>
              <span className="text-xs text-zinc-500">от {SLIDES_MIN} до {SLIDES_MAX}</span>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <Button icon={Minus} aria-label="Меньше слайдов" disabled={disabled || slides <= SLIDES_MIN} onClick={() => setSlides((n) => clampSlides(n - 1))} className="rounded-full" />
              <input
                id="ng-slides"
                type="number"
                min={SLIDES_MIN}
                max={SLIDES_MAX}
                value={slides}
                disabled={disabled}
                onChange={(e) => setSlides(Number(e.target.value))}
                onBlur={() => setSlides((n) => clampSlides(n))}
                className="h-14 w-full min-w-0 flex-1 rounded-2xl border-0 bg-zinc-100 text-center text-3xl font-bold tabular-nums tracking-tight text-zinc-900 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <Button icon={Plus} aria-label="Больше слайдов" disabled={disabled || slides >= SLIDES_MAX} onClick={() => setSlides((n) => clampSlides(n + 1))} className="rounded-full" />
            </div>
            <input type="range" min={SLIDES_MIN} max={SLIDES_MAX} value={clampSlides(slides)} disabled={disabled} onChange={(e) => setSlides(Number(e.target.value))} className="mt-4 w-full cursor-pointer accent-accent" aria-label="Число слайдов" />
            <p className="mt-2 text-xs leading-4 text-zinc-500">Планировщик подберёт структуру под объём; компактный вариант бывает на треть короче.</p>
          </section>

          <section className="space-y-4 rounded-3xl bg-white p-6 shadow-card">
            <p className="flex items-center gap-2 text-[13px] font-semibold text-zinc-700">
              <SlidersHorizontal className="h-4 w-4 text-zinc-400" aria-hidden /> Открытая модель
            </p>
            <Toggle
              label="План и тексты моделью"
              hint={modelsConfigured ? "Qwen пишет структуру и заголовки-выводы; без модели работает детерминированный планировщик" : "Модели не настроены — работает детерминированный планировщик"}
              checked={useModels && modelsConfigured}
              disabled={disabled || !modelsConfigured}
              onChange={(v) => {
                modelsTouched.current = true;
                setUseModels(v);
              }}
            />
            <Toggle
              label="Аудит моделью по картинкам"
              hint={modelsConfigured ? "Дополнительные проверки смысла и читаемости; дольше" : "Недоступно без настроенных моделей"}
              checked={auditModels && modelsConfigured}
              disabled={disabled || !modelsConfigured}
              onChange={(v) => {
                modelsTouched.current = true;
                setAuditModels(v);
              }}
            />
          </section>
        </div>
      </div>

      <section className="mt-6 rounded-3xl bg-white p-6 shadow-card">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <div>
            <h2 className="text-[17px] font-semibold text-zinc-900">Стратегии вёрстки</h2>
            <p className="text-[13px] text-zinc-500">Каждая стратегия — отдельный вариант колоды из того же брифа. Сравните и выберите лучший.</p>
          </div>
          {showErrors && strategiesError && <p role="alert" className="text-xs font-medium text-red-600">{strategiesError}</p>}
        </div>
        {strategies.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-2xl bg-zinc-100 text-xs text-zinc-500">
            {healthError ? "Список стратегий появится после подключения к API" : <Spinner size={14} label="Загружаем стратегии" showLabel />}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {strategies.map((s) => (
              <StrategyOption key={s.name} strategy={s} checked={selected.includes(s.name)} disabled={disabled} onChange={(on) => toggleStrategy(s.name, on)} />
            ))}
          </div>
        )}
      </section>

      <div className="sticky bottom-6 z-20 mt-6">
        <div className="flex w-full items-center gap-4 rounded-2xl bg-ink py-3 pl-6 pr-3 text-white shadow-pop">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold">
              {blocker ?? (briefLen === 0 ? "Напишите бриф или вставьте пример" : briefError ?? strategiesError ?? "Всё готово к сборке")}
            </p>
            <p className="truncate text-[13px] text-white/55">{summary}</p>
          </div>
          <Button type="submit" variant="primary" size="lg" icon={Sparkles} loading={submitting || jobRunning} disabled={noTemplate || healthError || (showErrors && !valid)} className="shadow-glow">
            Собрать презентацию
          </Button>
        </div>
      </div>
    </form>
  );
}
