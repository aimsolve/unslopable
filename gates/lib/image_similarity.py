"""How alike an image and its references are, for the generated-image gate. Runs under uv with Pillow:

  python image_similarity.py <image> <reference> [<reference> …]   ->   JSON {reference path: similarity}

Similarity is 1 minus the share of differing bits of a 16×16 difference hash (brightness gradients of a grey
thumbnail): 1 = the same picture, about 0.5 for two unrelated pictures. It survives resizing and recompression, so a
near-copy of a reference scores close to 1.
"""
import json
import sys

from PIL import Image

N = 16


def dhash(path: str) -> list[bool]:
    im = Image.open(path).convert("L").resize((N + 1, N))
    px = list(im.getdata())
    return [px[r * (N + 1) + c] > px[r * (N + 1) + c + 1] for r in range(N) for c in range(N)]


def main(argv: list[str]) -> None:
    a = dhash(argv[0])
    out = {}
    for ref in argv[1:]:
        b = dhash(ref)
        out[ref] = 1 - sum(x != y for x, y in zip(a, b)) / len(a)
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1:])
