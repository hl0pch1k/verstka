// Изображение на слайде без React (boards/R-picture; V2 модуль `rt`): какие картинки и места под них есть на слайде и
// где, что говорит о картинке карточка «Изображение».
import { about as pictureAbout } from "../../lib/pictures";
import type { BboxFrac, SlidePicture, Variant } from "../../types";
import { cap, clampBox } from "./marks";

/** Изображения и места под них на слайде `n` — те, о которых сервер сказал, где они на слайде. */
export function slidePictures(v: Variant | null | undefined, n: number): Array<SlidePicture & { bbox: BboxFrac }> {
  return (v?.pictures ?? []).flatMap((p) => {
    const b = p.slide === n && p.bbox ? clampBox(p.bbox) : null;
    return b ? [{ ...p, bbox: b }] : [];
  });
}

/** Выбранная картинка (V2 `rtTogglePic`): та, что выбрана на этом слайде (`slideKey` — вариант и слайд). Выбрана на
 *  другом слайде или её больше нет на слайде — null: колонка «Изображение» закрывается, чужая картинка не
 *  подставляется. */
export function pickedPicture<P extends SlidePicture>(sel: { k: string; id: string } | null, slideKey: string, pics: P[]): P | null {
  if (!sel || sel.k !== slideKey) return null;
  return pics.find((p) => p.id === sel.id) ?? null;
}

/** Подпись места «Фото», «Изображение» ничего не говорит о картинке. */
const GENERIC = /^(?:фото|фотография|изображение|картинка|рисунок|иллюстрация|picture|image|photo)$/i;

/** Карточка «Изображение» (R-picture): заголовок, метка, что на картинке, модель, почему место пустует, главное
 *  действие и можно ли убрать картинку. */
export interface PictureView {
  title: string;
  tag: string | null;
  about: string;
  model: string | null;
  why: string | null;
  action: string;
  canRemove: boolean;
  generated: boolean;
}
export function pictureView(pic: SlidePicture): PictureView {
  const generated = pic.status === "generated";
  const original = generated && pic.model === "original";
  const own = !!pic.own && !generated;
  const words = pictureAbout(pic);
  // место исходной презентации подписано «… · 729ed8» — хвост для сервера
  const hint = (pic.hint ?? "").replace(/\s*·\s*[0-9a-f]{6,}\s*$/i, "").trim();
  const about = pic.wish?.trim() ? `По вашему описанию: ${pic.wish.trim()}`
    : hint || (words && !GENERIC.test(words) ? words : "") || (pic.headline?.trim() ? `К слайду «${pic.headline.trim()}»` : "");
  const pm = typeof pic.palette_match === "number" && Number.isFinite(pic.palette_match) ? `в палитре шаблона ${Math.round(pic.palette_match * 100)}%` : null;
  return {
    title: generated ? "Изображение" : own ? "Место под ваше фото" : "Место под изображение",
    tag: original ? "из исходной презентации" : generated ? "сгенерировано" : null,
    about,
    model: generated && !original ? [pic.model_label || pic.model || null, pm].filter(Boolean).join(" · ") || null : null,
    why: !generated && pic.why?.trim() ? cap(pic.why.trim()) : null,
    action: generated ? "Заменить" : own ? "Сгенерировать всё равно" : "Сгенерировать",
    canRemove: generated,
    generated,
  };
}
