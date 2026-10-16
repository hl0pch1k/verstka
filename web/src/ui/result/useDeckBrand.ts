// Брендбук открытой презентации для карточки «Оформление» (resultView `lookCard`): тот же, что приложен на «Создать», —
// оттуда, иначе — с сервера (GET /api/brandbooks/{id}, один раз на брендбук за страницу). Спрашивается, как только
// презентация открыта: колонка результата входит с задержкой (p2-in 240 мс), и ответ обычно успевает до неё.
// Брендбука больше нет на сервере — null: карточка говорит без подробностей.
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useApp } from "../../store";
import type { BrandSpec, GenerationMeta } from "../../types";
import { deckTemplate } from "./resultView";

const asked = new Map<string, Promise<BrandSpec | null>>();

function ask(id: string, template: string): Promise<BrandSpec | null> {
  let p = asked.get(id);
  if (!p) {
    p = api.getBrandbook(id, template).then((r) => r.brand ?? null, () => null);
    asked.set(id, p);
  }
  return p;
}

/** BrandSpec брендбука презентации `g`; нет брендбука или он ещё не прочитан — null (`ready` — ответ получен). */
export function useDeckBrand(g: Pick<GenerationMeta, "brandbook_id" | "brandbook" | "template_id" | "base_template_id">): { spec: BrandSpec | null; ready: boolean } {
  const { data } = useApp();
  const id = g.brandbook_id ?? g.brandbook?.id ?? null;
  const local = id && data.brand.phase === "on" && data.brand.spec && data.brand.id === id ? data.brand.spec : null;
  const tpl = deckTemplate(g);
  const [got, setGot] = useState<{ id: string; spec: BrandSpec | null } | null>(null);
  useEffect(() => {
    if (!id || local) return;
    let off = false;
    void ask(id, tpl).then((spec) => {
      if (!off) setGot({ id, spec });
    });
    return () => {
      off = true;
    };
  }, [id, local, tpl]);
  if (!id) return { spec: null, ready: true };
  if (local) return { spec: local, ready: true };
  return got?.id === id ? { spec: got.spec, ready: true } : { spec: null, ready: false };
}
