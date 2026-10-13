import { test } from "node:test";
import assert from "node:assert/strict";
import { hasCyrillic, humanError } from "./errors";

const FB = "Не получилось. Попробуйте ещё раз.";

test("русский префикс остаётся, английский хвост сети («Failed to fetch») снимается", () => {
  assert.equal(
    humanError("Шаблон разобран, но не загрузился: Сеть недоступна: Failed to fetch", FB),
    "Шаблон разобран, но не загрузился: Сеть недоступна",
  );
});
test("хвост — статус ответа сервера («Not Found», «Internal Server Error») снимается", () => {
  assert.equal(humanError("Не удалось удалить шаблон: Not Found", FB), "Не удалось удалить шаблон");
  assert.equal(humanError("Не удалось переименовать: Internal Server Error", FB), "Не удалось переименовать");
  assert.equal(humanError("Не удалось загрузить: HTTP 502", FB), "Не удалось загрузить");
});
test("нет ни одного русского слова: даётся запасная строка", () => {
  assert.equal(humanError("OSError: [Errno 28] No space left on device", FB), FB);
  assert.equal(humanError("Failed to fetch", FB), FB);
  assert.equal(humanError("KeyError: 'ppt/presentation.xml'", FB), FB);
  assert.equal(humanError("", FB), FB);
  assert.equal(humanError("  \n ", FB), FB);
  assert.equal(humanError(null, FB), FB);
  assert.equal(humanError(undefined, FB), FB);
});
test("чисто русское сообщение не меняется", () => {
  for (const m of [
    "Шаблон не найден",
    "На этом шаблоне сейчас собирается презентация — удалите его, когда она будет готова",
    "Не удалось удалить шаблон — попробуйте ещё раз",
    "Нужен шаблон презентации: .pptx, .potx, .ppt или .odp",
    "PDF не подойдёт — нужен файл PowerPoint: .pptx или .potx",
  ]) assert.equal(humanError(m, FB), m);
});
test("сеть: «Сеть недоступна» остаётся без хвоста", () => {
  assert.equal(humanError("Сеть недоступна: Failed to fetch", FB), "Сеть недоступна");
  assert.equal(humanError("Не удалось переименовать: Сеть недоступна: NetworkError when attempting to fetch resource.", FB), "Не удалось переименовать: Сеть недоступна");
});
test("английский сегмент между русскими снимается, русские стоят в прежнем порядке", () => {
  assert.equal(humanError("Не удалось прочитать: ValueError: в файле нет слайдов", FB), "Не удалось прочитать: в файле нет слайдов");
});
test("английский префикс без русских слов снимается целиком", () => {
  assert.equal(humanError("Error: Файл повреждён", FB), "Файл повреждён");
});
test("после первой строки сервер дописывает трассировку: берётся первая строка", () => {
  assert.equal(humanError("Не удалось открыть: bad zip file\nTraceback (most recent call last):\n  File \"x.py\"", FB), "Не удалось открыть");
  assert.equal(humanError("\n  \nФайл пуст\nTraceback: плохо", FB), "Файл пуст");
});
test("двоеточие без пробела (время, адрес) не делит сообщение", () => {
  assert.equal(humanError("Не удалось дойти до сервера в 12:30", FB), "Не удалось дойти до сервера в 12:30");
});
test("запасная строка необязательна: по умолчанию русская", () => {
  assert.ok(hasCyrillic(humanError("Failed to fetch")));
});
test("hasCyrillic", () => {
  assert.equal(hasCyrillic("Ёж"), true);
  assert.equal(hasCyrillic("Failed to fetch"), false);
  assert.equal(hasCyrillic(""), false);
});
