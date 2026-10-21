"""Image validation and flat-background removal engine."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from scipy import ndimage


ALLOWED_FORMATS = ("PNG", "JPEG", "WEBP")


class InvalidImage(ValueError):
    """Raised when an uploaded image cannot be processed safely."""


@dataclass(frozen=True)
class PreparedImage:
    image: Image.Image
    sanitized_png: bytes
    width: int
    height: int
    detected_format: str


def prepare_image(raw: bytes, max_pixels: int) -> PreparedImage:
    """Decode, validate, orient and re-encode an image without metadata."""
    Image.MAX_IMAGE_PIXELS = max_pixels

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=ALLOWED_FORMATS) as source:
                detected_format = source.format or "UNKNOWN"
                if getattr(source, "n_frames", 1) != 1:
                    raise InvalidImage("Les images animées ne sont pas acceptées.")

                width, height = source.size
                if width < 1 or height < 1 or width * height > max_pixels:
                    raise InvalidImage(
                        f"L’image dépasse la limite de {max_pixels:,} pixels."
                    )

                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
    except InvalidImage:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("Le fichier n’est pas une image PNG, JPEG ou WebP valide.") from None
    except (OSError, ValueError):
        raise InvalidImage("L’image est endommagée ou utilise un format non pris en charge.") from None

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return PreparedImage(
        image=image,
        sanitized_png=buffer.getvalue(),
        width=image.width,
        height=image.height,
        detected_format=detected_format,
    )


def detect_background_color(rgb_array: np.ndarray) -> tuple[int, int, int]:
    """Return a robust dominant RGB color from the image border."""
    border_pixels = np.concatenate(
        (
            rgb_array[0, :, :],
            rgb_array[-1, :, :],
            rgb_array[:, 0, :],
            rgb_array[:, -1, :],
        )
    )
    # JPEG compression and antialiasing often turn a visually flat background
    # into many neighbouring RGB values. Group them before selecting the mode,
    # then return the median of the original pixels in the winning group.
    quantization_step = 16
    quantized = border_pixels // quantization_step
    colors, inverse, counts = np.unique(
        quantized.reshape(-1, 3), axis=0, return_inverse=True, return_counts=True
    )
    winning_group = int(np.argmax(counts))
    matching_pixels = border_pixels[inverse == winning_group]
    median = np.median(matching_pixels, axis=0)
    return tuple(int(round(channel)) for channel in median)


def remove_background(
    image: Image.Image,
    tolerance: int,
    background_color: tuple[int, int, int] | None = None,
    remove_enclosed: bool = True,
) -> tuple[bytes, tuple[int, int, int], int]:
    """Remove pixels matching the selected flat background."""
    if not 0 <= tolerance <= 255:
        raise ValueError("La tolérance doit être comprise entre 0 et 255.")

    rgba = image.convert("RGBA")
    pixels = np.asarray(rgba, dtype=np.uint8).copy()
    rgb = pixels[:, :, :3]

    selected_color = background_color or detect_background_color(rgb)
    delta = rgb.astype(np.int16)
    delta -= np.asarray(selected_color, dtype=np.int16)
    distance_squared = np.sum(delta.astype(np.int32) ** 2, axis=2)
    matching = distance_squared <= tolerance * tolerance

    if remove_enclosed:
        removable = matching
    else:
        labels, _ = ndimage.label(matching, structure=np.ones((3, 3), dtype=np.uint8))
        edge_labels = np.unique(
            np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]))
        )
        edge_labels = edge_labels[edge_labels != 0]
        removable = np.isin(labels, edge_labels) if edge_labels.size else np.zeros_like(matching)

    existing_alpha = pixels[:, :, 3]
    pixels[:, :, 3] = np.where(removable, 0, existing_alpha)
    removed_count = int(np.count_nonzero(removable))

    result = Image.fromarray(pixels, mode="RGBA")
    output = io.BytesIO()
    result.save(output, format="PNG", optimize=True)
    return output.getvalue(), selected_color, removed_count


def parse_hex_color(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6:
        raise ValueError("La couleur de fond est invalide.")
    try:
        return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        raise ValueError("La couleur de fond est invalide.") from None
