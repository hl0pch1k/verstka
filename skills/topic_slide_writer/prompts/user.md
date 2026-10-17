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
fragments ONLY: every figure, date, name and unit exactly as a fragment states it; nothing from your own knowledge; a
detail no fragment gives is left out. The slide's title and lead state its conclusion from these facts.
{{ reference }}
{% elif reference %}
Reference excerpt (Wikipedia):
{{ reference }}
{% endif %}
JSON only.
