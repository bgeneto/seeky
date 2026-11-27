"""Deterministic derivation identical to the SDC generator (SPEC-0004 4.4).

The drafter must reproduce the generator's digest exactly so that query IDs
receive the split the generator's ``judgments validate`` recomputes. Copying
ten lines is preferable to importing another tool's package.
"""

from __future__ import annotations

import hashlib

DOMAIN = b"SDC1\0"


def digest(seed: str, purpose: str, stable_key: str, counter: int | None = None) -> bytes:
    payload = DOMAIN + seed.encode("ascii") + b"\0" + purpose.encode("ascii")
    payload += b"\0" + stable_key.encode("utf-8")
    if counter is not None:
        payload += b"\0" + str(counter).encode("ascii")
    return hashlib.sha256(payload).digest()


def digest_hex(seed: str, purpose: str, stable_key: str, counter: int | None = None) -> str:
    return digest(seed, purpose, stable_key, counter).hex()


def unit_float(seed: str, purpose: str, stable_key: str) -> float:
    return int.from_bytes(digest(seed, purpose, stable_key)[:8], "big") / (1 << 64)


def uniform_int(seed: str, purpose: str, stable_key: str, lo: int, hi: int) -> int:
    if lo > hi:
        raise ValueError(f"empty range [{lo}, {hi}]")
    value = int.from_bytes(digest(seed, purpose, stable_key)[:8], "big")
    return lo + (value * (hi - lo + 1) >> 64)


def ordered(items, seed: str, purpose: str, key=lambda item: str(item)) -> list:
    keyed = [(digest(seed, purpose, key(item)), key(item), item) for item in items]
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in keyed]
