// Template fonts in the UI: a template's primary family is often a Google font (Play, Montserrat…) — load it so the
// passport shows type specimens in the real face. A family Google does not serve just falls back to the UI font.
import { useEffect } from "react";

const loaded = new Set<string>();

export function useTemplateFont(family: string | null | undefined): void {
  useEffect(() => {
    const name = family?.trim();
    if (!name || loaded.has(name) || !/^[\p{L}\p{N} \-]+$/u.test(name)) return;
    loaded.add(name);
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(name).replace(/%20/g, "+")}:wght@400;700&display=swap`;
    document.head.appendChild(link);
  }, [family]);
}

export const fontStack = (family?: string | null) => (family ? `"${family}", Onest, system-ui, sans-serif` : undefined);
