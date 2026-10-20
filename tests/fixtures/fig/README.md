# Файлы Figma `.fig` для тестов чтения брендбука

- `frame.fig`, `components.fig` — настоящие файлы Figma («Сохранить локальную копию»: ZIP с `canvas.fig` — kiwi, сообщение
  сжато zstd). Источник: тестовые данные проекта [gridaco/grida](https://github.com/gridaco/grida) (`fixtures/`),
  лицензия Apache-2.0; sha256 сверены с LFS-указателями репозитория.
  - `frame.fig` — sha256 `bf0687512d9a4a7733c319df81785d3c89033301a6fa943d762d7f278f70b293`
  - `components.fig` — sha256 `1fbdc089f3ab1ad5f7866d7ee37c096de34cb3c07ec26222991f4954dc022437`
- `zstd/` — эталоны для распаковщика Zstandard (`verstka/brand/zstd.py`): `*.zst` сжаты CLI `zstd` разными уровнями,
  рядом — sha256 исходных данных.

Синтетические `.fig` (переменные, стили, сетка, логотип-вектор) собирает кодировщик kiwi в `tests/unit/fig_helpers.py`.
