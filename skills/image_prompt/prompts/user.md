Deck topic: {{ deck }}

{%- if others %}
Pictures this deck already has (show something different):
{% for o in others %}- {{ o }}
{% endfor %}
{%- endif %}
Pictures to describe:
{% for it in items %}
- id: {{ it.id }}
  slide headline: {{ it.headline }}
  the author's description: {{ it.hint }}
{%- if it.frame %}
  the frame on the slide: {{ it.frame }}
{%- endif %}
{%- if it.wish %}
  the person's wish for a new picture: {{ it.wish }}
{%- endif %}
{% endfor %}
