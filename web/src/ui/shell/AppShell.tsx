// Оболочка «Слоёв»: страница (#F3F4F1, поля 24, ширина до 1392), шапка и колода в обёртке `hp-wrap` — сетке из двух
// колонок, где вторая (место помощника) 0 → 400 px. Разметка — boards/V2.dc.html, `.p2-root`. Задачи областей
// подключают сюда содержимое плит и слоёв через слоты `Deck`.
import type { CSSProperties } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { TemplateListItem } from "../../types";
import { Deck } from "../deck/Deck";
import type { StripData } from "../deck/Strip";
import { Header } from "./Header";

const ROOT: CSSProperties = {
  width: "100%", minHeight: 900, boxSizing: "border-box", padding: "0 24px 24px", background: "#F3F4F1", color: "#0B1220",
  fontFamily: "'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif", fontSize: 15, lineHeight: "24px",
};

/** Полоса 01: «VK Tech · 54 слайда · Play» — название шаблона, число его слайдов и шрифт. */
function templateStrip(t: TemplateListItem | undefined): StripData | undefined {
  if (!t) return undefined;
  const n = t.n_slides;
  const meta = [n ? plural(n, "слайд", "слайда", "слайдов") : null, t.font].filter(Boolean).join(" · ");
  return { title: tplLabel(t), meta: meta || undefined };
}

export function AppShell() {
  const { templates, templateId } = useApp();
  const s1 = templateStrip(templates.find((t) => t.template_id === templateId));
  return (
    <div className="p2-root" style={ROOT}>
      <div style={{ width: "100%", maxWidth: 1392, margin: "0 auto" }}>
        <Header />
        {/* место помощника закрыто (колонка 0); плиту помощника и сужение колоды добавляет его задача */}
        <div className="hp-wrap hp-closed">
          <Deck s1={s1} />
          <div className="hp-hcell" />
        </div>
      </div>
    </div>
  );
}
