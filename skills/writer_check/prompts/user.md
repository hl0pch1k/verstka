Topic: «{{ topic }}».{% if reference and not (sourced is defined and sourced) %}


Reference:
<<<
{{ reference }}
>>>{% endif %}


The text{% if (sourced is defined and sourced) %} (each statement with its source){% endif %}:
{{ numbered }}

Return the JSON only.
