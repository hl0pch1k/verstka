// Черновик «Создать» в localStorage (`verstka.brief_draft`): один JSON-объект, как прежде. Поле `brief` — текст шага
// «Текст»; параметры шага 03 ложатся рядом своими полями. Запись сливает новое с тем, что уже лежит.
import { LS, storage } from "./utils";

export type Draft = Record<string, unknown>;

export function readDraft(): Draft {
  try {
    const d = JSON.parse(storage.get(LS.brief) ?? "null") as unknown;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as Draft) : {};
  } catch {
    return {};
  }
}

export function writeDraft(patch: Draft): void {
  storage.set(LS.brief, JSON.stringify({ ...readDraft(), ...patch }));
}

/** Текст поля из черновика (пусто, если черновика нет или он испорчен). */
export function draftBrief(): string {
  const b = readDraft().brief;
  return typeof b === "string" ? b : "";
}
