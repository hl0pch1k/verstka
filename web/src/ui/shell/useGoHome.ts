// «На главную» (логотип) и «Новая презентация» компактного результата: V2 `goHome` / `restart` — `go('create')` и чистый
// лист: пустой текст и аудитория (черновик тоже; остальные параметры остаются), текст раскрыт, разделы и «Все
// параметры» закрыты, «Улучшить готовую» снята. С результата плита 04 уходит вниз непрозрачной вместе с плитами (`down`
// ставит сам `go`). Уже на «Создать» логотип только закрывает слои и листы: набранный текст, открытый шаг и «Улучшить
// готовую» остаются (черновик не теряется от случайного клика).
import { useApp } from "../../store";
import type { UiState } from "../deck/geometry";

/** Всё, что логотип закрывает на «Создать»: разделы шапки, лист «Подробнее», слои и окна поверх колоды. */
export const LAYERS_CLOSED: Partial<UiState> = {
  sect: null, sheet: null, pattern: null, textLayer: false, lightbox: false, tplPreview: null, tplDelete: null, brandLayer: false,
};

export function useGoHome(): () => void {
  const { ui, dispatch, setBrief, setParams, data } = useApp();
  return () => {
    if (ui.screen === "create") return dispatch({ type: "set", patch: LAYERS_CLOSED });
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: false } });
    setBrief("");
    setParams({ audience: "" });
    // чистый лист — и без файлов с данными (V2 `goHome`: `dt: []`); брендбук остаётся, как шаблон
    data.clear();
  };
}
