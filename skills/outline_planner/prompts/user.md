Language: {{ language }}. Tone: {{ tone }}. Audience: {{ audience }}. Purpose: {{ purpose }}.
Target slide count: {{ target }}.
{% if title_hint %}Title hint: {{ title_hint }}{% endif %}
{% if extra_instructions %}User instructions (must be honoured): {{ extra_instructions }}{% endif %}

Strategy:
{{ strategy_instructions }}

Available slide kinds in the template (with samples count and max repeated items):
{{ kinds_json }}

Facts registry (the only allowed source of numbers):
{{ facts_json }}

Brief:
{{ brief }}
{% if issues %}
Previous plan had these problems; fix them:
{{ issues }}
{% endif %}

Return the JSON plan only.
