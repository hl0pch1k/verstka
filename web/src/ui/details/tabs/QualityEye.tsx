// «Взгляд дизайнера» на вкладке «Качество» (boards/D-quality, правая колонка): что модель зрения увидела на готовых
// слайдах — пересобранные слайды «было / стало» с причиной, оставленные с объяснением и свёрнутые мелкие замечания.
import { Icon } from "../../kit/Icon";
import { Acc, Shot } from "../parts";
import type { EyeView } from "../quality";

const P = { margin: "16px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220" } as const;
const FRAME = { width: "100%", aspectRatio: "16 / 9", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" } as const;

export function EyeBox({ eye, open, onToggle }: { eye: EyeView; open: boolean; onToggle(): void }) {
  return (
    <section className="dd-box p2-in" aria-labelledby="dq-eye-h" style={{ animationDelay: "320ms" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span className="dd-ico" aria-hidden="true"><Icon name="eye" size={20} /></span>
        <div style={{ minWidth: 0 }}>
          <h3 id="dq-eye-h" className="dd-h">Взгляд дизайнера</h3>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{eye.line}</p>
        </div>
      </div>
      <p style={{ ...P, color: "#5A6272" }}>{eye.intro}</p>

      {eye.fixed.map((f) => (
        <article key={f.slide} aria-label={`${f.tag} пересобран`} style={{ marginTop: 16, padding: 16, borderRadius: 16, background: "#F3F4F1" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, height: 24 }}>
            <span className="dd-tag" style={{ background: "#FFFFFF", color: "#0B1220" }}>{f.tag}</span>
            <span style={{ minWidth: 0, fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.title}</span>
            <span className="dd-tag dd-tag-b" style={{ marginLeft: "auto", flex: "none" }}><Icon name="refresh" size={14} />пересобрал</span>
          </div>
          <p style={{ ...P, marginTop: 12 }}>{f.text}</p>
          {f.pics ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16, marginTop: 16 }}>
              <figure style={{ margin: 0 }}>
                <figcaption className="dd-cap" style={{ marginBottom: 8 }}>Было</figcaption>
                <Shot src={f.pics.before} alt={`${f.tag} до пересборки`} style={FRAME} />
              </figure>
              <figure style={{ margin: 0 }}>
                <figcaption className="dd-cap" style={{ marginBottom: 8, color: "#2563EB" }}>Стало</figcaption>
                <Shot src={f.pics.after} alt={`${f.tag} после пересборки`} style={FRAME} />
              </figure>
            </div>
          ) : f.redone ? (
            <p style={{ ...P, color: "#5A6272" }}>Слайд с тех пор переделан — картинки «было / стало» к нему больше не относятся.</p>
          ) : null}
          {f.why && <p style={P}><b style={{ fontWeight: 700 }}>Почему новая:</b> {f.why}</p>}
        </article>
      ))}

      {eye.kept.map((k) => (
        <p key={k.slide} style={{ ...P, display: "flex", alignItems: "flex-start", gap: 12 }}>
          <span className="dd-tag dd-tag-n" style={{ flex: "none", marginTop: -2 }}>{k.tag}</span>
          <span>{k.text}</span>
        </p>
      ))}

      {eye.seen.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <Acc id="dq-eye-rows" title="Мелкие замечания модели" n={eye.seen.length} open={open} onToggle={onToggle} first small>
            {eye.seen.map((s) => (
              <li key={s.slide} className="dq-row"><span className="dd-tag dd-tag-n">{s.tag}</span><span>{s.text}</span></li>
            ))}
          </Acc>
        </div>
      )}
    </section>
  );
}
