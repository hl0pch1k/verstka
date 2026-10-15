// «Не получилось» (boards/B-failed, V2 `bdFailed`): раскадровка гаснет, на её месте встаёт коробка ошибки — иконка-слои
// с красным знаком, «Не получилось собрать презентацию», причина простыми словами, «Вернуться к тексту» и «Собрать ещё
// раз» (тот же запрос). Появляется pop 360 мс через 120 мс.
// Помощник сужает колоду: поля коробки 48 → 24 (V2 версии 100). Сайт: заголовок и причина — одной ширины в обеих
// раскладках (не шире текста узкой, `text`), так что переносы не меняются посреди хода; кнопки, которым в узкой не
// хватает места в ряд (тесная колода, 1280), стоят столбиком в обеих (`column`).
import { Icon } from "../kit/Icon";

export function Failed({ text, onBack, onRetry, width, column }: {
  text: string; onBack(): void; onRetry(): void;
  /** Ширина текста коробки — общая для обеих раскладок (columns.ts `failText`). */
  width: number;
  /** Кнопки столбиком (columns.ts `failCol`). */
  column: boolean;
}) {
  return (
    <div className="p2-box p2-pop bf-empty p2-lic-host bd-errbox" role="alert"
      style={{ position: "absolute", left: 0, right: 0, top: 24, bottom: 0, animationDelay: "120ms" }}>
      <span className="p2-lic p2-lic-d p2-lic-err" aria-hidden="true">
        <span className="p2-lic-b" />
        <span className="p2-lic-f"><Icon name="alert" size={22} /></span>
      </span>
      <h2 className="bf-ttl" style={{ maxWidth: width }}>Не получилось собрать презентацию</h2>
      <p style={{ maxWidth: Math.min(480, width), margin: "8px 0 0", fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "#FFFFFF" }}>{text}</p>
      <div className="bd-acts" style={{ display: "flex", flexDirection: column ? "column" : "row", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 32 }}>
        <button type="button" className="p2-cta" onClick={onBack}>
          <Icon name="arrow-left" size={20} />
          <span>Вернуться к тексту</span>
        </button>
        <button type="button" className="bf-obd" onClick={onRetry}>
          <Icon name="refresh" size={18} />
          <span>Собрать ещё раз</span>
        </button>
      </div>
    </div>
  );
}
