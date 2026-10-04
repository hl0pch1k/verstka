// What the create screen reads in a text before anything is sent: the slides the text dictates (by the backend's own
// rules), the figures and the tables in it — the line under the field («В тексте: 6 слайдов, 14 чисел, 1 таблица»).
// Pure functions, no React.
import { plural } from "./utils";

// A text that dictates its slides, by the backend's rules (planning/brief_structure.py, compile.py `_order`,
// faithful.py `read_slide`): «Слайд 1 … Слайд 5» headings in ascending order (or «1. … 3.» headings with lines under
// each, in a text that speaks of slides) give a slide each, plus a cover unless the first one is a cover (its title
// says so, it names «Название:» / «Подзаголовок:», or it opens on a tagline — a short line without a final period —
// and holds no code, chart, table or picture of its own) or the text's own «на N слайдов» leaves no room for it;
// without headings «на 8 слайдов», «10 слайдов» give N.
const SPEC_HEAD = /^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*(\d{1,2})\s*(?:\*\*)?\s*(?:[.:)—–-]\s*|\s+|$)(.*?)\s*(?:\*\*)?\s*$/i;
const NUM_HEAD = /^\s*(?:#{1,6}\s*)?(\d{1,2})[.)]\s+(\S.{0,90})$/;
const COUNT = /(?:на|из|ровно|не более|не больше|максимум|до|в)\s+(\d{1,2})\s+слайд|(\d{1,2})\s+слайд(?:ов|а)(?![а-яё])|(\d{1,2})\s+slides?\b/i;
// (faithful.py _COVER_WORDS_RE: «Discovery» holds the letters of «cover» and is no cover)
const COVER = /титул|обложк|заглавн|\bcover\b|title\s+slide/i;
const TITLE_LINE = /^\s*(?:[—–\-•*]\s*)?(?:название|подзаголовок|заголовок|title|subtitle)\s*[:—–]/im;
const TABLE_LINE = /^\s*\|.*\|\s*$/m;
// what makes a slide more than a cover: a code fence, a note asking for a chart, a table or a picture, a sequence of steps
// the usual headings of a deck's parts (faithful.py SECTION_WORDS_RE): a first slide named so is content, not a cover
const SECTION_WORDS = /^(?:проблем|введени|актуальност|цел[ьи]|задач|решени|рын|контекст|обзор|о\s+(?:компании|проекте|нас|продукте)|предпосылк|план|содержани|повестк|итог|вывод|результат|команд|продукт|конкурент|бизнес-модел|финанс|риск|этап|ситуаци|аудитори|истори|предложени|problem|introduction|solution|market|overview|agenda|team|product|goal|result|conclusion|background|context)/i;
const RICH = /^\s*(?:```|~~~)|\[[^\]]*(?:диаграмм|график|гистограмм|таблиц|изображени|фото|картинк|иллюстрац|скриншот|схем)[^\]]*\]|→.*→/im;

const words = (s: string) => s.split(/\s+/).filter(Boolean).length;

interface Head { at: number; n: number; title: string }

function specHeads(lines: string[], text: string): Head[] {
  const heads: Head[] = [];
  lines.forEach((line, at) => {
    const m = SPEC_HEAD.exec(line);
    if (m && words(m[2]) <= 14) heads.push({ at, n: Number(m[1]), title: m[2] });
  });
  if (heads.length >= 2 && heads.every((h, i) => i === 0 || h.n > heads[i - 1].n)) return heads;
  if (!/слайд|slide/i.test(text)) return [];
  const nums: Head[] = [];
  lines.forEach((line, at) => {
    const m = NUM_HEAD.exec(line);
    if (m && words(m[2]) <= 10 && !/[;,]\s*$/.test(m[2])) nums.push({ at, n: Number(m[1]), title: m[2] });
  });
  if (nums.length < 3 || nums.some((h, i) => h.n !== i + 1)) return [];
  const ends = [...nums.slice(1).map((h) => h.at), lines.length];
  return nums.every((h, i) => lines.slice(h.at + 1, ends[i]).some((l) => l.trim())) ? nums : [];
}

export function dictatedSlides(text: string): number | null {
  const lines = text.split("\n");
  const c = COUNT.exec(text);
  const hard = c ? Number(c[1] ?? c[2] ?? c[3]) || null : null;
  const heads = specHeads(lines, text);
  if (heads.length === 0) return hard;
  // the first head is the cover when its title says so, or when it describes a title and a subtitle (not a table)
  const first = lines.slice(heads[0].at + 1, heads.length > 1 ? heads[1].at : lines.length).join("\n");
  const lead = first.split("\n").map((l) => l.trim()).find((l) => l) ?? "";
  const tagline = !!lead && words(lead) <= 14 && !/[.!?…]$/.test(lead) && !/^\s*(?:[-–—•*]|\d+[.)])\s/.test(lead);
  const paras = first.split(/\n\s*\n/).filter((b) => b.trim()).length;
  // (a first slide that is a heading alone is the cover too)
  const cover = !first.trim() || COVER.test(heads[0].title) || (TITLE_LINE.test(first) && !TABLE_LINE.test(first)) || (tagline && !RICH.test(first) && !TABLE_LINE.test(first) && paras <= 6 && !SECTION_WORDS.test(heads[0].title.trim()));
  return heads.length + (!cover && (hard === null || heads.length < hard) ? 1 : 0);
}

export interface TextFacts {
  /** The slides the text dictates (headings «Слайд 1 … Слайд 5», «на 8 слайдов»), null when it does not. */
  slides: number | null;
  /** Figures: numbers with or without a unit (a slide heading's number and a list's «1.» are not figures). */
  figures: number;
  /** Markdown tables. */
  tables: number;
}

// a number with its digit groups and decimals («1 240», «3,5», «18 %»); a slide heading's number and a list marker are
// skipped before counting
const FIGURE = /(?<![\p{L}\d])\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|(?<![\p{L}\d.,])\d+(?:[.,]\d+)?/gu;
const NOT_FIGURES = /^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*\d{1,2}|^\s*\d{1,2}[.)]\s/gim;
const TABLE_RULE = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/gm;

export function textFacts(text: string): TextFacts {
  const plain = text.replace(NOT_FIGURES, " ");
  return {
    slides: dictatedSlides(text),
    figures: (plain.match(FIGURE) ?? []).length,
    tables: (text.match(TABLE_RULE) ?? []).length,
  };
}

/** «6 слайдов, 14 чисел, 1 таблица» — only what the text has; null for a text with none of it. */
export function factsLine(f: TextFacts): string | null {
  const parts = [
    f.slides !== null ? plural(f.slides, "слайд", "слайда", "слайдов") : null,
    f.figures ? plural(f.figures, "число", "числа", "чисел") : null,
    f.tables ? plural(f.tables, "таблица", "таблицы", "таблиц") : null,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}
