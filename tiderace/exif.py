"""EXIF out of a photo, with the standard library and nothing else.

A phone photo of a fish already knows two of the three things a log entry
needs: where it was taken and when. Those are recorded by the camera at the
moment of the catch, which is exactly when nobody wants to fill in a form.

**This is what social media strips and your own camera roll does not.**
Facebook and Instagram re-encode every upload and drop the GPS block, so a
photo pulled off a feed carries nothing. The same photo, straight off the
phone, carries a coordinate good to a few metres and a timestamp good to the
second. That difference is the whole reason the retroactive-logging path
works at all.

Two deliberate limits:

  * **JPEG is parsed; everything else is scanned.** A JPEG is a walkable
    sequence of segments, so the Exif APP1 block is found properly. HEIC --
    which is what an iPhone shoots by default -- is ISO base media format,
    and writing a box parser for it is a lot of code for one tag. So for
    anything that is not a JPEG this scans the first few megabytes for an
    embedded TIFF header. That is a heuristic, not a parser, and it is
    labelled as such in the result so a caller can tell the difference.

  * **No orientation, no thumbnails, no maker notes.** Only the four things a
    trip needs: latitude, longitude, when, and which of those were actually
    present.
"""

from __future__ import annotations

import os
import struct
from datetime import datetime

# IFD0
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_DATETIME = 0x0132
# Exif IFD
TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011
# GPS IFD
TAG_LAT_REF, TAG_LAT = 0x0001, 0x0002
TAG_LON_REF, TAG_LON = 0x0003, 0x0004

# bytes per TIFF component type, indexed by type id
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
             11: 4, 12: 8}

SCAN_LIMIT = 4 * 1024 * 1024      # how far into a non-JPEG to look for a TIFF
MAX_READ = 32 * 1024 * 1024       # refuse to slurp a video by accident


class NoExif(ValueError):
    """The file parsed, and simply has no EXIF worth reading."""


def _tiff_block(data: bytes) -> tuple[bytes, bool] | None:
    """Locate the TIFF header inside a file. Returns (block, parsed_properly).

    For a JPEG this walks the segment table. For anything else it scans, and
    says so, because a scan can in principle land on bytes that merely look
    like a TIFF header.
    """
    if data[:2] == b"\xff\xd8":                       # JPEG
        i = 2
        n = len(data)
        while i + 4 <= n:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xD8, 0xD9):                # SOI / EOI carry no length
                i += 2
                continue
            if marker == 0xDA:                        # start of scan: pixels follow
                break
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if seg_len < 2:
                break
            payload = data[i + 4:i + 2 + seg_len]
            if marker == 0xE1 and payload[:6] == b"Exif\x00\x00":
                return payload[6:], True
            i += 2 + seg_len
        return None

    # HEIC, PNG with an eXIf chunk, TIFF itself, anything else.
    head = data[:SCAN_LIMIT]
    at = head.find(b"Exif\x00\x00")
    if at >= 0:
        return head[at + 6:], False
    for magic in (b"II\x2a\x00", b"MM\x00\x2a"):
        at = head.find(magic)
        if at >= 0:
            return head[at:], False
    return None


def _read_ifd(block: bytes, offset: int, endian: str) -> dict:
    """One IFD as {tag: (type, count, value_bytes_or_offset)}."""
    out: dict[int, tuple] = {}
    if offset + 2 > len(block):
        return out
    count = struct.unpack(endian + "H", block[offset:offset + 2])[0]
    # A corrupt offset can claim tens of thousands of entries; cap it rather
    # than walking off the end of a photo.
    for k in range(min(count, 512)):
        e = offset + 2 + k * 12
        if e + 12 > len(block):
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", block[e:e + 8])
        raw = block[e + 8:e + 12]
        size = TYPE_SIZE.get(typ, 0) * cnt
        if size > 4:
            (ptr,) = struct.unpack(endian + "I", raw)
            raw = block[ptr:ptr + size] if ptr + size <= len(block) else b""
        else:
            raw = raw[:size]
        out[tag] = (typ, cnt, raw)
    return out


def _ascii(entry) -> str | None:
    if not entry or entry[0] != 2:
        return None
    return entry[2].split(b"\x00")[0].decode("ascii", "replace").strip() or None


def _rationals(entry, endian: str) -> list[float]:
    if not entry or entry[0] not in (5, 10):
        return []
    out = []
    for i in range(entry[1]):
        chunk = entry[2][i * 8:(i + 1) * 8]
        if len(chunk) < 8:
            break
        num, den = struct.unpack(endian + ("ii" if entry[0] == 10 else "II"), chunk)
        out.append(num / den if den else 0.0)
    return out


def _dms(values: list[float], ref: str | None) -> float | None:
    """Degrees-minutes-seconds to a signed decimal degree."""
    if len(values) < 2:
        return None
    deg = values[0] + values[1] / 60 + (values[2] / 3600 if len(values) > 2 else 0)
    if ref and ref.upper() in ("S", "W"):
        deg = -deg
    return round(deg, 6)


def read(path: str) -> dict:
    """Coordinate and capture time from one photo.

    Returns a dict with `lat`, `lon`, `taken_at` (ISO, local as the camera
    recorded it) -- any of which may be None -- plus `has_gps`, `has_time`,
    and `exact`, which is False when the EXIF block was found by scanning
    rather than by parsing the container.
    """
    size = os.path.getsize(path)
    if size > MAX_READ:
        raise NoExif(f"{os.path.basename(path)} is {size/1e6:.0f} MB — "
                     "that is a video, not a photo")
    with open(path, "rb") as fh:
        data = fh.read(MAX_READ)

    found = _tiff_block(data)
    if not found:
        raise NoExif(f"no EXIF block in {os.path.basename(path)}")
    block, exact = found

    if block[:2] == b"II":
        endian = "<"
    elif block[:2] == b"MM":
        endian = ">"
    else:
        raise NoExif("EXIF block has no readable byte order")
    if len(block) < 8:
        raise NoExif("EXIF block truncated")
    (ifd0_at,) = struct.unpack(endian + "I", block[4:8])

    ifd0 = _read_ifd(block, ifd0_at, endian)

    taken_at = None
    tzoffset = None
    if TAG_EXIF_IFD in ifd0:
        (sub_at,) = struct.unpack(endian + "I", ifd0[TAG_EXIF_IFD][2][:4])
        sub = _read_ifd(block, sub_at, endian)
        taken_at = _ascii(sub.get(TAG_DATETIME_ORIGINAL))
        tzoffset = _ascii(sub.get(TAG_OFFSET_TIME_ORIGINAL))
    taken_at = taken_at or _ascii(ifd0.get(TAG_DATETIME))

    iso = None
    if taken_at:
        # EXIF writes "2026:08:30 05:41:12". Colons in the date, which is not
        # ISO and will not parse as it.
        try:
            iso = datetime.strptime(taken_at, "%Y:%m:%d %H:%M:%S").isoformat()
        except ValueError:
            iso = None

    lat = lon = None
    if TAG_GPS_IFD in ifd0:
        (gps_at,) = struct.unpack(endian + "I", ifd0[TAG_GPS_IFD][2][:4])
        gps = _read_ifd(block, gps_at, endian)
        lat = _dms(_rationals(gps.get(TAG_LAT), endian), _ascii(gps.get(TAG_LAT_REF)))
        lon = _dms(_rationals(gps.get(TAG_LON), endian), _ascii(gps.get(TAG_LON_REF)))
        # A camera with the GPS enabled but no fix writes 0/0 rather than
        # omitting the tags. Null Island is not a fishing spot.
        if lat == 0 and lon == 0:
            lat = lon = None

    return {
        "lat": lat, "lon": lon,
        "taken_at": iso,
        "taken_at_raw": taken_at,
        "tz_offset": tzoffset,
        "has_gps": lat is not None and lon is not None,
        "has_time": iso is not None,
        "exact": exact,
        "file": os.path.basename(path),
    }
