import { test } from "node:test";
import assert from "node:assert/strict";
import { docMeta, hostOf, isDocFile, isKbFile, kbHead, kbHint, kbRequest, linkProblem, skippedLine, splitKbFiles } from "./kbRules";
import type { KbDoc, KbSummary } from "../../types";

const doc = (p: Partial<KbDoc>): KbDoc => ({ id: "d", name: "a.pdf", title: "A", kind: "pdf", source: "file", chars: 10, fragments: 4, ...p });

test("документы и база: какие файлы берутся", () => {
  assert.deepEqual(["a.docx", "b.PDF", "c.md", "d.pptx", "e.rtf"].map(isDocFile), [true, true, false, false, true]);
  assert.deepEqual(["a.zip", "b.html", "c.png", ".DS_Store", "x/.hidden.md"].map(isKbFile), [true, true, false, false, false]);
});

test("карточка документа и заголовок блока", () => {
  assert.equal(docMeta(doc({ pages: 3, fragments: 12 })), "PDF · 3 страницы · 12 фрагментов");
  assert.equal(docMeta(doc({ kind: "docx", tables: 2, fragments: 1 })), "DOCX · 2 таблицы · 1 фрагмент");
  assert.equal(docMeta(doc({ kind: "html", source: "link", url: "https://www.example.com/a", fragments: 5 })), "Ссылка · example.com · 5 фрагментов");
  assert.equal(hostOf("not a url"), "");
  const kb: KbSummary = { id: "k", name: "База", docs: [doc({}), doc({ id: "e" })], fragments: 21, chars: 100 };
  assert.equal(kbHead(kb), "2 документа · 21 фрагмент");
  assert.equal(kbHead(null), "Документы и ссылки на публичные страницы");
  assert.deepEqual(kbRequest(kb), { knowledge_id: "k" });
  assert.deepEqual(kbRequest({ ...kb, docs: [] }), {});
  assert.deepEqual(kbRequest(null), {});
});

test("ссылка: только http(s), без логина, с сайтом", () => {
  assert.equal(linkProblem("example.com/page"), null);
  assert.equal(linkProblem("https://example.com"), null);
  assert.equal(linkProblem(""), "Вставьте адрес страницы");
  assert.ok(/http/.test(linkProblem("ftp://example.com") ?? ""));
  assert.ok(/логином/.test(linkProblem("https://user:pw@example.com") ?? ""));
  assert.ok(/нет сайта/.test(linkProblem("https://localhost") ?? ""));
});

test("файлы до отправки: формат и размер", () => {
  const r = splitKbFiles([{ name: "a.pdf", size: 10 }, { name: "logo.png", size: 10 }, { name: "big.pdf", size: 30 * 1024 * 1024 }, { name: "all.zip", size: 60 * 1024 * 1024 }, { name: "dir/.DS_Store", size: 1 }]);
  assert.deepEqual(r.take, [0, 3]);
  assert.deepEqual(r.refused.map((x) => x.name), ["logo.png", "big.pdf"]);
  assert.equal(skippedLine(r.refused), "Не взяты 2 файла: «logo.png» — этот формат не читаю — подходят DOCX, PDF, MD, TXT, HTML и архив .zip");
  assert.equal(skippedLine([r.refused[1]]), "Не взят «big.pdf»: больше 25 МБ");
  assert.equal(skippedLine([]), null);
});

test("подсказка: без модели база не используется", () => {
  assert.ok(/Без модели/.test(kbHint(false, 2)));
  assert.ok(/источник/.test(kbHint(true, 2)));
  assert.ok(/Добавьте документы/.test(kbHint(true, 0)));
});
