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
{% if reference %}
Reference excerpt (Wikipedia):
{{ reference }}
{% endif %}
JSON only.
