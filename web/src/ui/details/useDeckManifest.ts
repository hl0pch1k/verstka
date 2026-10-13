// Разбор шаблона открытой презентации для листа «Подробнее» (вкладки «Почему так» и «Шаблон», слой «Слайд N
// шаблона»): выбранный в хранилище, когда это он; иначе — свой запрос (шаблон мог остаться не выбранным). Шаблона больше
// нет в библиотеке (404) — «gone»: вкладки говорят об этом, а не показывают чужой шаблон.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api";
import { useApp } from "../../store";
import type { TemplateManifest } from "../../types";

const cache = new Map<string, TemplateManifest | "gone">();

export type DeckManifest = { manifest: TemplateManifest | null; state: "ready" | "loading" | "gone" | "error" };

export function useDeckManifest(templateId: string | null): DeckManifest {
  const { manifest } = useApp();
  const own = manifest && templateId && manifest.template_id === templateId ? manifest : null;
  const [, setTick] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    if (!templateId || own || cache.has(templateId)) return;
    let off = false;
    api.template(templateId).then(
      (m) => {
        cache.set(templateId, m);
        if (!off) setTick((t) => t + 1);
      },
      (e) => {
        if (e instanceof ApiError && e.status === 404) cache.set(templateId, "gone");
        if (!off) {
          setFailed(templateId);
          setTick((t) => t + 1);
        }
      },
    );
    return () => {
      off = true;
    };
  }, [templateId, own]);
  if (!templateId) return { manifest: null, state: "gone" };
  if (own) return { manifest: own, state: "ready" };
  const got = cache.get(templateId);
  if (got === "gone") return { manifest: null, state: "gone" };
  if (got) return { manifest: got, state: "ready" };
  return { manifest: null, state: failed === templateId ? "error" : "loading" };
}
