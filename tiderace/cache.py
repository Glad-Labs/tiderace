"""Atomic cache writes. No internal dependencies, so anything may import it.

Every cached file in this project was written straight to its final path:

    with open(path, "w") as fh:
        json.dump(data, fh)

which is fine until two processes are running, and on this project two
processes are the normal case -- `tiderace serve` is up on the tailnet while
you also run a command in a terminal. A reader that opens the file between the
truncate and the last flush gets a prefix of the JSON and raises
`JSONDecodeError` at whatever byte the writer had reached.

That is exactly what happened: the map's own /api/grid returned a 500 with
"Expecting ':' delimiter: line 1 column 8194", an 8 KB boundary, while an
iNaturalist cache file was mid-write in another process. Nothing was wrong
with the grid. The file was simply half there, and by the time anyone looked
it was whole again -- which is the worst kind of bug, because it does not
reproduce and it blames the wrong component.

`os.replace` is atomic on POSIX and on Windows, so writing to a temporary file
in the same directory and renaming it over the target means a reader sees
either the old complete file or the new complete file, never a prefix of
either. Same directory matters: a rename across filesystems is not atomic.
"""

from __future__ import annotations

import json
import os
import tempfile


def write_json(path: str, obj) -> None:
    """Write JSON so no reader can ever observe a partial file."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, default=str)
        os.replace(tmp, path)
    except BaseException:
        # Leaving a .tmp- file behind would be litter that the next read might
        # try to parse if a glob ever picks it up.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_bytes(path: str, data: bytes) -> None:
    """Same guarantee for non-JSON payloads (GeoJSON blobs, fetched pages)."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default=None):
    """Read a cache file, treating a corrupt one as absent.

    A cache is by definition reconstructible, so a damaged file left over from
    before atomic writes should cost one refetch, not an exception on a boat.
    """
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default
