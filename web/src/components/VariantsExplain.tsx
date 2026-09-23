// The two cards under the preview: «Почему такой макет» (plan entry + narrator text) and «Замечания слайда».
import { useEffect, useState } from "react";
import { ArrowUpRight, CheckCircle2, Copy, Lightbulb, RefreshCw, ShieldAlert, ShieldOff, Sparkles, Wand2 } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, fmtPct, kindLabel, SEVERITY_LABEL } from "../lib/utils";
import type { Issue, LayoutSlide, Pattern } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { fitTone, issuesSummary, MODE_LABEL, SEVERITY_TONE } from "./VariantsHelpers";

// ---- «Почему такой макет» -----------------------------------------------------------------------

type ExplainState = { status: "loading" } | { status: "ok"; text: string } | { status: "error"; message: string };

/** Narrator texts keyed by generation/strategy/slide/revision; survives tab switches (the panel remounts). */
const cache = new Map<string, string>();
const CACHE_MAX = 400;

function remember(key: string, text: string) {
  if (cache.size >= CACHE_MAX) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, text);
}

const fromCache = (key: string): ExplainState => {
  const hit = cache.get(key);
  return hit === undefined ? { status: "loading" } : { status: "ok", text: hit };
};

interface ExplainProps {
  generationId: string;
  strategy: string;
  slide: number; // 1-based
  rev: string;
  entry: LayoutSlide | null;
  hasPlan: boolean;
  /** Template pattern behind a cloned slide (when the template manifest is loaded). */
  pattern: Pattern | null;
  aspect: number;
}

function PlanEntry({ entry, pattern, aspect }: { entry: LayoutSlide; pattern: Pattern | null; aspect: number }) {
  const clone = entry.mode === "clone";
  const target = clone ? entry.pattern_id : entry.composition;
  return (
    <div className="space-y-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={clone ? "accent" : "info"} icon={clone ? Copy : Wand2}>
          {MODE_LABEL[entry.mode]}
        </Badge>
        <span className="font-mono text-xs text-zinc-700">{target ?? "—"}</span>
        <Badge tone={fitTone(entry.score)} className="ml-auto" title="Оценка соответствия слайда выбранному макету (0–1)">
          балл {entry.score.toFixed(2)}
        </Badge>
      </div>
      {pattern && (
        <div className="flex items-center gap-3 rounded-xl bg-zinc-50 p-2 shadow-inner-line">
          <div className="w-24 shrink-0 overflow-hidden rounded bg-zinc-100 ring-1 ring-zinc-200" style={{ aspectRatio: String(aspect) }}>
            {pattern.thumbnail_url && <img src={pattern.thumbnail_url} alt="" loading="lazy" decoding="async" draggable={false} className="h-full w-full object-cover" />}
          </div>
          <div className="min-w-0 text-[13px] leading-5">
            <p className="font-medium text-zinc-900">Слайд {pattern.source_slide} шаблона</p>
            <p className="truncate text-zinc-500">
              {kindLabel(pattern.kind)} · качество паттерна {fmtPct(pattern.quality)}
            </p>
          </div>
        </div>
      )}
      {entry.reasons.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Причины</p>
          <ul className="list-disc space-y-1 pl-5 text-[13px] leading-5 text-zinc-700">
            {entry.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {entry.alternatives.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Запасные варианты</p>
          <div className="flex flex-wrap gap-1.5">
            {entry.alternatives.map(([pid, score], i) => (
              <span key={`${pid}:${i}`} className="inline-flex h-6 items-center gap-1 rounded-md bg-zinc-100 px-2 text-xs text-zinc-700">
                <span className="font-mono">{pid}</span>
                <span className="text-zinc-400">·</span>
                <span className="tabular-nums">{score.toFixed(2)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function VariantsExplain({ generationId, strategy, slide, rev, entry, hasPlan, pattern, aspect }: ExplainProps) {
  const key = `${generationId}/${strategy}/${slide}/${rev}`;
  const [state, setState] = useState<ExplainState>(() => fromCache(key));
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const hit = cache.get(key);
    if (hit !== undefined) return void setState({ status: "ok", text: hit });
    let alive = true;
    setState({ status: "loading" });
    api.explain(generationId, strategy, slide).then(
      (r) => {
        remember(key, r.text);
        if (alive) setState({ status: "ok", text: r.text });
      },
      (e) => alive && setState({ status: "error", message: errText(e) }),
    );
    return () => {
      alive = false;
    };
  }, [key, generationId, strategy, slide, attempt]);

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle icon={Lightbulb} hint={`Слайд ${slide} · решение планировщика`}>
          Почему такой макет
        </CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="rounded-2xl bg-accent-50/70 px-4 py-3.5 text-[13px] leading-5 text-zinc-800" aria-live="polite" aria-busy={state.status === "loading"}>
          {state.status === "loading" && (
            <div className="space-y-2 py-0.5">
              <div className="skeleton h-3 w-11/12" />
              <div className="skeleton h-3 w-full" />
              <div className="skeleton h-3 w-2/3" />
            </div>
          )}
          {state.status === "error" && (
            <div className="flex items-start gap-3">
              <p className="min-w-0 flex-1 text-red-700">Не удалось получить объяснение: {state.message}</p>
              <Button size="sm" icon={RefreshCw} onClick={() => setAttempt((n) => n + 1)}>
                Повторить
              </Button>
            </div>
          )}
          {state.status === "ok" && <p className="whitespace-pre-line">{state.text}</p>}
        </div>
        {entry ? (
          <PlanEntry entry={entry} pattern={pattern} aspect={aspect} />
        ) : (
          <p className="text-[13px] leading-5 text-zinc-500">{hasPlan ? "Для этого слайда нет записи в плане раскладки." : "План раскладки (layout_plan.json) для варианта не сохранён."}</p>
        )}
      </CardBody>
    </Card>
  );
}

// ---- «Замечания слайда» ------------------------------------------------------------------------

interface IssuesProps {
  issues: Issue[];
  /** False when the variant has no audit report at all. */
  audited: boolean;
  highlightId: string | null;
  onHighlight(id: string | null): void;
  onOpenAudit(): void;
}

export function VariantsSlideIssues({ issues, audited, highlightId, onHighlight, onOpenAudit }: IssuesProps) {
  const hint = audited ? issuesSummary(issues) || "замечаний нет" : "проверка не запускалась";
  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader
        actions={
          <Button size="sm" iconRight={ArrowUpRight} onClick={onOpenAudit}>
            Все замечания
          </Button>
        }
      >
        <CardTitle icon={ShieldAlert} hint={hint}>
          Замечания слайда
        </CardTitle>
      </CardHeader>
      {issues.length === 0 ? (
        <EmptyState
          compact
          icon={audited ? CheckCircle2 : ShieldOff}
          title={audited ? "Замечаний нет" : "Аудит не запускался"}
          hint={audited ? "Проверки не нашли проблем на этом слайде." : "Для варианта нет отчёта audit_report.json — запустите проверку во вкладке «Аудит»."}
        />
      ) : (
        <ul className="scroll-thin max-h-[440px] divide-y divide-zinc-100 overflow-y-auto" onMouseLeave={() => onHighlight(null)}>
          {issues.map((issue) => {
            const fixable = !!issue.autofix && issue.autofix.action !== "none";
            return (
              <li
                key={issue.id}
                onMouseEnter={() => onHighlight(issue.id)}
                className={cn("px-5 py-3 transition-colors", highlightId === issue.id ? "bg-accent-50/60" : "hover:bg-zinc-50")}
              >
                <div className="flex items-center gap-2">
                  <Badge tone={SEVERITY_TONE[issue.severity]} size="sm" dot>
                    {SEVERITY_LABEL[issue.severity]}
                  </Badge>
                  <span className="font-mono text-[11px] text-zinc-500">{issue.check_id}</span>
                  {issue.kind === "model" && (
                    <Badge size="sm" tone="info" icon={Sparkles}>
                      модель
                    </Badge>
                  )}
                  <span className="ml-auto flex items-center gap-2">
                    {issue.bboxes.length === 0 && <span className="text-[11px] text-zinc-400">без области</span>}
                    {fixable && (
                      <Badge size="sm" tone="success" icon={Wand2} title={issue.autofix?.description}>
                        автофикс
                      </Badge>
                    )}
                  </span>
                </div>
                <p className="mt-1 text-[13px] leading-5 text-zinc-800">{issue.message}</p>
                {issue.suggestion && <p className="mt-0.5 text-xs leading-4 text-zinc-500">{issue.suggestion}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
