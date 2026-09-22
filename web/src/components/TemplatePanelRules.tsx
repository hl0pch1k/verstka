// Designer rules derived from the template, plus the analysis warnings.
import { useState } from "react";
import { AlertTriangle, ListChecks } from "lucide-react";
import { cn, fmtPct, plural } from "../lib/utils";
import type { StyleRule } from "../types";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { Collapsible } from "./ui/Collapsible";

const SOURCE_RU: Record<string, { label: string; tone: BadgeTone; hint: string }> = {
  derived: { label: "из анализа", tone: "neutral", hint: "выведено детерминированно из фигур и текста шаблона" },
  template_text: { label: "текст шаблона", tone: "info", hint: "правило записано дизайнером прямо на слайдах шаблона" },
  heuristic: { label: "эвристика", tone: "neutral", hint: "выведено детерминированно из фигур и текста шаблона" },
  theme: { label: "тема файла", tone: "info", hint: "прочитано из темы PPTX" },
  llm: { label: "LLM", tone: "accent", hint: "сформулировано языковой моделью по структуре слайдов" },
  vlm: { label: "VLM", tone: "accent", hint: "сформулировано мультимодальной моделью по картинкам слайдов" },
  manual: { label: "вручную", tone: "success", hint: "добавлено человеком" },
};

const confidenceTone = (c: number) => (c >= 0.9 ? "bg-emerald-500" : c >= 0.7 ? "bg-accent" : "bg-amber-500");
const RULES_LIMIT = 8;

export function StyleRulesCard({ rules }: { rules: StyleRule[] }) {
  const [all, setAll] = useState(false);
  const sorted = [...rules].sort((a, b) => b.confidence - a.confidence);
  const shown = all ? sorted : sorted.slice(0, RULES_LIMIT);
  return (
    <Card>
      <CardHeader actions={rules.length > RULES_LIMIT && <Button size="sm" variant="ghost" onClick={() => setAll(!all)}>{all ? "Свернуть" : `Показать все ${rules.length}`}</Button>}>
        <CardTitle icon={ListChecks} hint="ограничения, которые соблюдает генератор и проверяет аудит">Правила дизайнера</CardTitle>
      </CardHeader>
      <CardBody className="py-2">
        {rules.length === 0 ? (
          <p className="py-2 text-[13px] text-zinc-500">Правила не выведены — генератор опирается только на токены и паттерны.</p>
        ) : (
          <ol className="divide-y divide-zinc-100">
            {shown.map((r, i) => {
              const src = SOURCE_RU[r.source] ?? { label: r.source, tone: "neutral" as BadgeTone, hint: "" };
              return (
                <li key={`${r.source}-${i}`} className="flex items-start gap-3 py-2.5">
                  <span className="mt-0.5 w-5 shrink-0 text-right text-[11px] tabular-nums text-zinc-400">{i + 1}</span>
                  <p className="min-w-0 flex-1 text-[13px] leading-5 text-zinc-800">{r.text}</p>
                  <div className="flex shrink-0 items-center gap-2 pt-0.5">
                    <Badge size="sm" tone={src.tone} title={src.hint}>{src.label}</Badge>
                    <span className="flex items-center gap-1.5" title={`уверенность ${fmtPct(r.confidence)}`}>
                      <span className="h-1 w-10 overflow-hidden rounded-full bg-zinc-200">
                        <span className={cn("block h-full rounded-full", confidenceTone(r.confidence))} style={{ width: `${Math.round(Math.min(1, Math.max(0, r.confidence)) * 100)}%` }} />
                      </span>
                      <span className="w-8 text-right text-[11px] tabular-nums text-zinc-500">{fmtPct(r.confidence)}</span>
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}

export function WarningsSection({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <Collapsible
      icon={<AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden />}
      title="Предупреждения анализа"
      hint={plural(warnings.length, "замечание", "замечания", "замечаний")}
      right={<Badge tone="warn" size="sm">{warnings.length}</Badge>}
    >
      <ul className="space-y-1.5">
        {warnings.map((w, i) => (
          <li key={i} className="flex items-start gap-2 text-[13px] leading-5 text-zinc-700">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
            <span className="min-w-0 break-words">{w}</span>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}
