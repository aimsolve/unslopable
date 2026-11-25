"""The margin of background around a screenshot's content, for the screenshot-margin gate. Runs under uv with
Pillow:

  python image_margin.py <image>   ->   JSON {"width", "height", "background": [r, g, b],
                                          "bands": {"top", "right", "bottom", "left"}}

The background is the median colour of the image's outermost ring of pixels (transparency laid on white). A band is
how many whole rows (top, bottom) or columns (left, right), counted from that edge inward, are background: every
pixel of the line within TOLERANCE of the background colour on each channel, except at most OUTLIERS of the line in a
JPEG (compression noise), and the line's median colour within STEP of the outermost line's. Content that touches an edge,
a bar of another colour along it, or text cut at it gives a band of 0 on that side. STEP catches a light frame the
crop runs along: its colour is then the ring's, the white inside it is within TOLERANCE of it, and the band would
otherwise run on into the card.
"""
import json
import sys

from PIL import Image

TOLERANCE = 18   # per channel, 0..255: JPEG noise and faint anti-aliasing stay background
OUTLIERS = 0.001  # JPEG only: share of a line's pixels that may stray (compression noise); lossless formats have
                  # no noise, so there a 1-px line running into the edge stops the band
STEP = 5          # per channel: how far a line's median colour may lie from the edge line's


def load(path: str) -> Image.Image:
    im = Image.open(path)
    if im.mode in ("I", "I;16", "I;16B", "I;16L"):  # 16-bit grey: scale to 8 bits, or every grey reads as white
        im = im.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    if im.mode in ("RGBA", "LA", "P", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im)
    return im.convert("RGB")


def median(values: list) -> int:
    s = sorted(values)
    return s[len(s) // 2]


def main(path: str) -> None:
    im = load(path)
    lossy = Image.open(path).format == "JPEG"
    w, h = im.size
    px = im.load()
    ring = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)] + \
           [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    bg = tuple(median([c[k] for c in ring]) for k in range(3))

    def is_bg(line: list) -> bool:
        allowed = int(len(line) * OUTLIERS) if lossy else 0
        off = 0
        for c in line:
            if max(abs(c[0] - bg[0]), abs(c[1] - bg[1]), abs(c[2] - bg[2])) > TOLERANCE:
                off += 1
                if off > allowed:
                    return False
        return True

    def line_median(line: list) -> tuple:
        return tuple(median([c[k] for c in line]) for k in range(3))

    def band(lines) -> int:
        n, edge = 0, None
        for line in lines:
            mid = line_median(line)
            edge = edge or mid
            if not is_bg(line) or max(abs(mid[k] - edge[k]) for k in range(3)) > STEP:
                break
            n += 1
        return n

    rows = lambda ys: ([px[x, y] for x in range(w)] for y in ys)  # noqa: E731
    cols = lambda xs: ([px[x, y] for y in range(h)] for x in xs)  # noqa: E731
    bands = {"top": band(rows(range(h))), "right": band(cols(range(w - 1, -1, -1))),
             "bottom": band(rows(range(h - 1, -1, -1))), "left": band(cols(range(w)))}
    print(json.dumps({"width": w, "height": h, "background": list(bg), "bands": bands}))


if __name__ == "__main__":
    main(sys.argv[1])
