// Оболочка «Слоёв»: страница (#F3F4F1, поля 24, ширина до 1392), шапка и колода в обёртке `hp-wrap` — сетке из двух
// колонок, где вторая (место помощника) 0 → 400 px. Разметка — boards/V2.dc.html, `.p2-root`. Задачи областей
// подключают сюда содержимое плит и слоёв через слоты `Deck`.
import { useMemo, type CSSProperties } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import type { Generation, TemplateListItem, Variant } from "../../types";
import { BuildPlate } from "../build/BuildPlate";
import { buildStripText } from "../build/buildView";
import { buildTopic } from "../build/resume";
import { ImproveStrip, useModelOn } from "../create/ImproveNote";
import { ParamsBody, ParamsHead, useParamsPlate } from "../create/ParamsPlate";
import { tplMeta } from "../create/ribbon";
import { TemplateBody, TemplateHead, useTemplateUpload } from "../create/TemplatePlate";
import { TextBody, TextHead, useTextPlate } from "../create/TextPlate";
import { textLine, textStrip } from "../create/textRules";
import { useStrayFileDrop } from "../create/UploadZone";
import { Deck } from "../deck/Deck";
// лист «Подробнее» — в основном куске сборки: первое открытие въезжает, как любое (кусок, догружаемый по клику, мог бы
// не успеть к движению или не загрузиться вовсе); библиотеки — отдельным куском (vite.config `manualChunks`)
import { DetailsSheet } from "../details/DetailsSheet";
import { Icon } from "../kit/Icon";
import type { StripData } from "../deck/Strip";
import { HistoryLayer } from "../layers/HistoryLayer";
import { Lightbox } from "../layers/Lightbox";
import { Scrim } from "../layers/Scrim";
import { TemplatesLayer } from "../layers/TemplatesLayer";
import { TextLayer } from "../layers/TextLayer";
import { TplDeleteDialog } from "../layers/TplDeleteDialog";
import { TplPreviewLayer } from "../layers/TplPreviewLayer";
import { ResultPlate } from "../result/ResultPlate";
import { deckStrip, openDeck } from "../result/resultView";
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

/** Полоса 03 на результате (V2 `strip3`, `resultMeta`; тексты — buildStripText): «✓ Сборка завершена за 2:31 · 3 варианта ·
 *  12 слайдов» у законченной сборки; «Сборка остановилась» тихим красным B-failed (#F87171), без галочки, у упавшей;
 *  у идущей полосы нет. */
function buildStrip(g: Generation | null, v: Variant | null): StripData | undefined {
  const t = buildStripText(g, v);
  if (!t) return undefined;
  if (t.tone === "failed") return { title: <span style={{ color: "#F87171" }}>{t.title}</span> };
  return {
    icon: <span style={{ display: "inline-flex", flex: "none", color: "#38BDF8" }}><Icon name="check-circle" size={16} /></span>,
    title: t.title,
    meta: t.meta ?? undefined,
  };
}

export function AppShell() {
  const {
    templates, templateId, templateLabel, ui, dispatch, brief, improveSource, generation, generationId, generations, activeVariant, buildJob, buildAsk,
    health,
  } = useApp();
  const modelOn = useModelOn();
  /** Полоса 01 о шаблоне презентации или сборки: шаблон по id; его нет в библиотеке — имя по файлу; id нет — пусто. */
  const tplStrip = (id: string | null | undefined, file?: string | null): StripData | undefined =>
    templateStrip(templates.find((t) => t.template_id === id)) ?? (id ? { title: templateLabel(id, file) } : undefined);
  // полоса 01 на результате — шаблон открытой презентации; пока она грузится после перезагрузки — по её мете из
  // списка, а пока ничего не известно — пусто, не выбранный раньше шаблон. На «Создать» — выбранный
  const result = ui.screen === "result";
  const open = result ? openDeck(generation, generations, generationId) : null;
  // полосы 01/02 на сборке — шаблон и тема самой сборки (её запрос или мета её презентации), не черновик поля:
  // подключились к чужой сборке из «Мои презентации» — полосы о ней, а текст в поле «Создать» остаётся своим
  const build = ui.screen === "build";
  const topic = useMemo(() => (build ? buildTopic(buildJob, buildAsk, [generation, ...generations]) : null), [build, buildJob, buildAsk, generation, generations]);
  const s1 = result ? (open ? tplStrip(open.template_id, open.template_file) : undefined)
    : build ? (topic ? tplStrip(topic.template, topic.templateFile) : undefined)
    : templateStrip(templates.find((t) => t.template_id === templateId));
  const deck = result ? generation : null;
  const s3 = buildStrip(generation, activeVariant);
  // шаг «Текст» — одно состояние на заголовок и тело плиты 02; разбор текста в нём считается один раз на правку
  const text = useTextPlate();
  // шаг «Параметры и запуск» — одно состояние на заголовок плиты 03 (сводка, запуск) и её тело
  const params = useParamsPlate();
  // полоса 02 на «Создать» — текст поля; на сборке — тема сборки (пишет ли текст агент — по её запросу; «Улучшить
  // готовую» — имя исходной презентации, своё название у неё есть, если это та, что в поле); на результате — открытая
  // презентация: название и откуда текст
  const writer = !!health?.writer && modelOn;
  const buildText = useMemo(() => {
    if (!topic || topic.brief === null) return undefined;
    const from = topic.improved;
    const improve = from ? { ...from, title: improveSource?.name === from.name ? improveSource.title : undefined } : null;
    return textStrip(topic.brief, { line: textLine(topic.brief, writer && topic.useModels), improve });
  }, [topic, writer, improveSource]);
  const s2 = result ? (deck ? deckStrip(deck, activeVariant) : undefined)
    : build ? buildText
    : textStrip(brief, { line: text.line, improve: ui.improve ? improveSource : null });
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
      {/* слои результата: «Текст презентации» (до 160 px) и «На весь экран» (вся колода), z 5 */}
      <TextLayer />
      <Lightbox />
      {/* лист «Подробнее» (до 160 px, z 5): шесть вкладок и слой «Слайд N шаблона» */}
      <DetailsSheet />
      {/* пока раздел открыт, видимая полоса колоды над слоем закрывает его */}
      <Scrim open={!!ui.sect} onClose={() => dispatch({ type: "sect", sect: null })}
        label={ui.sect === "hist" ? "Закрыть «Мои презентации»" : "Закрыть «Шаблоны»"} />
      <HistoryLayer />
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
            h3={<ParamsHead pp={params} />} p3={<ParamsBody pp={params} />} b3={<BuildPlate />} s3={s3} p4={<ResultPlate />} layers={layers} />
          <div className="hp-hcell" />
        </div>
      </div>
    </div>
  );
}
