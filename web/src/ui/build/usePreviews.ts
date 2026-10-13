// Настоящие превью сверстанных слайдов для раскадровки. Превью пишет экспорт (с 86 % хода): с этого момента каждые
// 1,5 с спрашивается список готовых превью варианта (api.slideList) и грузятся только названные — запроса к картинке,
// которой ещё нет, не бывает; не загрузившаяся пробуется в следующий круг. Готовые встают вместо эскизов по три
// (V2 `LDN`: 3, 6, 9, 12 — такт 450 мс), а не все разом.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";

const POLL_MS = 1500;
/** Превью встают по три за такт. */
const BATCH = 3;
const TICK_MS = 450;

const slideUrl = (gid: string, variant: string, n: number) =>
  `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(variant)}/slides/slide-${String(n).padStart(3, "0")}.jpg`;

/** Превью варианта `variant`, уже загруженные браузером и открытые по три: вариант → адреса по порядку слайдов. */
export function usePreviews(gid: string | null | undefined, variant: string | null, count: number, enabled: boolean): Record<string, string[]> {
  // вариант → номер слайда → адрес (загружен)
  const [found, setFound] = useState<Record<string, Record<number, string>>>({});
  const foundRef = useRef(found);
  foundRef.current = found;
  useEffect(() => {
    if (!gid || !variant || !enabled || count <= 0) return;
    let alive = true;
    let timer = 0;
    const have = () => Object.keys(foundRef.current[variant] ?? {}).length;
    const load = (name: string) =>
      new Promise<void>((resolve) => {
        const n = Number(name.match(/(\d+)/)?.[1] ?? NaN);
        if (!Number.isFinite(n) || foundRef.current[variant]?.[n]) return resolve();
        const url = slideUrl(gid, variant, n);
        const img = new Image();
        img.onload = () => {
          if (alive) setFound((m) => (m[variant]?.[n] ? m : { ...m, [variant]: { ...m[variant], [n]: url } }));
          resolve();
        };
        img.onerror = () => resolve();
        img.src = url;
      });
    const round = async () => {
      let names: string[] = [];
      try {
        names = (await api.slideList(gid, variant)).slides;
      } catch {
        /* сервер занят экспортом: следующий круг спросит снова */
      }
      if (!alive) return;
      await Promise.all(names.map(load));
      if (alive && have() < count) timer = window.setTimeout(round, POLL_MS);
    };
    void round();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [gid, variant, count, enabled]);

  // сколько превью варианта уже открыто: прибавляется по три за такт, пока не догонит загруженные
  const ready = useMemo(() => {
    const own = found[variant ?? ""] ?? {};
    return Object.keys(own).map(Number).sort((a, b) => a - b).map((n) => own[n]);
  }, [found, variant]);
  const [open, setOpen] = useState<Record<string, number>>({});
  const shown = open[variant ?? ""] ?? 0;
  useEffect(() => {
    if (!variant || shown >= ready.length) return;
    const t = window.setTimeout(() => setOpen((o) => ({ ...o, [variant]: Math.min(ready.length, (o[variant] ?? 0) + BATCH) })), shown === 0 ? 0 : TICK_MS);
    return () => window.clearTimeout(t);
  }, [variant, shown, ready.length]);

  return useMemo(() => (variant ? { [variant]: ready.slice(0, shown) } : {}), [variant, ready, shown]);
}
