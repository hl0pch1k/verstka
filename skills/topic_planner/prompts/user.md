The person's request: «{{ request }}»
The topic: {{ subject }}
Language of the presentation: {{ language }}
Content slides (the cover is separate): {{ slides }}
{% if theses %}
The person's own points (each must be in the deck, as they wrote it):
{% for t in theses %}- {{ t }}
{% endfor %}{% endif %}
{% if plan_items is defined and plan_items %}
The person's plan — the deck follows it: one content slide per item, in this order; each slide's title states what the
slide shows about its item (a conclusion, not a bare topic); an ask inside an item («покажи на графике», «сравни»,
«нужна таблица») sets the slide's form and is never written on the slide:
{% for t in plan_items %}{{ loop.index }}. {{ t }}
{% endfor %}{% endif %}
{% if source is defined and source == "kb" %}
The person's knowledge base («{{ reference_title }}»): excerpts of their own documents, each under its document's and
section's name. This deck is built from these documents ONLY: every must-know fact is a fact the excerpts state — with
their exact figures, dates, names and units; no fact, figure or date from your own knowledge; a slide the documents
cannot fill is left out rather than invented. The documents may be about the person's own company, product or project:
write about it as the documents do. The deck tells what the documents say to the audience: an opening (why it
matters), the substance, the evidence in figures, and the last slide — the conclusion and what is asked or what comes
next (its title says so: «Выводы и что просим», «Что предлагаем»). Every figure of the documents goes to ONE slide —
never the same figure or fact on two slides. A table of the documents stays a table (form "table") or becomes a chart
(form "chart") when it compares figures of one measure. No pictures ("picture": false) unless the request asks for them.
A «timeline» only for events with their own dates (not one year repeated).
{{ reference }}
{% elif reference %}
Reference excerpt («{{ reference_title }}», Wikipedia):
{{ reference }}
{% else %}
No reference excerpt: write from well-established knowledge only.
{% endif %}
JSON only.
