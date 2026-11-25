# figure-text-size: text in a figure is readable when printed

The body size and the printed width of a figure differ by format and brand, so the numbers come from the brief.
The script checks figure files: its first line names `figures/*.svg`.

- Read each `<text>` element's font size and the SVG's width.
- Scale it to the printed width of the figure (the text column of the format, e.g. 160 mm for an A4 page with 25 mm
  margins).
- Fail a text below 7 pt or above the body size, naming the label and its printed size.
