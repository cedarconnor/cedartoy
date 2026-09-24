"""Minimal 16-bit PNG / TIFF writers.

Pillow (used for 8-bit PNG/TIFF output) cannot encode 16-bit-per-channel
RGB(A) images, so 16-bit frames are written with these small zlib-based
encoders instead. No extra dependencies.

- PNG: 16-bit greyscale / grey+alpha / RGB / RGBA, filter type 0, zlib
  level from `png_compress_level`.
- TIFF: baseline, little-endian, chunked strips, either uncompressed or
  Adobe Deflate (compression=8). `tif_lzw` maps to Deflate at 16-bit since
  LZW encoding would need an extra codec; Deflate is lossless and supported
  by every mainstream TIFF reader.
"""
import struct
import zlib
from pathlib import Path

import numpy as np


def _as_hwc_u16(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.uint16:
        raise ValueError(f"expected uint16 image, got {img.dtype}")
    if img.ndim == 2:
        img = img[:, :, None]
    if img.ndim != 3 or img.shape[2] not in (1, 2, 3, 4):
        raise ValueError(f"unsupported image shape {img.shape}")
    return img


def encode_png16(img: np.ndarray, compress_level: int = 1) -> bytes:
    img = _as_hwc_u16(img)
    h, w, c = img.shape
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    rows = np.ascontiguousarray(img.astype(">u2")).view(np.uint8).reshape(h, w * c * 2)
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), rows], axis=1)
    level = max(0, min(9, int(compress_level)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 16, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), level))
            + chunk(b"IEND", b""))


def encode_tiff16(img: np.ndarray, deflate: bool = False, rows_per_strip: int = 16) -> bytes:
    img = _as_hwc_u16(img)
    h, w, c = img.shape
    rows_per_strip = max(1, min(int(rows_per_strip), h))
    data = np.ascontiguousarray(img.astype("<u2"))

    strips = []
    for y in range(0, h, rows_per_strip):
        b = data[y:y + rows_per_strip].tobytes()
        strips.append(zlib.compress(b, 6) if deflate else b)
    n_strips = len(strips)

    # Layout: header(8) | extra tag values | strip data | IFD
    extra = bytearray()
    header_len = 8

    def put_extra(payload: bytes) -> int:
        off = header_len + len(extra)
        extra.extend(payload)
        if len(extra) % 2:
            extra.append(0)
        return off

    SHORT, LONG = 3, 4
    tags = []  # (tag, type, count, value_or_offset)

    def add(tag, typ, values):
        values = list(values)
        fmt = "<H" if typ == SHORT else "<I"
        if len(values) * (2 if typ == SHORT else 4) <= 4:
            packed = b"".join(struct.pack(fmt, v) for v in values).ljust(4, b"\0")
            tags.append((tag, typ, len(values), packed))
        else:
            off = put_extra(b"".join(struct.pack(fmt, v) for v in values))
            tags.append((tag, typ, len(values), struct.pack("<I", off)))

    # Strip offsets depend on where the extra tag data ends, so reserve the
    # offsets array with placeholders first and patch it below.
    add(256, LONG, [w])
    add(257, LONG, [h])
    add(258, SHORT, [16] * c)
    add(259, SHORT, [8 if deflate else 1])
    add(262, SHORT, [2 if c >= 3 else 1])
    offsets_tag_index = len(tags)
    add(273, LONG, [0] * n_strips)
    add(277, SHORT, [c])
    add(278, LONG, [rows_per_strip])
    add(279, LONG, [len(s) for s in strips])
    add(284, SHORT, [1])
    if c in (2, 4):
        add(338, SHORT, [2])  # ExtraSamples: unassociated alpha
    add(339, SHORT, [1] * c)  # SampleFormat: unsigned int

    data_start = header_len + len(extra)
    strip_offsets = []
    pos = data_start
    for s in strips:
        strip_offsets.append(pos)
        pos += len(s)
    if pos % 2:
        pos += 1
    ifd_offset = pos

    # Patch strip offsets.
    tag, typ, count, val = tags[offsets_tag_index]
    packed = b"".join(struct.pack("<I", o) for o in strip_offsets)
    if count == 1:
        tags[offsets_tag_index] = (tag, typ, count, packed)
    else:
        off = struct.unpack("<I", val)[0] - header_len
        extra[off:off + len(packed)] = packed

    out = bytearray(b"II*\0" + struct.pack("<I", ifd_offset))
    out += extra
    for s in strips:
        out += s
    if len(out) % 2:
        out.append(0)
    out += struct.pack("<H", len(tags))
    for tag, typ, count, val in sorted(tags, key=lambda t: t[0]):
        out += struct.pack("<HHI", tag, typ, count) + val
    out += struct.pack("<I", 0)
    return bytes(out)


def write_image16(path, img: np.ndarray, fmt: str, png_compress_level: int = 1) -> None:
    """Write a uint16 frame as PNG (`png`) or TIFF (`tif` / `tif_lzw`)."""
    if fmt == "png":
        payload = encode_png16(img, png_compress_level)
    elif fmt in ("tif", "tif_lzw"):
        payload = encode_tiff16(img, deflate=(fmt == "tif_lzw"))
    else:
        raise ValueError(f"16-bit output not supported for format {fmt!r}")
    Path(path).write_bytes(payload)
