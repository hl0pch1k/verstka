// «Как работал агент»: a compact card beside the slide (what the analyst found, what the designer made, what the
// critic said) and the full view in the «Подробнее» drawer — the variant's timeline step by step, the critic's notes
// per slide with the revisions, or the plain log for runs that kept only the log. Older runs show a calm empty state.
import { useMemo } from "react";
import { Bot, ChevronRight } from "lucide-react";
import { agentSummary, buildTimeline, formsSummary, hasAgentWork } from "../../lib/agent";
import { cn, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { Variant } from "../../types";
import { EmptyState } from "../ui/EmptyState";
import { AgentTimeline } from "./AgentTimeline";

/** The card on the result screen; nothing for a deck made before the agent kept a journal. */
export function AgentCard({ variant, onOpen }: { variant: Variant; onOpen(): void }) {
  const lines = useMemo(() => agentSummary(variant), [variant]);
  if (!hasAgentWork(variant) || lines.length === 0) return null;
  return (
    <section className="rounded-2xl bg-white p-2 shadow-card animate-fade">
      <button type="button" onClick={onOpen} className="group w-full cursor-pointer rounded-xl px-3 pb-2 pt-1.5 text-left transition-colors hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
        <span className="flex items-center gap-2">
          <span className="text-[15px] font-semibold text-zinc-900">Как работал агент</span>
          <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </span>
        <ul className="mt-1.5 space-y-1">
          {lines.map((l, i) => (
            <li key={i} className="flex gap-2 text-[12px] leading-[18px]" title={l.text}>
              {l.step && <span className="w-[62px] shrink-0 font-semibold text-zinc-700">{l.step}</span>}
              <span className="min-w-0 flex-1 truncate text-zinc-500">{l.text}</span>
            </li>
          ))}
        </ul>
      </button>
    </section>
  );
}

/** The drawer tab: the whole work of the agent on the variant on screen. */
export function AgentLog() {
  const { generation, activeVariant, strategyTitle, setSelectedSlide, setDetail } = useApp();
  const v = activeVariant ?? generation?.variants[0] ?? null;
  const events = v?.agent?.events ?? [];
  const rows = useMemo(() => {
    if (!v) return [];
    const audit = v.audit?.summary;
    const n = v.outline?.slides.length ?? v.slides.length;
    const fixes = v.audit?.applied_fixes?.length ?? 0;
    return buildTimeline({
      events,
      phase: "check",
      running: false,
      notes: {
        layout: n ? `${plural(n, "слайд", "слайда", "слайдов")} по макетам и стилю шаблона` : null,
        check: audit ? `оценка ${Math.round(audit.score)}/100${audit.errors ? `, ${plural(audit.errors, "ошибка", "ошибки", "ошибок")}` : ", без ошибок"}${fixes ? `, исправлено автоматически: ${fixes}` : ""}` : null,
      },
    });
  }, [v, events]);
  if (!generation || !v) return null;
  const log = v.agent?.log ?? [];
  const edits = v.edits ?? [];
  const openSlide = (n: number) => {
    setSelectedSlide(n);
    setDetail("why");
  };
  const forms = formsSummary(v.outline);
  const idx = generation.variants.findIndex((x) => x.strategy === v.strategy) + 1;

  if (!hasAgentWork(v)) {
    return (
      <EmptyState
        icon={Bot}
        title="Журнал агента не записан"
        hint="Эта презентация собрана до того, как агент начал вести журнал, или без модели. Соберите её заново — здесь появится, как агент читал текст, выбирал форму каждого слайда и проверял себя."
      />
    );
  }
  return (
    <div className="space-y-4">
      <section className="rounded-3xl bg-white p-6 shadow-card">
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">Вариант {idx} · {strategyTitle(v.strategy)}</p>
        <h3 className="mt-1 text-[17px] font-semibold text-zinc-900">Как агент собирал эту презентацию</h3>
        <p className="mt-1 text-[13px] leading-5 text-zinc-500">
          {v.outline ? `${plural(v.outline.slides.length, "слайд", "слайда", "слайдов")}${forms ? `: ${forms}` : ""}. ` : ""}
          Нажмите на номер слайда — откроется, почему он такой.
        </p>
        <div className="mt-5">
          {events.length > 0 ? (
            <AgentTimeline rows={rows} onSlide={openSlide} />
          ) : (
            <ol className="space-y-2">
              {log.map((line, i) => {
                const m = line.match(/^([А-ЯЁ][а-яё]+):\s*(.+)$/);
                return (
                  <li key={i} className="flex gap-3 text-[13px] leading-5 text-zinc-700">
                    <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-[11px] font-bold text-accent">{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      {m ? (
                        <>
                          <span className="font-semibold text-zinc-900">{m[1]}:</span> {m[2]}
                        </>
                      ) : (
                        line
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </section>
      {edits.length > 0 && (
        <section className="rounded-3xl bg-white p-6 shadow-card">
          <h3 className="text-[15px] font-semibold text-zinc-900">Правки по вашим просьбам</h3>
          <p className="mt-1 text-[13px] leading-5 text-zinc-500">Каждая правка сохраняет прежнюю версию — скажите помощнику «верни как было», чтобы откатить последнюю.</p>
          <ol className="mt-4 space-y-3">
            {edits.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-[11px] font-bold text-accent">{i + 1}</span>
                <div className="min-w-0 flex-1 text-[13px] leading-5">
                  <p className="font-semibold text-zinc-900">«{e.request}»</p>
                  <p className="text-zinc-600">{e.reply}</p>
                  {e.slides?.length && e.kind !== "delete" ? (
                    <button type="button" onClick={() => openSlide(e.slides[0])} className="mt-0.5 cursor-pointer text-[12px] font-semibold text-accent-700 hover:underline focus:outline-none focus-visible:underline">
                      Слайд {e.slides[0]}: почему он такой
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      {events.length > 0 && log.length > 0 && (
        <details className="group rounded-2xl bg-white px-6 py-4 shadow-card">
          <summary className={cn("cursor-pointer list-none text-[14px] font-semibold text-zinc-900 marker:hidden")}>
            Журнал одним списком <span className="font-normal text-zinc-500">· {plural(log.length, "запись", "записи", "записей")}</span>
          </summary>
          <ol className="mt-3 space-y-1.5 text-[13px] leading-5 text-zinc-600">
            {log.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="w-5 shrink-0 text-right tabular-nums text-zinc-400">{i + 1}.</span>
                <span className="min-w-0 flex-1">{line}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
