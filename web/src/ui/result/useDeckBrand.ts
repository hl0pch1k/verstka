// Брендбук открытой презентации для карточки «Оформление» (resultView `lookCard`): тот же, что приложен на «Создать», —
// оттуда, иначе — с сервера (GET /api/brandbooks/{id}, один раз на брендбук за страницу). Спрашивается, как только
// презентация открыта: колонка результата входит с задержкой (p2-in 240 мс), и ответ обычно успевает до неё.
// Брендбука больше нет на сервере (404) — null, это запоминается: карточка говорит без подробностей. Сервер не ответил
// (нет связи, 5xx) — не запоминается: карточка пока без подробностей, через 5 с — ещё раз (и при следующем открытии).
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useApp } from "../../store";
import type { BrandSpec, GenerationMeta } from "../../types";
import { brandRetry, makeBrandCache } from "./brandCache";
import { deckTemplate } from "./resultView";

const ask = makeBrandCache((id, template) => api.getBrandbook(id, template));

/** BrandSpec брендбука презентации `g`; нет брендбука или он ещё не прочитан — null (`ready` — ответ получен). */
export function useDeckBrand(g: Pick<GenerationMeta, "brandbook_id" | "brandbook" | "template_id" | "base_template_id">): { spec: BrandSpec | null; ready: boolean } {
  const { data } = useApp();
  const id = g.brandbook_id ?? g.brandbook?.id ?? null;
  const local = id && data.brand.phase === "on" && data.brand.spec && data.brand.id === id ? data.brand.spec : null;
  const tpl = deckTemplate(g);
  const [got, setGot] = useState<{ id: string; spec: BrandSpec | null } | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (!id || local) return;
    let off = false;
    let t = 0;
    void ask(id, tpl).then((a) => {
      if (off) return;
      setGot({ id, spec: a.spec });
      const later = brandRetry(a, round);
      if (later !== null) t = window.setTimeout(() => setRound((r) => r + 1), later);
    });
    return () => {
      off = true;
      window.clearTimeout(t);
    };
  }, [id, local, tpl, round]);
  if (!id) return { spec: null, ready: true };
  if (local) return { spec: local, ready: true };
  return got?.id === id ? { spec: got.spec, ready: true } : { spec: null, ready: false };
}
