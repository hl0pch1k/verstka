// Designer rules read out of the template (the generator follows them, the quality check verifies them) and what
// the analysis could not make out.
import { useState } from "react";
import { plural } from "../lib/utils";
import type { StyleRule } from "../types";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { Collapsible } from "./ui/Collapsible";

const SOURCE_RU: Record<string, string> = {
  template_text: "написано в шаблоне",
  theme: "из темы файла",
  llm: "сформулировала модель",
  vlm: "сформулировала модель",
  manual: "добавлено вручную",
};
const LIMIT = 8;

export function StyleRulesCard({ rules }: { rules: StyleRule[] }) {
  const [all, setAll] = useState(false);
  if (rules.length === 0) return null;
  const sorted = [...rules].sort((a, b) => b.confidence - a.confidence);
  const shown = all ? sorted : sorted.slice(0, LIMIT);
  return (
    <Card>
      <CardHeader actions={rules.length > LIMIT && <button type="button" onClick={() => setAll(!all)} className="cursor-pointer text-[13px] font-semibold text-accent-700 hover:underline">{all ? "Свернуть" : `Все ${rules.length}`}</button>}>
        <CardTitle hint="Им следует сборка слайдов, и их проверяет проверка качества">Правила оформления</CardTitle>
      </CardHeader>
      <CardBody className="pt-1">
        <ol className="space-y-2.5">
          {shown.map((r, i) => (
            <li key={`${r.source}-${i}`} className="flex gap-3 text-[14px] leading-5 text-zinc-800">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
              <span className="min-w-0">
                {r.text}
                {SOURCE_RU[r.source] && <span className="ml-1.5 text-xs text-zinc-400">{SOURCE_RU[r.source]}</span>}
              </span>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}

export function WarningsSection({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <Collapsible title="Что не удалось разобрать" hint={plural(warnings.length, "замечание", "замечания", "замечаний")}>
      <ul className="space-y-1.5">
        {warnings.map((w, i) => (
          <li key={i} className="flex items-start gap-2 text-[13px] leading-5 text-zinc-700">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" aria-hidden />
            <span className="min-w-0 break-words">{w}</span>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}
