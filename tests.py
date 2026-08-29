"""Smoke and correctness tests. Run: python3 tests.py

Deliberately stdlib unittest and no network. Anything that needs NOAA belongs
in a manual check, not here -- a test suite that fails when a government
website is slow trains you to ignore it.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from tiderace import astro, bait, evaluate, regs, score, spots
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


class Bait(unittest.TestCase):
    NOW = datetime(2026, 8, 28, 20, 0)

    def _one(self, what, days=0, nm=0.0, abundance="loaded", conf="high"):
        return [{"bait": what, "lat": 41.44 + nm / 60.0, "lon": -71.42,
                 "when": (self.NOW - timedelta(days=days)).isoformat(),
                 "abundance": abundance, "confidence": conf}]

    def _sig(self, rows, species="striped_bass"):
        return bait.bait_at(41.44, -71.42, self.NOW, species, rows)["signal"]

    def test_decay_actually_decays(self):
        """Regression: signal was a weighted mean, so the decay weight cancelled
        in the ratio and a fortnight-old rumour scored like a fresh sighting."""
        fresh = self._sig(self._one("bunker", days=0))
        half = self._sig(self._one("bunker", days=bait.HALF_LIFE_DAYS))
        old = self._sig(self._one("bunker", days=16))
        self.assertAlmostEqual(half, fresh / 2, places=1)
        self.assertLess(old, 0.15)
        self.assertGreater(fresh, half)

    def test_distance_decays(self):
        near = self._sig(self._one("bunker", nm=0))
        far = self._sig(self._one("bunker", nm=2))
        self.assertGreater(near, far)
        self.assertEqual(self._sig(self._one("bunker", nm=10)), 0.0)

    def test_relevance_scales_magnitude_not_just_weight(self):
        """Bunker is everything to a bass and nothing to a tautog."""
        self.assertGreater(self._sig(self._one("bunker"), "striped_bass"), 0.9)
        self.assertEqual(self._sig(self._one("bunker"), "tautog"), 0.0)
        self.assertGreater(self._sig(self._one("crabs"), "tautog"), 0.9)

    def test_absence_is_negative_but_ignorance_is_neutral(self):
        seen_nothing = self._sig(self._one("bunker", abundance="none"))
        self.assertLess(seen_nothing, -0.3)
        self.assertEqual(self._sig([]), 0.0)          # nobody looked
        self.assertEqual(bait.modifier(0.0), 1.0)

    def test_modifier_bounds(self):
        self.assertAlmostEqual(bait.modifier(1.0), 1.35)
        self.assertAlmostEqual(bait.modifier(-1.0), 0.75)
        for sig in (-1, -0.5, 0, 0.5, 1):
            self.assertTrue(0.7 <= bait.modifier(sig) <= 1.4)

    def test_abundance_is_monotonic(self):
        vals = [self._sig(self._one("bunker", abundance=a))
                for a in ("trace", "scattered", "decent", "loaded")]
        self.assertEqual(vals, sorted(vals))

    def test_future_sightings_ignored(self):
        future = [{"bait": "bunker", "lat": 41.44, "lon": -71.42,
                   "when": (self.NOW + timedelta(days=3)).isoformat(),
                   "abundance": "loaded", "confidence": "high"}]
        self.assertEqual(self._sig(future), 0.0)

    def test_bait_reaches_the_scorer(self):
        base = score.score("striped_bass", {
            "month": 9, "water_temp_f": 62, "current_speed": 1.4,
            "light_phase": "golden", "wind_kt": 8, "pressure_trend_3h": -1,
            "spring_strength": .7})
        fed = score.score("striped_bass", {
            "month": 9, "water_temp_f": 62, "current_speed": 1.4,
            "light_phase": "golden", "wind_kt": 8, "pressure_trend_3h": -1,
            "spring_strength": .7, "bait_signal": 1.0})
        self.assertGreater(fed["score"], base["score"])
        self.assertIn("bait", fed["modifiers"])


class Privacy(unittest.TestCase):
    def test_weather_coordinates_are_coarsened(self):
        """Your marks must not reach a third party at 11 m precision."""
        from tiderace.sources import _coarse
        lat, lon = _coarse(41.512345, -71.345678)
        self.assertEqual((lat, lon), (41.51, -71.35))

    def test_public_set_excludes_private_marks(self):
        pub = spots.public_only()
        self.assertTrue(all(not s.private for s in pub))
        self.assertEqual(len(pub), len([s for s in spots.SPOTS if not s.private]))


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
