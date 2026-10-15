import { test } from "node:test";
import assert from "node:assert/strict";
import { Children, type ReactElement } from "react";
import { Tx } from "../../kit/Tx";
import type { Fact } from "../files";
import { sheetMorph, filesCols } from "../sheetMorph";
import {
  labelPieces, PassportFacts, scrollbarOf, TILE_NARROW, TILE_WIDE, tileLayout, tileNat, tilesGrid, tileTrack, tileWidth, type Scroller, type TileNat,
} from "./Files";

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

// ── «Итог проверки» в тесной колоде: дорожки плиток по замеру подписей (ширины — замер Manrope 600 13 px и Unbounded 600
// 32 px в Chrome: «Ошибки» 49,76, «Предупреждения» 111,65, «Заметки» 53,82, «По картинке» 78,7, «Автоисправления» 114,29;
// «0» 28,38, «—» 37,2, «выключена» 72,15)
const W: Record<string, number> = {
  Ошибки: 49.76, Предупреждения: 111.65, Заметки: 53.82, "По картинке": 78.7, Автоисправления: 114.29,
  По: 17.19, картинке: 58.92, "Авто-": 35.78, исправления: 83.97, "0": 28.38, "1": 18, "5": 26, "2": 27, "—": 37.2, выключена: 72.15,
};
const measure = (s: string) => {
  assert.ok(s in W, s);
  return W[s];
};
const TILES = [
  { label: "Ошибки", v: "0", sub: "" }, { label: "Предупреждения", v: "1", sub: "" }, { label: "Заметки", v: "5", sub: "" },
  { label: "По картинке", v: "—", sub: "выключена" }, { label: "Автоисправления", v: "2", sub: "" },
];
const NAT: TileNat[] = TILES.map((t) => tileNat(t, measure));
const sum = (a: number[]) => a.reduce((s, x) => s + x, 0);
/** Место подписи в плитке: без полей и (в широкой) без значка с зазором. */
const room = (cols: number[], box: typeof TILE_WIDE | typeof TILE_NARROW, i: number) => tileWidth(cols, box.gap, i) - 2 * box.pad - box.ico;

test("куски подписи в две строки: по пробелу и мягкому переносу (с дефисом); одно слово не переносится", () => {
  assert.deepEqual(labelPieces("Автоисправления"), ["Авто-", "исправления"]);
  assert.deepEqual(labelPieces("По картинке"), ["По", "картинке"]);
  assert.deepEqual(labelPieces("Ошибки"), ["Ошибки"]);
  assert.deepEqual(NAT.map((n) => n.piece), [null, null, null, 58.92, 83.97]);
  // «— выключена»: в широкой — число с подписью, в узкой подпись гаснет
  assert.deepEqual([NAT[3].value, NAT[3].valueN], [37.2 + 8 + 72.15, 37.2]);
});

test("плитки поровну, где встают все подписи (1440 без помощника — 592 px), — как у V2", () => {
  const t = tileTrack(592, NAT, TILE_WIDE, false)!;
  t.cols.forEach((c) => assert.ok(Math.abs(c - (592 - 60) / 6) < 1e-9));
  assert.ok(t.wrap.every((x) => !x));
});

test("1280 без помощника: «Предупреждениям» — сколько нужно целиком, «Ошибки» и «Заметки» поровну, второй ряд поровну", () => {
  for (const width of [512, 504.5]) {
    const t = tileTrack(width, NAT, TILE_WIDE, false)!;
    assert.ok(room(t.cols, TILE_WIDE, 1) >= 111.65);
    assert.ok(Math.abs(tileWidth(t.cols, 12, 0) - tileWidth(t.cols, 12, 2)) < 1e-9);
    assert.ok(Math.abs(tileWidth(t.cols, 12, 3) - tileWidth(t.cols, 12, 4)) < 1e-9);
    assert.ok(Math.abs(sum(t.cols) + 5 * 12 - width) < 1e-9);
    // «— выключена» встаёт в строку
    assert.ok(tileWidth(t.cols, 12, 3) - 32 >= NAT[3].value);
  }
});

test("узкая тесная раскладка 1366 / 1400: все подписи, кроме «Предупреждений», — в строку и целиком", () => {
  for (const width of [266.4, 260.4, 280]) {
    const t = tileTrack(width, NAT, TILE_NARROW, true)!;
    assert.ok(t.wrap.every((x) => !x), String(width));
    for (const i of [0, 2, 3, 4]) assert.ok(room(t.cols, TILE_NARROW, i) >= NAT[i].label, `${width} ${TILES[i].label}`);
    assert.ok(room(t.cols, TILE_NARROW, 1) > 60); // «Предупр…» — не меньше, чем у V2 при 1440 (70,7 при 1366)
    assert.ok(t.cols.every((c) => c >= 0));
    assert.ok(Math.abs(sum(t.cols) + 5 * 8 - width) < 1e-9);
  }
});

test("узкая тесная раскладка 1280 (с полосой прокрутки и без): «Автоисправления» — в две строки, остальные — в строку", () => {
  for (const width of [232, 226]) {
    const t = tileTrack(width, NAT, TILE_NARROW, true)!;
    assert.deepEqual(t.wrap, [false, false, false, false, true]);
    for (const i of [0, 2, 3]) assert.ok(room(t.cols, TILE_NARROW, i) >= NAT[i].label, `${width} ${TILES[i].label}`);
    assert.ok(room(t.cols, TILE_NARROW, 4) >= 83.97); // «исправления»
    assert.ok(t.cols.every((c) => c >= 0));
    assert.ok(Math.abs(sum(t.cols) + 5 * 8 - width) < 1e-9);
  }
  // у́же не помещается и так — дорожки V2 (поровну)
  assert.equal(tileTrack(150, NAT, TILE_NARROW, true), null);
});

test("раскладка плиток: доли из px покоя, стопка — только у подписи в две строки, её --hpd — разница клеток", () => {
  const lay = tileLayout({ wide: 512, narrow: 232 }, NAT)!;
  const fr = (s: string) => s.split(") ").map((x) => Number(x.match(/([\d.]+)fr/)![1]));
  assert.equal(fr(lay.dtw).length, 6);
  assert.equal(fr(lay.dtn).length, 6);
  assert.ok(Math.abs(sum(fr(lay.dtw)) - (512 - 60)) < 0.01);
  assert.ok(Math.abs(sum(fr(lay.dtn)) - (232 - 40)) < 0.01);
  assert.deepEqual(lay.hpd.map((h) => h !== null), [false, false, false, false, true]);
  const wide = tileTrack(512, NAT, TILE_WIDE, false)!;
  const nar = tileTrack(232, NAT, TILE_NARROW, true)!;
  assert.ok(Math.abs(lay.hpd[4]! - (room(wide.cols, TILE_WIDE, 4) - room(nar.cols, TILE_NARROW, 4))) < 0.001);
  // при 1366 переносить нечего — стопок нет
  assert.ok(tileLayout({ wide: 555, narrow: 266.4 }, NAT)!.hpd.every((h) => h === null));
});

test("ширина сетки плиток: карточка справа (с «Временем по этапам») — правая колонка, слева — остаток, без полей 48", () => {
  const m = sheetMorph(1232);
  const cols = filesCols(m, 0);
  assert.deepEqual(tilesGrid(m, cols, 0, true), { wide: cols.wide - 48, narrow: cols.narrow - 48 });
  assert.deepEqual(tilesGrid(m, cols, 0, false), { wide: 1232 - 96 - 16 - cols.wide - 48, narrow: m.inner - 16 - cols.narrow - 48 });
  assert.equal(tilesGrid(sheetMorph(0), filesCols(sheetMorph(0), 0), 0, true), null);
});
