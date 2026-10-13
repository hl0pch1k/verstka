import { useCallback } from "react";
import { useApp } from "../../store";
import type { SheetTab } from "../deck/geometry";

/** Лист «Подробнее» на вкладке `tab` (ui/details/DetailsSheet). */
export function useOpenSheet(): (tab: SheetTab) => void {
  const { dispatch } = useApp();
  return useCallback((tab: SheetTab) => dispatch({ type: "sheet", tab }), [dispatch]);
}
