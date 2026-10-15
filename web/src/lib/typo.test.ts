import { test } from "node:test";
import assert from "node:assert/strict";
import { bindShort } from "./typo";
import { STAGE_TITLE } from "./stage";

const NB = " ";

test("bindShort: короткий предлог и союз привязаны к следующему слову", () => {
  assert.equal(bindShort("Смотрю на слайды целиком"), `Смотрю на${NB}слайды целиком`);
  assert.equal(bindShort("Проверяю шрифты и цвета"), `Проверяю шрифты и${NB}цвета`);
  assert.equal(bindShort("Не получилось собрать презентацию"), `Не${NB}получилось собрать презентацию`);
  assert.equal(bindShort("Модель проверяет слайды по картинке"), `Модель проверяет слайды по${NB}картинке`);
  assert.equal(bindShort("Готовлюсь к сборке"), `Готовлюсь к${NB}сборке`);
});

test("bindShort: подряд идущие короткие слова, заглавные, уже привязанные и длинные слова", () => {
  assert.equal(bindShort("а в тексте"), `а${NB}в${NB}тексте`);
  assert.equal(bindShort("В тексте"), `В${NB}тексте`);
  assert.equal(bindShort(`Смотрю на${NB}слайды`), `Смотрю на${NB}слайды`);
  assert.equal(bindShort("Раскладываю по макетам"), `Раскладываю по${NB}макетам`);
  // «Пишу», «сюжет» и т. п. не короткие; слово в конце строки не к чему привязывать
  assert.equal(bindShort("Выстраиваю сюжет"), "Выстраиваю сюжет");
  assert.equal(bindShort("Пишу текст по"), "Пишу текст по");
  // внутри слова не срабатывает
  assert.equal(bindShort("Сверяю план"), "Сверяю план");
});

test("bindShort: в названиях фаз ни один короткий предлог или союз не остаётся перед обычным пробелом", () => {
  for (const [k, t] of Object.entries(STAGE_TITLE)) {
    const b = bindShort(t);
    assert.ok(!/(^|\s)(в|к|с|о|у|и|а|на|по|за|из|от|до|не) /iu.test(b), `${k}: ${b}`);
  }
});
