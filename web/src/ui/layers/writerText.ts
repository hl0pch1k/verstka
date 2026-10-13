// Слой «Текст презентации» без React (boards/R-text, V2 модуль `rt`): текст, который агент написал по теме
// (generation.json `writer`, planning/writer.py), разложенный по слайдам; предложения, у которых есть источник
// (`writer.sources`: утверждение текста → предложение статьи), — отдельные куски с номером источника; подпись под
// заголовком, строка «Источник» внизу коробки и полоса «04 Результат» над слоем. Разбор предложений — как в старом
// WriterText.tsx (79c6f81): утверждение ищется в строке как есть, а не нашлось — без точки или «;» в конце.
import type { WriterInfo } from "../../types";

/** Источник утверждения (generation.json `writer.sources`): утверждение, как оно в тексте, статья и её предложение. */
export interface WriterSource { text: string; page: string; url: string; sentence: string }
/** Кусок строки: текст и номер его источника в `sources` (null — без источника). */
export interface TextPiece { text: string; src: number | null }
/** Слайд текста: номер и заголовок из «Слайд N. Заголовок» (null и пусто — текст до первого заголовка), строки тела. */
export interface TextSlide { n: number | null; title: string; lines: TextPiece[][] }
interface Page { title: string; url: string }

const HEAD = /^\s*Слайд\s+(\d{1,3})\.\s*(.*)$/;

/** Текст для слоя: только написанный агентом и непустой; иначе null («Показать текст» приглушена). */
export function writtenText(w: WriterInfo | null | undefined): string | null {
  return w?.status === "written" && w.text?.trim() ? w.text : null;
}

/** Строка, разрезанная на утверждения с источником и текст между ними. Утверждение, которое пересекается с уже
 *  найденным, пропускается; пустое ни с чем не совпадает. */
export function linePieces(line: string, sources: WriterSource[]): TextPiece[] {
  const found: { at: number; end: number; src: number }[] = [];
  sources.forEach((s, k) => {
    let t = s.text.trim();
    let at = t ? line.indexOf(t) : -1;
    if (at < 0 && t) {
      t = t.replace(/[.;]$/, "");
      at = t ? line.indexOf(t) : -1;
    }
    if (at < 0 || found.some((f) => at < f.end && at + t.length > f.at)) return;
    found.push({ at, end: at + t.length, src: k });
  });
  if (!found.length) return [{ text: line, src: null }];
  found.sort((a, b) => a.at - b.at);
  const out: TextPiece[] = [];
  let pos = 0;
  for (const f of found) {
    if (f.at > pos) out.push({ text: line.slice(pos, f.at), src: null });
    out.push({ text: line.slice(f.at, f.end), src: f.src });
    pos = f.end;
  }
  if (pos < line.length) out.push({ text: line.slice(pos), src: null });
  return out;
}

/** Текст по слайдам: «Слайд N. Заголовок» открывает слайд, строки тела — как написаны (без хвостовых пробелов),
 *  пустые строки — разделители. Строки до первого заголовка — блок без номера. */
export function writerSlides(text: string, sources: WriterSource[]): TextSlide[] {
  const out: TextSlide[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    const m = HEAD.exec(line);
    if (m) {
      out.push({ n: Number(m[1]), title: m[2].trim(), lines: [] });
      continue;
    }
    if (!line.trim()) continue;
    if (!out.length) out.push({ n: null, title: "", lines: [] });
    out[out.length - 1].lines.push(linePieces(line, sources));
  }
  return out;
}

/** Первый источник по порядку чтения — он подсвечен, когда слой открылся (как на доске); в тексте их нет — null. */
export function firstSource(slides: TextSlide[]): number | null {
  for (const s of slides) for (const l of s.lines) for (const p of l) if (p.src !== null) return p.src;
  return null;
}

/** Статьи, по которым написан текст: `pages`, иначе `source`; агент писал по своим знаниям — пусто. */
function pagesOf(w: WriterInfo): Page[] {
  const pages = (w.pages ?? []).filter((p) => p?.title);
  return pages.length ? pages : w.source?.title ? [w.source] : [];
}

/** ««A»», ««A» и «B»», ««A», «B» и «C»». */
const titles = (pages: Page[]) =>
  pages.map((p, i) => `${i === 0 ? "" : i === pages.length - 1 ? " и " : ", "}«${p.title}»`).join("");

/** Подпись под заголовком слоя: «Написал агент по статье «Интеграл» из Википедии» (названия статей — ссылки). */
export function writerByline(w: WriterInfo): { lead: string; pages: Page[]; tail: string } {
  const pages = pagesOf(w);
  if (!pages.length) return { lead: "Написал агент по своим знаниям", pages: [], tail: "" };
  return { lead: `Написал агент по ${pages.length > 1 ? "статьям" : "статье"}`, pages, tail: "из Википедии" };
}

/** Ссылка на предложение статьи: фрагмент текста (браузер прокручивает к нему и подсвечивает). */
function sentenceLink(src: WriterSource, fallback: string | null): string | null {
  if (!src.url) return fallback;
  const words = src.sentence.replace(/[«»"()]/g, " ").split(/\s+/).filter(Boolean).slice(0, 6).join(" ");
  return words ? `${src.url}#:~:text=${encodeURIComponent(words)}` : src.url;
}

/** Строка «Источник» внизу коробки: выбранное предложение статьи в кавычках и ссылка на него; источников нет —
 *  статья (статьи) и ссылка на неё; агент писал по своим знаниям — об этом, без ссылки. `title` — подсказка ссылки. */
export function sourceLine(w: WriterInfo, sources: WriterSource[], sel: number | null): { quote: string; href: string | null; label: string; title: string } {
  const pages = pagesOf(w);
  const article = pages[0]?.url || null;
  const src = sel !== null ? sources[sel] : undefined;
  if (src) {
    const page = src.page || pages[0]?.title || "";
    return { quote: `«${src.sentence.trim()}»`, href: sentenceLink(src, article), label: "Википедия", title: page ? `Статья «${page}» в Википедии` : "Википедия" };
  }
  if (!pages.length) return { quote: "знания агента — проверьте даты и цифры", href: null, label: "", title: "" };
  return {
    quote: `${pages.length > 1 ? "статьи" : "статья"} ${titles(pages)} в Википедии`,
    href: article,
    label: "Википедия",
    title: `Статья «${pages[0].title}» в Википедии`,
  };
}

/** Полоса «04 Результат» над слоем (V2 `rtStripMeta`): «Структурный · 89 из 100 · слайд 3 из 12»; чего нет — того нет. */
export function textStripMeta(variant: string, score: number | null, n: number, total: number): string {
  return [variant, score === null ? null : `${Math.round(score)} из 100`, total > 0 ? `слайд ${n} из ${total}` : null].filter(Boolean).join(" · ");
}
