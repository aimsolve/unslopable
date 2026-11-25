# out-of-scope: the document's own search

The plugin's script finds the names listed in GATES.md `out_of_scope_terms`, and the judge reads the rest. Some
things the brief puts out of scope are no list of names: write a script for them.

- «No prices»: find sums and currencies («€40», «40 euros», «$12.50», «price», «cost»).
- «Nothing about the old pump model»: find its model numbers and the words its makers use for it.
- «No dates of the build»: find dates and month names near «build», «built», «ready».

Print each place as a failure when the words alone break the rule, or as `CHECK:` when only a reader can tell.
