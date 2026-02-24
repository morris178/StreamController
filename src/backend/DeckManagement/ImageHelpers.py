"""
Author: Core447
Year: 2023

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This programm comes with ABSOLUTELY NO WARRANTY!

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

The functions:
create_full_deck_sized_image, create_wallpaper_image_array; crop_key_image_from_deck_sized_image
are based on the functions in the examples of: https://github.com/abcminiuser/python-elgato-streamdeck
Shoutout to Dean Camera alias abcminiuser for his amazing work!
"""
import io
import os
from functools import lru_cache

from PIL import Image, ImageOps
from StreamDeck.ImageHelpers import PILHelper

from gi.repository import GLib, GdkPixbuf


def invalidate_native_jpeg_quality_override_cache() -> None:
    get_native_jpeg_quality_override.cache_clear()


@lru_cache(maxsize=1)
def get_native_jpeg_quality_override() -> int | None:
    """
    Optional local performance override for Stream Deck JPEG payload size.

    Applies only to JPEG-based native image formats. Falls back to the upstream
    StreamDeck library encoder behavior when unset/invalid/100.
    """
    raw = os.getenv("SC_NATIVE_JPEG_QUALITY")
    if raw is None:
        # Keep compatibility with the experimental branch env var while testing.
        raw = os.getenv("SC_PRERENDER_JPEG_QUALITY")
    if raw not in (None, ""):
        try:
            quality = int(raw)
        except (TypeError, ValueError):
            quality = None
        if quality is not None:
            quality = max(1, min(100, quality))
            if quality >= 100:
                return None
            return quality

    # UI setting fallback (cached; invalidated when the Settings slider changes)
    try:
        app_settings = gl.settings_manager.get_app_settings() if getattr(gl, "settings_manager", None) else {}
        quality = int(app_settings.get("performance", {}).get("native-jpeg-quality", 70))
    except Exception:
        quality = 70
    quality = max(1, min(100, quality))
    if quality >= 100:
        return None
    return quality


def _to_native_format_with_quality(image: Image.Image, image_format: dict, jpeg_quality: int | None) -> bytes:
    if jpeg_quality is None:
        return PILHelper._to_native_format(image, image_format)

    fmt = str(image_format.get("format", "")).upper()
    if fmt not in {"JPEG", "JPG"}:
        return PILHelper._to_native_format(image, image_format)

    if image.size != image_format['size']:
        image.thumbnail(image_format['size'])

    if image_format['rotation']:
        image = image.rotate(image_format['rotation'])

    if image_format['flip'][0]:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)

    if image_format['flip'][1]:
        image = image.transpose(Image.FLIP_TOP_BOTTOM)

    with io.BytesIO() as compressed_image:
        image.save(compressed_image, image_format['format'], quality=jpeg_quality)
        return compressed_image.getvalue()


def to_native_key_format(deck, image: Image.Image) -> bytes:
    return _to_native_format_with_quality(image, deck.key_image_format(), get_native_jpeg_quality_override())


def to_native_touchscreen_format(deck, image: Image.Image) -> bytes:
    return _to_native_format_with_quality(image, deck.touchscreen_image_format(), get_native_jpeg_quality_override())


def _monkeypatch_streamdeck_pilhelper_native_encoders() -> None:
    """
    Make the JPEG quality override apply to code paths that call StreamDeck's
    PILHelper directly (including plugins outside this repository).
    """
    try:
        PILHelper.to_native_key_format = to_native_key_format
        PILHelper.to_native_touchscreen_format = to_native_touchscreen_format
        PILHelper.to_native_format = lambda deck, image: to_native_key_format(deck, image)
    except Exception:
        # Keep startup resilient if the library API changes unexpectedly.
        return


_monkeypatch_streamdeck_pilhelper_native_encoders()

def create_full_deck_sized_image(deck, image_filename = None, image = None):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()['size']
        spacing_x, spacing_y = (36, 36)

        # Compute total size of the full StreamDeck image, based on the number of
        # buttons along each axis. This doesn't take into account the spaces between
        # the buttons that are hidden by the bezel.
        key_width *= key_cols
        key_height *= key_rows

        # Compute the total number of extra non-visible pixels that are obscured by
        # the bezel of the StreamDeck.
        spacing_x *= key_cols - 1
        spacing_y *= key_rows - 1

        # Compute final full deck image size, based on the number of buttons and
        # obscured pixels.
        full_deck_image_size = (key_width + spacing_x, key_height + spacing_y)

        # Resize the image to suit the StreamDeck's full image size. We use the
        # helper function in Pillow's ImageOps module so that the image's aspect
        # ratio is preserved.
        if image_filename != None:
            with Image.open(image_filename) as image:
                image = image.copy().convert("RGBA")
        elif image != None:
            image = image.convert("RGBA")
        image = ImageOps.fit(image, full_deck_image_size, Image.Resampling.LANCZOS)
        return image
def create_wallpaper_image_array(deck, progress_dir = None, image = None):
        # Maybe use 2D array instead
        if progress_dir != None:
            image = create_full_deck_sized_image(deck, image_filename=progress_dir)
        elif image != None:
            image = create_full_deck_sized_image(deck, image=image)
            
        key_images = []
        for i in range(deck.key_count()):
            key_images.append(crop_key_image_from_deck_sized_image(deck, image, i)[1])
        return key_images

def crop_key_image_from_deck_sized_image(deck, image, key):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()['size']
        spacing_x, spacing_y = (36, 36)

        # Determine which row and column the requested key is located on.
        row = key // key_cols
        col = key % key_cols

        # Compute the starting X and Y offsets into the full size image that the
        # requested key should display.
        start_x = col * (key_width + spacing_x)
        start_y = row * (key_height + spacing_y)

        # Compute the region of the larger deck image that is occupied by the given
        # key, and crop out that segment of the full image.
        region = (start_x, start_y, start_x + key_width, start_y + key_height)
        segment = image.crop(region)

        # Return the segment directly, converting to RGBA to preserve transparency
        key_image = segment.convert("RGBA")

        return to_native_key_format(deck, key_image), key_image

def shrink_image(image):
        image = image.resize((50, 50), Image.Resampling.LANCZOS)
        bg = Image.new("RGB", (72, 72), (0, 0, 0))
        if image.has_transparency_data:
            bg.paste(image, (11, 11), image)
        else:
            bg.paste(image, (11, 11))
        return bg

def is_transparent(img: Image.Image):
    """
    Determines if an image has transparency.

    Args:
        img (PIL.Image.Image): The image to check for transparency.

    Returns:
        bool: True if the image has transparency, False otherwise.
    """
    return img.has_transparency_data

    if img.info.get("transparency", None) is not None:
        return True
    if img.mode == "P":
        transparent = img.info.get("transparency", -1)
        for _, index in img.getcolors():
            if index == transparent:
                return True
    elif img.mode == "RGBA":
        extrema = img.getextrema()
        if extrema[3][0] < 255:
            return True

    return False

def image2pixbuf(img, force_transparency=False):
    """
    Converts an image to a GdkPixbuf.Pixbuf object.

    Args:
        img (PIL.Image.Image): The image to convert.

    Returns:
        GdkPixbuf.Pixbuf: The converted GdkPixbuf.Pixbuf object.
    """
    img = img.convert("RGBA")
    force_transparency = True

    data = img.tobytes()
    w, h = img.size
    data = GLib.Bytes.new(data)
    transparent = True if force_transparency else is_transparent(img)
    channels = 4 if transparent else 3

    try:
        pix = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                transparent, 8, w, h, w * channels)
        # Clean up memory
        data = None
        w, h = None, None
        del data
        return pix
    except TypeError as e:
         # This usually happens if the image is a non RGB image
         return
