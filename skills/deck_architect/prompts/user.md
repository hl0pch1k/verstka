Audience: {{ audience }}. Purpose: {{ purpose }}. Language of the slides: {{ language }}.
{% if title_hint %}Title given by the user: «{{ title_hint }}».
{% endif %}
{% if rules %}The user's rules for the whole deck:
{{ rules }}
{% endif %}

The brief, sentence by sentence:
{{ sentences }}

Data of the brief (ids with values):
{{ data }}

Return the JSON storyline only.
