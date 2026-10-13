import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

// Названия проверок (GET /api/checks) — заголовки рядов замечаний. Список один на всё приложение: его просят один раз
// за сессию; не ответил — ряды говорят своими словами (marks.ts `remarkTitle`), следующий экран попросит снова.
let titles: Record<string, string> | null = null;
let asking: Promise<Record<string, string> | null> | null = null;

function ask(): Promise<Record<string, string> | null> {
  if (titles) return Promise.resolve(titles);
  asking ??= api.checks().then(
    (list) => (titles = Object.fromEntries(list.map((c) => [c.id, c.title]))),
    () => {
      asking = null;
      return null;
    },
  );
  return asking;
}

/** Название проверки по её id (null — неизвестно или список ещё не пришёл). */
export function useCheckTitles(): (checkId: string) => string | null {
  const [map, setMap] = useState(titles);
  useEffect(() => {
    if (map) return;
    let off = false;
    void ask().then((m) => {
      if (!off && m) setMap(m);
    });
    return () => {
      off = true;
    };
  }, [map]);
  return useCallback((id: string) => map?.[id] ?? null, [map]);
}
