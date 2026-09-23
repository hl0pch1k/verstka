// Progress messages of the pipeline are written for logs («visual: rendered slide 6/6»); the UI shows them in Russian.
import { plural } from "./utils";

const TEMPLATE_STEPS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^loaded cached manifest$/, () => "этот шаблон уже разобран раньше"],
  [/^opened package: (\d+) slides$/, (m) => `открыт файл: ${plural(Number(m[1]), "слайд", "слайда", "слайдов")}`],
  [/^extracted shapes$/, () => "фигуры и тексты прочитаны"],
  [/^extracted (\d+) assets$/, (m) => `найдено картинок и иконок: ${m[1]}`],
  [/^rendered slides$/, () => "слайды отрисованы"],
  [/^built tokens$/, () => "цвета, шрифты и сетка собраны"],
  [/^classified slides$/, () => "типы слайдов определены"],
  [/^assembled (\d+) patterns$/, (m) => `найдено ${plural(Number(m[1]), "макет", "макета", "макетов")} слайдов`],
  [/^derived components and rules$/, () => "правила оформления собраны"],
  [/^done$/, () => "готово"],
];

function templateStep(s: string): string {
  for (const [re, fn] of TEMPLATE_STEPS) {
    const m = s.match(re);
    if (m) return fn(m);
  }
  return s;
}

/** Where one variant of a generation is: a short status for its card and the share of its work done. */
export interface VariantProgress { text: string; done: boolean; frac: number }

/** «visual: rendered slide 6/10» → the progress of that variant; null for messages about the whole job. */
export function variantProgress(message: string): { name: string; state: VariantProgress } | null {
  const m = message.trim().match(/^([a-z_]+): (.+)$/);
  if (!m || m[1] === "analyze" || m[1] === "plan" || m[1] === "export") return null;
  const [, name, what] = m;
  let r: RegExpMatchArray | null;
  if ((r = what.match(/^rendered slide (\d+)\/(\d+)$/))) return { name, state: { text: `вёрстка ${r[1]} из ${r[2]}`, done: false, frac: 0.25 + 0.45 * (Number(r[1]) / Math.max(1, Number(r[2]))) } };
  if (/^planned \d+ slides/.test(what)) return { name, state: { text: "план готов", done: false, frac: 0.2 } };
  if (what === "audit") return { name, state: { text: "проверка качества", done: false, frac: 0.75 } };
  if (/^autofix/.test(what)) return { name, state: { text: "исправляю замечания", done: false, frac: 0.85 } };
  if (/^done in /.test(what)) return { name, state: { text: "готово", done: true, frac: 1 } };
  return null;
}

export function humanizeJobMessage(message: string, titleOf: (strategy: string) => string): string {
  const msg = message.trim();
  let m = msg.match(/^analyze: (.+)$/);
  if (m) return `Шаблон: ${templateStep(m[1])}`;
  m = msg.match(/^plan: (\d+) variants?$/);
  if (m) return `Планирую ${plural(Number(m[1]), "вариант", "варианта", "вариантов")}`;
  if (/^export: /.test(msg)) return "Сохраняю файлы: PowerPoint, PDF и веб-версию";
  m = msg.match(/^([a-z_]+): (.+)$/);
  if (m) {
    const who = titleOf(m[1]);
    const what = m[2];
    let r = what.match(/^planned (\d+) slides, rendering$/);
    if (r) return `${who}: план готов, ${plural(Number(r[1]), "слайд", "слайда", "слайдов")}`;
    r = what.match(/^rendered slide (\d+)\/(\d+)$/);
    if (r) return `${who}: свёрстан слайд ${r[1]} из ${r[2]}`;
    if (what === "audit") return `${who}: проверка качества`;
    r = what.match(/^autofix \((\d+) errors?\)$/);
    if (r) return `${who}: исправляю замечания${Number(r[1]) ? ` (${plural(Number(r[1]), "ошибка", "ошибки", "ошибок")})` : ""}`;
    r = what.match(/^done in ([\d.]+)s$/);
    if (r) return `${who}: готово за ${r[1].replace(".", ",")} с`;
    return `${who}: ${templateStep(what)}`;
  }
  return templateStep(msg);
}
