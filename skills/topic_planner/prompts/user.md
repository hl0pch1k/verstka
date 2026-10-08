The person's request: «{{ request }}»
The topic: {{ subject }}
Language of the presentation: {{ language }}
Content slides (the cover is separate): {{ slides }}
{% if theses %}
The person's own points (each must be in the deck, as they wrote it):
{% for t in theses %}- {{ t }}
{% endfor %}{% endif %}
{% if reference %}
Reference excerpt («{{ reference_title }}», Wikipedia):
{{ reference }}
{% else %}
No reference excerpt: write from well-established knowledge only.
{% endif %}
JSON only.
