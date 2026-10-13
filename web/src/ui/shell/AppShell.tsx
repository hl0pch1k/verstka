// Оболочка «Слоёв»: страница (#F3F4F1, поля 24, ширина до 1392), шапка и колода в обёртке `hp-wrap` — сетке из двух
// колонок, где вторая (место помощника) 0 → 400 px. Разметка — boards/V2.dc.html, `.p2-root`. Задачи областей
// подключают сюда содержимое плит и слоёв через слоты `Deck`.
import type { CSSProperties } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import type { TemplateListItem } from "../../types";
import { ImproveStrip } from "../create/ImproveNote";
import { ParamsBody, ParamsHead, useParamsPlate } from "../create/ParamsPlate";
import { tplMeta } from "../create/ribbon";
import { TemplateBody, TemplateHead, useTemplateUpload } from "../create/TemplatePlate";
import { TextBody, TextHead, useTextPlate } from "../create/TextPlate";
import { textStrip } from "../create/textRules";
import { useStrayFileDrop } from "../create/UploadZone";
import { Deck } from "../deck/Deck";
import type { StripData } from "../deck/Strip";
import { Scrim } from "../layers/Scrim";
import { TemplatesLayer } from "../layers/TemplatesLayer";
import { TplDeleteDialog } from "../layers/TplDeleteDialog";
import { TplPreviewLayer } from "../layers/TplPreviewLayer";
import { Header } from "./Header";

const ROOT: CSSProperties = {
  width: "100%", minHeight: 900, boxSizing: "border-box", padding: "0 24px 24px", background: "#F3F4F1", color: "#0B1220",
  fontFamily: "'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif", fontSize: 15, lineHeight: "24px",
};

/** Полоса 01: «VK Tech · 54 слайда · Play» — название шаблона, число его слайдов и шрифт. */
function templateStrip(t: TemplateListItem | undefined): StripData | undefined {
  if (!t) return undefined;
  return { title: tplLabel(t), meta: tplMeta(t) || undefined };
}

export function AppShell() {
  const { templates, templateId, ui, dispatch, brief, improveSource } = useApp();
  const s1 = templateStrip(templates.find((t) => t.template_id === templateId));
  // шаг «Текст» — одно состояние на заголовок и тело плиты 02; разбор текста в нём считается один раз на правку
  const text = useTextPlate();
  // шаг «Параметры и запуск» — одно состояние на заголовок плиты 03 (сводка, запуск) и её тело
  const params = useParamsPlate();
  // полоса 02 на «Создать» и сборке — текст поля; на результате её подпишет результат (название презентации)
  const s2 = ui.screen === "result" ? undefined : textStrip(brief, { line: text.line, improve: ui.improve ? improveSource : null });
  // загрузка своего шаблона — одна на плиту 01 и раздел «Шаблоны»
  const upload = useTemplateUpload();
  // файл, отпущенный мимо включённой зоны, браузер не открывает
  useStrayFileDrop();
  // «Загрузить свой» в разделе: раздел уезжает, раскрывается шаг 01 и над ним — выбор файла (V2 `tpGalUp`)
  const uploadFromGallery = () => {
    if (upload.busy) return; // плитка в разделе занята (aria-disabled), сюда не дойти; на случай прямого вызова
    if (ui.screen !== "create") dispatch({ type: "go", screen: "create" });
    dispatch({ type: "sect", sect: null });
    dispatch({ type: "open", step: "tpl" });
    upload.pick();
  };
  const layers = (
    <>
      {/* «Улучшить готовую»: полоса «01 Итоги квартала.pptx» над плитой 02 */}
      <ImproveStrip />
      {/* пока раздел открыт, видимая полоса колоды над слоем закрывает его */}
      <Scrim open={!!ui.sect} onClose={() => dispatch({ type: "sect", sect: null })}
        label={ui.sect === "hist" ? "Закрыть «Мои презентации»" : "Закрыть «Шаблоны»"} />
      <TemplatesLayer fresh={upload.fresh} onUpload={uploadFromGallery} busy={upload.busy} />
      <TplPreviewLayer />
      <TplDeleteDialog />
    </>
  );
  return (
    <div className="p2-root" style={ROOT}>
      <div style={{ width: "100%", maxWidth: 1392, margin: "0 auto" }}>
        <Header />
        {/* место помощника закрыто (колонка 0); плиту помощника и сужение колоды добавляет его задача */}
        <div className="hp-wrap hp-closed">
          <Deck s1={s1} h1={<TemplateHead upload={upload} />} p1={<TemplateBody upload={upload} />}
            s2={s2} h2={<TextHead tp={text} />} p2={<TextBody tp={text} />}
            h3={<ParamsHead pp={params} />} p3={<ParamsBody pp={params} />} layers={layers} />
          <div className="hp-hcell" />
        </div>
      </div>
    </div>
  );
}
