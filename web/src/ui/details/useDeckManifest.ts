// Разбор шаблона открытой презентации для листа «Подробнее» (вкладки «Почему так» и «Шаблон», слой «Слайд N
// шаблона»): выбранный в хранилище, когда это он; иначе — свой запрос (шаблон мог остаться не выбранным). Шаблона больше
// нет в библиотеке (404) — «gone»: вкладки говорят об этом, а не показывают чужой шаблон. Не загрузился — «offline»
// (нет связи с сервером) или «error» (сервер ответил ошибкой); новый `attempt` (лист открыли, вкладку сменили) просит
// разбор снова. Один запрос на шаблон за раз: повтор во время ожидания ждёт тот же ответ.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api";
import { useApp } from "../../store";
import type { TemplateManifest } from "../../types";

const cache = new Map<string, TemplateManifest | "gone">();
const asking = new Map<string, Promise<TemplateManifest>>();

export type DeckManifest = { manifest: TemplateManifest | null; state: "ready" | "loading" | "gone" | "offline" | "error" };

function ask(id: string): Promise<TemplateManifest> {
  let p = asking.get(id);
  if (!p) {
    p = api.template(id);
    asking.set(id, p);
    const done = () => void asking.delete(id);
    p.then(done, done);
  }
  return p;
}

export function useDeckManifest(templateId: string | null, attempt: unknown): DeckManifest {
  const { manifest } = useApp();
  const own = manifest && templateId && manifest.template_id === templateId ? manifest : null;
  const [, setTick] = useState(0);
  const [failed, setFailed] = useState<{ id: string; offline: boolean } | null>(null);
  useEffect(() => {
    if (!templateId || own || cache.has(templateId)) return;
    let off = false;
    setFailed(null); // повтор: пока ждём — «загружается»
    ask(templateId).then(
      (m) => {
        cache.set(templateId, m);
        if (!off) setTick((t) => t + 1);
      },
      (e) => {
        if (e instanceof ApiError && e.status === 404) cache.set(templateId, "gone");
        if (!off) {
          setFailed({ id: templateId, offline: e instanceof ApiError && e.status === 0 });
          setTick((t) => t + 1);
        }
      },
    );
    return () => {
      off = true;
    };
  }, [templateId, own, attempt]);
  if (!templateId) return { manifest: null, state: "gone" };
  if (own) return { manifest: own, state: "ready" };
  const got = cache.get(templateId);
  if (got === "gone") return { manifest: null, state: "gone" };
  if (got) return { manifest: got, state: "ready" };
  if (failed?.id === templateId) return { manifest: null, state: failed.offline ? "offline" : "error" };
  return { manifest: null, state: "loading" };
}
