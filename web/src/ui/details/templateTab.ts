// Вкладка «Шаблон» без React (boards/D-template, V2 модуль details `dlT`; логика — старый TemplatePanel*): обзор
// шаблона (имя, формат, слайды, типы слайдов, шрифт, палитра — клик копирует цвет), макеты (шесть, «Все N» — все),
// правила оформления и «Шрифты и поля». Данные — разбор шаблона презентации (`TemplateManifest`).
import { tplLabel } from "../../lib/plain";
import { kindLabel, plural } from "../../lib/utils";
import type { ColorToken, TemplateManifest } from "../../types";

const word = (n: number, one: string, few: string, many: string) => plural(n, one, few, many).replace(/^\d+\s/, "");
const RATIOS: Array<[string, number]> = [["16:9", 16 / 9], ["4:3", 4 / 3], ["16:10", 1.6], ["3:2", 1.5], ["1:1", 1]];

/** «16:9» — формат слайда по его размеру. */
export function slideRatio(size: { w: number; h: number }): string {
  if (!size.w || !size.h) return "—";
  const r = size.w / size.h;
  return RATIOS.find(([, v]) => Math.abs(v - r) < 0.02)?.[0] ?? `${r.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}:1`;
}

export function bandOf(m: TemplateManifest): { name: string; font: string | null; facts: { v: string; l: string }[] } {
  const kinds = new Set(m.patterns.map((p) => p.kind)).size;
  return {
    name: tplLabel(m),
    font: m.tokens.typography.families[0]?.family ?? null,
    facts: [
      { v: slideRatio(m.slide_size), l: "формат" },
      { v: String(m.n_slides), l: word(m.n_slides, "слайд", "слайда", "слайдов") },
      { v: String(kinds), l: `${word(kinds, "тип", "типа", "типов")} слайдов` },
    ],
  };
}

// ---- палитра ---------------------------------------------------------------------------------------------------------

const hexOf = (hex: string) => (hex.startsWith("#") ? hex : `#${hex}`).toUpperCase();
const SEMANTIC: Record<string, string> = { negative: "для негатива", positive: "для позитива", warning: "для предупреждений" };

function roleLabel(role: string): string {
  const [base, sub] = role.split(".");
  if (base === "background") return sub === "dark" ? "тёмный фон" : sub === "light" ? "светлый фон" : "фон";
  if (base === "surface") return "подложка";
  if (base === "text") return sub === "secondary" ? "второстепенный текст" : sub === "inverse" ? "текст на тёмном" : "основной текст";
  if (base === "accent") return "акцент";
  if (base === "neutral") return "нейтральный";
  return role;
}

/** Что цвет делает в шаблоне: «фирменный», «основной текст», «акцент»… */
export function colorRole(c: ColorToken): string {
  if (c.is_brand) return "фирменный";
  if (c.semantic) return SEMANTIC[c.semantic] ?? c.semantic;
  const roles = c.roles.length ? c.roles : c.role ? [c.role] : [];
  return roles[0] ? roleLabel(roles[0]) : "дополнительный";
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hexOf(hex).slice(i, i + 2), 16));
const near = (a: string, b: string) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i])) < 12;

/** Палитра ленты: до шести цветов по доле площади, почти одинаковые (#FAFCFF и #FEFFFF) — один цвет. */
export function paletteOf(m: TemplateManifest): { hex: string; tip: string }[] {
  const kept: ColorToken[] = [];
  for (const c of m.tokens.colors.slice(0, 16)) {
    const twin = kept.find((k) => near(k.hex, c.hex));
    if (twin) twin.weight += c.weight;
    else kept.push({ ...c });
  }
  return kept.sort((a, b) => b.weight - a.weight).slice(0, 6).map((c) => {
    const hex = hexOf(c.hex);
    return { hex, tip: `${hex} · ${colorRole(c)} · нажмите, чтобы скопировать` };
  });
}

/** Строка над лентой: подсказка, а после клика — «Цвет #0077FF скопирован» (или почему нет). */
export function copyHint(copied: { hex: string; ok: boolean } | null): string {
  if (!copied) return "нажмите, чтобы скопировать";
  return copied.ok ? `Цвет ${copied.hex} скопирован` : "Не удалось скопировать";
}

// ---- правила, шрифты и поля, макеты ----------------------------------------------------------------------------------

/** Правила, которые уже показывают обзор (шрифт, палитра) и «Шрифты и поля». */
const DUP = /^(?:Шрифты шаблона|Размеры шрифтов|Акцентные цвета|Основной цвет текста)(?![а-яё])/i;
/** Правило, которое стоит читать: законченная фраза словами, а не строка шаблона («font-family: …»). */
const readable = (t: string) => !/[{}]|font-family|https?:|#[0-9A-F]{6}\b/i.test(t) && t.split(/\s+/).length >= 3 && /[.!?)»]$/.test(t.trim());

export function rulesOf(m: TemplateManifest): string[] {
  return m.style_rules
    .filter((r) => r.source === "derived" && !DUP.test(r.text.trim()) && readable(r.text))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 5)
    .map((r) => r.text.trim());
}

const SCALE: Record<string, string> = { display: "Обложка", h1: "Заголовок", h2: "Подзаголовок", h3: "Заголовок блока", body: "Текст", small: "Мелкий текст", caption: "Подпись" };
const pct = (v: number) => `${Math.round(Math.max(0, v) * 100)}\u00a0%`;
const pt = (v: number) => v.toLocaleString("ru-RU", { maximumFractionDigits: 1 });

/** «Шрифты и поля» (для дизайнера): шкала шрифтов шаблона и поля, которые держат слайды. */
export function fontRows(m: TemplateManifest): { a: string; b: string }[] {
  const t = m.tokens.typography;
  const family = t.families[0]?.family ?? "";
  const rows = t.scale.map((s) => ({ a: SCALE[s.role] ?? s.role, b: [family ? `${family}${s.weight_bold_share > 0.5 ? " Bold" : ""}` : null, `${pt(s.size_pt)} пт`].filter(Boolean).join(" · ") }));
  const sa = m.tokens.spacing?.safe_area;
  if (sa) rows.push({ a: "Поля", b: `слева ${pct(sa.x)}, справа ${pct(1 - sa.x - sa.w)}, сверху ${pct(sa.y)}, снизу ${pct(1 - sa.y - sa.h)}` });
  return rows;
}

export interface LayoutTile { key: string; n: number; kind: string; img: string | null; delay: string }

/** Макеты шаблона по порядку слайдов: шесть, а «Все N» — все. Лесенка: первые шесть — с 200 мс, открытые «Все» — с 0. */
export function layoutsOf(m: TemplateManifest, all: boolean): LayoutTile[] {
  const list = m.patterns.slice().sort((a, b) => a.source_slide - b.source_slide);
  return (all ? list : list.slice(0, 6)).map((p, i) => ({
    key: p.id, n: p.source_slide, kind: kindLabel(p.kind), img: p.thumbnail_url ?? null,
    delay: `${i < 6 ? 200 + i * 40 : Math.min(i - 6, 7) * 40}ms`,
  }));
}
