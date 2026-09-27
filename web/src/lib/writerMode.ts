// Writer mode on the create screen: a text with no material of its own («История VK», «презентация про вторую
// мировую войну») is a topic, and the agent writes the deck's text before it builds the deck. This is the mirror of
// the server's rules (verstka/planning/writer.py `writer_mode` — keep the two in step): it only drives the one grey
// line in the bar («Текст напишет агент»); the server decides.
//   1. «не придумывай», «только по моему тексту» → the person's own text (faithful mode);
//   2. ≥ 2 slide headings, ≥ 2 table lines or ≥ 3 list lines → faithful;
//   3. ≥ 3 figures (years and the slide count do not count), ≥ 6 sentences or ≥ 70 words → faithful;
//   4. otherwise a topic («expand» when statements follow the first sentence).

export type WriterModeKind = "topic" | "expand";
export interface WriterModeOf { mode: WriterModeKind | null; privateHint: boolean }

const NO_WRITE = /не\s+(?:добавляй|придумывай|дописывай|выдумывай)|только\s+(?:по|из)\s+(?:моему\s+|этому\s+)?текст/i;
const SPEC_HEAD = /^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*\d{1,2}(?:\s|[.:)—–-]|$)/i;
const LIST_LINE = /^\s*(?:[—–\-•*]\s+|\d{1,2}[.)]\s+)/;
const YEAR = /(?<![\d.,])(?:1\d{3}|20\d{2})(?:\s*[-–—]\s*(?:1\d{3}|20\d{2}))?(?:\s*(?:год[а-яё]*|гг?\.?))?(?![\d.,])/gi;
const COUNT = /(?:(?:на|из|ровно|не\s+более|не\s+больше|максимум|до|в)\s+)?\d{1,2}\s+слайд[а-яё]*/gi;
// a figure: digits with their groups («14 500», «14,5»), not the digits of a name («Qwen3», «Q2»)
const NUMBER = /(?<![\wё.,])\d{1,3}(?:[\s ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\wё.,])\d+(?:[.,]\d+)?(?![\d])/g;
// «Сделай…», «Не перегружай…», «Используй…»: an instruction, not content (the server's `_is_rule`, roughly)
const RULE = /^(?:не\s+(?:перегружай|используй|добавляй|пиши|делай)|используй|сделай\s+(?:заголов|акцент|слайд)|добавь\s+(?:вывод|заметк)|пиши\s|тон\s|стиль\s|заголовки\s)/i;
const PRIVATE = /(?<![\p{L}\p{N}_])(?:наш[\p{L}]{0,3}|мо[йяеёи][\p{L}]{0,3}|мы|нас|нам|our|my|we)(?![\p{L}\p{N}_])/iu;
const FRONT = /^---\n[\s\S]*?\n---\n?/;

const MAX_FIGURES = 2;
const MAX_SENTENCES = 5;
const MAX_WORDS = 69;

/** Sentences of a text, line by line (a line without a stop is one sentence). */
function sentencesOf(text: string): string[] {
  const out: string[] = [];
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    const parts = s.split(/(?<=[.!?…])\s+(?=[«"„(]?[A-ZА-ЯЁ0-9])/).map((x) => x.trim()).filter(Boolean);
    out.push(...(parts.length ? parts : [s]));
  }
  return out;
}

/** Whether the create screen's text is a topic the agent will write («topic» / «expand»), or null (built strictly
 *  from the text). `privateHint`: the text speaks of «наш», «мы», «мой» — the subject may be the person's own (then
 *  the agent writes nothing about it, and the bar says nothing either). */
export function writerModeOf(text: string): WriterModeOf {
  const body = (text ?? "").replace(/\r\n/g, "\n").replace(FRONT, "").trim();
  const privateHint = PRIVATE.test(body);
  const off: WriterModeOf = { mode: null, privateHint };
  if (!body || NO_WRITE.test(body)) return off;
  const lines = body.split("\n").filter((l) => l.trim());
  if (lines.filter((l) => SPEC_HEAD.test(l)).length >= 2) return off;
  if (lines.filter((l) => l.trim().startsWith("|")).length >= 2) return off;
  if (lines.filter((l) => LIST_LINE.test(l)).length >= 3) return off;
  const sentences = sentencesOf(body).filter((s) => !RULE.test(s));
  const content = sentences.join(" ");
  const figures = content.replace(YEAR, " ").replace(COUNT, " ").match(NUMBER) ?? [];
  const words = content.match(/[\p{L}\p{N}_]+/gu) ?? [];
  if (figures.length > MAX_FIGURES || sentences.length > MAX_SENTENCES || words.length > MAX_WORDS) return off;
  return { mode: sentences.length > 1 ? "expand" : "topic", privateHint };
}
