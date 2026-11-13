"""
BackgroundBlur

Proc node blurring the background of a video frame, using the mask in its
alpha channel. numpy only, in 16-bit integers: the frame is reduced, blurred
and brought back to size, and only the pixels at the soft edge of the mask are
blended with the sharp ones.
"""

import time

import numpy as np

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import ImagePayload


class BackgroundBlur(Node[ImagePayload, ImagePayload]):
    """Keep the person sharp and blur what the mask marks as background."""

    def __init__(
        self, downscale: int = 4, radius: int = 2, passes: int = 3, **kwargs
    ):
        """
        Parameters
        ----------
        downscale : int
            Factor by which the frame is reduced before blurring, an even
            number.
        radius : int
            Radius, in pixels of the reduced frame, of each box blur pass, 7
            at most.
        passes : int
            Number of box blur passes.
        kwargs : dict
            Superclass arguments.

        Raises
        ------
        ValueError
            If ``downscale`` is not an even number of at least 2, or
            ``radius`` is not between 0 and 7.

        """
        super().__init__(**kwargs)

        if downscale < 2 or downscale % 2:
            raise ValueError(f'downscale must be even and >= 2: {downscale}')

        # the sums of a box blur are 16 bits wide, see _box_blur
        if not 0 <= radius <= 7:
            raise ValueError(f'radius must be between 0 and 7: {radius}')

        self._downscale = downscale
        self._radius = radius
        self._passes = passes

    def update(self, message: Message[ImagePayload], **kwargs):  # noqa: D102
        started = time.perf_counter()

        frame = message.payload.image
        height, width = frame.shape[:2]
        rgb = frame[..., :3]
        mask = frame[..., 3]

        blurred = self._blur(rgb)

        # the person keeps the frame, the background takes the blurred one
        out = frame.copy()
        person = mask == 255
        np.copyto(out[..., :3], blurred, where=~person[..., None])

        # the soft edge of the mask is a blend of the two
        ys, xs = np.nonzero((mask > 0) & ~person)

        if ys.size:
            weight = mask[ys, xs].astype(np.uint16)[:, None]
            weight += weight >> 7
            out[ys, xs, :3] = (
                rgb[ys, xs].astype(np.uint16) * weight
                + blurred[ys, xs].astype(np.uint16) * (256 - weight)
            ) >> 8

        out[..., 3] = 255

        result = Message[ImagePayload](
            creator=self.name,
            payload=ImagePayload(
                image=out,
                width=width,
                height=height,
                depth=4,
                pixel_format='rgba',
                timestamp=message.payload.timestamp,
            ),
        )
        result.meta.update(message.meta)
        result.meta['ms_blur'] = round((time.perf_counter() - started) * 1000, 1)

        self.transmit(result)

    def _blur(self, rgb: np.ndarray) -> np.ndarray:
        height, width = rgb.shape[:2]
        even = rgb[: height & ~1, : width & ~1]

        # a 2x2 average, then every other pixel: cheaper than averaging whole
        # blocks and smoother than picking one pixel per block
        pairs = (
            even[0::2, 0::2].astype(np.uint16)
            + even[1::2, 0::2]
            + even[0::2, 1::2]
            + even[1::2, 1::2]
        ) >> 2
        small = pairs[:: self._downscale // 2, :: self._downscale // 2].astype(
            np.uint8
        )

        for _ in range(self._passes):
            small = _box_blur(small, self._radius)

        big = np.repeat(
            np.repeat(small, self._downscale, axis=0), self._downscale, axis=1
        )

        return np.pad(
            big[:height, :width],
            ((0, height - min(height, big.shape[0])),
             (0, width - min(width, big.shape[1])),
             (0, 0)),
            mode='edge',
        )


def _box_blur(image: np.ndarray, radius: int) -> np.ndarray:
    """Box blur in 16-bit sums: (2 * radius + 1) ** 2 values of at most 255
    must fit in 65535, so radius <= 7."""
    size = 2 * radius + 1
    padded = np.pad(image, ((radius, radius), (radius, radius), (0, 0)), 'edge')

    vertical = padded[: image.shape[0]].astype(np.uint16)
    for i in range(1, size):
        vertical += padded[i : i + image.shape[0]]

    total = vertical[:, : image.shape[1]].copy()
    for i in range(1, size):
        total += vertical[:, i : i + image.shape[1]]

    return (total // (size * size)).astype(np.uint8)
