// «Как работал агент»: a compact card beside the slide (what the analyst found, what the designer made, what the
// critic said) and the full view in the drawer's «Агент» tab — the variant's timeline step by step with the critic's
// notes per slide and their fixes, then the person's own edits. Older runs show a calm empty state.
import { useMemo, useState } from "react";
import { Bot, ChevronRight, PenTool, RotateCcw, ScanText, ShieldCheck, type LucideIcon } from "lucide-react";
import { api } from "../../api";
import { agentSummary, buildTimeline, formsSummary, hasAgentWork, mendCut } from "../../lib/agent";
import { errText } from "../../lib/narrate";
import { plainTerms } from "../../lib/plain";
import { plural, sessionId } from "../../lib/utils";
import { useApp } from "../../store";
import type { Variant } from "../../types";
import { useChatActions } from "../ChatActions";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { AgentTimeline } from "./AgentTimeline";

const STEP_ICON: Record<string, LucideIcon> = { Аналитик: ScanText, Дизайнер: PenTool, Критик: ShieldCheck };

/** The card on the result screen: a mini timeline of three steps; nothing for a deck made before the agent kept a
 *  journal. The whole card opens the drawer's «Агент». */
export function AgentCard({ variant, onOpen }: { variant: Variant; onOpen(): void }) {
  const lines = useMemo(() => agentSummary(variant).slice(0, 3), [variant]);
  if (!hasAgentWork(variant) || lines.length === 0) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group w-full shrink-0 cursor-pointer rounded-2xl bg-white p-4 text-left shadow-card transition-colors duration-150 hover:bg-zinc-50 animate-fade"
    >
      <span className="flex items-center gap-2">
        <span className="text-title3 font-semibold text-zinc-900">Как работал агент</span>
        <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-zinc-400 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
      </span>
      {/* a button holds phrasing content only: the mini timeline is spans laid out as blocks */}
      <span className="mt-3 block space-y-2">
        {lines.map((l, i) => {
          const Icon = STEP_ICON[l.step] ?? Bot;
          const last = i === lines.length - 1;
          return (
            <span key={i} className="relative flex gap-2" title={l.step ? `${l.step}: ${l.text}` : l.text}>
              {!last && <span className="absolute -bottom-2 left-[7px] top-5 w-px bg-zinc-200" aria-hidden />}
              <Icon className="relative mt-0.5 h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
              <span className="line-clamp-3 min-w-0 flex-1 text-footnote">
                {l.step && <b className="font-semibold text-zinc-800">{l.step}</b>} <span className="text-zinc-600">{l.text}</span>
              </span>
            </span>
          );
        })}
      </span>
    </button>
  );
}

/** «Вернуть как было»: the same words the helper understands, sent the same way (the reply and the job show in it). */
function useUndo() {
  const { pushMessage, templateId, generationId, activeStrategy, selectedSlide, setAgentOpen, toast } = useApp();
  const handleActions = useChatActions();
  const [busy, setBusy] = useState(false);
  const undo = async () => {
    if (busy) return;
    const message = "Верни как было";
    setBusy(true);
    setAgentOpen(true);
    pushMessage("user", message);
    try {
      const res = await api.chat({ session_id: sessionId(), message, template_id: templateId, generation_id: generationId, strategy: activeStrategy, slide: selectedSlide });
      pushMessage("assistant", res.reply);
      handleActions(res);
    } catch (e) {
      toast("error", `Не получилось вернуть: ${errText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  return { undo, busy };
}

/** The drawer tab: the whole work of the agent on the variant on screen. */
export function AgentLog() {
  const { generation, activeVariant, setSelectedSlide, setDetail, activeJob } = useApp();
  const v = activeVariant ?? generation?.variants[0] ?? null;
  const events = useMemo(() => v?.agent?.events ?? [], [v]);
  const { undo, busy } = useUndo();
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
        check: audit ? `оценка ${Math.round(audit.score)}${audit.errors ? `, ${plural(audit.errors, "ошибка", "ошибки", "ошибок")}` : ", без ошибок"}${fixes ? `, исправлено автоматически: ${fixes}` : ""}` : null,
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
  const jobBusy = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");

  if (!hasAgentWork(v)) {
    return <EmptyState icon={Bot} title="Журнал агента не записан" hint="Соберите презентацию заново" />;
  }
  return (
    <div className="space-y-4">
      <section className="rounded-2xl bg-white p-6 shadow-card">
        {v.outline && (
          <p className="mb-4 text-footnote text-zinc-500">
            {[plural(v.outline.slides.length, "слайд", "слайда", "слайдов"), forms].filter(Boolean).join(" · ")}
          </p>
        )}
        {events.length > 0 ? (
          <AgentTimeline rows={rows} onSlide={openSlide} />
        ) : (
          <ol className="space-y-2">
            {log.map((line, i) => {
              const m = line.match(/^([А-ЯЁ][а-яё]+):\s*(.+)$/);
              return (
                <li key={i} className="flex gap-3 text-footnote text-zinc-700">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-caption font-bold text-accent-700">{i + 1}</span>
                  <span className="min-w-0 max-w-[680px] flex-1">
                    {m ? (
                      <>
                        <span className="font-semibold text-zinc-900">{m[1]}:</span> {plainTerms(m[2])}
                      </>
                    ) : (
                      plainTerms(line)
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </section>
      {edits.length > 0 && (
        <section className="rounded-2xl bg-white p-6 shadow-card">
          <div className="flex h-8 items-center gap-3">
            <h3 className="text-title3 font-semibold text-zinc-900">
              Ваши правки<span className="ml-2 text-footnote font-normal tabular-nums text-zinc-500">{edits.length}</span>
            </h3>
            <Button variant="tonal" size="sm" icon={RotateCcw} loading={busy} disabled={jobBusy} onClick={() => void undo()} className="ml-auto">
              Вернуть как было
            </Button>
          </div>
          <ol className="mt-4 space-y-3">
            {edits.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-caption font-bold text-accent-700">{i + 1}</span>
                <div className="min-w-0 max-w-[680px] flex-1 text-footnote">
                  <p className="font-semibold text-zinc-900">«{e.request}»</p>
                  <p className="text-zinc-600">{e.reply}</p>
                  {e.slides?.length && e.kind !== "delete" ? (
                    <Button variant="ghost" size="sm" iconRight={ChevronRight} onClick={() => openSlide(e.slides[0])} className="-ml-3 mt-1">
                      Почему слайд {e.slides[0]} такой
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

/** The agent's log as one list, for the Files tab's «Для разработчиков». */
export function AgentJournal({ log }: { log: string[] }) {
  return (
    <ol className="space-y-2 text-footnote text-zinc-700">
      {log.map((line, i) => (
        <li key={i} className="flex gap-2">
          <span className="w-6 shrink-0 text-right tabular-nums text-zinc-500">{i + 1}.</span>
          <span className="min-w-0 flex-1">{plainTerms(mendCut(line))}</span>
        </li>
      ))}
    </ol>
  );
}
