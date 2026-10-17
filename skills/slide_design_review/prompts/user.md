Slide {{ slide_index }}{% if deck_title %} of the deck «{{ deck_title }}»{% endif %}{% if form and form != "слайд" %}: {{ form }}{% endif %}.
{% if headline %}Heading: «{{ headline }}»
{% endif %}{% if data_note %}The chart's data is checked against the file already: {{ data_note }} Do not report the values, the gaps or which point sits at which label — only how the slide reads.
{% endif %}
Check the attached image of the slide. JSON only.
