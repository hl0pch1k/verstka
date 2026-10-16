Brief (what the person wrote):
{{ brief }}
{% if audience %}

Audience: {{ audience }}
{% endif %}

Draft title: {{ title }}
Draft subtitle: {{ subtitle or "—" }}
{% if context %}

Draft context lines (from the brief):
{% for line in context %}
- {{ line }}
{% endfor %}
{% endif %}

Data slides (in the order of the story):
{% for s in slides %}

[{{ s.id }}] file «{{ s.file }}»{% if s.task %}, task: {{ s.task }}{% endif %}

  topic: {{ s.topic }}
  draft headline: {{ s.headline }}
{% if s.caption %}
  caption under the chart: {{ s.caption }}
{% endif %}
  facts (the only numbers allowed in this slide's headline):
{% for f in s.facts %}
  - {{ f.text }} (value {{ f.value }}{% if f.unit %} {{ f.unit }}{% endif %})
{% endfor %}
{% endfor %}

{% if notes %}
What the files themselves say (their text around the tables — it already explains these things):
{% for n in notes %}
- «{{ n.file }}»: {{ n.text }}
{% endfor %}

{% endif %}
Draft summary title: {{ summary_title or "—" }}
Draft summary conclusions:
{% for line in summary %}
- {{ line }}
{% endfor %}

Write the connecting text by the rules. Return JSON only.
