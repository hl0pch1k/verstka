The brief:
"""
{{ brief }}
"""

{% if rules %}
The user's rules for the whole deck:
{{ rules }}

{% endif %}
{% if requests %}
The user's requests per slide:
{{ requests }}

{% endif %}
The plan of the variant «{{ variant }}» ({{ variant_hint }}), one line per slide:
{{ plan }}

Return the JSON with the issues only.
