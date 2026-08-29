"""Smoke and correctness tests. Run: python3 tests.py

Deliberately stdlib unittest and no network. Anything that needs NOAA belongs
in a manual check, not here -- a test suite that fails when a government
website is slow trains you to ignore it.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from tiderace import astro, bait, evaluate, gso, regs, score, spots

STALE_REC = regs.STALE_AFTER_DAYS
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


class GSO(unittest.TestCase):
    """Climatology maths, tested against a synthetic curve so the suite does
    not depend on the spreadsheets being downloaded."""

    def _fake(self):
        # A clean sinusoid: cold in Feb, warm in Aug, like the real bay.
        import math
        weeks = {}
        for w in range(1, 53):
            t = 54 - 20 * math.cos(2 * math.pi * (w - 6) / 52)
            weeks[str(w)] = {"surface_f": round(t, 2), "bottom_f": round(t - 1, 2),
                             "p10_f": round(t - 4, 2), "p90_f": round(t + 4, 2),
                             "sd_f": 2.0, "n": 60}
        return {"stations": {"fox_island": {"weeks": weeks, "observations": 3000,
                                            "years": [1959, 2024]}}}

    def test_excel_serial_dates(self):
        """Anchored on well-known serials in Excel's 1900 date system, which
        offsets from 1899-12-30 because of its phantom 1900 leap day."""
        self.assertEqual(gso._excel_date("45292"), date(2024, 1, 1))
        self.assertEqual(gso._excel_date("25569"), date(1970, 1, 1))   # unix epoch
        self.assertEqual(gso._excel_date("21571"), date(1959, 1, 21))  # first GSO row
        self.assertIsNone(gso._excel_date("not-a-date"))

    def test_celsius_conversion(self):
        self.assertAlmostEqual(gso.c_to_f(0), 32.0)
        self.assertAlmostEqual(gso.c_to_f(100), 212.0)

    def test_no_day_estimate_on_a_flat_curve(self):
        """Regression: a 3F August anomaly reported '35 days', which was purely
        the clamp -- the summer plateau has no meaningful slope to divide by."""
        d = self._fake()
        peak_week = max(d["stations"]["fox_island"]["weeks"].items(),
                        key=lambda kv: kv[1]["surface_f"])[0]
        when = date(2026, 1, 1) + timedelta(days=(int(peak_week) - 1) * 7)
        a = gso.anomaly(d["stations"]["fox_island"]["weeks"][peak_week]["surface_f"] + 3,
                        when, "fox_island", d)
        self.assertIsNone(a["season_shift_days"])

    def test_shift_direction_matches_phase(self):
        d = self._fake()
        spring = gso.anomaly(60, date(2026, 5, 10), "fox_island", d)
        autumn = gso.anomaly(60, date(2026, 10, 20), "fox_island", d)
        self.assertEqual(spring["phase"], "warming")
        self.assertEqual(autumn["phase"], "cooling")
        # Warm water in spring is ahead of schedule; in autumn it is behind.
        if spring["delta_f"] > 0:
            self.assertGreater(spring["season_shift_days"], 0)
        if autumn["delta_f"] > 0:
            self.assertLess(autumn["season_shift_days"], 0)

    def test_shift_is_bounded(self):
        d = self._fake()
        a = gso.anomaly(200, date(2026, 5, 10), "fox_island", d)
        self.assertLessEqual(abs(a["season_shift_days"]), 21)

    def test_thermal_presence_replaces_guessed_months(self):
        """Tautog should come out bimodal -- spring and autumn, not summer."""
        curve = gso.thermal_season("tautog", "fox_island", self._fake())
        if not curve:
            self.skipTest("no climatology")
        summer = [v for w, v in curve.items() if 27 <= w <= 35]
        shoulder = [v for w, v in curve.items() if w in (17, 18, 19, 43, 44, 45)]
        self.assertLess(max(summer), 0.2)
        self.assertGreater(max(shoulder), 0.8)

    def test_season_term_degrades_without_climatology(self):
        p = score.PROFILES["striped_bass"]
        self.assertGreater(score._season_term(p, 6), 0)      # in season
        self.assertEqual(score._season_term(p, 1), 0.0)      # out of season

    def test_season_term_uses_thermal_when_given(self):
        p = score.PROFILES["tautog"]
        cold = score._season_term(p, 11, week=45, thermal={45: 1.0, 46: 1.0})
        warm = score._season_term(p, 11, week=45, thermal={45: 0.0, 46: 0.0})
        self.assertGreater(cold, warm)


class Commercial(unittest.TestCase):
    FRI = date(2026, 8, 28)      # a Friday

    def test_commercial_differs_where_it_matters(self):
        """Commercial minimums are smaller for some species and LARGER for
        others. Showing the wrong column is the whole risk of this feature."""
        self.assertEqual(regs.status("fluke", self.FRI, "commercial")["min_inches"], 14)
        self.assertEqual(regs.status("fluke", self.FRI)["min_inches"], 19)
        self.assertEqual(regs.status("striped_bass", self.FRI, "commercial")["min_inches"], 34)
        self.assertEqual(regs.status("striped_bass", self.FRI)["slot"], (28, 31))

    def test_quota_closure_beats_the_calendar(self):
        st = regs.status("striped_bass", self.FRI, "commercial")
        self.assertFalse(st["open"])
        self.assertIn("quota", st["season"])

    def test_closed_weekdays_are_honoured(self):
        r = regs.COMMERCIAL["tautog"]
        weekend = regs.CommercialRule("x", 16.0, (((1, 1), (12, 31)),),
                                      closed_weekdays=(4, 5, 6, 0))
        self.assertFalse(weekend.is_open(date(2026, 8, 28)))   # Friday
        self.assertTrue(weekend.is_open(date(2026, 8, 26)))    # Wednesday
        self.assertTrue(r.is_open(date(2026, 8, 28)))          # tautog: no closed days

    def test_sub_periods(self):
        r = regs.COMMERCIAL["tautog"]
        self.assertTrue(r.is_open(date(2026, 4, 15)))
        self.assertFalse(r.is_open(date(2026, 6, 15)))   # between sub-periods
        self.assertTrue(r.is_open(date(2026, 8, 10)))
        self.assertFalse(r.is_open(date(2026, 10, 1)))   # gap before 10/15
        self.assertTrue(r.is_open(date(2026, 11, 1)))

    def test_commercial_is_always_advisory(self):
        """Recreational regs go stale in months; commercial in days."""
        st = regs.status("scup", self.FRI, "commercial")
        self.assertTrue(st["advisory"])
        self.assertIn("401", st["hotline"])
        self.assertLess(regs.COMMERCIAL_STALE_AFTER_DAYS, STALE_REC)

    def test_differences_reports_both_axes(self):
        diffs = regs.differences("striped_bass", self.FRI)
        self.assertTrue(any("size" in d for d in diffs))
        self.assertTrue(any("open" in d for d in diffs))

    def test_mode_defaults_to_recreational(self):
        self.assertEqual(regs.status("scup", self.FRI)["mode"], "recreational")
        self.assertEqual(regs.status("scup", self.FRI, "commercial")["mode"], "commercial")

    def test_every_species_has_both_regimes(self):
        for sp in score.PROFILES:
            self.assertIn(sp, regs.RULES, f"{sp} missing recreational rule")
            self.assertIn(sp, regs.COMMERCIAL, f"{sp} missing commercial rule")


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
