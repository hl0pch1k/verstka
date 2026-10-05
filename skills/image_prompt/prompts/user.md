Deck topic: {{ deck }}

Pictures to describe:
{% for it in items %}
- id: {{ it.id }}
  slide headline: {{ it.headline }}
  the author's description: {{ it.hint }}
{%- if it.wish %}
  the person's wish for a new picture: {{ it.wish }}
{%- endif %}
{% endfor %}
