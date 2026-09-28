The topic, in the user's words: «{{ topic }}».
{% if private_hint %}
The text speaks of «наш», «мой» or «мы»: unless the subject is a well-known public one (a country, a planet, a famous company), it is the user's own — answer {"status": "private"}.
{% endif %}
{% if theses %}
The user's own statements (keep each of them word for word, first in the slide it belongs to, and never contradict them):
{{ theses }}
{% endif %}
{% if reference %}
Reference text (the only source of facts{% if (cited is defined and cited) %}; cite the numbers of the sentences each of your sentences comes from{% endif %}):
<<<
{{ reference }}
>>>
{% endif %}
{% if refill is defined and refill %}
The deck already has these slides: {{ written_titles }}.
These facts are already told on them — do not repeat any of them:
{{ told }}
Write ONLY the {{ n_content }} slides listed below, with the same rules: each tells facts of the reference the deck does not tell yet (other events, other dates, other figures, other names). A slide listed with the title of one of the deck's slides keeps that title and gets 3–4 new sentences. Answer with the same JSON shape; "title" and "subtitle" may be empty.
{% elif written_titles %}
The deck is already written up to slide {{ first_number - 1 }}; its slides are: {{ written_titles }}.
Write ONLY the next {{ n_content }} content slides (they continue the story; do not repeat those slides), with the same rules. Answer with the same JSON shape; "title" and "subtitle" may be empty.
{% endif %}
The order of the {{ n_content }} content slides (working titles):
{{ storyline }}

Audience: {{ audience }}. Language of the text: {{ language }}.
Write exactly {{ n_content }} content slides{% if not written_titles %} (the cover is made from the title and the subtitle; do not write it){% endif %}.
Return the JSON only.
