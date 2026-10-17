// «Цели из текста» так, как их поймёт сборка: POST /api/goals (цели брифа над приложенными наборами — модель с проверкой
// кодом, без модели — правила; предложения без ответа в данных). Запрос — через 1,5 с после последней правки текста и
// сразу, когда сменились наборы; устаревший отменяется; ответы помнятся по тексту и наборам (тот же текст — без запроса).
// Пока ответа нет, показывается прежний ответ для тех же наборов (таблетки не мигают при каждой паузе в наборе); его
// нет, запрос не удался или файлов нет — null: GoalsBox показывает мгновенную прикидку по тексту (`goalsOf`).
import { useEffect, useRef, useState } from "react";
import { api, type GoalsAnswer } from "../../api";
import { goalsKey } from "./dataRules";

/** Пауза после последней правки текста, мс. */
export const GOALS_DEBOUNCE_MS = 1500;
const CACHE_MAX = 60;
const cache = new Map<string, GoalsAnswer>();
const remember = (key: string, a: GoalsAnswer) => {
  cache.delete(key);
  cache.set(key, a);
  if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value as string);
};

export function useServerGoals(brief: string, ids: string[], models: boolean): GoalsAnswer | null {
  const idsKey = ids.join(",");
  const key = goalsKey(brief, ids, models);
  const [got, setGot] = useState<{ key: string; ids: string; a: GoalsAnswer } | null>(() => {
    const hit = cache.get(key);
    return hit && ids.length ? { key, ids: idsKey, a: hit } : null;
  });
  const [failed, setFailed] = useState<string | null>(null);
  // первый запрос (коробка только что появилась — файлы приложили) и новые наборы — сразу, правка текста — после паузы
  const lastIds = useRef<string | null>(null);
  const latest = useRef({ brief, ids, models });
  latest.current = { brief, ids, models };
  useEffect(() => {
    const idsChanged = lastIds.current !== idsKey;
    lastIds.current = idsKey;
    if (!idsKey) return;
    const hit = cache.get(key);
    if (hit) {
      setGot({ key, ids: idsKey, a: hit });
      return;
    }
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      const { brief: b, ids: d, models: m } = latest.current;
      api.goals({ brief: b, dataset_ids: d, use_models: m }, ctl.signal).then((a) => {
        if (ctl.signal.aborted) return;
        remember(key, a);
        setFailed(null);
        setGot({ key, ids: idsKey, a });
      }, () => {
        if (!ctl.signal.aborted) setFailed(key);
      });
    }, idsChanged ? 0 : GOALS_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [key, idsKey]);
  if (!idsKey || failed === key || !got || got.ids !== idsKey) return null;
  return got.a;
}
