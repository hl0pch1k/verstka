import { test } from "node:test";
import assert from "node:assert/strict";
import { Children, type ReactElement } from "react";
import { Tx } from "../../kit/Tx";
import { WhyTerms } from "./Why";

// компонент без хуков — его дерево элементов и есть разметка (стопку раскрывает kit/Tx: две копии, открыта одна)
const kids = (e: ReactElement): ReactElement[] => Children.toArray(e.props.children) as ReactElement[];

const DL = [
  { t: "Вывод", d: "Интеграл превращает задачу о площади в вычисление" },
  { t: "Сноска", d: "Источник: Фихтенгольц, т. 2" },
];

test("«Вывод» и «Сноска» в «Почему так» — по правилам HTML: в dl только dt и dd, стопка из двух копий — внутри dd", () => {
  const dl = WhyTerms({ dl: DL });
  assert.equal(dl.type, "dl");
  const items = kids(dl);
  assert.deepEqual(items.map((k) => k.type), ["dt", "dd", "dt", "dd"]);
  DL.forEach((x, i) => {
    const [dt, dd] = [items[2 * i], items[2 * i + 1]];
    assert.deepEqual([dt.props.className, dt.props.children], ["dw-sub", x.t]);
    const [stack] = kids(dd);
    assert.equal(stack.type, Tx);
    // копии — абзацы (as по умолчанию — p) с текстом определения
    assert.deepEqual([stack.props.tx, stack.props.as, stack.props.children], ["w-dd", undefined, x.d]);
  });
});
