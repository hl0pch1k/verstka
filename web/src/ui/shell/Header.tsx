// Шапка «Слоёв»: логотип (на главную) со строкой связи и пункты разделов. Разметка — boards/V2.dc.html,
// `<header class="p2-hdr">`.
import { useApp } from "../../store";
import { Brand } from "./Brand";
import { Nav } from "./Nav";
import { useGoHome } from "./useGoHome";

export function Header() {
  const { healthError } = useApp();
  const goHome = useGoHome();
  return (
    <header className="p2-hdr" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 64, padding: "0 48px" }}>
      <Brand offline={healthError} onHome={goHome} />
      <Nav />
    </header>
  );
}
