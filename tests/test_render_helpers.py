"""Pure-Python render helpers (no GL context required)."""
import math
import struct
import zlib
from datetime import datetime

import numpy as np
import pytest

from cedartoy.render import (
    band_series_length,
    channel_resolution_value,
    date_uniform,
    image_to_float,
    resolve_frame_end,
    sample_time,
    stitch_tiles_by_rows,
    stitch_tiles_in_memory,
    temporal_offsets,
    to_output_pixels,
)
from cedartoy.image_io import encode_png16, encode_tiff16


# --- frame range / band series -------------------------------------------

def test_resolve_frame_end_explicit():
    assert resolve_frame_end(0, 100, 30.0, 10.0, 20.0) == 100


def test_resolve_frame_end_from_duration_then_audio():
    assert resolve_frame_end(0, 0, 30.0, 2.0, 99.0) == 60
    assert resolve_frame_end(0, 0, 30.0, 0.0, 3.0) == 90
    assert resolve_frame_end(10, 0, 30.0, None, 3.0) == 100
    assert resolve_frame_end(0, 0, 30.0, 0.0, None) == 0


def test_band_series_covers_resolved_end_and_audio():
    # frame_end=0 in the job must not collapse the series to one frame.
    end = resolve_frame_end(0, 0, 60.0, 0.0, 5.0)
    n = band_series_length(end, 60.0, 5.0)
    assert n >= 300
    assert band_series_length(10, 60.0, 5.0) >= int(math.ceil(5.0 * 60))
    assert band_series_length(0, 60.0, None) == 1


# --- shutter ----------------------------------------------------------------

def test_sample_time_single_sample_is_exact():
    base = 42 / 24.0
    (off,) = temporal_offsets(1, 42)
    assert sample_time(base, off, 0.5, 24.0) == base


def test_sample_time_shutter_is_fraction_of_frame():
    fps = 24.0
    base = 1.0
    lo = sample_time(base, 0.0, 0.5, fps)
    hi = sample_time(base, 1.0, 0.5, fps)
    assert hi - lo == pytest.approx(0.5 / fps)
    assert (lo + hi) / 2 == pytest.approx(base)
    for off in temporal_offsets(8, 3):
        assert abs(sample_time(base, off, 1.0, fps) - base) <= 0.5 / fps + 1e-12


# --- uniforms ------------------------------------------------------------------

def test_channel_resolution_value_packs_as_vec3_array():
    import _moderngl

    written = {}

    class _Ctx:
        def _write_uniform(self, prog, loc, gl_type, n, size, data):
            written["data"] = data

    u = _moderngl.Uniform()
    u.fmt, u.array_length, u.dimension, u.ctx = "3f", 4, 3, _Ctx()
    u.program_obj = u.location = u.gl_type = u.element_size = 0
    ch_res = [(512.0, 2.0, 1.0), (0.0, 0.0, 0.0), (64, 32, 1), (0.0, 0.0, 0.0)]
    u.value = channel_resolution_value(ch_res)
    assert struct.unpack("12f", written["data"])[:3] == (512.0, 2.0, 1.0)
    assert struct.unpack("12f", written["data"])[6:9] == (64.0, 32.0, 1.0)


def test_date_uniform_is_deterministic():
    start = datetime(2024, 12, 31, 23, 59, 58)
    a = date_uniform(start, 1.5)
    assert a == date_uniform(start, 1.5)
    assert a == (2024.0, 12.0, 31.0, pytest.approx(86399.5))
    assert date_uniform(start, 3.0)[:3] == (2025.0, 1.0, 1.0)


# --- image conversion ------------------------------------------------------------

def test_image_to_float_uses_dtype_max():
    img16 = np.array([[[0, 65535, 32768, 65535]]], dtype=np.uint16)
    out = image_to_float(img16)
    assert out[0, 0, 1] == pytest.approx(1.0)
    assert out[0, 0, 2] == pytest.approx(32768 / 65535)
    img8 = np.array([[[255, 0, 128, 255]]], dtype=np.uint8)
    assert image_to_float(img8)[0, 0, 0] == pytest.approx(1.0)


def test_image_to_float_keeps_hdr():
    hdr = np.array([[[4.0, -0.5, 0.25, 1.0]]], dtype=np.float32)
    np.testing.assert_array_equal(image_to_float(hdr), hdr)


def test_to_output_pixels_8bit_rounds():
    img = np.full((1, 1, 4), 0.999, dtype=np.float32)  # 254.745 -> 255
    out = to_output_pixels(img, "png", "8")
    assert out.dtype == np.uint8 and out[0, 0, 0] == 255
    assert to_output_pixels(np.full((1, 1, 4), 0.5 / 255 + 1e-6, np.float32), "png", "8")[0, 0, 0] == 1


@pytest.mark.parametrize("depth", ["16f", "32f"])
def test_to_output_pixels_high_depth_is_uint16(depth):
    img = np.array([[[0.0, 1.0, 0.5, 2.0]]], dtype=np.float32)
    out = to_output_pixels(img, "tif", depth)
    assert out.dtype == np.uint16
    assert out.tolist() == [[[0, 65535, 32768, 65535]]]


def test_to_output_pixels_exr_stays_float():
    img = np.array([[[2.0, -1.0, 0.5, 1.0]]], dtype=np.float32)
    assert to_output_pixels(img, "exr", "16f").dtype == np.float16
    np.testing.assert_array_equal(to_output_pixels(img, "exr", "32f"), img)


def _decode_png16(data: bytes) -> np.ndarray:
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    w, h, depth, ctype = ihdr[:4]
    assert depth == 16
    c = {0: 1, 4: 2, 2: 3, 6: 4}[ctype]
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * c * 2)
    assert (raw[:, 0] == 0).all()
    return raw[:, 1:].copy().view(">u2").reshape(h, w, c).astype(np.uint16)


def test_png16_roundtrip():
    a = (np.random.default_rng(0).random((13, 17, 4)) * 65535).astype(np.uint16)
    np.testing.assert_array_equal(_decode_png16(encode_png16(a, 6)), a)


@pytest.mark.parametrize("deflate", [False, True])
def test_tiff16_roundtrip(deflate):
    iio = pytest.importorskip("imageio.v3")
    a = (np.random.default_rng(1).random((37, 19, 4)) * 65535).astype(np.uint16)
    back = iio.imread(encode_tiff16(a, deflate=deflate), extension=".tif")
    np.testing.assert_array_equal(back, a)


# --- tile stitching ------------------------------------------------------------

def _synthetic_render(width, height, tiles_x, tiles_y):
    """Reference image plus per-tile arrays as read back from GL (flipud)."""
    tile_w = math.ceil(width / tiles_x)
    tile_h = math.ceil(height / tiles_y)
    rng = np.random.default_rng(width * 1000 + height)
    # Image in GL orientation (row 0 = bottom), padded to full tile grid.
    gl = rng.random((tile_h * tiles_y, tile_w * tiles_x, 4)).astype(np.float32)
    expected = np.flipud(gl[:height, :width])
    tiles = {}
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            t = gl[ty * tile_h:(ty + 1) * tile_h, tx * tile_w:(tx + 1) * tile_w]
            tiles[(tx, ty)] = np.flipud(t).copy()
    return expected, tiles, tile_w, tile_h


@pytest.mark.parametrize("w,h,tx,ty", [
    (8, 6, 2, 2), (10, 7, 3, 2), (9, 13, 2, 4), (5, 5, 1, 1), (17, 11, 4, 3),
])
def test_stitch_paths_match_reference(w, h, tx, ty):
    expected, tiles, tile_w, tile_h = _synthetic_render(w, h, tx, ty)
    load = lambda x, y: tiles[(x, y)]
    mem = stitch_tiles_in_memory(load, tx, ty, tile_w, tile_h, w, h)
    rows = stitch_tiles_by_rows(load, tx, ty, tile_w, tile_h, w, h)
    np.testing.assert_array_equal(mem, expected)
    np.testing.assert_array_equal(rows, mem)
