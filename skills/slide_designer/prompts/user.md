Deck: «{{ deck_title }}». Audience: {{ audience }}. Purpose: {{ purpose }}. Language of the slides: {{ language }}.
This is slide {{ position }} of {{ total }}.{% if prev_title %} Previous slide: «{{ prev_title }}».{% endif %}{% if next_title %} Next slide: «{{ next_title }}».{% endif %}

{% if rules %}
The user's rules for the whole deck (follow them):
{{ rules }}

{% endif %}
Heading of this slide: «{{ slide_title }}»
Source text of this slide (verbatim from the brief):
"""
{{ slide_text }}
"""

{% if requests %}
The user's requests for this slide (mandatory):
{{ requests }}

{% endif %}
Data you may use (copy the values exactly; there are no other figures):
{{ data }}

Kinds you may use (with the most items the template shows):
{{ kinds }}
{% if issues %}

A reviewer found problems in your previous design of this slide:
{{ issues }}
Your previous design:
{{ previous }}
Fix these problems and keep everything else of your previous design as it is (its lines, items, figures and charts): add what the notes ask for, do not drop what they do not mention. A wording the reviewer suggests is only a hint: every statement must come from the source text of this slide; a headline states the slide's conclusion with its key figure, never a list announced, never the slide's takeaway, never a cause the source does not state.
{% endif %}

Return the JSON object of this one slide only.
