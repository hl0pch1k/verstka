You are a presentation designer reviewing slides of a corporate PowerPoint template. You see ONE rendered slide. Decide which pattern kind it is and describe in one short sentence what this slide is meant for (what content a user would put on it).

Kinds (choose exactly one): title, section, agenda, bullets, cards, two_column, big_number, stat_row, comparison, timeline, process, table, chart, image_text, team, quote, code, mockup, thanks, freeform.

Guidance:
- title = opening slide; thanks = closing/contacts/Q&A; section = divider with a big heading and little else; agenda = table of contents.
- cards = several equal blocks with small headings; stat_row = 3+ KPI numbers; big_number = 1–2 huge numbers; chart / table when they dominate; timeline / process = ordered steps or dates; team = people photos with names; mockup = device screenshot; image_text = big illustration plus text; quote = quotation; code = code block; two_column = two text columns; comparison = options contrasted side by side; bullets = heading plus a list; freeform = nothing fits.
- Placeholder texts (Заголовок, Текст, Lorem ipsum) are normal in templates; judge the structure, not the words.

Return JSON only: {"kind": "...", "purpose": "...", "confidence": 0.0-1.0}
