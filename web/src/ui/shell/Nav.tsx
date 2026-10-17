// Пункты шапки: «Мои презентации» и «Шаблоны» открывают слои-разделы (`ui.sect`), «Помощник» — плиту помощника
// (`ui.helper`); открытый пункт — белая таблетка p2-nav-on. Разметка — boards/V2.dc.html, `<nav class="p2-navs">`.
// Телефон (окно уже 768, stack.css; доски M-create, M-result): пункты — за круглой кнопкой меню (раскрытие,
// aria-expanded; открыта — тёмная): белая плита со значками под шапкой, проявляется как меню «Из файла»; пункт, Esc,
// щелчок мимо или фокус, ушедший из меню (Tab за последний пункт), закрывают её, Esc возвращает фокус на кнопку. На
// компьютере и планшете кнопки нет — пункты в ряд, как на холсте.
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { usePop } from "../kit/usePop";
import { usePhone } from "./tier";

export function Nav() {
  const { ui, dispatch } = useApp();
  const hist = ui.sect === "hist";
  const tpls = ui.sect === "tpls";
  const phone = usePhone();
  // меню — только на телефоне; окно стало шире — меню нет (kit/usePop: фокус, Esc, щелчок и фокус мимо)
  const pop = usePop<HTMLButtonElement, HTMLElement>(phone);
  const open = pop.open;
  const pick = pop.pick;
  return (
    <>
      <button ref={pop.btn} type="button" id="p2-navbtn" className="p2-navbtn" aria-expanded={open} aria-controls="p2-navmenu"
        aria-label="Меню" title="Мои презентации, шаблоны, помощник" onClick={pop.toggle}>
        <Icon name="menu" size={20} />
      </button>
      <nav ref={pop.box} id="p2-navmenu" className={cls("p2-navs", open && "p2-navs-on")} aria-label="Разделы" onKeyDown={pop.onKey} onBlur={pop.onBlur}
        style={{ display: "flex", alignItems: "center", gap: 8, marginRight: -16 }}>
        <button type="button" className={cls("p2-nav", hist && "p2-nav-on")} aria-expanded={hist} aria-controls="p2-lay-h"
          onClick={() => pick(() => dispatch({ type: "sect", sect: hist ? null : "hist" }))}>{phone && <Icon name="history" size={20} />}Мои презентации</button>
        <button type="button" className={cls("p2-nav", tpls && "p2-nav-on")} aria-expanded={tpls} aria-controls="p2-lay-t"
          onClick={() => pick(() => dispatch({ type: "sect", sect: tpls ? null : "tpls" }))}>{phone && <Icon name="layout" size={20} />}Шаблоны</button>
        <button type="button" id="hp-nav" className={cls("p2-nav", ui.helper && "p2-nav-on")} aria-expanded={ui.helper} aria-controls="hp-help"
          title={ui.helper ? "Закрыть помощника" : "Открыть помощника"}
          onClick={() => pick(() => dispatch({ type: "set", patch: { helper: !ui.helper } }))}>{phone && <Icon name="chat" size={20} />}Помощник</button>
      </nav>
    </>
  );
}
