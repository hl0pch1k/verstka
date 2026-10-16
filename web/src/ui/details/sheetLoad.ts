// Загрузка ленивого куска листа «Подробнее» без React (lazySheet): один запрос на все вызовы, неудача — следующий вызов
// спросит снова; неудача загрузки куска отличается от ошибки в нём.

/** Загрузчик куска: один запрос на все вызовы, пока он не кончился неудачей; после неудачи следующий вызов спросит
 *  снова. */
export function makeLoader<T>(importer: () => Promise<T>): () => Promise<T> {
  let chunk: Promise<T> | null = null;
  return () => {
    chunk ??= importer().catch((e: unknown) => {
      chunk = null;
      throw e;
    });
    return chunk;
  };
}

/** Не загрузился сам кусок (сеть, сервер обновил сборку) — а не ошибка в нём. */
export function isChunkError(e: unknown): boolean {
  const name = e instanceof Error ? e.name : "";
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return name === "ChunkLoadError" || /dynamically imported module|Importing a module script failed|Loading chunk|Failed to fetch|NetworkError/i.test(msg);
}
