// Слайды с данными настоящей колоды (пример «данные продаж», без модели; verstka/data/story.py) — для тестов «Почему так».
import type { OutlineSlide } from "../../types";

export const DATA_SLIDES: Record<number, OutlineSlide> = {
 "2": {
  "id": "data-7",
  "kind": "stat_row",
  "section": null,
  "headline": "Выручка растёт быстрее числа клиентов: +23% против +18%",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [
    {
     "value": "1,24 млрд ₽",
     "label": "Выручка, +23% к III кв. 2025",
     "fact_id": null
    },
    {
     "value": "3 480",
     "label": "Клиенты, +18% к III кв. 2025",
     "fact_id": null
    },
    {
     "value": "356 тыс. ₽",
     "label": "Средний чек, +4% к III кв. 2025",
     "fact_id": null
    },
    {
     "value": "52",
     "label": "NPS, +6 п. к III кв. 2025",
     "fact_id": null
    }
   ],
   "table": null,
   "chart": null,
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Ключевые значения — карточки ключевых показателей. 4 числа с изменением — каждое крупно, со своим ростом.",
  "footnote": "Источник: Итоги квартала.txt",
  "data": {
   "dataset_id": "dfa725b1b703",
   "file": "Итоги квартала.txt",
   "profile_line": "TXT · 4 строки × 4 колонки · таблица в тексте",
   "nature": "text_table",
   "nature_label": "Таблица в тексте",
   "columns": [
    {
     "name": "Показатель",
     "unit": null,
     "type": "category",
     "role": "dimension",
     "missing": 0,
     "distinct": 4,
     "min": null,
     "max": null,
     "median": null,
     "first": "Выручка",
     "last": "NPS",
     "outliers": [],
     "samples": [
      "Выручка",
      "Клиенты",
      "Средний чек"
     ]
    },
    {
     "name": "III кв. 2026",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 0,
     "distinct": 4,
     "min": null,
     "max": null,
     "median": null,
     "first": "1,24 млрд ₽",
     "last": "52",
     "outliers": [],
     "samples": [
      "1,24 млрд ₽",
      "3 480",
      "356 тыс. ₽"
     ]
    },
    {
     "name": "III кв. 2025",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 0,
     "distinct": 4,
     "min": null,
     "max": null,
     "median": null,
     "first": "1,01 млрд ₽",
     "last": "46",
     "outliers": [],
     "samples": [
      "1,01 млрд ₽",
      "2 949",
      "342 тыс. ₽"
     ]
    },
    {
     "name": "Изменение",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 0,
     "distinct": 4,
     "min": null,
     "max": null,
     "median": null,
     "first": "+23%",
     "last": "+6 п.",
     "outliers": [],
     "samples": [
      "+23%",
      "+18%",
      "+4%"
     ]
    }
   ],
   "time_axis": null,
   "metrics": [
    "III кв. 2026",
    "III кв. 2025",
    "Изменение"
   ],
   "dimensions": [
    "Показатель"
   ],
   "missing_total": 0,
   "outliers": [],
   "task": {
    "task": "kpi",
    "reasons": [
     "4 итоговых числа с изменением к III кв. 2025 — важны сами значения и их рост."
    ],
    "goal": null,
    "scores": {
     "kpi": 0.95,
     "dynamics": 0.0,
     "shares": 0.0,
     "distribution": 0.0,
     "comparison": 0.0,
     "relationship": 0.0,
     "reference": 0.15
    }
   },
   "options": [
    {
     "kind": "kpi_cards",
     "score": 0.95,
     "title": "Карточки ключевых показателей",
     "reasons": [
      "4 числа с изменением — каждое крупно, со своим ростом."
     ],
     "why_not": null,
     "aggregation": null
    },
    {
     "kind": "table",
     "score": 0.5,
     "title": "Таблица",
     "reasons": [
      "Все значения и изменения в одном месте."
     ],
     "why_not": "Читается, но главные числа теряются в строках.",
     "aggregation": null
    },
    {
     "kind": "column",
     "score": 0.05,
     "title": "Столбцы",
     "reasons": [
      "Сравнение по высоте."
     ],
     "why_not": "Разные единицы — сравнивать нельзя.",
     "aggregation": null
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "value_0",
     "text": "Выручка — 1,24 млрд ₽",
     "value": 1.24,
     "unit": "млрд ₽",
     "kind": "total",
     "explain": "Выручка: 1,24 млрд ₽ (III кв. 2026)."
    },
    {
     "id": "value_1",
     "text": "Клиенты — 3 480",
     "value": 3480.0,
     "unit": null,
     "kind": "total",
     "explain": "Клиенты: 3 480 (III кв. 2026)."
    },
    {
     "id": "value_2",
     "text": "Средний чек — 356 тыс. ₽",
     "value": 356.0,
     "unit": "тыс. ₽",
     "kind": "total",
     "explain": "Средний чек: 356 тыс. ₽ (III кв. 2026)."
    },
    {
     "id": "value_3",
     "text": "NPS — 52",
     "value": 52.0,
     "unit": null,
     "kind": "total",
     "explain": "NPS: 52 (III кв. 2026)."
    },
    {
     "id": "kpi_value",
     "text": "Выручка — 1,24 млрд ₽",
     "value": 1.24,
     "unit": "млрд ₽",
     "kind": "total",
     "explain": "Выручка: 1,24 млрд ₽."
    },
    {
     "id": "kpi_a",
     "text": "Выручка: +23%",
     "value": 23.0,
     "unit": "%",
     "kind": "change",
     "explain": "Выручка — 1,24 млрд ₽, было 1,01 млрд ₽: +23% к III кв. 2025."
    },
    {
     "id": "kpi_b",
     "text": "Клиенты: +18%",
     "value": 18.0,
     "unit": "%",
     "kind": "change",
     "explain": "Клиенты — 3 480, было 2 949: +18% к III кв. 2025."
    }
   ],
   "plain_headline": "Итоги квартала",
   "aggregation": null,
   "part": [
    1,
    1
   ]
  }
 },
 "3": {
  "id": "data-1",
  "kind": "chart",
  "section": null,
  "headline": "Выручка выросла на 23% к сентябрю",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [],
   "table": null,
   "chart": {
    "type": "line",
    "series_ids": [],
    "title": null,
    "unit": "млн ₽",
    "highlight_index": 20,
    "categories": [
     "янв 2025",
     "фев 2025",
     "мар 2025",
     "апр 2025",
     "май 2025",
     "июн 2025",
     "июл 2025",
     "авг 2025",
     "сен 2025",
     "окт 2025",
     "ноя 2025",
     "дек 2025",
     "янв 2026",
     "фев 2026",
     "мар 2026",
     "апр 2026",
     "май 2026",
     "июн 2026",
     "июл 2026",
     "авг 2026",
     "сен 2026"
    ],
    "series": [
     {
      "name": "Выручка",
      "values": [
       296.0,
       301.0,
       312.0,
       309.0,
       315.0,
       322.0,
       330.0,
       334.0,
       344.0,
       351.0,
       358.0,
       379.0,
       352.0,
       361.0,
       374.0,
       381.0,
       389.0,
       398.0,
       406.0,
       411.0,
       423.0
      ],
      "unit": "млн ₽"
     }
    ],
    "split": false,
    "x_title": "Месяц",
    "y_title": "Выручка",
    "gaps": false,
    "source": "Источник: Выручка по месяцам.csv",
    "xy": [],
    "kind_locked": true
   },
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Динамика — линейный график. Дата и одна метрика, 21 точка — тренд виден сразу. Цель «покажи рост выручки» подтвердила выбор.",
  "footnote": "Источник: Выручка по месяцам.csv",
  "data": {
   "dataset_id": "efebecbf04ca",
   "file": "Выручка по месяцам.csv",
   "profile_line": "CSV · 21 строка × 3 колонки · временной ряд",
   "nature": "time_series",
   "nature_label": "Временной ряд",
   "columns": [
    {
     "name": "Месяц",
     "unit": null,
     "type": "date",
     "role": "time",
     "missing": 0,
     "distinct": 21,
     "min": "2025-01-01",
     "max": "2026-09-01",
     "median": "2025-11-01",
     "first": "2025-01-01",
     "last": "2026-09-01",
     "outliers": [],
     "samples": [
      "2025-01-01",
      "2025-02-01",
      "2025-03-01"
     ]
    },
    {
     "name": "Выручка",
     "unit": "млн ₽",
     "type": "money",
     "role": "metric",
     "missing": 0,
     "distinct": 21,
     "min": 296.0,
     "max": 423.0,
     "median": 352.0,
     "first": 296,
     "last": 423,
     "outliers": [],
     "samples": [
      296,
      301,
      312
     ]
    },
    {
     "name": "Клиентов",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 0,
     "distinct": 21,
     "min": 2610.0,
     "max": 3480.0,
     "median": 3047.0,
     "first": 2610,
     "last": 3480,
     "outliers": [],
     "samples": [
      2610,
      2648,
      2702
     ]
    }
   ],
   "time_axis": {
    "column": "Месяц",
    "freq": "month",
    "start": "2025-01",
    "end": "2026-09",
    "points": 21,
    "missing_periods": []
   },
   "metrics": [
    "Выручка",
    "Клиентов"
   ],
   "dimensions": [],
   "missing_total": 0,
   "outliers": [],
   "task": {
    "task": "dynamics",
    "reasons": [
     "Есть ось времени (21 месяц) и одна главная метрика — важно, как выручка менялась месяц за месяцем.",
     "Цель «покажи рост выручки» совпала с тем, что видно по данным."
    ],
    "goal": "покажи рост выручки",
    "scores": {
     "kpi": 0.0,
     "dynamics": 1.4,
     "shares": 0.0,
     "distribution": 0.0,
     "comparison": 0.0,
     "relationship": 0.0,
     "reference": 0.15
    }
   },
   "options": [
    {
     "kind": "line",
     "score": 1.0,
     "title": "Линейный график",
     "reasons": [
      "Дата и одна метрика, 21 точка — тренд виден сразу.",
      "Цель «покажи рост выручки» подтвердила выбор."
     ],
     "why_not": null,
     "aggregation": null
    },
    {
     "kind": "column",
     "score": 0.55,
     "title": "Столбцы",
     "reasons": [
      "Месяцы дискретны — каждый период отдельным столбцом."
     ],
     "why_not": "Месяцы дискретны, но за 21 столбцом тренд виден хуже.",
     "aggregation": null
    },
    {
     "kind": "table",
     "score": 0.2,
     "title": "Таблица",
     "reasons": [
      "Точные значения каждого периода."
     ],
     "why_not": "21 строка — тренд не читается.",
     "aggregation": "по 10 строк на слайд"
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "last",
     "text": "сентябрь 2026: 423 млн ₽",
     "value": 423.0,
     "unit": "млн ₽",
     "kind": "max",
     "explain": "Последнее значение — сентябрь 2026. Посчитано по колонке «Выручка»."
    },
    {
     "id": "max",
     "text": "Максимум — 423 млн ₽ (сентябрь 2026)",
     "value": 423.0,
     "unit": "млн ₽",
     "kind": "max",
     "explain": "Наибольшее значение ряда. Посчитано по колонке «Выручка»."
    },
    {
     "id": "min",
     "text": "Минимум — 296 млн ₽ (январь 2025)",
     "value": 296.0,
     "unit": "млн ₽",
     "kind": "min",
     "explain": "Наименьшее значение ряда. Посчитано по колонке «Выручка»."
    },
    {
     "id": "change",
     "text": "+23% год к году",
     "value": 23.0,
     "unit": "%",
     "kind": "change",
     "explain": "Сентябрь 2026 к сентябрю 2025: 423 млн ₽ — на 23% больше. Посчитано по колонке «Выручка»."
    }
   ],
   "plain_headline": "Выручка по месяцам",
   "aggregation": null,
   "part": [
    1,
    1
   ]
  }
 },
 "4": {
  "id": "data-2",
  "kind": "chart",
  "section": null,
  "headline": "Москва даёт 41% выручки, Казань растёт быстрее всех",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [],
   "table": null,
   "chart": {
    "type": "bar",
    "series_ids": [],
    "title": null,
    "unit": "млн ₽",
    "highlight_index": 0,
    "categories": [
     "Москва",
     "Санкт-Петербург",
     "Екатеринбург",
     "Казань",
     "Новосибирск",
     "Краснодар",
     "Ростов-на-Дону",
     "Нижний Новгород"
    ],
    "series": [
     {
      "name": "Выручка",
      "values": [
       1433.0,
       612.0,
       318.0,
       274.0,
       236.0,
       214.0,
       210.0,
       198.0
      ],
      "unit": "млн ₽"
     }
    ],
    "split": false,
    "x_title": "Регион",
    "y_title": "Выручка",
    "gaps": false,
    "source": "Источник: Регионы.xlsx",
    "xy": [],
    "kind_locked": true
   },
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Сравнение категорий — ранжированные горизонтальные столбцы. 8 категорий с длинными названиями: подписи слева, порядок — по выручке. Цель «сравни регионы» подтвердила выбор.",
  "footnote": "Источник: Регионы.xlsx",
  "data": {
   "dataset_id": "7f221e6076bf",
   "file": "Регионы.xlsx",
   "profile_line": "XLSX · 8 строк × 3 колонки · сравнение",
   "nature": "comparison",
   "nature_label": "Сравнение",
   "columns": [
    {
     "name": "Регион",
     "unit": null,
     "type": "category",
     "role": "dimension",
     "missing": 0,
     "distinct": 8,
     "min": null,
     "max": null,
     "median": null,
     "first": "Москва",
     "last": "Нижний Новгород",
     "outliers": [],
     "samples": [
      "Москва",
      "Санкт-Петербург",
      "Екатеринбург"
     ]
    },
    {
     "name": "Выручка",
     "unit": "млн ₽",
     "type": "money",
     "role": "metric",
     "missing": 0,
     "distinct": 8,
     "min": 198.0,
     "max": 1433.0,
     "median": 255.0,
     "first": 1433,
     "last": 198,
     "outliers": [],
     "samples": [
      1433,
      612,
      318
     ]
    },
    {
     "name": "Рост",
     "unit": "%",
     "type": "percent",
     "role": "metric",
     "missing": 0,
     "distinct": 8,
     "min": 15.0,
     "max": 38.0,
     "median": 23.0,
     "first": 19,
     "last": 27,
     "outliers": [],
     "samples": [
      19,
      21,
      24
     ]
    }
   ],
   "time_axis": null,
   "metrics": [
    "Выручка",
    "Рост"
   ],
   "dimensions": [
    "Регион"
   ],
   "missing_total": 0,
   "outliers": [],
   "task": {
    "task": "comparison",
    "reasons": [
     "8 регионов и одна главная метрика — важно, кто больше и кто растёт быстрее.",
     "Цель «сравни регионы» совпала с тем, что видно по данным."
    ],
    "goal": "сравни регионы",
    "scores": {
     "kpi": 0.0,
     "dynamics": 0.0,
     "shares": 0.35,
     "distribution": 0.0,
     "comparison": 1.25,
     "relationship": 0.0,
     "reference": 0.15
    }
   },
   "options": [
    {
     "kind": "bar",
     "score": 1.0,
     "title": "Ранжированные горизонтальные столбцы",
     "reasons": [
      "8 категорий с длинными названиями: подписи слева, порядок — по выручке.",
      "Цель «сравни регионы» подтвердила выбор."
     ],
     "why_not": null,
     "aggregation": null
    },
    {
     "kind": "column",
     "score": 0.45,
     "title": "Вертикальные столбцы",
     "reasons": [
      "8 категорий — каждая отдельным столбцом, сравнение по высоте."
     ],
     "why_not": "Названия регионов не помещаются под столбцами.",
     "aggregation": null
    },
    {
     "kind": "pie",
     "score": 0.12,
     "title": "Круговая диаграмма",
     "reasons": [
      "Показывает, какую часть целого даёт лидер."
     ],
     "why_not": "8 долей — мелкие сектора нечитаемы.",
     "aggregation": null
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "leader_share",
     "text": "Москва — 41%",
     "value": 41.0,
     "unit": "%",
     "kind": "share",
     "explain": "Москва — 1 433 млн ₽ из 3 495 млн ₽, это 41%. Посчитано по колонке «Выручка»."
    },
    {
     "id": "total",
     "text": "Всего — 3 495 млн ₽",
     "value": 3495.0,
     "unit": "млн ₽",
     "kind": "total",
     "explain": "Сумма по колонке «Выручка»."
    },
    {
     "id": "leader_value",
     "text": "Москва — 1 433 млн ₽",
     "value": 1433.0,
     "unit": "млн ₽",
     "kind": "leader",
     "explain": "Наибольшее значение — у категории «Москва». Посчитано по колонке «Выручка»."
    },
    {
     "id": "last_value",
     "text": "Нижний Новгород — 198 млн ₽",
     "value": 198.0,
     "unit": "млн ₽",
     "kind": "min",
     "explain": "Наименьшее значение — у категории «Нижний Новгород»."
    },
    {
     "id": "spread",
     "text": "Разрыв — в 7,2 раза",
     "value": 7.2,
     "unit": "раз",
     "kind": "max",
     "explain": "Москва — 1 433 млн ₽, Нижний Новгород — 198 млн ₽."
    },
    {
     "id": "growth_max",
     "text": "Казань: +38%",
     "value": 38.0,
     "unit": "%",
     "kind": "max",
     "explain": "Самый быстрый рост — Казань: +38%. Посчитано по колонке «Рост»."
    }
   ],
   "plain_headline": "Выручка по регионам",
   "aggregation": null,
   "part": [
    1,
    1
   ]
  }
 },
 "6": {
  "id": "data-4",
  "kind": "chart",
  "section": null,
  "headline": "80% обращений получают ответ за 2 часа",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [],
   "table": null,
   "chart": {
    "type": "histogram",
    "series_ids": [],
    "title": null,
    "unit": null,
    "highlight_index": null,
    "categories": [
     "0–20",
     "20–40",
     "40–60",
     "60–80",
     "80–100",
     "100–120",
     "120–140",
     "140–160",
     "160–180",
     "больше 180"
    ],
    "series": [
     {
      "name": "Число обращений",
      "values": [
       103.0,
       101.0,
       85.0,
       52.0,
       37.0,
       32.0,
       22.0,
       17.0,
       12.0,
       48.0
      ],
      "unit": null
     }
    ],
    "split": false,
    "x_title": "Минут до ответа",
    "y_title": "Число обращений",
    "gaps": false,
    "source": "Источник: Время ответа поддержки.csv",
    "xy": [],
    "kind_locked": true
   },
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Распределение — гистограмма. Одна числовая колонка, 512 значений — видно, где большинство и насколько длинный хвост. 3 выброса — отдельно. Данные: 10 интервалов по 20 мин, последний — «больше 180»; 3 выброса — отдельно.",
  "footnote": "Источник: Время ответа поддержки.csv",
  "data": {
   "dataset_id": "a5cda0380b25",
   "file": "Время ответа поддержки.csv",
   "profile_line": "CSV · 512 строк × 2 колонки · распределение",
   "nature": "distribution",
   "nature_label": "Распределение",
   "columns": [
    {
     "name": "Обращение",
     "unit": null,
     "type": "id",
     "role": "id",
     "missing": 0,
     "distinct": 512,
     "min": null,
     "max": null,
     "median": null,
     "first": "SUP-48213",
     "last": "SUP-48724",
     "outliers": [],
     "samples": [
      "SUP-48213",
      "SUP-48214",
      "SUP-48215"
     ]
    },
    {
     "name": "Минут до ответа",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 0,
     "distinct": 185,
     "min": 2.0,
     "max": 1430.0,
     "median": 54.0,
     "first": 25,
     "last": 3,
     "outliers": [
      44,
      293,
      338
     ],
     "samples": [
      25,
      176,
      18
     ]
    }
   ],
   "time_axis": null,
   "metrics": [
    "Минут до ответа"
   ],
   "dimensions": [],
   "missing_total": 0,
   "outliers": [
    {
     "column": "Минут до ответа",
     "row": 44,
     "value": 655.0,
     "reason": "выше границы 224 (третий квартиль + 1,5 межквартильного размаха) и отдельно от остальных значений"
    },
    {
     "column": "Минут до ответа",
     "row": 293,
     "value": 812.0,
     "reason": "выше границы 224 (третий квартиль + 1,5 межквартильного размаха) и отдельно от остальных значений"
    },
    {
     "column": "Минут до ответа",
     "row": 338,
     "value": 1430.0,
     "reason": "выше границы 224 (третий квартиль + 1,5 межквартильного размаха) и отдельно от остальных значений"
    }
   ],
   "task": {
    "task": "distribution",
    "reasons": [
     "Одна числовая колонка из 512 значений — важны форма распределения и типичное время."
    ],
    "goal": null,
    "scores": {
     "kpi": 0.0,
     "dynamics": 0.0,
     "shares": 0.0,
     "distribution": 0.88,
     "comparison": 0.0,
     "relationship": 0.0,
     "reference": 0.7
    }
   },
   "options": [
    {
     "kind": "histogram",
     "score": 0.9,
     "title": "Гистограмма",
     "reasons": [
      "Одна числовая колонка, 512 значений — видно, где большинство и насколько длинный хвост.",
      "3 выброса — отдельно."
     ],
     "why_not": null,
     "aggregation": "10 интервалов по 20 мин, последний — «больше 180»; 3 выброса — отдельно"
    },
    {
     "kind": "kpi_cards",
     "score": 0.45,
     "title": "Карточки ключевых показателей",
     "reasons": [
      "Медиана и 80-й перцентиль — коротко."
     ],
     "why_not": "Медиана и 80-й перцентиль — коротко, но без формы распределения.",
     "aggregation": null
    },
    {
     "kind": "table",
     "score": 0.05,
     "title": "Таблица",
     "reasons": [
      "Точные значения."
     ],
     "why_not": "512 строк не показать.",
     "aggregation": null
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "median",
     "text": "Медиана — 54 мин",
     "value": 54.0,
     "unit": "мин",
     "kind": "median",
     "explain": "Половина значений меньше 54 мин. Посчитано по колонке «Минут до ответа»."
    },
    {
     "id": "count",
     "text": "512 обращений",
     "value": 512.0,
     "unit": null,
     "kind": "count",
     "explain": "Строк с числом в колонке."
    },
    {
     "id": "share_within",
     "text": "80% — не больше 120 мин",
     "value": 80.0,
     "unit": "%",
     "kind": "percentile",
     "explain": "410 из 512 обращений — не больше 120 мин. Посчитано по колонке «Минут до ответа»."
    },
    {
     "id": "threshold",
     "text": "2 часа",
     "value": 2.0,
     "unit": "ч",
     "kind": "percentile",
     "explain": "Граница — 120 мин: 80-й перцентиль 119 мин, округлено вверх."
    },
    {
     "id": "p80",
     "text": "80-й перцентиль — 119 мин",
     "value": 119.0,
     "unit": "мин",
     "kind": "percentile",
     "explain": "80% значений не больше этого числа. Посчитано по колонке «Минут до ответа»."
    },
    {
     "id": "outliers",
     "text": "3 выброса",
     "value": 3.0,
     "unit": null,
     "kind": "outliers",
     "explain": "Значения 655, 812, 1 430 — далеко от остальных (правило Тьюки с отрывом)."
    },
    {
     "id": "outlier_bound_high",
     "text": "больше 10 часов",
     "value": 600.0,
     "unit": "мин",
     "kind": "outliers",
     "explain": "Граница выбросов: 3 значения больше 10 часов."
    }
   ],
   "plain_headline": "Время ответа поддержки",
   "aggregation": "10 интервалов по 20 мин, последний — «больше 180»; 3 выброса — отдельно",
   "part": [
    1,
    1
   ]
  }
 },
 "7": {
  "id": "data-6",
  "kind": "chart",
  "section": null,
  "headline": "NPS вырос до 52, за два квартала данных нет",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [],
   "table": null,
   "chart": {
    "type": "line",
    "series_ids": [],
    "title": null,
    "unit": null,
    "highlight_index": 7,
    "categories": [
     "IV кв. 2024",
     "I кв. 2025",
     "II кв. 2025",
     "III кв. 2025",
     "IV кв. 2025",
     "I кв. 2026",
     "II кв. 2026",
     "III кв. 2026"
    ],
    "series": [
     {
      "name": "NPS",
      "values": [
       41.0,
       43.0,
       null,
       46.0,
       47.0,
       49.0,
       null,
       52.0
      ],
      "unit": null
     }
    ],
    "split": false,
    "x_title": "Квартал",
    "y_title": "NPS",
    "gaps": true,
    "source": "Источник: NPS по кварталам.csv",
    "xy": [],
    "kind_locked": true
   },
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Динамика — линейный график с разрывами. Квартал и одна метрика, 6 точек — тренд виден сразу. Пропуски — разрывы линии, а не падение до нуля.",
  "footnote": "Источник: NPS по кварталам.csv",
  "data": {
   "dataset_id": "5c9d922c4d88",
   "file": "NPS по кварталам.csv",
   "profile_line": "CSV · 8 строк × 3 колонки · с пропусками",
   "nature": "with_gaps",
   "nature_label": "С пропусками",
   "columns": [
    {
     "name": "Квартал",
     "unit": null,
     "type": "period",
     "role": "time",
     "missing": 0,
     "distinct": 8,
     "min": "2024-Q4",
     "max": "2026-Q3",
     "median": "2025-Q3",
     "first": "2024-Q4",
     "last": "2026-Q3",
     "outliers": [],
     "samples": [
      "2024-Q4",
      "2025-Q1",
      "2025-Q2"
     ]
    },
    {
     "name": "NPS",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 2,
     "distinct": 6,
     "min": 41.0,
     "max": 52.0,
     "median": 46.5,
     "first": 41,
     "last": 52,
     "outliers": [],
     "samples": [
      41,
      43,
      46
     ]
    },
    {
     "name": "Ответов",
     "unit": null,
     "type": "number",
     "role": "metric",
     "missing": 2,
     "distinct": 6,
     "min": 287.0,
     "max": 368.0,
     "median": 335.5,
     "first": 312,
     "last": 368,
     "outliers": [],
     "samples": [
      312,
      287,
      341
     ]
    }
   ],
   "time_axis": {
    "column": "Квартал",
    "freq": "quarter",
    "start": "2024-Q4",
    "end": "2026-Q3",
    "points": 8,
    "missing_periods": [
     "2025-Q2",
     "2026-Q2"
    ]
   },
   "metrics": [
    "NPS",
    "Ответов"
   ],
   "dimensions": [],
   "missing_total": 4,
   "outliers": [],
   "task": {
    "task": "dynamics",
    "reasons": [
     "Ось времени, одна главная метрика и два пустых квартала — их нельзя показать нулём или падением."
    ],
    "goal": null,
    "scores": {
     "kpi": 0.0,
     "dynamics": 0.9,
     "shares": 0.0,
     "distribution": 0.0,
     "comparison": 0.0,
     "relationship": 0.0,
     "reference": 0.15
    }
   },
   "options": [
    {
     "kind": "line",
     "score": 0.9,
     "title": "Линейный график с разрывами",
     "reasons": [
      "Квартал и одна метрика, 6 точек — тренд виден сразу.",
      "Пропуски — разрывы линии, а не падение до нуля."
     ],
     "why_not": null,
     "aggregation": null
    },
    {
     "kind": "column",
     "score": 0.7,
     "title": "Столбцы с пустыми местами",
     "reasons": [
      "Кварталы дискретны — каждый период отдельным столбцом."
     ],
     "why_not": "Пропуски видны, но рост читается хуже.",
     "aggregation": null
    },
    {
     "kind": "table",
     "score": 0.25,
     "title": "Таблица с прочерками",
     "reasons": [
      "8 строк — помещаются на слайд."
     ],
     "why_not": "8 строк читаются, но динамика не видна.",
     "aggregation": null
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "last",
     "text": "III кв. 2026: 52",
     "value": 52.0,
     "unit": null,
     "kind": "max",
     "explain": "Последнее значение — III кв. 2026. Посчитано по колонке «NPS»."
    },
    {
     "id": "max",
     "text": "Максимум — 52 (III кв. 2026)",
     "value": 52.0,
     "unit": null,
     "kind": "max",
     "explain": "Наибольшее значение ряда. Посчитано по колонке «NPS»."
    },
    {
     "id": "min",
     "text": "Минимум — 41 (IV кв. 2024)",
     "value": 41.0,
     "unit": null,
     "kind": "min",
     "explain": "Наименьшее значение ряда. Посчитано по колонке «NPS»."
    },
    {
     "id": "gaps",
     "text": "Нет данных: II кв. 2025, II кв. 2026",
     "value": 2.0,
     "unit": null,
     "kind": "gap",
     "explain": "2 квартала без значения: II кв. 2025, II кв. 2026. На графике — разрывы, а не ноль."
    },
    {
     "id": "change",
     "text": "+6 п. к III кв. 2025",
     "value": 6.0,
     "unit": "п.",
     "kind": "change",
     "explain": "III кв. 2026 к III кв. 2025: 52 против 46 — +6 п.. Посчитано по колонке «NPS»."
    }
   ],
   "plain_headline": "NPS по кварталам",
   "aggregation": null,
   "part": [
    1,
    1
   ]
  }
 },
 "8": {
  "id": "data-5",
  "kind": "table",
  "section": null,
  "headline": "Топ-10 клиентов дают 38% выручки",
  "subtitle": null,
  "content": {
   "bullets": [],
   "paragraphs": [],
   "items": [],
   "numbers": [],
   "table": {
    "columns": [
     "Клиент",
     "Отрасль",
     "Регион",
     "Выручка, млн ₽",
     "Доля, %"
    ],
    "rows": [
     [
      "АО «Северный капитал»",
      "Банки и финансы",
      "Москва",
      "212,4",
      "6,1"
     ],
     [
      "ПАО «Магистраль Телеком»",
      "Телеком",
      "Москва",
      "176,8",
      "5,1"
     ],
     [
      "ООО «Невская логистика»",
      "Логистика",
      "Санкт-Петербург",
      "158,3",
      "4,5"
     ],
     [
      "ГК «Колос-Ритейл»",
      "Ритейл",
      "Москва",
      "141,6",
      "4,1"
     ],
     [
      "АО «Опора Страхование»",
      "Страхование",
      "Москва",
      "129,9",
      "3,7"
     ],
     [
      "ООО «Идель Нефтесервис»",
      "Промышленность",
      "Казань",
      "118,2",
      "3,4"
     ],
     [
      "ООО «Кадр Медиа»",
      "Медиа",
      "Москва",
      "106,7",
      "3,1"
     ],
     [
      "АО «Уральские машины»",
      "Промышленность",
      "Екатеринбург",
      "98,4",
      "2,8"
     ],
     [
      "ООО «Лавка24»",
      "Электронная коммерция",
      "Москва",
      "94,5",
      "2,7"
     ],
     [
      "ООО «Балтийская верфь-Сервис»",
      "Промышленность",
      "Санкт-Петербург",
      "91,2",
      "2,6"
     ]
    ],
    "unit": "млн ₽",
    "caption": null,
    "source_span": null
   },
   "chart": null,
   "quote": null,
   "quote_author": null,
   "image_hint": null,
   "columns": []
  },
  "notes": "",
  "fact_refs": [],
  "rationale": "Справочные значения — таблица топ-10 и итог «остальные 230». 240 строк не помещаются: 10 крупнейших — строками, остальные — одной строкой, 2 167 млн ₽ и 62%. На слайде 5 колонок: тариф и дата договора не вошли, доля посчитана. Данные: топ-10 и строка «Остальные 230».",
  "footnote": "Источник: Клиенты.xlsx",
  "data": {
   "dataset_id": "52a375fabb13",
   "file": "Клиенты.xlsx",
   "profile_line": "XLSX · 240 строк × 6 колонок · справочник",
   "nature": "reference",
   "nature_label": "Справочник",
   "columns": [
    {
     "name": "Клиент",
     "unit": null,
     "type": "text",
     "role": "text",
     "missing": 0,
     "distinct": 240,
     "min": null,
     "max": null,
     "median": null,
     "first": "АО «Северный капитал»",
     "last": "АО «Цитадельцифра»",
     "outliers": [],
     "samples": [
      "АО «Северный капитал»",
      "ПАО «Магистраль Телеком»",
      "ООО «Невская логистика»"
     ]
    },
    {
     "name": "Отрасль",
     "unit": null,
     "type": "category",
     "role": "dimension",
     "missing": 0,
     "distinct": 13,
     "min": null,
     "max": null,
     "median": null,
     "first": "Банки и финансы",
     "last": "Госсектор",
     "outliers": [],
     "samples": [
      "Банки и финансы",
      "Телеком",
      "Логистика"
     ]
    },
    {
     "name": "Регион",
     "unit": null,
     "type": "category",
     "role": "dimension",
     "missing": 0,
     "distinct": 8,
     "min": null,
     "max": null,
     "median": null,
     "first": "Москва",
     "last": "Санкт-Петербург",
     "outliers": [],
     "samples": [
      "Москва",
      "Санкт-Петербург",
      "Казань"
     ]
    },
    {
     "name": "Выручка",
     "unit": "млн ₽",
     "type": "money",
     "role": "metric",
     "missing": 0,
     "distinct": 139,
     "min": 0.5,
     "max": 212.4,
     "median": 6.2,
     "first": 212.4,
     "last": 0.5,
     "outliers": [
      0,
      1,
      2,
      3,
      4,
      5,
      6,
      7,
      8,
      9
     ],
     "samples": [
      212.4,
      176.8,
      158.3
     ]
    },
    {
     "name": "Тариф",
     "unit": null,
     "type": "category",
     "role": "dimension",
     "missing": 0,
     "distinct": 4,
     "min": null,
     "max": null,
     "median": null,
     "first": "Корпоративный",
     "last": "Старт",
     "outliers": [],
     "samples": [
      "Корпоративный",
      "Бизнес",
      "Стандарт"
     ]
    },
    {
     "name": "Дата договора",
     "unit": null,
     "type": "date",
     "role": "attribute",
     "missing": 0,
     "distinct": 228,
     "min": "2019-01-07",
     "max": "2026-09-02",
     "median": "2022-12-17",
     "first": "2019-11-14",
     "last": "2025-01-15",
     "outliers": [],
     "samples": [
      "2019-11-14",
      "2020-03-02",
      "2021-06-21"
     ]
    }
   ],
   "time_axis": null,
   "metrics": [
    "Выручка"
   ],
   "dimensions": [
    "Отрасль",
    "Регион",
    "Тариф"
   ],
   "missing_total": 0,
   "outliers": [],
   "task": {
    "task": "reference",
    "reasons": [
     "Нужны конкретные клиенты и их цифры, а не форма. 240 строк целиком не поместятся — агрегирую: топ-10 и итог «остальные 230»."
    ],
    "goal": null,
    "scores": {
     "kpi": 0.0,
     "dynamics": 0.0,
     "shares": 0.35,
     "distribution": 0.35,
     "comparison": 0.45,
     "relationship": 0.0,
     "reference": 0.8
    }
   },
   "options": [
    {
     "kind": "table",
     "score": 0.85,
     "title": "Таблица топ-10 и итог «остальные 230»",
     "reasons": [
      "240 строк не помещаются: 10 крупнейших — строками, остальные — одной строкой, 2 167 млн ₽ и 62%.",
      "На слайде 5 колонок: тариф и дата договора не вошли, доля посчитана."
     ],
     "why_not": null,
     "aggregation": "топ-10 и строка «Остальные 230»"
    },
    {
     "kind": "bar",
     "score": 0.5,
     "title": "Столбцы топ-10",
     "reasons": [
      "Видно лидеров и разрыв между ними."
     ],
     "why_not": "Видно лидеров, но теряются отрасль и регион.",
     "aggregation": "топ-10"
    },
    {
     "kind": "table",
     "score": 0.1,
     "title": "Разбиение на 24 слайда",
     "reasons": [
      "Все строки, ничего не теряется."
     ],
     "why_not": "По 10 строк на слайд — слишком много.",
     "aggregation": "по 10 строк на слайд"
    }
   ],
   "chosen": 0,
   "headline_facts": [
    {
     "id": "count",
     "text": "Всего строк — 240",
     "value": 240.0,
     "unit": null,
     "kind": "count",
     "explain": "Строк данных в таблице."
    },
    {
     "id": "top_n",
     "text": "Топ-10",
     "value": 10.0,
     "unit": null,
     "kind": "count",
     "explain": "10 крупнейших из 240 по колонке «Выручка»."
    },
    {
     "id": "top_share",
     "text": "Топ-10 — 38%",
     "value": 38.0,
     "unit": "%",
     "kind": "share",
     "explain": "Выручка 10 крупнейших из 240: 1 328 млн ₽ из 3 495 млн ₽. Посчитано по колонке «Выручка»."
    },
    {
     "id": "rest_share",
     "text": "Остальные 230 — 62%",
     "value": 62.0,
     "unit": "%",
     "kind": "share",
     "explain": "Остальные 230 дают 2 167 млн ₽."
    },
    {
     "id": "rest_count",
     "text": "Остальные 230",
     "value": 230.0,
     "unit": null,
     "kind": "count",
     "explain": "Строки, собранные в итог."
    }
   ],
   "plain_headline": "Список клиентов",
   "aggregation": "топ-10 и строка «Остальные 230»",
   "part": [
    1,
    1
   ]
  }
 }
};
