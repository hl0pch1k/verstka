// «На главную» (логотип) и «Новая презентация» компактного результата: V2 `goHome` / `restart` — `go('create')` и чистый
// лист: пустой текст, аудитория и число слайдов, без данных, брендбука и базы знаний (черновик тоже; шаблон и остальные
// параметры остаются), текст раскрыт, разделы и «Все параметры» закрыты, «Улучшить готовую» снята. С результата плита 04 уходит вниз непрозрачной вместе с плитами (`down`
// ставит сам `go`). Уже на «Создать» логотип только закрывает слои и листы: набранный текст, открытый шаг и «Улучшить
// готовую» остаются (черновик не теряется от случайного клика).
import { useApp } from "../../store";
import type { UiState } from "../deck/geometry";

/** Всё, что логотип закрывает на «Создать»: разделы шапки, лист «Подробнее», слои и окна поверх колоды. */
export const LAYERS_CLOSED: Partial<UiState> = {
  sect: null, sheet: null, pattern: null, textLayer: false, lightbox: false, tplPreview: null, tplDelete: null, brandLayer: false, kbLayer: false,
};

export function useGoHome(): () => void {
  const { ui, dispatch, setBrief, setParams, data, kb } = useApp();
  return () => {
    if (ui.screen === "create") return dispatch({ type: "set", patch: LAYERS_CLOSED });
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: false } });
    setBrief("");
    // число слайдов прошлой презентации не переходит в новую: степпер снова «не трогали»
    setParams({ audience: "", slides: null });
    // чистый лист — без файлов с данными (V2 `goHome`: `dt: []`), без брендбука и без базы знаний прошлой презентации
    // (на сервере они остаются: на них ссылаются собранные презентации); шаблон остаётся
    data.clear();
    data.restore({ brandbookId: null });
    kb.clear();
  };
}
