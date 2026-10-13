// Плита 03 «Параметры и запуск» (V2, плита 03; C-params; C-errors). Справа в заголовке — сводка «VK Tech · 12 слайдов ·
// 3 варианта» (под ней строка ошибки запуска) и «Создать презентацию»; тело `#p2-b3` — короткий ряд: степпер слайдов,
// варианты оформления, «Модель пишет тексты» и «С изображениями». Ниже — «Все параметры» (`#p2-b3m`, ParamsAll) и
// стрелка под «03». Стрелка, «03» и заголовок переключают `ui.more` (заголовок с «03» — в Deck): плиты 01/02 уходят в
// полосы, плита 03 поднимается на 80 за 520 мс, меню проявляется лесенкой с 40 мс, стрелка поворачивается вверх.
// Разметка — boards/V2.dc.html, правила — params.ts.
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApp } from "../../store";
import { humanError } from "../../lib/errors";
import { tplLabel } from "../../lib/plain";
import { dictatedSlides } from "../../lib/textFacts";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Switch } from "../kit/Switch";
import { useHeld, useModelOn } from "./ImproveNote";
import { ParamsAll } from "./ParamsAll";
import {
  buildRequest, imagesHint, presetParams, SLIDES_LOCKED, slidesView, slideWord, stepSlides, summaryLine, toggleStrategy, variantCards, writesHint,
  type SlidesView, type SwitchView, type VariantCard,
} from "./params";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");

export const NO_TEMPLATE = "Выберите или загрузите шаблон";
/** Сервер не начал сборку, а причину сказал не по-русски. */
export const START_FAILED = "Не удалось начать сборку — попробуйте ещё раз";
const START_PREFIX = /^Не удалось начать сборку презентации:\s*/;

/** Состояние шага на обе части плиты (заголовок и тело). Одно на приложение — его создаёт AppShell. */
export interface ParamsPlate {
  slides: SlidesView;
  step(delta: number): void;
  cards: VariantCard[];
  toggle(name: string): void;
  writes: SwitchView; eyes: SwitchView; pictures: SwitchView;
  toggleWrites(): void; toggleEyes(): void; togglePictures(): void;
  writesHint: string; imagesHint: string;
  summary: string;
  /** Строка под сводкой: поле пусто или коротко, нет шаблона, сервер не начал сборку; null — всё хорошо. */
  issue: string | null;
  /** Строка повторяет ошибку у поля «Текст» (её читает та строка). */
  issueEcho: boolean;
  /** Запрос сборки ушёл, ответа ещё нет. */
  starting: boolean;
  start(): void;
}

export function useParamsPlate(): ParamsPlate {
  const {
    params, setParams, brief, strategies, health, templates, templateId, checkText, textIssue, startGeneration, ui, dispatch, notices,
    improveSource, composerPreset, takeComposerPreset,
  } = useApp();
  const modelOn = useModelOn();
  const imagesOn = !!health?.images?.configured;
  const improve = ui.improve ? improveSource : null;

  // «Изменить текст» на результате: параметры собранной презентации встают сюда (текст взяло поле)
  useEffect(() => {
    if (!composerPreset) return;
    setParams((p) => presetParams(p, composerPreset));
    takeComposerPreset();
  }, [composerPreset, setParams, takeComposerPreset]);

  // число слайдов, заданное в тексте, — один разбор на изменение текста
  const dictated = useMemo(() => dictatedSlides(brief), [brief]);
  const slides = slidesView(params.slides, dictated);
  const cards = useMemo(() => variantCards(strategies, params.strategies), [strategies, params.strategies]);
  const step = useCallback((delta: number) => setParams((p) => ({ ...p, slides: stepSlides(p.slides, delta) })), [setParams]);
  const toggle = useCallback((name: string) => {
    setParams((p) => {
      const next = toggleStrategy(strategies, p.strategies, name);
      return next ? { ...p, strategies: next } : p;
    });
  }, [setParams, strategies]);

  const tpl = templates.find((t) => t.template_id === templateId);
  const summary = summaryLine(tpl ? tplLabel(tpl) : null, slides.count, cards.filter((c) => c.on).length);

  // запуск: ответ сервера — это смена экрана (сборка началась) или строка области «Сборка» (не началась). Строку
  // показывает только та, что пришла после нажатия; ушли с «Создать» — нажатие забыто
  const [attempt, setAttempt] = useState<number | null>(null);
  const [noTpl, setNoTpl] = useState(false);
  useEffect(() => {
    if (ui.screen !== "create") setAttempt(null);
  }, [ui.screen]);
  const note = notices.build;
  const failed = attempt !== null && note?.kind === "error" && note.at >= attempt ? note.text : null;
  const starting = attempt !== null && failed === null;

  const start = () => {
    if (starting) return;
    setNoTpl(false);
    setAttempt(null);
    // поле пусто или коротко: ошибка встаёт у поля, плиты поднимают шаг «Текст» (V2 `txStart`)
    if (!checkText()) return;
    if (!templateId) {
      setNoTpl(true);
      dispatch({ type: "open", step: "tpl" });
      return;
    }
    setAttempt(Date.now());
    void startGeneration(buildRequest({ templateId, brief, params, strategies, modelOn, imagesOn, improve }), slides.count);
  };

  const textBad = textIssue && (textIssue.kind === "empty" || textIssue.kind === "short") ? textIssue.text : null;
  const issue = textBad ?? (noTpl && !templateId ? NO_TEMPLATE : null) ?? (failed !== null ? humanError(failed.replace(START_PREFIX, ""), START_FAILED) : null);

  const writes: SwitchView = { on: modelOn && params.useModels, disabled: !modelOn, title: modelOn ? undefined : "Модель не подключена" };
  // «Улучшить готовую»: модель смотрит на каждый новый слайд (так говорит заметка над полем) — переключатель стоит
  const eyes: SwitchView = {
    on: modelOn && (params.eyes || !!improve), disabled: !modelOn || !!improve,
    title: !modelOn ? "Модель не подключена" : improve ? "В «Улучшить готовую» модель смотрит на каждый новый слайд" : undefined,
  };
  const pictures: SwitchView = { on: imagesOn && params.pictures, disabled: !imagesOn, title: imagesOn ? undefined : "Модель изображений не подключена" };

  return {
    slides, step, cards, toggle, writes, eyes, pictures,
    toggleWrites: () => setParams((p) => ({ ...p, useModels: !p.useModels })),
    toggleEyes: () => setParams((p) => ({ ...p, eyes: !p.eyes })),
    togglePictures: () => setParams((p) => ({ ...p, pictures: !p.pictures })),
    writesHint: writesHint(writes.on), imagesHint: imagesHint(pictures.on),
    summary, issue, issueEcho: textBad !== null, starting, start,
  };
}

/** Заголовок плиты 03 справа (слот `h3`): сводка, строка ошибки под ней (C-errors) и «Создать презентацию». */
export function ParamsHead({ pp }: { pp: ParamsPlate }) {
  const bad = pp.issue !== null;
  const shown = useHeld(pp.issue);
  return (
    <>
      <span style={{ flex: 1, minWidth: 0 }} />
      <div className={cls("pp-sum", bad && "pp-bad")}>
        <span className="p2-hide-s pp-sumt" title={pp.summary}>{pp.summary}</span>
        <div id="pp-err" className={cls("pp-err", show(bad))}>
          <ErrorLine key={shown ?? ""} text={shown ?? ""} lines={1} quiet={pp.issueEcho} style={{ color: "#F87171" }} />
        </div>
      </div>
      <button type="button" className="p2-cta" onClick={pp.start} aria-busy={pp.starting || undefined} aria-describedby={bad ? "pp-err" : undefined}>
        <span>Создать презентацию</span>
        <Icon name="arrow-right" size={20} />
      </button>
    </>
  );
}

/** Степпер короткого ряда: «−», число и «слайдов» (или «задано в тексте»), «+». */
function ShortSlides({ pp }: { pp: ParamsPlate }) {
  const s = pp.slides;
  // подпись под числом сменилась («слайдов» ↔ «задано в тексте») — новая проявляется; при первом показе — как есть
  const [first] = useState(s.locked);
  const [changed, setChanged] = useState(false);
  if (!changed && s.locked !== first) setChanged(true);
  const enter = changed ? "p2-in" : undefined;
  return (
    <div className="p2-box p2-stag" title={s.locked ? SLIDES_LOCKED : undefined}
      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 88, padding: "0 16px", transitionDelay: "0ms" }}>
      <button type="button" className="p2-rb" onClick={() => pp.step(-1)} disabled={!s.dec} aria-label="Меньше слайдов"><Icon name="minus" size={18} /></button>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 0 }}>
        <span aria-live="polite" style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#FFFFFF" }}>{s.count}</span>
        {s.locked
          ? <span key="locked" className={enter} style={{ fontSize: 12, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.64)", whiteSpace: "nowrap" }}>задано в тексте</span>
          : <span key="word" className={enter} style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{slideWord(s.count)}</span>}
      </div>
      <button type="button" className="p2-rb" onClick={() => pp.step(1)} disabled={!s.inc} aria-label="Больше слайдов"><Icon name="plus" size={18} /></button>
    </div>
  );
}

const SW_ROW = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 32 } as const;
const SW_NAME = { fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#FFFFFF" } as const;

/** Тело плиты 03 (слот `p3`): короткий ряд `#p2-b3`, «Все параметры» `#p2-b3m` и стрелка под «03». */
export function ParamsBody({ pp }: { pp: ParamsPlate }) {
  const { ui, dispatch } = useApp();
  const create = ui.screen === "create";
  const more = create && ui.more;
  const on = create && ui.open === "text" && !ui.more;
  return (
    <>
      <div id="p2-b3" className={cls("p2-body p2-params pp-row", show(on))} style={{ "--pp-n": pp.cards.length } as CSSProperties}>
        <ShortSlides pp={pp} />
        {pp.cards.map((v, i) => (
          <div key={v.name} className="p2-stag" style={{ transitionDelay: `${40 + i * 40}ms` }}>
            <button type="button" role="checkbox" aria-checked={v.on} className={cls("p2-vc", v.on && "p2-vc-on")} onClick={() => pp.toggle(v.name)} title={v.full}>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, width: "100%" }}>
                <span className="pp-vt" style={{ fontSize: 16, fontWeight: 700, lineHeight: "24px", color: "#FFFFFF" }}>{v.title}</span>
                <span className="p2-vbox" aria-hidden="true"><Icon name="check" size={12} /></span>
              </span>
              <span className="pp-vt" style={{ maxWidth: "100%", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{v.desc}</span>
            </button>
          </div>
        ))}
        <div className="p2-box p2-stag pp-sws" style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 8, height: 88, padding: "8px 16px", transitionDelay: "160ms" }}>
          <div style={SW_ROW}>
            <span id="p2-sw1" style={SW_NAME}>Модель пишет тексты</span>
            <Switch on={pp.writes.on} disabled={pp.writes.disabled} title={pp.writes.title} labelledBy="p2-sw1" onToggle={pp.toggleWrites} />
          </div>
          <div style={SW_ROW}>
            <span id="p2-sw2" style={SW_NAME}>С изображениями</span>
            <Switch on={pp.pictures.on} disabled={pp.pictures.disabled} title={pp.pictures.title} labelledBy="p2-sw2" onToggle={pp.togglePictures} />
          </div>
        </div>
      </div>
      <ParamsAll pp={pp} on={more} />
      <button type="button" className={cls("p2-more", more && "p2-more-up")} onClick={() => dispatch({ type: "more" })}
        aria-expanded={more} aria-controls="p2-b3m" aria-label={more ? "Свернуть параметры" : "Открыть все параметры"} title={more ? "Свернуть" : "Все параметры"}
        style={{ position: "absolute", left: 48, top: 140, zIndex: 1 }}>
        <span className="p2-more-w" aria-hidden="true">03</span>
        {/* как в V2: 64 px, толщина 2.25 — цифра «03» рядом той же прозрачности */}
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6.5 9.5L12 15l5.5-5.5" />
        </svg>
      </button>
    </>
  );
}
