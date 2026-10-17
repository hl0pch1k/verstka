// База знаний на «Создать» (направление I финальной доводки): правила без React — какие файлы она берёт, что пишет
// карточка документа и заголовок блока, какая ссылка годится, что уходит в запрос сборки. Сервер: verstka/knowledge,
// POST /api/knowledge…; агент пишет текст по её документам и у каждого факта называет документ и место.
import { plural } from "../../lib/utils";
import type { KbDoc, KbSummary } from "../../types";

const EXT_RE = /\.[a-z0-9]+$/i;
const extOf = (name: string) => (name.match(EXT_RE)?.[0] ?? "").toLowerCase();

/** Документы, которые сервер читает как текст с заголовками и таблицами (verstka/ingest/documents.py). */
export const DOC_EXTS = [".docx", ".pdf", ".doc", ".rtf", ".odt"];
/** Что берёт база знаний: документы, текст, страницы HTML, архив .zip с ними. */
export const KB_EXTS = [...DOC_EXTS, ".md", ".markdown", ".txt", ".html", ".htm", ".zip"];
export const KB_ACCEPT = [...KB_EXTS, "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"].join(",");
/** Документ больше этого не уходит (сервер: VERSTKA_MAX_DOC_MB, 25 МБ); архив — до 100 МБ за раз. */
const MB = 1024 * 1024;
export const MAX_DOC_BYTES = 25 * MB;
export const MAX_KB_UPLOAD_BYTES = 100 * MB;

export const isDocFile = (name: string): boolean => DOC_EXTS.includes(extOf(name));
export const isKbFile = (name: string): boolean => KB_EXTS.includes(extOf(name)) && !name.split("/").pop()!.startsWith(".");

const KIND_RU: Record<string, string> = { docx: "DOCX", pdf: "PDF", md: "Markdown", txt: "Текст", html: "Страница" };

/** Хозяин ссылки для карточки: «example.com». */
export function hostOf(url: string | null | undefined): string {
  try {
    return new URL(url ?? "").hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Вторая строка карточки: «PDF · 3 страницы · 12 фрагментов», «Ссылка · example.com · 4 фрагмента». */
export function docMeta(d: KbDoc): string {
  const parts: string[] = [];
  if (d.source === "link") parts.push("Ссылка", hostOf(d.url) || "страница");
  else parts.push(KIND_RU[d.kind] ?? d.kind.toUpperCase());
  if (d.pages) parts.push(plural(d.pages, "страница", "страницы", "страниц"));
  if (d.tables) parts.push(plural(d.tables, "таблица", "таблицы", "таблиц"));
  parts.push(plural(d.fragments, "фрагмент", "фрагмента", "фрагментов"));
  return parts.join(" · ");
}

/** Заголовок блока: «4 документа · 18 фрагментов»; пустая база — «пусто». */
export function kbHead(kb: KbSummary | null): string {
  const docs = kb?.docs.length ?? 0;
  if (!docs) return "Документы и ссылки на публичные страницы";
  return `${plural(docs, "документ", "документа", "документов")} · ${plural(kb!.fragments, "фрагмент", "фрагмента", "фрагментов")}`;
}

/** Что не так со ссылкой до отправки (пусто — годится; остальное проверит сервер: публичный адрес, размер, время). */
export function linkProblem(raw: string): string | null {
  const v = raw.trim();
  if (!v) return "Вставьте адрес страницы";
  if (/^[a-z][a-z0-9+.-]*:/i.test(v) && !/^https?:\/\//i.test(v)) return "Подходят только ссылки http:// и https://";
  const url = /^https?:\/\//i.test(v) ? v : `https://${v}`;
  try {
    const u = new URL(url);
    if (!u.hostname.includes(".")) return "В адресе нет сайта — проверьте ссылку";
    if (u.username || u.password) return "Страницы с логином и паролем в адресе не беру — нужна публичная страница";
  } catch {
    return "Адрес не читается — проверьте ссылку";
  }
  return null;
}

/** Файлы, которые база возьмёт, и отказ по остальным (не тот формат, слишком большой) — до отправки. */
export function splitKbFiles(files: { name: string; size: number }[]): { take: number[]; refused: { name: string; reason: string }[] } {
  const take: number[] = [];
  const refused: { name: string; reason: string }[] = [];
  files.forEach((f, i) => {
    const name = f.name.split("/").pop() ?? f.name;
    if (name.startsWith(".")) return;
    if (!isKbFile(name)) refused.push({ name, reason: "этот формат не читаю — подходят DOCX, PDF, MD, TXT, HTML и архив .zip" });
    else if (extOf(name) !== ".zip" && f.size > MAX_DOC_BYTES) refused.push({ name, reason: "больше 25 МБ" });
    else if (f.size > MAX_KB_UPLOAD_BYTES) refused.push({ name, reason: "больше 100 МБ" });
    else take.push(i);
  });
  return { take, refused };
}

/** Строка о том, что не взято: «Не взят «logo.png»: этот формат не читаю…», «Не взяты 3 файла: «a.png» — …». */
export function skippedLine(skipped: { name: string; reason: string }[]): string | null {
  if (!skipped.length) return null;
  const first = skipped[0];
  if (skipped.length === 1) return `Не взят «${first.name}»: ${first.reason}`;
  return `Не взяты ${plural(skipped.length, "файл", "файла", "файлов")}: «${first.name}» — ${first.reason}`;
}

/** Поле запроса сборки: база с документами — её id; пустая или её нет — поля нет. */
export function kbRequest(kb: KbSummary | null): { knowledge_id?: string } {
  return kb && kb.docs.length ? { knowledge_id: kb.id } : {};
}

/** Подсказка блока: что агент сделает с базой (и почему не сделает — модель не пишет тексты). */
export function kbHint(writer: boolean, docs: number): string {
  if (!docs) return "Добавьте документы — агент возьмёт факты из них и у каждого укажет источник";
  if (!writer) return "Без модели база знаний не используется — включите «Модель пишет тексты» в шаге 03";
  return "Агент возьмёт факты из этих документов, у каждого — источник в заметках слайда";
}
