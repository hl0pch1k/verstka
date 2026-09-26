// The designer rules the template's analysis derived (the generator follows them, the quality check verifies them):
// up to five, in words. The font, its sizes and the colours are left out — the overview and «Шрифты и поля» show them.
import type { StyleRule } from "../types";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";

const LIMIT = 5;
/** Rules the overview's font tile, the palette and «Шрифты и поля» already show (and colours only as codes). */
const DUP = /^(?:Шрифты шаблона|Размеры шрифтов|Акцентные цвета|Основной цвет текста)(?![а-яё])/i;

/** A rule worth reading: a sentence of words, not a stray line of the template («font-family: …», «логотип / …»). */
function readable(text: string): boolean {
  const t = text.trim();
  if (/[{}]|font-family|https?:|#[0-9A-F]{6}\b/i.test(t) || t.split(/\s+/).length < 3) return false;
  return /[.!?)»]$/.test(t); // a finished sentence: the template's own stray lines are cut mid-phrase
}

export function StyleRulesCard({ rules }: { rules: StyleRule[] }) {
  const shown = rules
    .filter((r) => r.source === "derived" && !DUP.test(r.text.trim()) && readable(r.text))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, LIMIT);
  if (shown.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Правила оформления</CardTitle>
      </CardHeader>
      <CardBody className="pb-6 pt-2">
        <ul className="space-y-2">
          {shown.map((r, i) => (
            <li key={`${r.source}-${i}`} className="flex gap-3 text-body leading-6 text-zinc-700">
              <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden />
              <span className="min-w-0">{r.text}</span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
