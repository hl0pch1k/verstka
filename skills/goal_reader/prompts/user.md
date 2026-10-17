Brief (what the person wrote, between the lines):
---
{{ brief }}
---

Datasets:
{% for d in datasets %}

[{{ d.id }}] «{{ d.file }}»{% if d.sheet %}, sheet «{{ d.sheet }}»{% endif %} — {{ d.title }}; {{ d.nature }}; {{ d.rows }} rows; tasks the data can do: {{ d.tasks | join(", ") or "—" }}
{% if d.time %}
  time axis: «{{ d.time.column }}» ({{ d.time.freq }}) {{ d.time.start }} … {{ d.time.end }}, {{ d.time.points }} periods{% if d.time.missing %}, {{ d.time.missing }} without data{% endif %}

{% if d.time.periods %}
  periods: {{ d.time.periods | join(", ") }}
{% endif %}
{% endif %}
{% if d.period_columns %}
  periods as columns: {{ d.period_columns | join(", ") }}
{% endif %}
  columns:
{% for c in d.columns %}
  - «{{ c.name }}» — {{ c.type }}, {{ c.role }}{% if c.unit %}, unit «{{ c.unit }}»{% endif %}{% if c.range %}; from {{ c.range[0] }} to {{ c.range[1] }}{% endif %}{% if c.adds_up is not none %}; {{ "adds up" if c.adds_up else "does not add up" }}{% endif %}{% if c.weight %}; weight «{{ c.weight }}»{% endif %}{% if c.forecast %}; forecast{% endif %}{% if c["values"] %}; values: {{ c["values"] | join(" | ") }}{% if c.distinct > c["values"] | length %} … ({{ c.distinct }} distinct){% endif %}{% endif %}

{% endfor %}
{% if d.total_rows %}
  total rows: {{ d.total_rows | join(", ") }}
{% endif %}
{% if d.total_column %}
  total column: «{{ d.total_column }}»
{% endif %}
{% if d.benchmarks %}
  benchmark rows (not categories): {{ d.benchmarks | join(", ") }}
{% endif %}
{% if d.forecast_rows %}
  forecast rows: {{ d.forecast_rows }}
{% endif %}
{% if d.notes %}
  text around the table: {{ d.notes }}
{% endif %}
{% endfor %}

Return the brief's goals over these datasets by the rules, and its sentences the data cannot answer: every sentence of
the brief that asks or requests something is one of the two. JSON only.
{% if retry %}

Your previous answer was empty, but the brief does ask something about the data: every sentence that asks or requests
something must become a goal (or an unanswerable entry). Do not return an empty object.
{% endif %}
