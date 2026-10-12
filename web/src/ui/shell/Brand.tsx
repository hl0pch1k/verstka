// Логотип Verstka (S-logo, вариант 18: слово и три полоски) и строка «Нет связи с сервером» рядом с ним.
// Разметка — boards/V2.dc.html, `<div class="of-wrap">` в шапке; без связи полоски краснеют и бегут (G-toasts).
import { Icon } from "../kit/Icon";
import { ofClasses } from "./offline";
import { useOffline } from "./useOffline";

export function Brand({ offline, onHome }: { offline: boolean; onHome: () => void }) {
  const { mode } = useOffline(offline);
  const c = ofClasses(offline, mode);
  return (
    <div className="of-wrap" style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <button type="button" className={c.brand} onClick={onHome} aria-label="Verstka — на главную, новая презентация"
        style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-start", gap: 0, padding: 0, border: 0, borderRadius: 8, background: "none", cursor: "pointer", color: "#0B1220" }}>
        <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 20, lineHeight: "24px", letterSpacing: "-0.03em" }}>Verstka</span>
        <span className="p2-bars" aria-hidden="true">
          <span className={c.mv}>
            <span className={c.tr}>
              {c.lb.map((lb, i) => (
                <span key={i} className={lb}>
                  <span className="p2-lbr"><span className={`p2-lbar p2-lbar${i + 1}`} /></span>
                </span>
              ))}
            </span>
          </span>
        </span>
      </button>
      <span role="status" aria-live="polite" className={c.line}
        style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#DC2626", fontSize: 14, fontWeight: 600, lineHeight: "20px", whiteSpace: "nowrap" }}>
        <Icon name="wifi-off" size={16} />
        <span>Нет связи с сервером — переподключение…</span>
      </span>
    </div>
  );
}
