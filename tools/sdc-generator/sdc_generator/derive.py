"""Deterministic derivation rules from SPEC-0004 section 4.4.

No function here reads a clock, host name, user name, working directory, or a
language-runtime global PRNG. Every value is a pure function of the seed, a
purpose string, and a stable key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import TypeVar

from .errors import SCHEMA_INVALID, SdcError

DOMAIN = b"SDC1\0"
_U64_MAX = (1 << 64) - 1

T = TypeVar("T")


def _check_ascii(value: str, what: str, file: str | None = None) -> None:
    if not value:
        raise SdcError(SCHEMA_INVALID, f"{what} must be nonempty", file=file)
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SdcError(
            SCHEMA_INVALID, f"{what} must be ASCII: {value!r}", file=file
        ) from exc
    if "\x00" in value:
        raise SdcError(
            SCHEMA_INVALID, f"{what} must not contain NUL", file=file
        )


def digest(
    seed: str,
    purpose: str,
    stable_key: str,
    counter: int | None = None,
) -> bytes:
    """Return the 32-byte derivation digest ``D`` for a stable key."""

    _check_ascii(seed, "seed")
    _check_ascii(purpose, "purpose")
    _check_ascii(stable_key, "stable_key")
    payload = DOMAIN + seed.encode("ascii") + b"\0" + purpose.encode("ascii")
    payload += b"\0" + stable_key.encode("ascii")
    if counter is not None:
        if counter < 0:
            raise ValueError("counter must be non-negative")
        payload += b"\0" + str(counter).encode("ascii")
    return hashlib.sha256(payload).digest()


def digest_hex(
    seed: str,
    purpose: str,
    stable_key: str,
    counter: int | None = None,
) -> str:
    return digest(seed, purpose, stable_key, counter).hex()


def unit_float(seed: str, purpose: str, stable_key: str) -> float:
    """Return ``u`` in ``[0, 1)`` derived from the first eight digest bytes."""

    value = int.from_bytes(digest(seed, purpose, stable_key)[:8], "big")
    return value / (1 << 64)


def uniform_int(
    seed: str, purpose: str, stable_key: str, lo: int, hi: int
) -> int:
    """Return an inclusive integer in ``[lo, hi]`` per section 4.4."""

    if lo > hi:
        raise ValueError(f"empty range [{lo}, {hi}]")
    value = int.from_bytes(digest(seed, purpose, stable_key)[:8], "big")
    return lo + (value * (hi - lo + 1) >> 64)


def ordered(
    items: Iterable[T],
    seed: str,
    purpose: str,
    key=lambda item: str(item),
) -> list[T]:
    """Sort items by the full digest, breaking digest ties by stable key."""

    keyed = [(digest(seed, purpose, key(item)), key(item), item) for item in items]
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in keyed]


def choose(
    items: Sequence[T],
    seed: str,
    purpose: str,
    stable_key: str,
) -> T:
    if not items:
        raise ValueError("cannot choose from an empty sequence")
    index = uniform_int(seed, purpose, stable_key, 0, len(items) - 1)
    return items[index]


def shuffled(
    items: Sequence[T],
    seed: str,
    purpose: str,
    key=lambda item: str(item),
) -> list[T]:
    return ordered(items, seed, purpose, key)


def stream_bytes(
    seed: str,
    purpose: str,
    stable_key: str,
    length: int,
    *,
    counter_start: int = 0,
) -> bytes:
    """Return ``length`` deterministic bytes from the multi-block stream."""

    if length < 0:
        raise ValueError("length must be non-negative")
    out = bytearray()
    counter = counter_start
    while len(out) < length:
        out.extend(digest(seed, purpose, stable_key, counter))
        counter += 1
    return bytes(out[:length])


def stream_u64(seed: str, purpose: str, stable_key: str, index: int) -> int:
    """Return the ``index``-th 64-bit word of the multi-block stream."""

    block = index // 4
    offset = (index % 4) * 8
    data = digest(seed, purpose, stable_key, block)
    return int.from_bytes(data[offset : offset + 8], "big")


class XorShift64:
    """A small deterministic stream for pixel-level expansion.

    The state is derived from a SHA-256 digest, so the stream stays independent
    of iteration order and of the host's global PRNG.
    """

    __slots__ = ("_state",)

    def __init__(self, seed_word: int) -> None:
        self._state = seed_word & _U64_MAX or 0x9E3779B97F4A7C15

    def next_u64(self) -> int:
        x = self._state
        x ^= (x << 13) & _U64_MAX
        x ^= x >> 7
        x ^= (x << 17) & _U64_MAX
        self._state = x
        return x

    def next_u32(self) -> int:
        return self.next_u64() >> 32

    def random_below(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError("bound must be positive")
        # Rejection sampling keeps the distribution unbiased and deterministic.
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound


def iso_utc(value: datetime) -> str:
    """Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""

    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(text: str, *, file: str | None = None, field: str | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SdcError(
            SCHEMA_INVALID,
            f"invalid UTC timestamp: {text!r}",
            file=file,
            field=field,
        ) from exc
    if parsed.tzinfo is None:
        raise SdcError(
            SCHEMA_INVALID,
            f"timestamp must carry a UTC offset: {text!r}",
            file=file,
            field=field,
        )
    return parsed.astimezone(UTC)


def timestamp_between(
    seed: str,
    purpose: str,
    stable_key: str,
    start: datetime,
    end: datetime,
) -> str:
    if start > end:
        raise ValueError("start must not be after end")
    span = int((end - start).total_seconds())
    offset = uniform_int(seed, purpose, stable_key, 0, span)
    return iso_utc(start + _seconds(offset))


def _seconds(count: int):
    from datetime import timedelta

    return timedelta(seconds=count)


def uuid4_like(seed: str, stable_key: str) -> str:
    """Return a seeded RFC-4122-shaped UUID with version 4 and variant bits."""

    data = bytearray(digest(seed, "uuid", stable_key)[:16])
    data[6] = (data[6] & 0x0F) | 0x40
    data[8] = (data[8] & 0x3F) | 0x80
    text = data.hex()
    return (
        f"{text[0:8]}-{text[8:12]}-{text[12:16]}-"
        f"{text[16:20]}-{text[20:32]}"
    )


def slugify(text: str, *, max_length: int = 60) -> str:
    """Return a stable ASCII slug used only inside identifiers, never paths."""

    out: list[str] = []
    last_dash = False
    for char in text.lower():
        if char.isascii() and char.isalnum():
            out.append(char)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    slug = "".join(out).strip("-")
    return slug[:max_length].strip("-") or "item"
