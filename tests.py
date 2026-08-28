"""Smoke and correctness tests. Run: python3 tests.py

Deliberately stdlib unittest and no network. Anything that needs NOAA belongs
in a manual check, not here -- a test suite that fails when a government
website is slow trains you to ignore it.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime

from tiderace import astro, evaluate, regs, score, spots
from tiderace.features import _local_tz, _wind_against_tide
from tiderace.sources import current_at


class Astro(unittest.TestCase):
    def test_dst_boundaries(self):
        """The old code hardcoded 'March-November is UTC-4' and was wrong for
        all of early March and late November."""
        for d, expect in [(datetime(2026, 3, 1), -5), (datetime(2026, 3, 15), -4),
                          (datetime(2026, 7, 4), -4), (datetime(2026, 11, 15), -5)]:
            off = d.replace(tzinfo=_local_tz(d)).utcoffset().total_seconds() / 3600
            self.assertEqual(off, expect, f"{d:%d %b}")

    def test_sun_is_up_at_noon_down_at_midnight(self):
        tz = _local_tz(datetime(2026, 7, 1))
        noon = datetime(2026, 7, 1, 12, tzinfo=tz)
        midnight = datetime(2026, 7, 1, 0, tzinfo=tz)
        self.assertGreater(astro.solar_elevation(noon, 41.5, -71.33), 60)
        self.assertLess(astro.solar_elevation(midnight, 41.5, -71.33), -20)

    def test_full_moon_2026_08_28(self):
        """Verified against published lunar tables (Sturgeon Moon)."""
        tz = _local_tz(datetime(2026, 8, 28))
        _, illum = astro.moon_phase(datetime(2026, 8, 28, 12, tzinfo=tz))
        self.assertGreater(illum, 0.97)

    def test_spring_neap_bounded(self):
        for day in range(0, 30):
            v = astro.spring_tide_strength(day)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


class Curves(unittest.TestCase):
    def test_trapezoid_edges(self):
        self.assertEqual(score.trapezoid(0, 1, 2, 3, 4), 0.0)
        self.assertEqual(score.trapezoid(2.5, 1, 2, 3, 4), 1.0)
        self.assertEqual(score.trapezoid(5, 1, 2, 3, 4), 0.0)
        self.assertAlmostEqual(score.trapezoid(1.5, 1, 2, 3, 4), 0.5)

    def test_peaked_prefers_the_optimum(self):
        """The bug this replaced: a flat-topped trapezoid scored 0.6 kt and
        1.4 kt identically, so every spot tied."""
        opt = score.peaked(1.4, 1.4, 0.62, 1.15, 4.0)
        off = score.peaked(0.6, 1.4, 0.62, 1.15, 4.0)
        self.assertGreater(opt, off)
        self.assertEqual(score.peaked(4.5, 1.4, 0.62, 1.15, 4.0), 0.0)

    def test_scores_stay_in_range(self):
        for sp in score.PROFILES:
            for speed in (0, 0.5, 1.4, 3.0, 6.0):
                for light in ("day", "night", "golden", "twilight"):
                    r = score.score(sp, {
                        "month": 9, "water_temp_f": 62, "current_speed": speed,
                        "light_phase": light, "wind_kt": 10,
                        "pressure_trend_3h": -1, "spring_strength": 0.7})
                    self.assertGreaterEqual(r["score"], 0.0)
                    self.assertLessEqual(r["score"], 100.0)


class Currents(unittest.TestCase):
    def test_interpolation_is_sinusoidal_not_linear(self):
        ev = [{"time": datetime(2026, 8, 28, 0, 0), "velocity": 0.0, "type": "slack",
               "flood_dir": 10, "ebb_dir": 190},
              {"time": datetime(2026, 8, 28, 3, 0), "velocity": 2.0, "type": "flood",
               "flood_dir": 10, "ebb_dir": 190}]
        mid = current_at(ev, datetime(2026, 8, 28, 1, 30))
        self.assertAlmostEqual(mid["velocity"], 1.0, places=6)
        quarter = current_at(ev, datetime(2026, 8, 28, 0, 45))
        # Linear would give 0.5; a quarter-sine gives clearly less.
        self.assertLess(quarter["velocity"], 0.4)

    def test_wind_against_tide(self):
        # Ebb running 190 (south); wind FROM the south blows toward 0 -> opposed.
        self.assertTrue(_wind_against_tide("S", 190, 1.0))
        self.assertFalse(_wind_against_tide("N", 190, 1.0))
        self.assertFalse(_wind_against_tide("S", 190, 0.1))   # too slack to matter


class Regulations(unittest.TestCase):
    def test_tautog_summer_closure(self):
        self.assertFalse(regs.RULES["tautog"].is_open(date(2026, 6, 15)))
        self.assertFalse(regs.RULES["tautog"].is_open(date(2026, 7, 31)))
        self.assertTrue(regs.RULES["tautog"].is_open(date(2026, 8, 1)))
        self.assertTrue(regs.RULES["tautog"].is_open(date(2026, 4, 15)))

    def test_every_scored_species_has_a_rule(self):
        for sp in score.PROFILES:
            self.assertIn(sp, regs.RULES, f"{sp} can be scored but has no regulation")

    def test_striped_bass_slot_is_surfaced(self):
        self.assertEqual(regs.status("striped_bass")["slot"], (28, 31))
        self.assertIn('slot 28–31"', regs.summary_line("striped_bass"))


class Spots(unittest.TestCase):
    def test_every_spot_species_is_modelled(self):
        for s in spots.SPOTS:
            for sp in s.species:
                self.assertIn(sp, score.PROFILES, f"{s.key} lists unmodelled {sp}")

    def test_priors_bounded_and_keys_unique(self):
        self.assertEqual(len(spots.BY_KEY), len(spots.SPOTS), "duplicate spot key")
        for s in spots.SPOTS:
            for sp, v in s.quality.items():
                self.assertTrue(0.0 <= v <= 1.0, f"{s.key}/{sp} prior out of range")
                self.assertIn(sp, s.species, f"{s.key} rates {sp} it does not list")


class Evaluation(unittest.TestCase):
    def _rows(self, n, kind):
        import random
        rng = random.Random(7)
        out = []
        for _ in range(n):
            spd = rng.uniform(0, 2.5)
            light = rng.choice(["day", "golden", "night", "twilight"])
            c = spd * 3 + (4 if light in ("golden", "night") else 0)
            if kind == "noise":
                c = rng.uniform(0, 10)
            out.append({"species": "striped_bass", "count": max(0, int(c)),
                        "conditions": {"current_speed": spd, "light_phase": light,
                                       "month": 9, "water_temp_f": 62, "wind_kt": 8,
                                       "spring_strength": .6, "pressure_trend_3h": -.5,
                                       "exposed": False}})
        return out

    def test_detects_signal_and_absence_of_it(self):
        sig = evaluate.evaluate(self._rows(120, "signal"))
        self.assertGreater(sig["baseline_rho"], 0.4)
        noise = evaluate.evaluate(self._rows(120, "noise"))
        self.assertLess(abs(noise["baseline_rho"]), 0.2)

    def test_refuses_to_conclude_on_thin_data(self):
        r = evaluate.evaluate(self._rows(5, "signal"))
        self.assertFalse(r["ready"])
        self.assertIn("need about", r["verdict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
