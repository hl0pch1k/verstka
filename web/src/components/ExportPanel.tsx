// «Файлы»: every variant's deck in one card — a row per variant with PowerPoint, PDF and the web version. The JSON
// artefacts of the run live in the passport's «Для разработчиков».
import { Download, FileText, Globe, Presentation } from "lucide-react";
import { fileSafe } from "../lib/plain";
import { cn, scoreTone, TONE_TEXT } from "../lib/utils";
import { useApp } from "../store";
import { Card, CardHeader, CardTitle } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { LinkButton } from "./ui/Button";
import { variantScore } from "./VariantsHelpers";

export function ExportPanel() {
  const { generation, generationLoading, activeStrategy, strategyTitle } = useApp();
  if (generationLoading && !generation) return <div className="skeleton h-56 rounded-2xl" aria-busy />;
  if (!generation || generation.variants.length === 0) {
    return (
      <Card>
        <EmptyState compact icon={Download} title="Файлов пока нет" />
      </Card>
    );
  }
  const active = activeStrategy ?? generation.variants[0].strategy;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Файлы</CardTitle>
      </CardHeader>
      <ul className="divide-y divide-zinc-100 pb-3">
        {generation.variants.map((v, i) => {
          const score = variantScore(v, generation.summary?.[v.strategy]?.score);
          const name = strategyTitle(v.strategy);
          const base = `${fileSafe(v.outline?.title || generation.title || "Презентация")} — ${name}`;
          const pptx = v.files["deck.pptx"] ?? null;
          const pdf = v.files["deck.pdf"] ?? null;
          const html = v.files["deck.html"] ?? null;
          // on the tinted row of the variant on screen the buttons are white, as on every tinted surface
          const current = v.strategy === active;
          return (
            <li key={v.strategy} className={cn("flex h-14 items-center gap-3 px-6", current && "bg-accent-50")} aria-current={current || undefined}>
              <span className="min-w-0 truncate text-body font-semibold text-zinc-900">
                <span className="font-normal tabular-nums text-zinc-500">{i + 1}</span> · {name}
              </span>
              {score !== null && <span className={cn("text-footnote font-semibold tabular-nums", TONE_TEXT[scoreTone(score)])} title={`Оценка качества ${Math.round(score)} из 100`}>{Math.round(score)}</span>}
              <span className="ml-auto flex shrink-0 items-center gap-2">
                {pptx && (
                  <LinkButton variant={current ? "white" : "secondary"} size="md" icon={Presentation} href={pptx} download={`${base}.pptx`} title={`${base}.pptx`}>
                    PowerPoint
                  </LinkButton>
                )}
                {pdf && (
                  <LinkButton variant={current ? "white" : "secondary"} size="md" icon={FileText} href={pdf} download={`${base}.pdf`} title={`${base}.pdf`}>
                    PDF
                  </LinkButton>
                )}
                {html && (
                  <LinkButton variant={current ? "white" : "secondary"} size="md" icon={Globe} href={html} target="_blank" rel="noopener noreferrer" title="Откроется в новой вкладке">
                    Веб
                  </LinkButton>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
