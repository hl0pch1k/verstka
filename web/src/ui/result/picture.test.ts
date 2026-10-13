import { test } from "node:test";
import assert from "node:assert/strict";
import type { SlidePicture } from "../../types";
import { pickedPicture, pictureView, slidePictures } from "./picture";
import { variant } from "./remarks.fixtures";

const PIC: SlidePicture = {
  id: "s3-111", slide: 3, status: "generated", hint: "", label: "Фото", headline: "Интеграл обобщает сумму", model: "tongyi-mai/z-image", model_label: "Z-Image",
  palette_match: 1, bbox: { x: 0.4875, y: 0.0667, w: 0.4875, h: 0.8519 },
};

test("изображения слайда — только с местом на слайде", () => {
  const v = variant([], { pictures: [PIC, { ...PIC, id: "s3-2", bbox: null }, { ...PIC, id: "s4-1", slide: 4 }] });
  assert.deepEqual(slidePictures(v, 3).map((p) => p.id), ["s3-111"]);
  assert.deepEqual(slidePictures(v, 5), []);
});

test("выбранная картинка: та, что выбрана на этом слайде; пропала или другой слайд — колонки нет, чужая не подставляется", () => {
  const pics = slidePictures(variant([], { pictures: [PIC, { ...PIC, id: "s3-222" }] }), 3);
  assert.equal(pickedPicture({ k: "structured:3", id: "s3-222" }, "structured:3", pics)?.id, "s3-222");
  assert.equal(pickedPicture({ k: "structured:3", id: "s3-999" }, "structured:3", pics), null);
  assert.equal(pickedPicture({ k: "structured:4", id: "s3-111" }, "structured:3", pics), null);
  assert.equal(pickedPicture(null, "structured:3", pics), null);
});

test("карточка «Изображение»: что на ней, модель; место без картинки — почему пустует", () => {
  const g = pictureView(PIC);
  assert.deepEqual([g.title, g.tag, g.about, g.model, g.action, g.canRemove], ["Изображение", "сгенерировано", "К слайду «Интеграл обобщает сумму»", "Z-Image · в палитре шаблона 100%", "Заменить", true]);
  assert.equal(pictureView({ ...PIC, wish: "вид сверху" }).about, "По вашему описанию: вид сверху");
  assert.equal(pictureView({ ...PIC, hint: "Экран панели управления" }).about, "Экран панели управления");
  const own = pictureView({ id: "a", slide: 4, status: "free", own: true, label: "Фото", hint: "Вид теплицы сверху", why: "место под ваше фото — вставьте его в PowerPoint" });
  assert.deepEqual([own.title, own.tag, own.model, own.why, own.action, own.canRemove], ["Место под ваше фото", null, null, "Место под ваше фото — вставьте его в PowerPoint", "Сгенерировать всё равно", false]);
  assert.equal(pictureView({ ...PIC, model: "original", model_label: "исходная презентация" }).tag, "из исходной презентации");
  assert.equal(pictureView({ ...PIC, model: "original", model_label: "исходная презентация" }).model, null);
});
