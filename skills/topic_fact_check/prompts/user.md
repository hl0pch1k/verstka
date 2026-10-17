The presentation: «{{ deck_title }}» — on {{ subject }}.

Statements:
{% for s in statements %}{{ s.id }}: {{ s.text }}
{% endfor %}
{% if source is defined and source == "kb" %}
Fragments of the person's knowledge base — the deck's only source: a statement that contradicts them is an error (give
the fix from the fragments); a statement with a figure, date or name the fragments do not state is an error with
"fix": "" unless your fix takes it from the fragments.
{{ reference }}
{% elif reference %}
Reference excerpt (Wikipedia):
{{ reference }}
{% endif %}
JSON only.
