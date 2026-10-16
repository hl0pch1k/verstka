// Ответы сервера о брендбуках презентаций за страницу (useDeckBrand): что помнить, а что спросить снова.
import { ApiError } from "../../api";
import type { BrandSpec } from "../../types";

/** Ответ о брендбуке: `spec` (null — нет его), `final` — так и есть (не спрашивать снова). */
export interface BrandAnswer { spec: BrandSpec | null; final: boolean }

/** Кэш ответов на страницу: удачный ответ и «брендбука нет» (404) помнятся, неудача связи и 5xx — нет (следующий вызов
 *  спросит снова). */
export function makeBrandCache(get: (id: string, template: string) => Promise<{ brand?: BrandSpec | null }>) {
  const asked = new Map<string, Promise<BrandAnswer>>();
  return (id: string, template: string): Promise<BrandAnswer> => {
    let p = asked.get(id);
    if (!p) {
      p = get(id, template).then(
        (r) => ({ spec: r.brand ?? null, final: true }),
        (e: unknown) => {
          const gone = e instanceof ApiError && e.status === 404;
          if (!gone) asked.delete(id);
          return { spec: null, final: gone };
        },
      );
      asked.set(id, p);
    }
    return p;
  };
}

/** Сервер не ответил — спросить снова через столько (мс), не больше трёх раз за открытие. */
export const BRAND_RETRY_MS = 5000;
export const BRAND_RETRIES = 3;
/** Когда спросить снова после ответа `a` (`round` — сколько раз уже спрашивали снова); не нужно — null. */
export const brandRetry = (a: BrandAnswer, round: number): number | null => (a.final || round >= BRAND_RETRIES ? null : BRAND_RETRY_MS);
