The presentation: «{{ deck_title }}» — on {{ subject }}.

Statements:
{% for s in statements %}{{ s.id }}: {{ s.text }}
{% endfor %}
{% if reference %}
Reference excerpt (Wikipedia):
{{ reference }}
{% endif %}
JSON only.
