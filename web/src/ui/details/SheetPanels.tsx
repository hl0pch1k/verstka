// Содержимое листа «Подробнее» — шесть вкладок и слой «Слайд N шаблона» (DetailsSheet). Отдельный кусок сборки: к
// первой отрисовке он не нужен, лист грузит его в свободное время после неё (`loadSheet`) и, на всякий случай, при
// открытии. Пока куска нет, на месте вкладок — пустая область листа (панели стоят в абсолютно поставленном слое, место не
// меняется; дольше 600 мс — спокойная строка загрузки), а пришедшее содержимое входит своей лесенкой p2-in — ничего не
// выскакивает. Каждая вкладка — за своей границей (TabBoundary): ошибка разметки в одной не гасит остальные.
import type { Generation, Variant } from "../../types";
import type { SheetTab } from "../deck/geometry";
import { TabBoundary } from "./lazySheet";
import { Panel } from "./parts";
import { PatternLayer } from "./PatternLayer";
import { AgentTab } from "./tabs/Agent";
import { FilesTab } from "./tabs/Files";
import { PlanTab } from "./tabs/Plan";
import { QualityTab } from "./tabs/Quality";
import { TemplateTab } from "./tabs/Template";
import { WhyTab } from "./tabs/Why";
import type { DeckManifest } from "./useDeckManifest";

export function SheetPanels({ g, v, deck, tab, mounted, open }: {
  g: Generation; v: Variant; deck: DeckManifest; tab: SheetTab; mounted: ReadonlySet<SheetTab>; open: boolean;
}) {
  return (
    <div style={{ pointerEvents: "auto" }}>
      <Panel tab="quality" on={tab === "quality"} mount={mounted.has("quality")}><TabBoundary reset={v}><QualityTab g={g} v={v} deck={deck} /></TabBoundary></Panel>
      <Panel tab="why" on={tab === "why"} mount={mounted.has("why")}><TabBoundary reset={v}><WhyTab g={g} v={v} deck={deck} active={open && tab === "why"} /></TabBoundary></Panel>
      <Panel tab="agent" on={tab === "agent"} mount={mounted.has("agent")}><TabBoundary reset={v}><AgentTab g={g} v={v} /></TabBoundary></Panel>
      <Panel tab="plan" on={tab === "plan"} mount={mounted.has("plan")} style={{ height: 508, display: "flex", flexDirection: "column" }}><TabBoundary reset={v}><PlanTab g={g} v={v} active={open && tab === "plan"} /></TabBoundary></Panel>
      <Panel tab="template" on={tab === "template"} mount={mounted.has("template")} style={{ height: 508, display: "flex", flexDirection: "column" }}><TabBoundary reset={v}><TemplateTab deck={deck} /></TabBoundary></Panel>
      <Panel tab="files" on={tab === "files"} mount={mounted.has("files")} style={{ height: 508, display: "flex", flexDirection: "column" }}><TabBoundary reset={v}><FilesTab g={g} v={v} deck={deck} /></TabBoundary></Panel>
    </div>
  );
}

export { PatternLayer };
