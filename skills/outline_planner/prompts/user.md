Language: {{ language }}. Tone: {{ tone }}. Audience: {{ audience }}. Purpose: {{ purpose }}.
Maximum number of slides: {{ target }} (use fewer when the brief has less content).
{% if title_hint %}Title hint: {{ title_hint }}{% endif %}
{% if extra_instructions %}User instructions (must be honoured): {{ extra_instructions }}{% endif %}

Strategy:
{{ strategy_instructions }}

Slide kinds of the template (samples count, max repeated items):
{{ kinds_json }}

Facts registry — the only source of numbers ("facts": single figures with ids f…, "series": chart data with ids s…, "tables"):
{{ facts_json }}

Brief:
{{ brief }}
{% if issues %}
The previous plan had these problems; fix them (remove what the brief does not support):
{{ issues }}
{% endif %}

Return the JSON plan only.
