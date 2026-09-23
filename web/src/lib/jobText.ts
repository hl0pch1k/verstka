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
