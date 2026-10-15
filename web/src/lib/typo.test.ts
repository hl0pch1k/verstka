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

test("bindShort: в названиях фаз без неразрывных пробелов ни один короткий предлог или союз не остаётся перед обычным пробелом", () => {
  // STAGE_TITLE уже с неразрывными пробелами — проверяется сырой текст (с обычными), иначе тест ничего не проверяет
  for (const [k, t] of Object.entries(STAGE_TITLE)) {
    const raw = t.replace(/\u00a0/g, " ");
    const b = bindShort(raw);
    assert.ok(!/(^|\s)(в|к|с|о|у|и|а|на|по|за|из|от|до|не) /iu.test(b), `${k}: ${b}`);
    assert.equal(b.replace(/\u00a0/g, " "), raw, k);
  }
  assert.equal(bindShort("Сверяю план с текстом"), `Сверяю план с${NB}текстом`);
  assert.equal(bindShort("Проверяю шрифты и цвета"), STAGE_TITLE.check);
});

test("bindShort: через тире и закрывающие знаки не привязывает; к числу, кавычке и скобке — привязывает", () => {
  assert.equal(bindShort("план и — текст"), "план и — текст");
  assert.equal(bindShort("план и – текст"), "план и – текст");
  assert.equal(bindShort("план и … текст"), "план и … текст");
  assert.equal(bindShort("«план и » текст"), "«план и » текст");
  assert.equal(bindShort("на 12 слайдов"), `на${NB}12 слайдов`);
  assert.equal(bindShort("по «Плану»"), `по${NB}«Плану»`);
  assert.equal(bindShort("для (черновика)"), `для${NB}(черновика)`);
});

test("bindShort: частица «ли» относится к предыдущему слову — вперёд не привязывается", () => {
  assert.equal(bindShort("Есть ли ошибки"), "Есть ли ошибки");
  assert.equal(bindShort("Верно ли посчитано"), "Верно ли посчитано");
});
