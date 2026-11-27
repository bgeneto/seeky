"""The drafter must reproduce the generator's SPEC-0004 4.4 derivation."""

import unittest

from qrels_drafter.digest import digest_hex, uniform_int, unit_float


class DigestCompatibility(unittest.TestCase):
    def test_matches_generator_vectors(self):
        # Values produced by sdc_generator.derive; a drift would reassign splits.
        self.assertEqual(
            digest_hex("sdc-v1-split-v1", "query-split-order", "q-sdc-v1-000001"),
            "f1e2529efcc21c65704a33db8ef6b85512a8a724963e9cc8a2d8b9b24d70e582",
        )
        self.assertEqual(
            digest_hex("seed", "purpose", "key"),
            "94f4a768d38d631aef40f0191c34a0a66ada1d671d2c466df4afe8aa449b24a0",
        )
        self.assertAlmostEqual(unit_float("seed", "purpose", "key"), 0.5818581229137201)
        self.assertEqual(uniform_int("seed", "purpose", "key", 0, 99), 58)


if __name__ == "__main__":
    unittest.main()
