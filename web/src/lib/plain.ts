import type { PlannerInfo } from "../types";
import { reasonWords } from "./modelText";

// Plain words for the interface: what a variant is, in one line a non-designer understands.
export const VARIANT_HINT: Record<string, string> = {
  structured: "Одна мысль на слайд, по порядку",
  visual: "Крупные цифры и диаграммы",
  compact: "Плотные композиции: колонки и таблицы",
};

export const variantHint = (name: string, fallback?: string) => VARIANT_HINT[name] ?? fallback ?? "";

/** Who wrote the plan of a variant, in words (outline.planned_by; the model's name and the reason when known). */
export function plannedByText(plannedBy: string | undefined, strategyTitle: (name: string) => string, planner?: PlannerInfo | null): string {
  const by = planner?.planned_by === "supplied" ? "supplied" : plannedBy ?? planner?.planned_by ?? null;
  const model = planner?.model_label ? `модель ${planner.model_label}` : "модель";
  if (by === "supplied") return "ваш готовый план";
  if (by === "model") return model;
  if (by === "agent") return planner?.model_label ? `агент: слайды продумала модель ${planner.model_label}` : "агент: слайды продумала модель";
  if (by === "skeleton") return "каркас по теме";
  if (by?.startsWith("shared:")) return `${model}, план варианта «${strategyTitle(by.slice(7))}»`;
  if (!by) return "не записано";
  const why = reasonWords(planner);
  return why ? `встроенный планировщик: ${why}` : "встроенный планировщик";
}

export const templateName = (file: string | null | undefined, fallback = "Шаблон") => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");

/** A template's short name for people: «ЛЦТ2026», «VK Tech», «VK Education», «VK WorkSpace Клиентская конференция».
 *  Drops .pptx, underscores, the word «шаблон (презентации)» and a trailing number; falls back to templateName(file). */
export function templateTitle(file: string | null | undefined, fallback?: string): string {
  if (!file) return fallback ?? templateName(file);
  const t = file
    .replace(/\.pptx$/i, "")
    .replace(/_/g, " ")
    .replace(/\s*шаблон(?:а)?(?:\s+презентаци[ия])?(?![а-яё])\s*/gi, " ")
    .trim()
    .replace(/[\s_]+\d{1,3}$/, "") // «…_Шаблон_03» → «…», but «ЛЦТ2026» keeps its digits
    .replace(/\s+/g, " ")
    .trim();
  return t || templateName(file, fallback);
}

// English layout words the model sometimes leaves in its reasoning → the words the interface uses (field names, then
// the slide kinds; `_` counts as a letter, so «image_text» is one word)
const W = (word: string) => new RegExp(`(?<![A-Za-z_])${word}(?![A-Za-z_])`, "gi");
const TERMS: Array<[RegExp, string]> = [
  [/\bbig[_\s-]?numbers?\b/gi, "большое число"],
  [/\bstat[_\s-]?rows?\b/gi, "ряд чисел"],
  [/\btwo[_\s-]?columns?\b/gi, "две колонки"],
  [/\btakeaways?\b/gi, "вывод"],
  [/\bbullets?\b/gi, "пункты"],
  [/\bheadlines?\b/gi, "заголовок"],
  [/\bsubtitles?\b/gi, "подзаголовок"],
  [/\bfootnotes?\b/gi, "сноска"],
  [/\bcallouts?\b/gi, "выноска"],
  [/\bkpis?\b/gi, "показатели"],
  [W("cards?"), "карточки"],
  [W("charts?"), "диаграмма"],
  [W("tables?"), "таблица"],
  [W("timelines?"), "хронология"],
  [W("comparisons?"), "сравнение"],
  [W("image_text"), "картинка и текст"],
  [W("quotes?"), "цитата"],
  [W("agenda"), "повестка"],
  [W("process"), "процесс"],
  [W("mockups?"), "макет экрана"],
  [/\bbrief\b/gi, "текст"],
  [/(?<![а-яёa-z])бриф(а|е|ом|у)?(?![а-яё])/gi, "текст$1"],
];

// the form a reason starts with, quoted as a name, so the verb agrees with «Форма»: «Формат две колонки позволяет…» →
// «Форма «две колонки» позволяет…» (the same rule as the server's tidy_form and lib/agent's plainWords)
const FORM_NAMES = "большое число|ряд чисел|две колонки|карточки|пункты|список|диаграмма|таблица|хронология|сравнение|картинка и текст|цитата|повестка|процесс|макет экрана";
const FORM_LEAD = new RegExp(`^(\\s*)Формат?\\s+«?(${FORM_NAMES})»?(?=[\\s,.:;!?]|$)`, "i");

const capital = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** The model's reasoning in the interface's words: layout ids (big_number, bullets, takeaway, cards…) → Russian, «бриф» →
 *  «текст», and a leading «Формат/Форма <form>» becomes «Форма «<form>»». Whole words, case-insensitive; a capital
 *  stays at a sentence start. Idempotent. */
export function plainTerms(text: string): string {
  if (!text) return text;
  let out = text;
  for (const [re, word] of TERMS) {
    out = out.replace(re, (_m: string, ...rest: unknown[]) => {
      const offset = rest.find((x) => typeof x === "number") as number;
      const src = rest[rest.length - 1] as string;
      const ending = typeof rest[0] === "string" ? (rest[0] as string) : "";
      const rep = word.replace("$1", ending);
      const before = src.slice(0, offset);
      const starts = /^\s*$/.test(before) || /[.!?…]\s+$/.test(before) || /[«"(]\s*$/.test(before);
      return starts ? capital(rep) : rep;
    });
  }
  return out.replace(FORM_LEAD, (_m: string, sp: string, name: string) => `${sp}Форма «${name.toLowerCase()}»`);
}

/** A safe file name: no \\ / : * ? " < > |, single spaces, at most 80 characters. */
export function fileSafe(name: string): string {
  const s = (name ?? "").replace(/[\\/:*?"<>|]/g, " ").replace(/\s+/g, " ").trim();
  return s.length > 80 ? s.slice(0, 80).trim() : s;
}
