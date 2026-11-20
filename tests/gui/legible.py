"""Measuring what a person sees: can the text of a widget be read?"""

from __future__ import annotations

from collections import Counter


def readable(widget) -> float:
    """The contrast, as WCAG measures it, between a widget's background (its
    commonest color) and the color farthest from it, which is its text."""
    image = widget.grab().toImage()
    inner = [
        (c.red(), c.green(), c.blue())
        for y in range(6, image.height() - 6)
        for x in range(6, image.width() - 6)
        for c in (image.pixelColor(x, y),)
    ]

    def luminance(rgb: tuple[int, int, int]) -> float:
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in (v / 255 for v in rgb)
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    ground = luminance(Counter(inner).most_common(1)[0][0])
    return max(
        (max(luminance(c), ground) + 0.05) / (min(luminance(c), ground) + 0.05)
        for c in inner
    )
