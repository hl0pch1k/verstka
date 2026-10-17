// Результат на телефоне (доска M-result): плита 04 под полосами 01–03 — колонка во всю её видимую часть. Сверху вниз:
// название и строка «шаблон · N слайдов · когда», справа оценка (кнопка — лист «Подробнее» на «Качестве»); слайд (кнопка
// «на весь экран») с номером «3 / 12» в углу; лента миниатюр; варианты оформления сегментами с оценками; ряд действий
// «Замечания [N]», «Почему так», «Текст»; внизу — закреплённый ряд «Скачать PowerPoint» и «…» (меню: PDF, «Изменить
// текст», «Новая презентация»). Что не помещается над закреплённым рядом (короткое окно, панель замечаний, карточка
// «Изображение»), прокручивается внутри плиты. Данные, разметка на сцене и работа над слайдом — те же, что у ResultBody
// на компьютере: он передаёт их сюда готовыми.
import type { ReactNode } from "react";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { usePop } from "../kit/usePop";
import { useChanged } from "../kit/useChanged";
import { Shots } from "./Stage";
import { remarksSwitch } from "./marks";
import type { AsideData } from "./Aside";

export interface PhoneResultProps {
  d: AsideData;
  n: number;
  total: number;
  src: string | null;
  alt: string;
  aspect: number;
  /** Разметка на сцене (замечания, зоны изображения, эскиз исправления): есть — слайд не кнопка, а сцена с ней. */
  marks: ReactNode | null;
  film: ReactNode;
  /** Строка уведомления или неудачи — над колонкой (её же показывает компьютер над рабочей областью). */
  note: ReactNode | null;
  /** Панель замечаний или карточка «Изображение» — под рядом действий. */
  extra: ReactNode | null;
  /** Замечания на слайдах варианта (resultView `remarkCount`). */
  remarks: { count: number; errors: boolean };
  remarksOn: boolean;
  /** Почему «Замечания» недоступны (подсказка); null — доступны. */
  remarksOff: string | null;
  textOff?: string | null;
  onVariant(key: string): void;
  onRemarks(): void;
  onQuality(): void;
  onWhy(): void;
  onText(): void;
  onLightbox(): void;
  onEditText(): void;
  onNew(): void;
}

export function PhoneResult(p: PhoneResultProps) {
  const { d } = p;
  const more = usePop<HTMLButtonElement, HTMLDivElement>();
  const swapped = useChanged(d.variant);
  const chip = `${p.n} / ${p.total}`;
  // «Замечания» — как переключатель шапки сцены на компьютере (marks.ts `remarksSwitch`): нечего показывать — нет кнопки
  const sw = remarksSwitch(p.remarks, p.remarksOn);
  return (
    <div className="mr-col">
      <div className="mr-scroll">
        {p.note}
        <div className="mr-head p2-in" style={{ animationDelay: "160ms" }}>
          <div style={{ minWidth: 0 }}>
            <h1 className="mr-h1" title={d.title}>{d.title}</h1>
            <p className="mr-line" title={d.line}>{d.line}</p>
          </div>
          {d.score !== null && (
            <button type="button" className="mr-score" onClick={p.onQuality} aria-label={`Оценка качества ${d.score} из 100 — подробнее`}>
              <span className="mr-scw">
                <span key={d.variant} className={cls("mr-scn", swapped && "ra-xf")}>{d.score}</span>
                <span className="mr-sct"><span>из 100</span><span>оценка</span></span>
              </span>
            </button>
          )}
        </div>
        {p.marks ? (
          <div className="mr-slide mr-stage p2-in" style={{ aspectRatio: String(p.aspect), animationDelay: "200ms" }}>
            <Shots src={p.src} alt={p.alt} />
            {p.marks}
            <span className="mr-chip" aria-hidden="true">{chip}</span>
          </div>
        ) : (
          <button type="button" className="mr-slide p2-in" onClick={p.onLightbox} aria-label={`Открыть слайд ${chip} на весь экран`}
            style={{ aspectRatio: String(p.aspect), animationDelay: "200ms" }}>
            <Shots src={p.src} alt={p.alt} />
            <span className="mr-chip" aria-hidden="true">{chip}</span>
          </button>
        )}
        {p.film}
        {d.variants.length > 1 && (
          <div role="group" aria-label="Вариант оформления" className="mr-segs p2-in" style={{ animationDelay: "280ms" }}>
            {d.variants.map((s) => (
              <button key={s.key} type="button" className={cls("p2-rseg", s.key === d.variant && "p2-rseg-on")} aria-pressed={s.key === d.variant}
                title={s.title} onClick={() => p.onVariant(s.key)}>
                <span className="mr-sgl">{s.label}</span>
                {s.score !== null && <span className="p2-rsc">{s.score}</span>}
              </button>
            ))}
          </div>
        )}
        <div className="mr-acts p2-in" style={{ animationDelay: "320ms" }}>
          {sw.shown && (
            <button type="button" className={cls("p2-gb", p.remarksOn && "mr-on")} onClick={p.remarksOff ? undefined : p.onRemarks} aria-pressed={p.remarksOn}
              aria-disabled={p.remarksOff ? true : undefined} title={p.remarksOff ?? undefined}
              aria-label={sw.counter ? `Замечания: ${p.remarks.count}${p.remarks.errors ? ", есть ошибка" : ""}` : "Замечания"}>
              <span>Замечания</span>
              {sw.counter && <span className={cls("mr-badge", sw.counter === "err" && "mr-badge-err")} aria-hidden="true">{p.remarks.count}</span>}
            </button>
          )}
          <button type="button" className="p2-gb" onClick={p.onWhy}>Почему так</button>
          <button type="button" className="p2-gb" onClick={p.onText} aria-label="Текст презентации"
            aria-disabled={p.textOff ? true : undefined} title={p.textOff ?? undefined}>Текст</button>
        </div>
        {p.extra}
      </div>
      <div className="mr-bar">
        {d.pptx ? (
          <a className="p2-cta p2-cta-flat" href={d.pptx} download={`${d.fileBase}.pptx`} title={d.pptxTitle}>
            <Icon name="download" size={20} />
            <span>Скачать PowerPoint</span>
          </a>
        ) : (
          <button type="button" className="p2-cta p2-cta-flat" disabled title="Файл PowerPoint ещё не готов">
            <Icon name="download" size={20} />
            <span>Скачать PowerPoint</span>
          </button>
        )}
        <button ref={more.btn} type="button" className="p2-rbl mr-more" onClick={more.toggle} aria-label="Ещё: PDF, изменить текст, новая презентация"
          aria-haspopup="true" aria-expanded={more.open} aria-controls="mr-more">
          <Icon name="more" size={20} />
        </button>
        <div ref={more.box} id="mr-more" role="group" aria-label="Ещё" className={cls("mr-pop", more.open && "mr-pop-on")}
          onKeyDown={more.onKey} onBlur={more.onBlur} aria-hidden={more.open ? undefined : true}>
          {d.pdf && (
            <a className="mp-mi" href={d.pdf} download={`${d.fileBase}.pdf`} tabIndex={more.open ? undefined : -1}
              onClick={() => more.pick(() => {})}>
              <Icon name="file" size={20} /><span>Скачать PDF</span>
            </a>
          )}
          <button type="button" className="mp-mi" tabIndex={more.open ? undefined : -1} onClick={() => more.pick(p.onEditText)}>
            <Icon name="pen" size={20} /><span>Изменить текст</span>
          </button>
          <button type="button" className="mp-mi" tabIndex={more.open ? undefined : -1} onClick={() => more.pick(p.onNew)}>
            <Icon name="plus" size={20} /><span>Новая презентация</span>
          </button>
        </div>
      </div>
    </div>
  );
}
