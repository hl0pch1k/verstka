import { test } from "node:test";
import assert from "node:assert/strict";
import { Children, type ReactElement } from "react";
import { Tx } from "../../kit/Tx";
import type { Fact } from "../files";
import { PassportFacts, scrollbarOf, type Scroller } from "./Files";

const el = (offsetWidth: number, clientWidth: number, visible = true): Scroller => ({ offsetWidth, clientWidth, checkVisibility: () => visible });

test("полоса прокрутки «Файлов»: обычная — 15, накладная — 0; не рисуется — замера нет", () => {
  assert.equal(scrollbarOf(el(1296, 1281), "visible"), 15);
  assert.equal(scrollbarOf(el(1296, 1296), "visible"), 0);
  assert.equal(scrollbarOf(el(1296, 1296), "hidden"), null); // догасшая вкладка: полосы нет, хотя содержимое длиннее
  assert.equal(scrollbarOf(el(0, 0, false), "visible"), null); // нет рамки
  assert.equal(scrollbarOf({ offsetWidth: 1296, clientWidth: 1281 }, "visible"), 15); // без checkVisibility (старый Safari)
});

test("скрыть и показать «Файлы» несколько раз — полоса та же, ни одного перезамера", () => {
  // обычная полоса: показана — 15; догасла (content-visibility: hidden) — у рамки полосы нет
  const shown = (): [Scroller, string] => [el(1296, 1281), "visible"];
  const hidden = (): [Scroller, string] => [el(1296, 1296), "hidden"];
  let bar = 0;
  let sets = 0;
  const measure = ([s, cv]: [Scroller, string]) => {
    const b = scrollbarOf(s, cv);
    if (b !== null && b !== bar) {
      bar = b;
      sets++;
    }
  };
  measure(shown()); // монтирование
  assert.equal(bar, 15);
  sets = 0;
  for (let i = 0; i < 5; i++) {
    measure(hidden());
    assert.equal(bar, 15);
    measure(shown());
  }
  assert.equal(sets, 0);
  // смонтирована скрытой, пока лист ещё рисует все вкладки: содержимое рисуется — замер сразу настоящий
  bar = 0;
  measure(shown());
  assert.equal(bar, 15);
});

// ── разметка: компонент без хуков — его дерево элементов и есть разметка (стопку раскрывает kit/Tx: две копии, открыта одна)
const kids = (e: ReactElement): ReactElement[] => Children.toArray(e.props.children) as ReactElement[];

const FACTS: Fact[] = [
  { k: "Шаблон", v: "VK Tech", dim: false, title: "vk.pptx" },
  { k: "Проверка по картинке", v: "выключена", dim: true },
];

test("паспорт «Файлов» — по правилам HTML: в dl только группы div из dt и dd, стопка из двух копий — внутри dd", () => {
  const dl = PassportFacts({ facts: FACTS, hpd: 40 });
  assert.equal(dl.type, "dl");
  const groups = kids(dl);
  assert.deepEqual(groups.map((g) => [g.type, kids(g).map((k) => k.type)]), [["div", ["dt", "dd"]], ["div", ["dt", "dd"]]]);
  groups.forEach((g, i) => {
    const [dt, dd] = kids(g);
    // название читается из dt (визуально скрытого) — в копиях стопки оно aria-hidden; значение — из открытой копии
    assert.equal(dt.props.className, "p2-sr");
    assert.equal(dt.props.children, FACTS[i].k);
    const [stack] = kids(dd);
    assert.equal(stack.type, Tx);
    assert.deepEqual([stack.props.tx, stack.props.hpd, stack.props.title], ["f-fact", 40, FACTS[i].title]);
    const [k, v] = kids(stack);
    assert.deepEqual([k.props.className, k.props["aria-hidden"], k.props.children], ["df-fk", "true", FACTS[i].k]);
    assert.deepEqual([v.props.className, v.props["aria-hidden"], v.props.children], [FACTS[i].dim ? "df-fv df-dim" : "df-fv", undefined, FACTS[i].v]);
  });
});
