// Компактный вид «Результата» без React (boards/G-helper, G-helper-open; V2 `hp-ncol`): итоги проверки в узкой колонке
// 184 px — качество, сверенные числа и откуда текст. Числа — те же, что у карточки «Качество» полного вида
// (qualityCard), чего в данных нет — того пункта нет.
import { templateTitle } from "../../lib/plain";
import type { Generation, Variant } from "../../types";
import type { IconName } from "../kit/icons";
import { qualityCard } from "./resultView";

/** Пункт итогов: значок, жирное начало и остальное; `title` — подсказка целиком. */
export interface CheckItem { icon: IconName; tone: "ok" | "warn" | "error"; lead: string; rest: string; title: string }

const pages = (g: Generation) => {
  const w = g.writer;
  const list = (w?.pages ?? []).filter((p) => p?.title);
  return list.length ? list : w?.source?.title ? [w.source] : [];
};

/** Откуда текст (V2 `hpSrc`): агент по статье Википедии, «Улучшить готовую» — исходная презентация, уведомление
 *  результата — его заголовок, иначе свой текст. */
export function sourceText(g: Generation, note: { title: string } | null): string {
  if (g.writer?.status === "written" && g.writer.text) {
    const p = pages(g);
    if (!p.length) return "Текст написал агент по своим знаниям — проверьте даты и цифры";
    const names = p.map((x, i) => `${i === 0 ? "" : i === p.length - 1 ? " и " : ", "}«${x.title}»`).join("");
    return `Текст написал агент — по ${p.length > 1 ? "статьям" : "статье"} ${names} в Википедии`;
  }
  if (g.improved_from?.name) return `Текст из презентации «${templateTitle(g.improved_from.name)}»`;
  return note?.title || "Ваш текст — агент разложил его по слайдам";
}

/** «9 чисел сверены с текстом» → «9 чисел» и « сверены с текстом». */
function splitCount(text: string): { lead: string; rest: string } {
  const m = /^(\d[\d\s ]*\S+)(.*)$/.exec(text);
  return m ? { lead: m[1], rest: m[2] } : { lead: "", rest: text };
}

/** Итоги проверки узкой колонки: качество (ошибки · предупреждения), сверенные числа, источник текста. */
export function compactChecks(g: Generation, v: Variant, note: { title: string } | null): CheckItem[] {
  const out: CheckItem[] = [];
  const q = qualityCard(g, v);
  if (q) {
    out.push({
      icon: q.errors ? "alert" : "check-circle", tone: q.errors ? "error" : "ok",
      lead: q.verdict ?? `Оценка ${q.score}`, rest: q.warnings ? ` · ${q.warnings}` : "", title: q.title,
    });
    if (q.figures) out.push({ icon: "numbers", tone: q.figures.tone, ...splitCount(q.figures.text), title: q.figures.title ?? q.figures.text });
  }
  const src = sourceText(g, note);
  out.push({ icon: "book", tone: "ok", lead: "", rest: src, title: src });
  return out;
}
