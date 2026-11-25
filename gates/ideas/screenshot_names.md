# screenshot-names: no real people on a screenshot

Whose names, handles, emails and avatars may not show differs per document. The script checks screenshots: its
first line names `figures/`.

- From the brief and the material, list the people and accounts that must not appear (the owner of the house, the
  plumber's email, the family's shared account).
- A script cannot read an image, so print one `CHECK:` line per screenshot with that list, and write the rule for
  the judge in `.gates/custom/<gate>.md`: a real name, handle, email or avatar fails; a placeholder («Jane Doe»,
  «user@example.com») passes.
