The presentation: «{{ deck_title }}» — on {{ subject }}. Language: {{ language }}.

The deck's plan (your slide is marked →):
{% for s in plan %}{{ '→' if s.n == n else ' ' }} {{ s.n }}. {{ s.title }} — {{ s.goal }}
{% endfor %}
Your slide: {{ n }}. «{{ title }}»
Goal: {{ goal }}
Form: {{ form }}{% if picture %}; with a picture{% endif %}
Must-know facts of this slide:
{% for f in facts %}- {{ f }}
{% else %}- (none given: cover the goal)
{% endfor %}
{% if source is defined and source == "kb" %}
Fragments of the person's knowledge base (each with its document and place in brackets). Write the slide from these
fragments ONLY: every figure, date, name and unit exactly as a fragment states it; a change names both of its periods
(«с 980 в первом квартале до 1 240 в третьем», never a bare «с 980 до 1 240»); every point is a whole sentence with its verb; nothing from your own knowledge; a
detail no fragment gives is left out. The slide's title and lead state its conclusion from these facts. Only this
slide's ground: a fact the other slides of the plan cover is not repeated here; no point repeats the lead. A table of a
fragment goes to "table" (or "chart" for one measure), never into the points as «| … |» lines.
{{ reference }}
{% elif reference %}
Reference excerpt (Wikipedia):
{{ reference }}
{% endif %}
{% if beside_data is defined and beside_data %}
Data tables of the person stand beside these slides in the same deck: they, not the documents, show what was achieved.
A goal, a norm or a threshold of the documents is stated as the documents state it (as a goal, a norm, a rule — «цель
— NPS не ниже 45 к концу года»); never write whether it is reached, missed, exceeded, behind or on track («цели не
достигнуты», «отставание от плана», «перерасход требует одобрения»), and never a step that asks for an approval or an
exception a rule needs only past its threshold: the deck checks every goal against the tables itself.
{% endif %}
JSON only.
