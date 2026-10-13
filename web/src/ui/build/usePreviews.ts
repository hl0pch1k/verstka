// Настоящие превью сверстанных слайдов для раскадровки. Превью пишет экспорт (с 86 % хода): с этого момента каждые
// 1,5 с спрашивается список готовых превью варианта (api.slideList) и грузятся только названные — запроса к картинке,
// которой ещё нет, не бывает; не загрузившаяся пробуется в следующий круг. Готовые встают вместо эскизов по три
// (V2 `LDN`: 3, 6, 9, 12 — такт 450 мс), а не все разом. Опрос идёт, пока идёт сборка: кончилась (или упала) — ещё
// один круг и всё; превью держатся за генерацию — у повтора («Собрать ещё раз») свои, прежние к нему не пристают.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";

const POLL_MS = 1500;
/** Предел опроса: 200 кругов по 1,5 с — пять минут экспорта на вариант. */
export const MAX_ROUNDS = 200;
/** Превью встают по три за такт. */
const BATCH = 3;
const TICK_MS = 450;

const slideUrl = (gid: string, variant: string, n: number) =>
  `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(variant)}/slides/slide-${String(n).padStart(3, "0")}.jpg`;

/** Ключ превью варианта: генерация и вариант («Структурный» повтора — не «Структурный» прежней сборки); "" — нечего. */
export const previewKey = (gid: string | null | undefined, variant: string | null | undefined): string =>
  gid && variant ? `${gid}/${variant}` : "";

/** Спросить список ещё раз: сборка идёт, превью ещё не все, предел кругов не пройден. */
export const pollAgain = (s: { live: boolean; have: number; count: number; round: number }): boolean =>
  s.live && s.have < s.count && s.round < MAX_ROUNDS;

/** Превью варианта `variant` генерации `gid`, уже загруженные браузером и открытые по три: вариант → адреса по порядку
 *  слайдов. `enabled` — пора спрашивать (экспорт начался), `live` — сборка идёт (опрос продолжается). */
export function usePreviews(gid: string | null | undefined, variant: string | null, count: number, enabled: boolean, live: boolean): Record<string, string[]> {
  const key = previewKey(gid, variant);
  // генерация/вариант → номер слайда → адрес (загружен)
  const [found, setFound] = useState<Record<string, Record<number, string>>>({});
  const foundRef = useRef(found);
  foundRef.current = found;
  useEffect(() => {
    if (!gid || !variant || !key || !enabled || count <= 0) return;
    let alive = true;
    let timer = 0;
    let round = 0;
    const have = () => Object.keys(foundRef.current[key] ?? {}).length;
    const load = (name: string) =>
      new Promise<void>((resolve) => {
        const n = Number(name.match(/(\d+)/)?.[1] ?? NaN);
        if (!Number.isFinite(n) || foundRef.current[key]?.[n]) return resolve();
        const url = slideUrl(gid, variant, n);
        const img = new Image();
        img.onload = () => {
          if (alive) setFound((m) => (m[key]?.[n] ? m : { ...m, [key]: { ...m[key], [n]: url } }));
          resolve();
        };
        img.onerror = () => resolve();
        img.src = url;
      });
    const next = async () => {
      round += 1;
      let names: string[] = [];
      try {
        names = (await api.slideList(gid, variant)).slides;
      } catch {
        /* сервер занят экспортом: следующий круг спросит снова */
      }
      if (!alive) return;
      await Promise.all(names.map(load));
      if (alive && pollAgain({ live, have: have(), count, round })) timer = window.setTimeout(next, POLL_MS);
    };
    void next();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [gid, variant, key, count, enabled, live]);

  // сколько превью варианта уже открыто: прибавляется по три за такт, пока не догонит загруженные
  const ready = useMemo(() => {
    const own = found[key] ?? {};
    return Object.keys(own).map(Number).sort((a, b) => a - b).map((n) => own[n]);
  }, [found, key]);
  const [open, setOpen] = useState<Record<string, number>>({});
  const shown = open[key] ?? 0;
  useEffect(() => {
    if (!key || shown >= ready.length) return;
    const t = window.setTimeout(() => setOpen((o) => ({ ...o, [key]: Math.min(ready.length, (o[key] ?? 0) + BATCH) })), shown === 0 ? 0 : TICK_MS);
    return () => window.clearTimeout(t);
  }, [key, shown, ready.length]);

  return useMemo(() => (variant && key ? { [variant]: ready.slice(0, shown) } : {}), [variant, key, ready, shown]);
}
