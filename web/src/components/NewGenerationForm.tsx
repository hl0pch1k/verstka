// «Новая презентация»: brief → strategies → startGeneration(). Rendered inside the collapsible card in App
// (title, chevron, border and paddings come from App) — only the form fields live here.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { FileText, Minus, Plus, Sparkles } from "lucide-react";
import { cn, plural } from "../lib/utils";
import { useApp } from "../store";
import {
  BRIEF_MIN, Field, INPUT_CLS, PURPOSES, SAMPLE_AUDIENCE, SAMPLE_BRIEF, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN, StrategyOption, Toggle,
} from "./NewGenerationFormParts";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/Spinner";

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Number.isFinite(n) ? Math.round(n) : SLIDES_DEFAULT));

export function NewGenerationForm() {
  const { health, healthError, strategies, templateId, manifest, manifestLoading, activeJob, startGeneration } = useApp();
  const modelsConfigured = health?.models_configured ?? false;

  const [brief, setBrief] = useState("");
  const [audience, setAudience] = useState("");
  const [purpose, setPurpose] = useState("product");
  const [slides, setSlides] = useState(SLIDES_DEFAULT);
  const [selected, setSelected] = useState<string[]>([]);
  const [useModels, setUseModels] = useState(modelsConfigured);
  const [auditModels, setAuditModels] = useState(modelsConfigured);
  const [submitting, setSubmitting] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  // Defaults follow the server until the user touches a control.
  const strategiesTouched = useRef(false);
  const modelsTouched = useRef(false);
  useEffect(() => {
    if (!strategiesTouched.current) setSelected(strategies.map((s) => s.name));
  }, [strategies]);
  useEffect(() => {
    if (!modelsTouched.current) {
      setUseModels(modelsConfigured);
      setAuditModels(modelsConfigured);
    }
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

  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="space-y-5">
      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6">
        <Field
          label="Бриф"
          required
          htmlFor="ng-brief"
          error={showErrors ? briefError : null}
          hint="Текст, цифры и таблицы в markdown — факты попадут на слайды без искажений."
          right={
            <button type="button" onClick={fillSample} disabled={disabled} className="inline-flex items-center gap-1 text-xs font-medium text-accent-700 hover:underline disabled:opacity-50">
              <FileText className="h-3.5 w-3.5" aria-hidden />
              Вставить пример брифа
            </button>
          }
        >
          <div className="relative">
            <textarea
              id="ng-brief"
              value={brief}
              disabled={disabled}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="Например: итоги пилота функции «Умные сводки» за Q2 — проблема, решение, метрики до/после, дорожная карта, риски, запрос к комитету…"
              rows={8}
              className={cn(INPUT_CLS, "scroll-thin h-auto min-h-[176px] resize-y py-2.5 leading-5", showErrors && briefError && "border-red-300 focus:border-red-400 focus:ring-red-100")}
            />
            <span className={cn("pointer-events-none absolute bottom-2 right-3 rounded bg-white/90 px-1 text-[11px] tabular-nums", briefLen >= BRIEF_MIN ? "text-zinc-400" : "text-amber-600")}>
              {briefLen} / мин. {BRIEF_MIN}
            </span>
          </div>
        </Field>

        <div className="space-y-4">
          <Field label="Аудитория" htmlFor="ng-audience" hint="Кому показываем — влияет на тон и глубину.">
            <input id="ng-audience" type="text" value={audience} disabled={disabled} onChange={(e) => setAudience(e.target.value)} placeholder="Продуктовый комитет, инвесторы, команда…" className={INPUT_CLS} />
          </Field>
          <Field label="Цель" htmlFor="ng-purpose">
            <select id="ng-purpose" value={purpose} disabled={disabled} onChange={(e) => setPurpose(e.target.value)} className={cn(INPUT_CLS, "pr-8")}>
              {PURPOSES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Слайдов" htmlFor="ng-slides" hint={`От ${SLIDES_MIN} до ${SLIDES_MAX}. Планировщик подберёт структуру под объём.`}>
            <div className="flex items-center gap-2">
              <Button size="sm" icon={Minus} aria-label="Меньше слайдов" disabled={disabled || slides <= SLIDES_MIN} onClick={() => setSlides((n) => clampSlides(n - 1))} />
              <input
                id="ng-slides"
                type="number"
                min={SLIDES_MIN}
                max={SLIDES_MAX}
                value={slides}
                disabled={disabled}
                onChange={(e) => setSlides(Number(e.target.value))}
                onBlur={() => setSlides((n) => clampSlides(n))}
                className={cn(INPUT_CLS, "w-20 text-center tabular-nums")}
              />
              <Button size="sm" icon={Plus} aria-label="Больше слайдов" disabled={disabled || slides >= SLIDES_MAX} onClick={() => setSlides((n) => clampSlides(n + 1))} />
              <input type="range" min={SLIDES_MIN} max={SLIDES_MAX} value={clampSlides(slides)} disabled={disabled} onChange={(e) => setSlides(Number(e.target.value))} className="ml-1 min-w-0 flex-1 accent-accent" aria-label="Число слайдов" />
            </div>
          </Field>
        </div>
      </div>

      <Field
        label="Стратегии вёрстки"
        error={showErrors ? strategiesError : null}
        hint={strategies.length ? `Каждая стратегия даёт отдельный вариант — ${plural(selected.length, "вариант", "варианта", "вариантов")} за один запуск.` : undefined}
      >
        {strategies.length === 0 ? (
          <div className="flex h-16 items-center justify-center rounded-lg border border-dashed border-zinc-200 text-xs text-zinc-500">
            {healthError ? "Список стратегий появится после подключения к API" : <Spinner size={14} label="Загружаем стратегии" showLabel />}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {strategies.map((s) => (
              <StrategyOption key={s.name} strategy={s} checked={selected.includes(s.name)} disabled={disabled} onChange={(on) => toggleStrategy(s.name, on)} />
            ))}
          </div>
        )}
      </Field>

      <div className="flex items-center gap-8 border-t border-zinc-100 pt-4">
        <Toggle
          label="Использовать модели"
          hint={modelsConfigured ? "LLM пишет структуру и тексты, VLM проверяет слайды" : "Модели не настроены — работают эвристики и детерминированный планировщик"}
          checked={useModels && modelsConfigured}
          disabled={disabled || !modelsConfigured}
          onChange={(v) => {
            modelsTouched.current = true;
            setUseModels(v);
          }}
        />
        <Toggle
          label="Аудит моделями"
          hint={modelsConfigured ? "Дополнительные проверки смысла и связности" : "Недоступно без настроенных моделей"}
          checked={auditModels && modelsConfigured}
          disabled={disabled || !modelsConfigured}
          onChange={(v) => {
            modelsTouched.current = true;
            setAuditModels(v);
          }}
        />
        <div className="ml-auto flex items-center gap-3">
          {blocker ? (
            <span className="text-xs text-zinc-500">{blocker}</span>
          ) : (
            manifest && <span className="max-w-[260px] truncate text-xs text-zinc-500">Шаблон «{manifest.source_file}» · {plural(manifest.patterns.length, "паттерн", "паттерна", "паттернов")}</span>
          )}
          <Button type="submit" variant="primary" icon={Sparkles} loading={submitting || jobRunning} disabled={noTemplate || healthError || (showErrors && !valid)}>
            Сгенерировать
          </Button>
        </div>
      </div>
    </form>
  );
}
