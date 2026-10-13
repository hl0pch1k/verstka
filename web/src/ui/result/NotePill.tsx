// Уведомление над рабочей областью (R-aside, V2 `ra-note`): в покое — таблетка «иконка + заголовок + ›»; по клику
// голубая подложка раскрывается вправо (clip-path 360 мс), затем лесенкой (40 мс) проявляются основание и кнопки;
// сворачивание — кнопки гаснут 120 мс, подложка уезжает влево 240 мс. Движение — классы ra-note-on / ra-ni1…5
// (result.css). Текст и действия — `noteView` (deckNotice): чего у презентации нет, той кнопки нет. Уведомления нет, а
// есть строка неудачи — ряд (48 px) без таблетки (NoteRow); нет ни того, ни другого — нет и ряда: рабочая область
// встаёт с самого верха (ResultPlate, resultView `workGeo`; доски R-remarks, R-picture).
import type { ReactNode } from "react";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import type { NoteView } from "./resultView";

export interface NoteActions {
  onToggle(): void;
  onClose(): void;
  /** «Показать текст» — слой «Текст презентации» (TextLayer). */
  onShowText(): void;
  /** Текста у презентации нет — «Показать текст» приглушена и не открывает слой, причина в подсказке (V2 rt-nb-off). */
  textOff?: string | null;
  onRebuild(): void;
  onRewrite(): void;
  /** «Собрать ещё раз» сейчас не начнётся (идёт другая сборка, модель на паузе) — кнопка приглушена, причина в подсказке. */
  rebuildOff: string | null;
  /** «Собрать ещё раз» нажата, сервер ещё не ответил: дуга загрузки вместо значка, кнопка занята. */
  rebuildBusy?: boolean;
}

/** Ряд уведомления без таблетки: сказать о презентации нечего, а строка неудачи есть («Не удалось открыть презентацию»,
 *  отказ «Собрать ещё раз») — она на месте таблетки. */
export function NoteRow({ children }: { children?: ReactNode }) {
  return (
    <div className="ra-note p2-in" style={{ gap: 16, animationDelay: "160ms" }}>
      {children}
    </div>
  );
}

export function NotePill({ note, open, actions, line }: {
  note: NoteView;
  open: boolean;
  actions: NoteActions;
  /** Строка неудачи результата (не открылась презентация, не началась повторная сборка) — справа в том же ряду. */
  line?: ReactNode;
}) {
  const off = actions.rebuildOff;
  const busy = !!actions.rebuildBusy;
  return (
    <div className={cls("ra-note p2-in", open && "ra-note-on")} role="note" aria-label={note.label} style={{ animationDelay: "160ms" }}>
      <button type="button" className="ra-ntg" onClick={actions.onToggle} aria-expanded={open} aria-controls="ra-nd" title={open ? "Свернуть" : "Показать действия"}>
        <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="info" size={20} /></span>
        <span>{note.title}</span>
        <span className="ra-chev" aria-hidden="true"><Icon name="chevron-right" size={18} /></span>
      </button>
      <div id="ra-nd" className="ra-nd">
        <span className="ra-nbg" aria-hidden="true" />
        <span className="ra-ni ra-ni1"><span className="ra-src" title={note.full}>{note.body}</span></span>
        <span className="ra-nsp" aria-hidden="true" />
        {note.showText && (
          <span className="ra-ni ra-ni2">
            <button type="button" className={cls("p2-ob ra-nb", actions.textOff && "rt-nb-off")} onClick={actions.onShowText} aria-haspopup="dialog"
              aria-disabled={actions.textOff ? true : undefined} title={actions.textOff ?? undefined}>
              <Icon name="file-text" size={18} />
              <span>Показать текст</span>
            </button>
          </span>
        )}
        {note.retry && (
          <span className="ra-ni ra-ni3">
            <button type="button" className={cls("p2-ob ra-nb", off && "rt-nb-off")} onClick={actions.onRebuild} aria-disabled={off || busy ? true : undefined}
              aria-busy={busy || undefined} title={off ?? (busy ? "Отправляю запрос на сборку…" : "Собрать ту же презентацию заново")}>
              {busy ? <span style={{ display: "flex", color: "#2563EB" }}><Spinner size={18} /></span> : <Icon name="retry" size={18} />}
              <span>Собрать ещё раз</span>
            </button>
          </span>
        )}
        {note.rewrite && (
          <span className="ra-ni ra-ni4">
            <button type="button" className="p2-ob ra-nb" onClick={actions.onRewrite}>
              <Icon name="pen" size={18} />
              <span>Дописать текст</span>
            </button>
          </span>
        )}
        <span className="ra-ni ra-ni5">
          <button type="button" className="p2-rbl ra-nx" onClick={actions.onClose} aria-label="Свернуть уведомление" title="Свернуть">
            <Icon name="x" size={18} />
          </button>
        </span>
      </div>
      {line}
    </div>
  );
}
