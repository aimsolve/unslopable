# plan-promises: the text delivers what the plan promised

Written after level 3 of the plan, one check per element whose line promises something countable or named.

- A `table` element «three columns: room, size, heating»: the table in the text has exactly those column headers.
- A `list` element «5 steps to bleed a radiator»: the list has 5 items.
- An element with `facts: F12, F13`: the text of that element holds the numbers of F12 and F13.

Read the element's text by its id marker in TEXT.md (`<!-- S2.e3 -->`) and fail each element that misses what its
plan line says.
