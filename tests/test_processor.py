import io

from PIL import Image

from app.processor import parse_hex_color, prepare_image, remove_background
from app.storage import safe_client_filename


def make_test_png() -> bytes:
    image = Image.new("RGB", (8, 8), "white")
    for x in range(2, 6):
        for y in range(2, 6):
            image.putpixel((x, y), (15, 25, 35))
    output = io.BytesIO()
    image.save(output, "PNG", pnginfo=None)
    return output.getvalue()


def test_removes_only_border_connected_background():
    prepared = prepare_image(make_test_png(), max_pixels=1000)
    result_bytes, color, removed = remove_background(
        prepared.image, tolerance=0, remove_enclosed=False
    )
    result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    assert color == (255, 255, 255)
    assert removed == 48
    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((3, 3))[3] == 255


def test_removes_enclosed_background_regions_when_enabled():
    image = Image.new("RGB", (9, 9), "black")
    for x in range(2, 7):
        for y in range(2, 7):
            image.putpixel((x, y), (255, 255, 255))
    image.putpixel((4, 4), (0, 0, 0))

    connected_bytes, _, _ = remove_background(
        image, tolerance=0, remove_enclosed=False
    )
    complete_bytes, _, _ = remove_background(
        image, tolerance=0, remove_enclosed=True
    )
    connected = Image.open(io.BytesIO(connected_bytes)).convert("RGBA")
    complete = Image.open(io.BytesIO(complete_bytes)).convert("RGBA")

    assert connected.getpixel((4, 4))[3] == 255
    assert complete.getpixel((4, 4))[3] == 0


def test_tolerance_accepts_the_extended_range():
    prepared = prepare_image(make_test_png(), max_pixels=1000)
    remove_background(prepared.image, tolerance=255)


def test_color_and_filename_sanitization():
    assert parse_hex_color("#A0b1C2") == (160, 177, 194)
    assert safe_client_filename("../../un nom<script>.png") == "un nom_script_.png"
