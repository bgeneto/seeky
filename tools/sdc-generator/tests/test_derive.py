"""Derivation and profile validation tests (SPEC-0004-R3, R5)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from support import PROFILES_DIR, TESTMINI_PROFILE, temporary_directory

from sdc_generator import derive
from sdc_generator.errors import SCHEMA_INVALID, SdcError
from sdc_generator.profiles import load_profile


class DerivationTests(unittest.TestCase):
    def test_digest_is_stable_and_keyed(self) -> None:
        first = derive.digest("seed-a", "purpose", "key-1")
        second = derive.digest("seed-a", "purpose", "key-1")
        third = derive.digest("seed-a", "purpose", "key-2")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(len(first), 32)

    def test_uniform_int_is_inclusive_and_deterministic(self) -> None:
        values = {
            derive.uniform_int("seed", "purpose", f"key-{index}", 3, 9)
            for index in range(500)
        }
        self.assertEqual(values, set(range(3, 10)))
        self.assertEqual(
            derive.uniform_int("seed", "purpose", "key", 0, 0), 0
        )

    def test_ordered_is_independent_of_input_order(self) -> None:
        left = derive.ordered(["a", "b", "c", "d"], "seed", "order")
        right = derive.ordered(["d", "b", "a", "c"], "seed", "order")
        self.assertEqual(left, right)

    def test_uuid_is_version_4_shaped(self) -> None:
        value = derive.uuid4_like("seed", "doc")
        self.assertRegex(
            value,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        self.assertEqual(value, derive.uuid4_like("seed", "doc"))

    def test_timestamp_stays_inside_the_profile_clock(self) -> None:
        start = derive.parse_iso_utc("2018-01-01T00:00:00Z")
        end = derive.parse_iso_utc("2025-12-31T23:59:59Z")
        for index in range(50):
            value = derive.timestamp_between(
                "seed", "modified-at", f"doc-{index}", start, end
            )
            parsed = derive.parse_iso_utc(value)
            self.assertGreaterEqual(parsed, start)
            self.assertLessEqual(parsed, end)
            self.assertTrue(value.endswith("Z"))

    def test_xor_shift_stream_is_deterministic(self) -> None:
        first = derive.XorShift64(derive.stream_u64("s", "p", "k", 0))
        second = derive.XorShift64(derive.stream_u64("s", "p", "k", 0))
        self.assertEqual(
            [first.next_u64() for _ in range(10)],
            [second.next_u64() for _ in range(10)],
        )

    def test_non_ascii_seed_is_rejected(self) -> None:
        with self.assertRaises(SdcError):
            derive.digest("sé", "purpose", "key")


class ProfileValidationTests(unittest.TestCase):
    def _load_mutated(self, mutate) -> None:
        data = json.loads(TESTMINI_PROFILE.read_text(encoding="utf-8"))
        mutate(data)
        with temporary_directory() as directory:
            path = directory / "testmini.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SdcError) as caught:
                load_profile(path)
            self.assertEqual(caught.exception.code, SCHEMA_INVALID)

    def test_unknown_field_is_rejected(self) -> None:
        self._load_mutated(lambda data: data.__setitem__("seed", "x"))

    def test_missing_field_is_rejected(self) -> None:
        self._load_mutated(lambda data: data.pop("renderers"))

    def test_unknown_schema_version_is_rejected(self) -> None:
        self._load_mutated(lambda data: data.__setitem__("schema_version", 2))

    def test_missing_renderer_is_rejected(self) -> None:
        self._load_mutated(lambda data: data["renderers"].remove("epub"))

    def test_bad_injection_key_is_rejected(self) -> None:
        self._load_mutated(lambda data: data["injection"].__setitem__("extra_copies", 1))

    def test_negative_injection_count_is_rejected(self) -> None:
        self._load_mutated(
            lambda data: data["injection"].__setitem__("exact_byte_copies", -1)
        )

    def test_too_many_injections_leave_no_base_documents(self) -> None:
        self._load_mutated(
            lambda data: data["injection"].__setitem__("exact_byte_copies", 40)
        )

    def test_smoke_profile_cap_and_seed(self) -> None:
        profile = load_profile(PROFILES_DIR / "sdc-smoke.json")
        self.assertEqual(profile.max_committed_bytes, 67_108_864)
        self.assertEqual(profile.default_seed, "sdc-smoke-v1")
        self.assertEqual(profile.injection["version_groups"], 8)
        self.assertIsNone(profile.extends)


if __name__ == "__main__":
    unittest.main()
