"""A deliberately rough «last quarter's» deck for «Улучшить готовую презентацию» (Verstka 3.0): the default Office look,
a wall of text, a twelve-row table, a chart, a picture, mixed fonts and sizes, text running off its box — the kind of
deck people bring. Upload it with «Улучшить готовую» and see what the agent says about it and what it builds.

Usage:
    python scripts/make_old_deck.py                    # → examples/improve/old_quarter_report.pptx
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Emu, Pt

OUT = Path(__file__).resolve().parents[1] / "examples" / "improve" / "old_quarter_report.pptx"


def _photo() -> io.BytesIO:
    """An office photo stand-in: a sky-to-floor gradient with a few windows."""
    w, h = 640, 400
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(90 + 120 * k), int(140 + 60 * k), int(200 - 80 * k)))
    for i in range(5):
        x = 40 + i * 120
        d.rectangle([x, 120, x + 80, 300], fill=(240, 240, 230), outline=(60, 60, 60), width=3)
        d.line([(x + 40, 120), (x + 40, 300)], fill=(60, 60, 60), width=2)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf


def main() -> Path:
    prs = Presentation()  # the 4:3 default Office template
    title_only, bullets = prs.slide_layouts[5], prs.slide_layouts[1]

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Отчёт отдела продаж за III квартал 2026"
    s.placeholders[1].text = "ООО «Северный ветер» · подготовил отдел продаж"

    s = prs.slides.add_slide(bullets)
    s.shapes.title.text = "Итоги квартала"
    tf = s.placeholders[1].text_frame
    lines = [
        "Выручка за квартал составила 48,6 млн рублей, это на 18% больше, чем во втором квартале, и на 31% больше, чем год назад",
        "Количество клиентов выросло с 1 240 до 1 610",
        "Средний чек увеличился с 27 400 до 30 200 рублей",
        "Доля повторных покупок — 46%",
        "Открыли новый офис в Казани",
        "Запустили онлайн-заказ для корпоративных клиентов",
        "Отток клиентов снизился с 9% до 6%",
        "Маркетинговый бюджет — 3,9 млн рублей",
        "Стоимость привлечения клиента снизилась с 4 100 до 3 200 рублей",
        "План на IV квартал — 55 млн рублей выручки",
    ]
    tf.text = lines[0]
    for ln in lines[1:]:
        tf.add_paragraph().text = ln
    for k, p in enumerate(tf.paragraphs):
        for r in p.runs:
            r.font.size = Pt(20 if k % 3 else 24)
            r.font.name = "Times New Roman" if k % 2 else "Arial"

    s = prs.slides.add_slide(title_only)
    s.shapes.title.text = "Выручка по месяцам, млн руб."
    cd = CategoryChartData()
    cd.categories = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь"]
    cd.add_series("Выручка, млн руб.", (11.2, 11.9, 12.4, 12.8, 13.6, 14.8, 15.1, 16.0, 17.5))
    s.shapes.add_chart(XL_CHART_TYPE.LINE, Emu(457200), Emu(1600000), Emu(8229600), Emu(4800000), cd)

    s = prs.slides.add_slide(title_only)
    s.shapes.title.text = "Продажи по регионам"
    rows = [["Регион", "Выручка, млн руб.", "Клиенты", "Средний чек, руб."],
            ["Москва", "18,4", "560", "32 800"], ["Санкт-Петербург", "9,7", "330", "29 400"], ["Казань", "4,1", "160", "25 600"],
            ["Екатеринбург", "3,8", "140", "27 100"], ["Новосибирск", "3,2", "120", "26 700"], ["Нижний Новгород", "2,6", "95", "27 400"],
            ["Самара", "2,1", "80", "26 300"], ["Краснодар", "1,9", "75", "25 300"], ["Ростов-на-Дону", "1,5", "60", "25 000"],
            ["Пермь", "0,8", "35", "22 900"], ["Остальные", "0,5", "35", "14 300"]]
    tbl = s.shapes.add_table(len(rows), 4, Emu(300000), Emu(1450000), Emu(8500000), Emu(5000000)).table
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            cell = tbl.cell(i, j)
            cell.text = v
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(14)

    s = prs.slides.add_slide(title_only)
    s.shapes.title.text = "Новый офис в Казани"
    s.shapes.add_picture(_photo(), Emu(4800000), Emu(1700000), Emu(3900000), Emu(2450000))
    tb = s.shapes.add_textbox(Emu(400000), Emu(1700000), Emu(4200000), Emu(1800000))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = ("Офис открылся 4 сентября. За первый месяц в нём оформили 41 договор на 4,1 млн рублей. "
                          "Команда — 6 менеджеров и руководитель направления. Окупаемость офиса ожидаем через 7 месяцев.")
    for r in tb.text_frame.paragraphs[0].runs:
        r.font.size = Pt(22)
        r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    s = prs.slides.add_slide(bullets)
    s.shapes.title.text = "Планы на IV квартал"
    tf = s.placeholders[1].text_frame
    plans = ["Выручка — 55 млн рублей", "Открыть офис в Екатеринбурге", "Запустить программу лояльности", "Довести долю повторных покупок до 50%",
             "Снизить отток до 5%", "Нанять 8 менеджеров", "Обновить CRM", "Провести 3 отраслевых мероприятия"]
    tf.text = plans[0]
    for ln in plans[1:]:
        tf.add_paragraph().text = ln

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    return OUT


if __name__ == "__main__":
    print(main())
