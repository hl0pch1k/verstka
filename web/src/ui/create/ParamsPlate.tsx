// Плита 03 «Параметры и запуск» (V2, плита 03; C-params; C-errors). Справа в заголовке — сводка «VK Tech · 12 слайдов ·
// 3 варианта» (под ней строка ошибки запуска или тихая «Сборка уже идёт») и «Создать презентацию»; тело `#p2-b3` —
// короткий ряд: степпер слайдов, варианты оформления, «Модель пишет тексты» и «С изображениями». Ниже — «Все параметры»
// (`#p2-b3m`, ParamsAll) и стрелка под «03». Стрелка, «03» и заголовок переключают `ui.more` (заголовок с «03» — в
// Deck): плиты 01/02 уходят в полосы, плита 03 поднимается на 80 за 520 мс, меню проявляется лесенкой с 40 мс, стрелка
// поворачивается вверх.
// Разметка — boards/V2.dc.html, правила — params.ts.
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import { dictatedSlides } from "../../lib/textFacts";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Switch } from "../kit/Switch";
import { useHeld, useModelOn } from "./ImproveNote";
import { ParamsAll } from "./ParamsAll";
import { errBelow, rowMode } from "../deck/fit";
import { useDeckWidth } from "../deck/useDeckFit";
import { useSwap } from "../kit/useSwap";
import {
  buildRequest, eyesOn, imagesHint, picturesOn, presetParams, SLIDES_LOCKED, slidesView, slideWord, startFailure, stepSlides,
  summaryLine, toggleEyes as nextEyes, togglePictures as nextPictures, toggleStrategy, variantCards, writesHint,
  type ImagesInfo, type SlidesView, type SwitchView, type VariantCard,
} from "./params";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");

export const NO_TEMPLATE = "Выберите или загрузите шаблон";
export const BUILD_RUNNING = "Сборка уже идёт";

/** Строка под сводкой: ошибка (поле пусто или коротко, нет шаблона, сервер не начал сборку; `echo` — она повторяет
 *  ошибку у поля «Текст», её читает та строка) или тихая «Сборка уже идёт» со ссылкой «Вернуться к сборке». */
export type HeadLine = { kind: "error"; text: string; echo: boolean } | { kind: "busy" };

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
  /** Строка под сводкой; null — сказать нечего. */
  line: HeadLine | null;
  /** Запрос сборки ушёл, ответа ещё нет. */
  starting: boolean;
  start(): void;
  /** «Вернуться к сборке»: экран «Сборка» идущей сборки. */
  goBuild(): void;
}

export function useParamsPlate(): ParamsPlate {
  const {
    params, setParams, brief, strategies, health, templates, templateId, checkText, textIssue, startGeneration, ui, dispatch, notices,
    improveSource, composerPreset, takeComposerPreset, building,
  } = useApp();
  const modelOn = useModelOn();
  const images: ImagesInfo = { configured: !!health?.images?.configured, enabled: !!health?.images?.enabled };
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
  // показывает только неудача этого запроса (`startFailure`: после нажатия и именно «не удалось начать», а не строка
  // упавшей прежней сборки); ушли с «Создать» — нажатие забыто
  const [attempt, setAttempt] = useState<number | null>(null);
  const [noTpl, setNoTpl] = useState(false);
  // сборка уже идёт (любая задача generate, не только самая новая задача в слоте): вторая поверх не начинается, нажатие
  // ставит тихую строку; сборка кончилась — строка уходит
  const [busyAsk, setBusyAsk] = useState(false);
  useEffect(() => {
    if (ui.screen !== "create") {
      setAttempt(null);
      setBusyAsk(false);
    }
  }, [ui.screen]);
  useEffect(() => {
    if (!building) setBusyAsk(false);
  }, [building]);
  const failed = startFailure(notices.build, attempt);
  const starting = attempt !== null && failed === null;

  const start = () => {
    if (starting) return;
    setNoTpl(false);
    setAttempt(null);
    setBusyAsk(building);
    if (building) return;
    // поле пусто или коротко: ошибка встаёт у поля, плиты поднимают шаг «Текст» (V2 `txStart`)
    if (!checkText()) return;
    if (!templateId) {
      setNoTpl(true);
      dispatch({ type: "open", step: "tpl" });
      return;
    }
    setAttempt(Date.now());
    void startGeneration(buildRequest({ templateId, brief, params, strategies, modelOn, images, improve }), slides.count);
  };

  const textBad = textIssue && (textIssue.kind === "empty" || textIssue.kind === "short") ? textIssue.text : null;
  const bad = textBad ?? (noTpl && !templateId ? NO_TEMPLATE : null) ?? failed;
  const line: HeadLine | null = busyAsk && building ? { kind: "busy" } : bad !== null ? { kind: "error", text: bad, echo: bad === textBad } : null;

  const writes: SwitchView = { on: modelOn && params.useModels, disabled: !modelOn, title: modelOn ? undefined : "Модель не подключена" };
  // взгляд дизайнера: пока не трогали — как модель; «Улучшить готовую»: модель смотрит на каждый новый слайд (так
  // говорит заметка над полем) — переключатель стоит
  const eyes: SwitchView = {
    on: eyesOn(params, modelOn) || (modelOn && !!improve), disabled: !modelOn || !!improve,
    title: !modelOn ? "Модель не подключена" : improve ? "В «Улучшить готовую» модель смотрит на каждый новый слайд" : undefined,
  };
  const pictures: SwitchView = { on: picturesOn(params, images), disabled: !images.configured, title: images.configured ? undefined : "Модель изображений не подключена" };

  return {
    slides, step, cards, toggle, writes, eyes, pictures,
    toggleWrites: () => setParams((p) => ({ ...p, useModels: !p.useModels })),
    toggleEyes: () => setParams((p) => nextEyes(p, modelOn)),
    togglePictures: () => setParams((p) => nextPictures(p, images)),
    writesHint: writesHint(writes.on), imagesHint: imagesHint(pictures.on),
    summary, line, starting, start,
    goBuild: () => dispatch({ type: "go", screen: "build" }),
  };
}

/** Тихая строка (не ошибка): сборка уже идёт, вторая поверх не начинается; «Вернуться к сборке» — её экран. */
function BusyLine({ onBack }: { onBack(): void }) {
  return (
    <p role="status" className="pp-busy">
      <span>{BUILD_RUNNING}</span>
      <button type="button" className="pp-go" onClick={onBack}>Вернуться к сборке</button>
    </p>
  );
}

/** Заголовок плиты 03 справа (слот `h3`): сводка, строка под ней (ошибка — C-errors, или «Сборка уже идёт») и
 *  «Создать презентацию». */
export function ParamsHead({ pp }: { pp: ParamsPlate }) {
  const on = pp.line !== null;
  // уходящая строка гаснет со своим текстом
  const shown = useHeld(pp.line);
  // плита 03 уже доски (окно около 1280, помощник): строке ошибки тесно рядом со сводкой — она встаёт под ряд заголовка
  const low = errBelow(useDeckWidth());
  return (
    <>
      <span style={{ flex: 1, minWidth: 0 }} />
      <div className={cls("pp-sum", on && "pp-bad", low && "pp-low")}>
        <span className="p2-hide-s pp-sumt" title={pp.summary}>{pp.summary}</span>
        <div id="pp-err" className={cls("pp-err", show(on))}>
          {shown?.kind === "busy"
            ? <BusyLine onBack={pp.goBuild} />
            : <ErrorLine key={shown?.text ?? ""} text={shown?.text ?? ""} lines={1} quiet={shown?.echo} style={{ color: "#F87171" }} />}
        </div>
      </div>
      {/* тесная колода (помощник при 1280) — «Создать»: кнопка целиком видна рядом с названием шага */}
      <button type="button" className="p2-cta pp-cta" onClick={pp.start} aria-busy={pp.starting || undefined} aria-describedby={on ? "pp-err" : undefined}
        aria-label="Создать презентацию">
        <span className="pp-cta-l">Создать презентацию</span>
        <span className="pp-cta-s">Создать</span>
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
/** Варианты в тесной колоде (помощник при 1280): одна коробка рядом со степпером, варианты — строками с галочкой. */
function VariantList({ pp }: { pp: ParamsPlate }) {
  return (
    <div className="p2-box p2-stag pp-vlist" role="group" aria-label="Варианты оформления" style={{ transitionDelay: "40ms" }}>
      {pp.cards.map((v) => (
        <button key={v.name} type="button" role="checkbox" aria-checked={v.on} className={cls("pp-vli", v.on && "pp-vli-on")} onClick={() => pp.toggle(v.name)} title={v.full}>
          <span className="p2-vbox" aria-hidden="true"><Icon name="check" size={12} /></span>
          <span className="pp-vt">{v.title}</span>
        </button>
      ))}
    </div>
  );
}

export function ParamsBody({ pp }: { pp: ParamsPlate }) {
  const { ui, dispatch } = useApp();
  const create = ui.screen === "create";
  const more = create && ui.more;
  const on = create && ui.open === "text" && !ui.more;
  // короткий ряд по ширине колоды (fit.ts `rowMode`): полный (доска), без переключателей, узкий, тесный — варианты
  // карточками рядом со степпером не помещаются, одна коробка-список. Ряд меняется перекрёстным затуханием (useSwap):
  // старый гаснет, подменяется невидимым — и разметка, и правила `.pp-row[data-row=…]` сразу, — новый проявляется
  const width = useDeckWidth();
  const row = useSwap(rowMode(width), on);
  const tight = row.shown === "tight";
  return (
    <>
      <div className={row.cls}>
      <div id="p2-b3" className={cls("p2-body p2-params pp-row", show(on))} data-row={row.shown} style={{ "--pp-n": pp.cards.length } as CSSProperties}>
        <ShortSlides pp={pp} />
        {tight ? <VariantList pp={pp} /> : pp.cards.map((v, i) => (
          <div key={v.name} className="p2-stag" style={{ transitionDelay: `${40 + i * 40}ms` }}>
            <button type="button" role="checkbox" aria-checked={v.on} className={cls("p2-vc pp-vc", v.on && "p2-vc-on")} onClick={() => pp.toggle(v.name)} title={v.full}>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, width: "100%" }}>
                <span className="pp-vt" style={{ fontSize: 16, fontWeight: 700, lineHeight: "24px", color: "#FFFFFF" }}>{v.title}</span>
                <span className="p2-vbox" aria-hidden="true"><Icon name="check" size={12} /></span>
              </span>
              <span className="pp-vt pp-vd" style={{ maxWidth: "100%", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.64)" }}>{v.desc}</span>
            </button>
          </div>
        ))}
        {/* переключатели — только в полном ряду (варианту нужно 173 px); уже — они в «Все параметры» */}
        {row.shown === "full" && (
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
        )}
      </div>
      </div>
      <ParamsAll pp={pp} on={more} short={rowMode(width) !== "full"} />
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
