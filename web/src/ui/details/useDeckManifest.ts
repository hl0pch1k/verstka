// Разбор шаблона открытой презентации для листа «Подробнее» (вкладки «Почему так» и «Шаблон», слой «Слайд N
// шаблона»): выбранный в хранилище, когда это он; иначе — свой запрос (шаблон мог остаться не выбранным). Шаблона нет в
// библиотеке (404) — «gone»: вкладки говорят об этом, а не показывают чужой шаблон. 404 не запоминается навсегда (он
// бывает и у шаблона, который загрузили заново с тем же id): лист открыли, вкладку сменили (`attempt`) или список
// шаблонов изменился — разбор спрашивается снова (`manifestAsk`). Не загрузился — «offline» (нет связи с сервером) или
// «error» (сервер ответил ошибкой); новый `attempt` просит разбор снова. Один запрос на шаблон за раз: повтор во время
// ожидания ждёт тот же ответ.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api";
import { useApp } from "../../store";
import type { TemplateManifest } from "../../types";
import { goneMark, manifestAsk } from "./sheetView";

const cache = new Map<string, TemplateManifest>();
/** Шаблоны, на которые сервер ответил 404, и при каком открытии листа и списке шаблонов (`goneMark`). */
const gone = new Map<string, string>();
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
  const { manifest, templates } = useApp();
  const own = manifest && templateId && manifest.template_id === templateId ? manifest : null;
  const list = templates.map((t) => t.template_id).join(",");
  const [, setTick] = useState(0);
  const [failed, setFailed] = useState<{ id: string; offline: boolean } | null>(null);
  useEffect(() => {
    if (!templateId || own || !manifestAsk({ have: cache.has(templateId), goneAt: gone.get(templateId) ?? null, attempt, list })) return;
    let off = false;
    setFailed(null); // повтор: пока ждём — «загружается» (шаблон, которого не было, остаётся «нет» до ответа)
    ask(templateId).then(
      (m) => {
        cache.set(templateId, m);
        gone.delete(templateId);
        if (!off) setTick((t) => t + 1);
      },
      (e) => {
        if (e instanceof ApiError && e.status === 404) gone.set(templateId, goneMark(attempt, list));
        if (!off) {
          setFailed({ id: templateId, offline: e instanceof ApiError && e.status === 0 });
          setTick((t) => t + 1);
        }
      },
    );
    return () => {
      off = true;
    };
  }, [templateId, own, attempt, list]);
  if (!templateId) return { manifest: null, state: "gone" };
  if (own) return { manifest: own, state: "ready" };
  const got = cache.get(templateId);
  if (got) return { manifest: got, state: "ready" };
  if (gone.has(templateId)) return { manifest: null, state: "gone" };
  if (failed?.id === templateId) return { manifest: null, state: failed.offline ? "offline" : "error" };
  return { manifest: null, state: "loading" };
}
