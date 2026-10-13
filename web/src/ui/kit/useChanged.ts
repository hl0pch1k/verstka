import { useRef } from "react";

/** Ключ сменился хотя бы раз: текст уже не первый — он проявляется (ra-xf), а не входит вместе со своим блоком. */
export function useChanged(key: string): boolean {
  const first = useRef(key);
  const changed = useRef(false);
  if (key !== first.current) changed.current = true;
  return changed.current;
}
