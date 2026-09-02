"""Smoke and correctness tests. Run: python3 tests.py

Deliberately stdlib unittest and no network. Anything that needs NOAA belongs
in a manual check, not here -- a test suite that fails when a government
website is slow trains you to ignore it.
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import date, datetime, timedelta

from tiderace import (astro, bait, birds, conditions, evaluate, extract, fetch, gso, hms,
                      provenance,
                      bathy, cache as cachemod, species as speciesmod, track, voicelog, llm, reconcile, reports, protected, survey, whales,
                      exif as exifmod, madmf, photolog,
                      regs, ridem, score, solunar, spots)

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

    def test_thermometers_are_in_the_same_water_as_the_spot(self):
        # Nearest-by-distance is the WRONG test here. Wickford and Quonset are
        # marginally closer to Newport, but they are shallow west-side spots
        # that warm with the upper bay, so Conimicut is the better proxy.
        # What matters is that the gauge sits in the same arm, because the arms
        # do not mix freely. Mount Hope Bay is its own arm: Conimicut is around
        # the corner in the Providence River and reads about a degree cooler.
        ARM = {
            "8452660": "east_passage_mouth",
            "8452944": "upper_bay",
            "8447386": "mount_hope",
            "8454000": "providence_river",
        }
        EXPECTED = {"mount_hope": "mount_hope"}
        for s in spots.SPOTS:
            want = EXPECTED.get(s.key)
            if want:
                self.assertEqual(
                    ARM.get(s.thermometer), want,
                    f"{s.key} reads a gauge in another arm of the bay")

    def test_temp_station_override_is_a_real_gauge(self):
        KNOWN = {"8452660", "8452944", "8447386", "8454000"}
        for s in spots.SPOTS:
            if s.temp_station:
                self.assertIn(s.temp_station, KNOWN,
                              f"{s.key} overrides to unknown gauge {s.temp_station}")


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


class WebFetching(unittest.TestCase):
    """Offline only -- no test here touches the network."""

    def test_html_to_text_drops_chrome_and_keeps_prose(self):
        markup = """<html><head><title>RI Report</title>
          <style>.x{color:red}</style><script>var a=1;</script></head>
          <body><nav>menu menu</nav>
          <p>Bunker are thick off Conimicut.</p>
          <div>Bass to 30 inches on the ebb.</div>
          <footer>copyright</footer></body></html>"""
        text = fetch.to_text(markup)
        self.assertIn("Bunker are thick off Conimicut.", text)
        self.assertIn("Bass to 30 inches", text)
        for junk in ("var a=1", "color:red", "menu menu", "copyright"):
            self.assertNotIn(junk, text)

    def test_title_extraction(self):
        self.assertEqual(fetch.title_of("<html><title>Fish &amp; Chips</title>"),
                         "Fish & Chips")
        self.assertEqual(fetch.title_of("<html><body>no title</body></html>"), "")

    def test_entities_and_whitespace_are_normalised(self):
        text = fetch.to_text("<p>Bass   &amp;   blues</p>\n\n\n<p>on   the ebb</p>")
        self.assertIn("Bass & blues", text)
        self.assertNotIn("   ", text)

    def test_every_source_declares_a_kind(self):
        for key, src in fetch.SOURCES.items():
            self.assertIn(src["kind"], ("regulation", "report"), key)
            self.assertTrue(src["url"].startswith("https://"), key)


class Extraction(unittest.TestCase):
    def test_place_matching_rejects_generic_geography(self):
        """Regression: matching on shared generic words put 'Newport Bridge'
        at the Mount Hope Bridge, and 'Block Island' -- twelve miles offshore --
        at Rose Island."""
        self.assertIsNone(extract._match_spot("Newport Bridge area"))
        self.assertIsNone(extract._match_spot("Block Island"))
        self.assertIsNone(extract._match_spot("the south shore"))
        self.assertIsNone(extract._match_spot(""))

    def test_place_matching_finds_real_spots(self):
        for text, want in [("Whale Rock", "whale_rock"),
                           ("the Mount Hope Bridge", "mount_hope"),
                           ("off Beavertail", "beavertail"),
                           ("Point Judith breachway", "pt_judith_breachway"),
                           ("Fort Wetherill", "fort_wetherill")]:
            got = extract._match_spot(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got.key, want, text)

    def test_schemas_are_strict_and_demand_provenance(self):
        """Every extracted claim must carry a quote and a confidence, so a
        human can check it without re-reading the page."""
        for schema in (extract.REG_SCHEMA, extract.REPORT_SCHEMA):
            self.assertFalse(schema["additionalProperties"])
            self.assertIn("injection_suspected", schema["properties"])
        for arr in ("changes",):
            item = extract.REG_SCHEMA["properties"][arr]["items"]
            self.assertIn("quote", item["required"])
            self.assertIn("confidence", item["required"])
        for arr in ("bait", "catches"):
            item = extract.REPORT_SCHEMA["properties"][arr]["items"]
            self.assertIn("quote", item["required"])
            self.assertIn("confidence", item["required"])

    def test_system_prompt_defends_against_injection(self):
        p = extract.SYSTEM.lower()
        self.assertIn("untrusted", p)
        self.assertIn("never an instruction", p)
        self.assertIn("do not comply", p)

    def test_bait_vocabulary_matches_the_bait_model(self):
        """The extractor must not emit bait types the scorer has never heard of.

        The vocabulary lives in the prompt, not a schema description, because
        Ollama compiles the schema to a grammar and never shows the model its
        descriptions."""
        for known in ("bunker", "sand eels", "squid", "crabs"):
            self.assertIn(known, extract.SYSTEM)
        described = extract.REPORT_SCHEMA["properties"]["bait"]["items"]["properties"]
        self.assertEqual(set(described["abundance"]["enum"]), set(bait.ABUNDANCE))
        for level in bait.ABUNDANCE:
            self.assertIn(f"{level} =", extract.SYSTEM)

    def test_review_queue_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "q.jsonl")
            extract._queue({"kind": "regulation", "status": "pending",
                            "species": "scup"}, path)
            extract._queue({"kind": "bait", "status": "applied",
                            "bait": "bunker"}, path)
            self.assertEqual(len(extract.load_queue(path)), 2)
            self.assertEqual(len(extract.pending(path=path)), 1)
            self.assertEqual(len(extract.pending("regulation", path)), 1)
            self.assertEqual(len(extract.pending("bait", path)), 0)

    def test_missing_backend_fails_loudly_not_silently(self):
        """A missing SDK or an unreachable Ollama must raise, never return
        an empty extraction that looks like 'nothing was reported'."""
        try:
            llm.Anthropic().complete("s", "u", {"type": "object"})
        except llm.BackendUnavailable as e:
            self.assertTrue(str(e))
        except Exception as e:                                    # noqa: BLE001
            self.fail(f"expected BackendUnavailable, got {type(e).__name__}: {e}")

        dead = llm.Ollama(host="http://127.0.0.1:1")
        with self.assertRaises(llm.BackendUnavailable):
            dead.complete("s", "u", {"type": "object"})
        self.assertFalse(dead.available())


class RidemParser(unittest.TestCase):
    """Deterministic, so it is fully testable without a model or a network."""

    NOTICE = ("Beginning 12:00AM on Sunday, August 30, 2026, the commercial "
              "possession limit for Black Sea Bass will be four hundred (400) "
              "pounds per day until further notice.")

    def test_parses_the_template(self):
        r = ridem.parse_notice(self.NOTICE)
        self.assertEqual(r["effective_date"], "2026-08-30")
        self.assertEqual(r["species_key"], "black_sea_bass")
        self.assertEqual(r["license_mode"], "commercial")
        self.assertEqual(r["change_type"], "possession_limit")
        self.assertEqual(r["amount"]["value"], 400)
        self.assertEqual(r["amount"]["unit"], "pounds")
        self.assertEqual(r["period"], "per day")
        self.assertTrue(r["until_further_notice"])

    def test_number_words_cross_check_the_digits(self):
        """RIDEM writes every quantity twice. Requiring the two to agree is a
        checksum no language model can offer."""
        r = ridem.parse_notice(self.NOTICE)
        self.assertTrue(r["amount"]["cross_checked"])
        self.assertTrue(r["amount"]["agrees"])
        self.assertEqual(r["amount"]["spelled"], 400)

    def test_mismatch_is_reported_never_resolved(self):
        bad = self.NOTICE.replace("(400)", "(300)")
        r = ridem.parse_notice(bad)
        self.assertFalse(r["amount"]["agrees"])
        page = ridem.parse_page(bad)
        self.assertTrue(any("check the source" in w for w in page["warnings"]))

    def test_word_number_parsing(self):
        for text, want in [("four hundred", 400), ("ten thousand", 10000),
                           ("twenty-five", 25), ("three", 3),
                           ("two thousand eight hundred", 2800)]:
            self.assertEqual(ridem.words_to_number(text), want, text)
        self.assertIsNone(ridem.words_to_number("Black Sea Bass will be"))

    def test_spelled_group_cannot_swallow_the_clause(self):
        """Regression: a generic letter run captured the whole sentence, which
        then failed to parse as a number and silently disabled every
        cross-check on the page."""
        a = ridem.parse_amount("limit for Black Sea Bass will be four hundred (400) pounds")
        self.assertEqual(a["spelled"], 400)
        self.assertTrue(a["agrees"])

    def test_closure_detected(self):
        r = ridem.parse_notice(
            "Beginning 12:00AM on Tuesday, June 23, 2026, the commercial fishery "
            "for Striped Bass will close until further notice.")
        self.assertEqual(r["change_type"], "season_close")
        self.assertEqual(r["species_key"], "striped_bass")

    def test_non_notices_are_ignored(self):
        self.assertIsNone(ridem.parse_notice("Fishing was good last week."))
        page = ridem.parse_page("Nothing here.\nOr here.")
        self.assertEqual(page["notices"], [])


class Reconcile(unittest.TestCase):
    TODAY = date(2026, 8, 28)

    CLOSED_UFN = ("Beginning 12:00AM on Tuesday, June 23, 2026, the GENERAL CATAGORY "
                  "commercial fishery for Striped Bass will close until further notice.")
    CLOSED_REOPENS = ("Beginning 12:00AM on Saturday, May 30, 2026, the commercial "
                      "Tautog fishery will close, until the next sub-period begins "
                      "on August 1, 2026 at ten (10) fish per day.")
    REOPEN_OR = ("Beginning 12:00AM on Monday, March 16, 2026, the commercial Scup "
                 "General Category fishery will close until further notice, or until "
                 "the fishery re-opens on May 1, 2026 at ten-thousand (10,000) pounds "
                 "per week.")

    def test_closure_with_reopen_date_is_not_still_closed(self):
        """The bug this guards: reading a closure and ignoring its own reopen
        clause reported tautog and scup as shut months after they legally
        reopened — worse than silence, because it stops you fishing an open
        season."""
        n = ridem.parse_notice(self.CLOSED_REOPENS)
        self.assertEqual(n["reopens_on"], "2026-08-01")
        self.assertFalse(n["until_further_notice"])

        n2 = ridem.parse_notice(self.REOPEN_OR)
        self.assertEqual(n2["reopens_on"], "2026-05-01")
        self.assertFalse(n2["until_further_notice"])

    def test_indefinite_closure_has_no_reopen_date(self):
        n = ridem.parse_notice(self.CLOSED_UFN)
        self.assertIsNone(n["reopens_on"])
        self.assertTrue(n["until_further_notice"])

    def test_expired_closure_resolves_to_the_rule_that_replaced_it(self):
        """Stronger than merely noticing the reopen: the notice states what
        took over -- "at ten (10) fish per day" -- so that is what should end
        up in force, not a bare 'reopened'."""
        notices = [ridem.parse_notice(self.CLOSED_REOPENS)]
        r = reconcile.compare(notices, self.TODAY)
        self.assertEqual({f["severity"] for f in r["findings"]}, {"ok"})
        live = list(reconcile.effective_state(notices, self.TODAY).values())[0]
        self.assertEqual(live["amount"]["value"], 10)
        self.assertEqual(live["amount"]["unit"], "fish")
        self.assertEqual(live["derived_from"], "2026-05-30")

    def test_live_closure_agrees_where_the_code_also_closes(self):
        """On 31 July the tautog closure is still in force — and regs.py has
        commercial tautog shut too (the June–July gap between sub-periods).
        Agreement is the correct finding, not a mismatch."""
        r = reconcile.compare([ridem.parse_notice(self.CLOSED_REOPENS)],
                              date(2026, 7, 31))
        self.assertFalse(any(f["severity"] == "mismatch" for f in r["findings"]))

    def test_live_closure_is_flagged_where_the_code_says_open(self):
        """Commercial scup is open all year in regs.py, so a closure still in
        force must surface as a mismatch."""
        closed = ("Beginning 12:00AM on Monday, March 16, 2026, the commercial Scup "
                  "General Category fishery will close until further notice.")
        r = reconcile.compare([ridem.parse_notice(closed)], self.TODAY)
        mismatches = [f for f in r["findings"] if f["severity"] == "mismatch"]
        self.assertEqual(len(mismatches), 1)
        self.assertIn("regs.py says open", mismatches[0]["detail"])

    def test_later_notice_supersedes_earlier(self):
        base = ("Beginning 12:00AM on {d}, 2026, the commercial possession limit "
                "for Black Sea Bass will be {w} ({n}) pounds per day.")
        notices = [ridem.parse_notice(base.format(d="July 19", w="three hundred", n="300")),
                   ridem.parse_notice(base.format(d="March 29", w="seven hundred fifty", n="750"))]
        state = reconcile.effective_state(notices, self.TODAY)
        vals = [n["amount"]["value"] for n in state.values()]
        self.assertEqual(vals, [300])

    def test_future_notices_are_upcoming_not_effective(self):
        future = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, August 30, 2026, the commercial possession "
            "limit for Black Sea Bass will be four hundred (400) pounds per day.")
        self.assertEqual(reconcile.effective_state([future], self.TODAY), {})
        up = reconcile.upcoming([future], self.TODAY)
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]["amount"]["value"], 400)

    def test_number_present_in_stored_prose_counts_as_agreement(self):
        """regs.py stores limits as prose, so the test is deliberately weak:
        does the stored text mention the number RIDEM publishes?"""
        n = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, July 19, 2026, the commercial possession "
            "limit for Black Sea Bass will be three hundred (300) pounds per day.")
        r = reconcile.compare([n], self.TODAY)
        self.assertEqual(r["findings"][0]["severity"], "ok")

    def test_same_date_collisions_are_reported_not_resolved(self):
        a = ("Beginning 12:00AM on Sunday, July 19, 2026, the commercial possession "
             "limit for Summer Flounder for vessels with a Summer Flounder Exemption "
             "Certificate will be three hundred (300) pounds per day.")
        b = ("Beginning 12:00AM on Sunday, July 19, 2026, the commercial possession "
             "limit for Summer Flounder will be three hundred (300) pounds per day.")
        state = reconcile.effective_state([ridem.parse_notice(a), ridem.parse_notice(b)],
                                         self.TODAY)
        self.assertEqual(list(state.values())[0]["same_date_notices"], 2)

    def test_possession_notice_is_not_mislabelled_a_closure(self):
        """Bare 'close' appears inside reopen clauses; only the verb form counts."""
        n = ridem.parse_notice(self.REOPEN_OR)
        self.assertEqual(n["change_type"], "season_close")
        n2 = ridem.parse_notice(
            "Beginning 12:00AM on Wednesday, April 1, 2026, the commercial possession "
            "limit for Scup General Category will be two thousand (2,000) pounds per day.")
        self.assertEqual(n2["change_type"], "possession_limit")


class SubFisheries(unittest.TestCase):
    AUG = date(2026, 8, 28)

    GC = ("Beginning 12:00AM on Wednesday, April 1, 2026, the commercial possession "
          "limit for Scup General Category will be two thousand (2,000) pounds per "
          "day for State Vessels Only until further notice, or until the next sub "
          "period begins on May 1, 2026 at ten thousand (10,000) pounds per week.")
    FFT = ("Beginning 12:00AM on Wednesday, April 1, 2026, the commercial possession "
           "limit for Scup Floating Fish Trap will be two thousand (2,000) pounds per "
           "day for State Vessels Only until further notice, or until the next sub "
           "period begins on May 1, 2026 at an unlimited possession limit.")

    def test_parallel_fisheries_are_told_apart(self):
        """On 1 April both scup fisheries were set to 2,000 lb/day — identical
        numbers, different licences, indistinguishable without the name."""
        self.assertEqual(ridem.parse_notice(self.GC)["sub_fishery"], "general_category")
        self.assertEqual(ridem.parse_notice(self.FFT)["sub_fishery"], "floating_fish_trap")

    def test_possession_limits_expire_too(self):
        """The bug: superseded_on was parsed for possession limits but only
        *used* for closures, so an April rule was reported as in force in
        August — against code that was already correct."""
        n = ridem.parse_notice(self.GC)
        self.assertEqual(n["superseded_on"], "2026-05-01")
        state = reconcile.effective_state([n], self.AUG)
        live = list(state.values())
        self.assertEqual(len(live), 1)
        self.assertNotEqual(live[0]["amount"]["value"], 2000)

    def test_successor_is_promoted_into_force(self):
        """The amendments page lists changes, not current state. For scup the
        rule in force exists only inside a spent notice's tail."""
        live = list(reconcile.effective_state([ridem.parse_notice(self.GC)],
                                              self.AUG).values())[0]
        self.assertEqual(live["amount"]["value"], 10000)
        self.assertEqual(live["period"], "per week")
        self.assertEqual(live["derived_from"], "2026-04-01")

    def test_unlimited_successor_carries_no_period(self):
        live = list(reconcile.effective_state([ridem.parse_notice(self.FFT)],
                                              self.AUG).values())[0]
        self.assertTrue(live["unlimited"])
        self.assertIsNone(live["period"])

    def test_a_closing_programme_leaves_nothing_in_force(self):
        """'or until the program closes on April 30' ends the rule outright —
        'closes' had to join the supersede verbs alongside 'begins'."""
        n = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, March 15, 2026, the commercial possession "
            "limit for Summer Flounder for participants in the Winter Aggregate "
            "Program will be six-thousand (6,000) pounds per bi-week until further "
            "notice (permitted vessels only), or until the program closes on "
            "April 30, 2026.")
        self.assertEqual(n["superseded_on"], "2026-04-30")
        self.assertEqual(reconcile.effective_state([n], self.AUG), {})
        self.assertEqual(len(reconcile.effective_state([n], date(2026, 4, 1))), 1)

    def test_filtering_to_your_own_fishery(self):
        notices = [ridem.parse_notice(self.GC), ridem.parse_notice(self.FFT)]
        both = reconcile.compare(notices, self.AUG)
        gc = reconcile.compare(notices, self.AUG, only_fishery="general_category")
        self.assertEqual(len(both["findings"]), 2)
        self.assertEqual(len(gc["findings"]), 1)
        self.assertEqual(gc["findings"][0]["severity"], "ok")

    def test_state_vessels_only_is_recorded(self):
        self.assertTrue(ridem.parse_notice(self.GC)["state_vessels_only"])


class Backends(unittest.TestCase):
    def test_ollama_needs_no_python_dependency(self):
        """The whole point of defaulting to ollama: the client is urllib."""
        import inspect
        src = inspect.getsource(llm.Ollama)
        self.assertIn("urllib", src)
        self.assertNotIn("import anthropic", src)

    def test_unknown_backend_falls_back_safely(self):
        self.assertIsInstance(llm.get_backend({"llm_backend": "ollama"}), llm.Ollama)
        self.assertIsInstance(llm.get_backend({"llm_backend": "anthropic"}),
                              llm.Anthropic)
        with self.assertRaises(llm.BackendUnavailable):
            llm.get_backend({"llm_backend": "none"})

    def test_guidance_lives_in_the_prompt_not_the_schema(self):
        """Ollama compiles the schema to a grammar and never shows the model
        its description fields — measured 1/4 vs 4/4 on the same task."""
        self.assertIn("loaded = thick", extract.SYSTEM)
        self.assertIn("bunker", extract.SYSTEM)
        props = extract.REPORT_SCHEMA["properties"]["bait"]["items"]["properties"]
        self.assertNotIn("description", props["bait"])
        self.assertNotIn("description", props["place"])

    def test_prompt_separates_forage_from_tackle(self):
        p = extract.SYSTEM.lower()
        self.assertIn("caught on", p)
        self.assertIn("tackle, not forage", p)

    def test_injection_field_is_scoped_to_real_directives(self):
        p = extract.SYSTEM.lower()
        self.assertIn("ordinary fishing prose is never an injection", p)


class AggregateProgram(unittest.TestCase):
    AUG = date(2026, 8, 28)
    MAR = date(2026, 3, 20)

    def test_enrolment_is_opt_in(self):
        """Permit required annually — an unenrolled vessel fishing to these
        limits would be over its own."""
        self.assertFalse(regs.aggregate_status("fluke", "none", self.AUG)["applies"])
        self.assertFalse(
            regs.status("fluke", self.AUG, "commercial")["aggregate"]["applies"])
        self.assertTrue(
            regs.status("fluke", self.AUG, "commercial",
                        "summer_fall")["aggregate"]["applies"])

    def test_summer_fall_is_a_multiplier_not_a_poundage(self):
        """The notices publish '7x the daily limit, or 2,800 lb per week'. The
        2,800 is derived from a 400 lb/day base, so storing it would go stale
        the moment the daily limit moved — which it does several times a
        season."""
        a = regs.aggregate_status("fluke", "summer_fall", self.AUG)
        self.assertEqual(a["multiplier"], 7.0)
        daily = int(re.search(r"(\d+) lb/day",
                              regs.COMMERCIAL["fluke"].limit).group(1))
        self.assertIn(f"{daily * 7:,}", a["limit"])

    def test_winter_is_summer_flounder_only(self):
        self.assertTrue(regs.aggregate_status("fluke", "winter", self.MAR)["applies"])
        self.assertFalse(
            regs.aggregate_status("black_sea_bass", "winter", self.MAR)["applies"])

    def test_winter_window_closes_end_of_april(self):
        self.assertTrue(regs.aggregate_status("fluke", "winter", self.MAR)["open"])
        self.assertFalse(regs.aggregate_status("fluke", "winter", self.AUG)["open"])
        self.assertFalse(
            regs.aggregate_status("fluke", "winter", date(2026, 5, 1))["open"])

    def test_summary_line_only_mentions_an_open_programme(self):
        line = regs.summary_line("fluke", self.AUG, "commercial", "summer_fall")
        self.assertIn("Aggregate", line)
        self.assertNotIn("Aggregate",
                         regs.summary_line("fluke", self.AUG, "commercial", "winter"))
        self.assertNotIn("Aggregate",
                         regs.summary_line("fluke", self.AUG, "commercial"))

    def test_parser_tags_aggregate_notices(self):
        n = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, March 15, 2026, the commercial possession "
            "limit for Summer Flounder for participants in the Winter Aggregate "
            "Program will be six-thousand (6,000) pounds per bi-week until further "
            "notice (permitted vessels only), or until the program closes on "
            "April 30, 2026.")
        self.assertEqual(n["aggregate_program"], "winter")
        self.assertEqual(n["period"], "per bi-week")
        self.assertEqual(n["amount"]["value"], 6000)

    def test_aggregate_notices_do_not_collide_with_general_limits(self):
        """Comparing a 6,000 lb bi-weekly aggregate limit against the general
        300 lb/day one is a category error, not a disagreement."""
        agg = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, March 15, 2026, the commercial possession "
            "limit for Summer Flounder for participants in the Winter Aggregate "
            "Program will be six-thousand (6,000) pounds per bi-week.")
        gen = ridem.parse_notice(
            "Beginning 12:00AM on Sunday, July 19, 2026, the commercial possession "
            "limit for Summer Flounder will be three hundred (300) pounds per day.")
        state = reconcile.effective_state([agg, gen], self.AUG)
        self.assertEqual(len(state), 2)
        r = reconcile.compare([agg, gen], self.AUG)
        self.assertEqual([f["severity"] for f in r["findings"]], ["ok", "ok"])


class Packaging(unittest.TestCase):
    """The CLI has to run from somewhere other than the project directory.

    `python3 -m tiderace` only works with the project as the current directory,
    because that is the one place Python adds to sys.path. Every command in the
    README was written that way and none of them worked from a home directory.
    """

    ROOT = os.path.dirname(os.path.abspath(__file__))

    def test_wrapper_exists_and_is_executable(self):
        w = os.path.join(self.ROOT, "tiderace-cli")
        self.assertTrue(os.path.isfile(w), "launcher missing")
        self.assertTrue(os.access(w, os.X_OK), "launcher is not executable")

    def test_wrapper_runs_from_a_foreign_directory(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([os.path.join(self.ROOT, "tiderace-cli"), "spots"],
                               cwd=d, capture_output=True, text=True, timeout=90)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("whale_rock", r.stdout)

    def test_module_entry_point_is_callable(self):
        """pyproject wires tiderace.cli:run as the console script."""
        from tiderace.cli import run
        self.assertTrue(callable(run))

    def test_pyproject_declares_the_script_and_no_dependencies(self):
        pp = os.path.join(self.ROOT, "pyproject.toml")
        self.assertTrue(os.path.isfile(pp))
        text = open(pp).read()
        self.assertIn('tiderace = "tiderace.cli:run"', text)
        self.assertIn("dependencies = []", text)
        self.assertIn('requires-python = ">=3.9"', text)

    def test_web_assets_are_packaged(self):
        """serve is useless if index.html does not ship with the package."""
        from tiderace import server
        self.assertTrue(os.path.isfile(os.path.join(server.WEB_DIR, "index.html")))

    def test_data_paths_do_not_depend_on_cwd(self):
        """Data paths must anchor to the installed package, not the current
        directory and not the checkout's name.

        This previously asserted the string "tiderace" appeared in the path,
        which only passed because the working copy happened to be a directory
        of that name. A fresh `git clone` into any other folder failed it --
        caught by cloning the pushed repo and running the suite, which is the
        only way that class of assumption shows up.
        """
        import tempfile
        import tiderace as pkg
        from tiderace import bait as b, charts, gso, stations
        from tiderace import log as catchlog

        root = os.path.dirname(os.path.dirname(os.path.abspath(pkg.__file__)))
        paths = (catchlog.LOG_PATH, b.BAIT_PATH, charts.CHART_DIR, gso.CACHE,
                 stations.CATALOG_PATH, spots.PRIVATE_PATH)

        for path in paths:
            resolved = os.path.abspath(path)
            self.assertTrue(os.path.isabs(resolved), path)
            self.assertTrue(resolved.startswith(root + os.sep),
                            f"{path} is not anchored to the package root {root}")

        # And they must not move when the process does.
        before = [os.path.abspath(p) for p in paths]
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as d:
                os.chdir(d)
                self.assertEqual([os.path.abspath(p) for p in paths], before)
        finally:
            os.chdir(cwd)


class MapLayout(unittest.TestCase):
    """Layout regressions found by looking at the actual rendered page.

    These are string assertions on the stylesheet rather than real layout
    tests -- they cannot prove the page looks right, only that the two fixes
    below have not been quietly reverted.
    """

    HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "tiderace", "web", "index.html")

    def setUp(self):
        self.css = open(self.HTML).read()

    def test_scrubber_is_not_offset_by_the_panel_height(self):
        """The scrubber is positioned inside the map wrapper, not the app grid.
        Offsetting it by the stacked panel's 300px height pushed it up from the
        map's own bottom edge and parked it in the middle of the chart."""
        self.assertNotIn("bottom:314px", self.css)

    def test_scrubber_clears_the_attribution_when_stacked(self):
        """Attribution lives bottom-right and occupies the last ~34px. The
        basemap is ODbL, so covering that credit is a licence breach, not a
        cosmetic issue."""
        block = self.css.split("@media (max-width:900px)")[1]
        self.assertIn("#timebar{right:12px; bottom:44px}", block)

    def test_attribution_control_is_left_to_maplibre(self):
        """An earlier fix disabled the built-in control and re-added it by
        hand, which risks losing the credit entirely if the wiring is wrong."""
        self.assertIn("attributionControl:true", self.css)
        self.assertNotIn("attributionControl:false", self.css)
        self.assertNotIn("new maplibregl.AttributionControl", self.css)

    def test_desktop_scrubber_reserves_the_side_panel(self):
        self.assertIn("right:calc(360px + 12px)", self.css)


class Solunar(unittest.TestCase):
    JAMESTOWN = (41.4963, -71.3712)

    def _tz(self, d):
        from tiderace.features import _local_tz
        return _local_tz(d)

    def test_full_moon_rises_at_sunset_and_sets_at_sunrise(self):
        """The strongest available check without an ephemeris to compare
        against: at full moon the sun and moon are opposed, so moonrise must
        land near sunset and moonset near sunrise."""
        d = datetime(2026, 8, 28)          # verified full moon
        dd = d.replace(tzinfo=self._tz(d))
        ev = solunar.events(dd, *self.JAMESTOWN)
        sun = astro.sun_events(dd, *self.JAMESTOWN)
        rise_gap = abs((ev["moonrise"] - sun["sunset"]).total_seconds()) / 60
        set_gap = abs((ev["moonset"] - sun["sunrise"]).total_seconds()) / 60
        self.assertLess(rise_gap, 45, "moonrise should track sunset at full moon")
        self.assertLess(set_gap, 45, "moonset should track sunrise at full moon")

    def test_new_moon_rises_and_sets_with_the_sun(self):
        d = datetime(2026, 9, 11)          # verified new moon
        dd = d.replace(tzinfo=self._tz(d))
        ev = solunar.events(dd, *self.JAMESTOWN)
        sun = astro.sun_events(dd, *self.JAMESTOWN)
        self.assertLess(abs((ev["moonrise"] - sun["sunrise"]).total_seconds()) / 60, 45)
        self.assertLess(abs((ev["moonset"] - sun["sunset"]).total_seconds()) / 60, 45)

    def test_transit_and_underfoot_are_about_half_a_lunar_day_apart(self):
        d = datetime(2026, 8, 28)
        ev = solunar.events(d.replace(tzinfo=self._tz(d)), *self.JAMESTOWN)
        gap = abs((ev["transit"] - ev["antitransit"]).total_seconds()) / 3600
        self.assertTrue(11.5 < gap < 13.0, f"transit/underfoot gap was {gap:.1f}h")

    def test_altitude_is_highest_at_transit(self):
        d = datetime(2026, 8, 28)
        tz = self._tz(d)
        ev = solunar.events(d.replace(tzinfo=tz), *self.JAMESTOWN)
        at = solunar.moon_altitude(ev["transit"], *self.JAMESTOWN)
        for offset in (-3, -1, 1, 3):
            other = solunar.moon_altitude(
                ev["transit"] + timedelta(hours=offset), *self.JAMESTOWN)
            self.assertGreater(at, other)

    def test_major_periods_beat_minor_ones(self):
        d = datetime(2026, 8, 28)
        tz = self._tz(d)
        ev = solunar.events(d.replace(tzinfo=tz), *self.JAMESTOWN)
        major = solunar.score(ev["transit"], *self.JAMESTOWN, ev)
        minor = solunar.score(ev["moonset"], *self.JAMESTOWN, ev)
        self.assertEqual(major["kind"], "major")
        self.assertEqual(minor["kind"], "minor")
        self.assertGreater(major["score"], minor["score"])

    def test_quiet_hours_score_zero(self):
        d = datetime(2026, 8, 28)
        tz = self._tz(d)
        ev = solunar.events(d.replace(tzinfo=tz), *self.JAMESTOWN)
        self.assertEqual(
            solunar.score(d.replace(hour=4, tzinfo=tz), *self.JAMESTOWN, ev)["score"], 0.0)

    def test_solunar_is_a_rival_not_a_score_term(self):
        """It must not reach the scorer. Solunar peaks at lunar transit, which
        drives the tide, which drives the current -- scoring it alongside
        current speed counts the moon twice and calls it corroboration."""
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tiderace", "score.py")).read()
        self.assertNotIn("solunar", src)
        self.assertIn("solunar", open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "tiderace", "evaluate.py")).read())

    def test_evaluate_reports_solunar_as_its_own_column(self):
        rows = [{"species": "striped_bass", "count": 3,
                 "conditions": {"current_speed": 1.2, "light_phase": "night",
                                "month": 9, "water_temp_f": 62, "wind_kt": 8,
                                "spring_strength": .6, "pressure_trend_3h": -.5,
                                "exposed": False, "solunar": 0.8}}] * 5
        r = evaluate.evaluate(rows)
        self.assertIn("solunar_rho", r)
        self.assertEqual(evaluate.solunar_baseline({"solunar": 0.8}), 80.0)
        self.assertEqual(evaluate.solunar_baseline({}), 0.0)


class Offline(unittest.TestCase):
    """The PWA pieces, checked as far as a non-browser test can reach.

    The behaviour that matters -- queue while offline, drain on reconnect --
    was exercised in a real browser with the server stopped; these guard the
    wiring it depends on.
    """

    WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiderace", "web")

    def test_pwa_assets_exist(self):
        for f in ("manifest.webmanifest", "sw.js", "icon-192.png",
                  "icon-512.png", "icon-maskable-512.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.WEB, f)), f)

    def test_manifest_is_valid_and_installable(self):
        import json as J
        m = J.load(open(os.path.join(self.WEB, "manifest.webmanifest")))
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["scope"], "/")
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        self.assertIn("maskable", {i["purpose"] for i in m["icons"]})

    def test_icons_are_real_pngs(self):
        for f in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            with open(os.path.join(self.WEB, f), "rb") as fh:
                self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n", f)

    def test_service_worker_does_not_cache_map_tiles(self):
        """Covering the bay at usable zoom is hundreds of megabytes, and the
        map is the one part you can lose and still fish."""
        sw = open(os.path.join(self.WEB, "sw.js")).read()
        self.assertIn("openstreetmap", sw)
        self.assertIn("openseamap", sw)
        self.assertIn("return", sw.split("openstreetmap")[1][:200])

    def test_service_worker_is_network_first_for_data(self):
        sw = open(os.path.join(self.WEB, "sw.js")).read()
        self.assertIn("/api/", sw)
        self.assertIn("X-Tiderace-Offline", sw)

    def test_client_queues_before_sending(self):
        """A trip you did not record is gone; one that has not synced is fine."""
        html = open(os.path.join(self.WEB, "index.html")).read()
        self.assertIn("queueAdd", html)
        self.assertIn("indexedDB", html)
        i_queue = html.index("await queueAdd(body)")
        i_send = html.index("const res = await flushQueue()")
        self.assertLess(i_queue, i_send, "must write locally before the network")

    def test_server_routes_the_worker_at_root_scope(self):
        """A service worker only controls paths at or below its own."""
        srv = open(os.path.join(os.path.dirname(self.WEB), "server.py")).read()
        self.assertIn('url.path == "/sw.js"', srv)
        self.assertIn('url.path == "/manifest.webmanifest"', srv)
        self.assertIn('url.path == "/api/health"', srv)

    def test_batch_log_accepts_a_flushed_queue(self):
        srv = open(os.path.join(os.path.dirname(self.WEB), "server.py")).read()
        self.assertIn('data.get("entries")', srv)
        self.assertIn("client_id", srv)


class HMS(unittest.TestCase):
    """Federal rules for the offshore species Rhode Island does not manage."""

    def test_bluefin_size_classes_are_ordered_and_gapless(self):
        cls = hms.RULES["bluefin"].size_classes
        self.assertEqual([c[0] for c in cls],
                         ["school", "large school / small medium", "trophy"])
        for (_, _, hi), (_, lo2, _) in zip(cls, cls[1:]):
            self.assertEqual(hi, lo2, "a gap here means a legal fish scores as none")

    def test_classify_matches_the_boundaries(self):
        self.assertEqual(hms.classify("bluefin", 27), "school")
        self.assertEqual(hms.classify("bluefin", 46.9), "school")
        self.assertEqual(hms.classify("bluefin", 47), "large school / small medium")
        self.assertEqual(hms.classify("bluefin", 72.9), "large school / small medium")
        self.assertEqual(hms.classify("bluefin", 73), "trophy")
        self.assertIn("released", hms.classify("bluefin", 26))

    def test_billfish_minimums(self):
        self.assertEqual(hms.RULES["blue marlin"].min_inches, 99)
        self.assertEqual(hms.RULES["white marlin"].min_inches, 66)
        self.assertEqual(hms.RULES["sailfish"].min_inches, 63)
        for k in ("blue marlin", "white marlin", "roundscale spearfish"):
            self.assertEqual(hms.RULES[k].measure, "lower-jaw fork length")

    def test_mahi_and_wahoo_are_flagged_as_managed_elsewhere(self):
        """Silence would read as 'no rules'. They have rules, just not these."""
        for sp in ("mahi", "wahoo"):
            st = hms.status(sp)
            self.assertFalse(st["known"])
            self.assertTrue(st["managed_elsewhere"])
            self.assertIn("FMP", st["note"])

    def test_volatile_species_are_marked(self):
        """NOAA adjusts bluefin retention and billfish landings in-season."""
        self.assertTrue(hms.status("bluefin")["volatile"])
        self.assertTrue(hms.status("white marlin")["volatile"])
        self.assertFalse(hms.status("yellowfin")["volatile"])

    def test_everything_is_advisory_with_a_short_shelf_life(self):
        self.assertTrue(hms.status("bluefin")["advisory"])
        self.assertLessEqual(hms.STALE_AFTER_DAYS, 14)

    def test_every_pelagic_the_offshore_report_names_is_covered(self):
        from tiderace import offshore
        for common in offshore.PELAGICS:
            st = hms.status(common)
            self.assertTrue(st.get("known") or st.get("managed_elsewhere"),
                            f"{common} appears offshore with no federal note")


class Conditions(unittest.TestCase):
    def test_marine_zones_cover_the_bay_and_outside(self):
        self.assertIn("ANZ236", conditions.ZONES)
        self.assertIn("ANZ237", conditions.ZONES)

    def test_river_gauges_are_usgs_site_numbers(self):
        for site in conditions.RIVERS:
            self.assertTrue(site.isdigit() and len(site) >= 8, site)

    def test_anomaly_sign_is_observed_minus_predicted(self):
        """Positive must mean more water than predicted -- wind stacked it in.
        Getting the sign backwards would invert every reading."""
        import inspect
        src = inspect.getsource(conditions.water_level_anomaly)
        self.assertIn("o[latest] - p[latest]", src)

    def test_marine_forecast_uses_the_products_api(self):
        """/zones/{id}/forecast 404s for marine zones; the forecast is a text
        product covering every zone the office issues."""
        import inspect
        src = inspect.getsource(conditions.marine_forecast)
        self.assertIn("products/types/CWF", src)
        self.assertNotIn("zones/forecast", src)


class Birds(unittest.TestCase):
    """Seabirds as a bait sensor. No network in these -- the key is the user's."""

    def test_bird_weights_rank_plunge_divers_above_loafers(self):
        """A cormorant on a rock says nothing; a gannet diving says everything."""
        w = birds.BAIT_BIRDS
        self.assertGreater(w["Northern Gannet"], w["Herring Gull"])
        self.assertGreater(w["Common Tern"], w["Double-crested Cormorant"])
        self.assertGreater(w["Great Shearwater"], w["Great Black-backed Gull"])

    def test_weights_are_bounded(self):
        for name, w in birds.BAIT_BIRDS.items():
            self.assertTrue(0 < w <= 1.0, name)

    def test_missing_key_fails_loudly(self):
        """Silence would look like 'no birds' rather than 'not configured'."""
        import os
        from tiderace import config as cfgmod
        old_env = os.environ.pop("EBIRD_API_KEY", None)
        try:
            if not cfgmod.load().get("ebird_key"):
                with self.assertRaises(birds.NoKey):
                    birds.api_key()
        finally:
            if old_env:
                os.environ["EBIRD_API_KEY"] = old_env

    def test_key_lives_in_gitignored_config(self):
        from tiderace import config as cfgmod
        self.assertIn("ebird_key", cfgmod.DEFAULTS)
        root = os.path.dirname(os.path.abspath(__file__))
        ignore = open(os.path.join(root, ".gitignore")).read()
        self.assertIn("data/config.json", ignore)


class Provenance(unittest.TestCase):
    """A score is a measurement, a prediction, an inference and a guess
    multiplied together. Those are worth different amounts and the number
    hides that."""

    FEAT = dict(month=8, water_temp_f=70, current_speed=1.3, light_phase="night",
                wind_kt=7, pressure_trend_3h=-0.4, spring_strength=0.9)

    def test_every_scoring_term_is_classified(self):
        """An unclassified input silently becomes 'assumed', which would
        understate the model rather than overstate it -- but still wrongly."""
        r = score.score("striped_bass", self.FEAT)
        for name in r["weighted"]:
            self.assertIn(name, provenance.INPUTS, f"{name} has no provenance")

    def test_every_modifier_is_classified(self):
        seen = set()
        for bait_sig, bird_sig in ((0, 0), (0.8, 0), (0, 0.8), (0.8, 0.8)):
            r = score.score("striped_bass",
                            dict(self.FEAT, bait_signal=bait_sig,
                                 bird_signal=bird_sig))
            seen |= set(r["modifiers"])
        for name in seen:
            self.assertIn(name, provenance.MODIFIERS, f"{name} has no provenance")

    def test_tiers_are_ordered_strongest_first(self):
        self.assertEqual(provenance.TIER_ORDER[0], provenance.OBSERVED)
        self.assertEqual(provenance.TIER_ORDER[-1], provenance.ASSUMED)

    def test_hand_set_curves_are_always_declared(self):
        """They shape every term, so no score is ever free of them."""
        b = provenance.breakdown(score.score("striped_bass", self.FEAT))
        names = [i["name"] for i in b["tiers"][provenance.ASSUMED]]
        self.assertIn("species_curve", names)

    def test_lunar_inputs_share_one_origin(self):
        """Tidal current and spring tide are both the moon. Counting them as
        two agreeing sources is the error this exists to prevent."""
        self.assertEqual(provenance.INPUTS["current"][2], "moon")
        self.assertEqual(provenance.MODIFIERS["spring_tide"][2], "moon")

    def test_birds_and_bait_share_the_bait_origin(self):
        """Birds are over bait. They are not a second independent witness to
        bait being present -- they are a proxy for the same fact."""
        self.assertEqual(provenance.MODIFIERS["birds"][2], "bait")
        self.assertEqual(provenance.MODIFIERS["bait"][2], "bait")

    def test_agreement_counts_witnesses_by_kind(self):
        none = provenance.agreement({})
        self.assertEqual(none["count"], 0)
        self.assertFalse(none["corroborated"])

        both = provenance.agreement({"bait_sources": ["own", "report"],
                                     "bird_signal": 0.5})
        self.assertEqual(both["count"], 3)
        self.assertTrue(both["corroborated"])
        self.assertEqual(both["strongest"], provenance.OBSERVED)

    def test_a_single_source_is_not_corroboration(self):
        one = provenance.agreement({"bait_sources": ["own"]})
        self.assertEqual(one["count"], 1)
        self.assertFalse(one["corroborated"])


class EvidenceRanking(unittest.TestCase):
    """Evidence of unequal quality is ranked, never averaged.

    Two people looking at the same water do not make the better look worse.
    Averaging did exactly that -- twice, with two different sources -- before
    the shape was fixed rather than the symptom.
    """

    NOW = datetime(2026, 8, 29, 20, 0)
    OWN = {"bait": "silversides", "lat": 41.36, "lon": -71.64,
           "when": "2026-08-29T18:00", "abundance": "loaded",
           "confidence": "high", "source": "own"}

    def _report(self, abundance="trace", confidence="medium"):
        return {"bait": "silversides", "lat": 41.36, "lon": -71.64,
                "when": "2026-08-29T12:00", "abundance": abundance,
                "confidence": confidence, "source": "report"}

    def _sig(self, rows):
        return bait.bait_at(41.36, -71.64, self.NOW, "striped_bass", rows)["signal"]

    def test_a_weak_report_never_dilutes_a_first_hand_sighting(self):
        """Regression: a `trace` secondhand report pulled a `loaded` first-hand
        sighting from 0.69 down to 0.47."""
        alone = self._sig([self.OWN])
        with_weak = self._sig([self.OWN, self._report()])
        self.assertGreaterEqual(with_weak, alone)

    def test_a_contradicting_weaker_report_cannot_override(self):
        alone = self._sig([self.OWN])
        with_denial = self._sig([self.OWN, self._report("none", "high")])
        self.assertEqual(with_denial, alone)

    def test_corroboration_scales_with_the_supporting_evidence(self):
        base = self._sig([self.OWN])
        weak = self._sig([self.OWN, self._report("trace", "low")])
        strong = self._sig([self.OWN, self._report("loaded", "high")])
        self.assertLess(base, weak)
        self.assertLess(weak, strong)

    def test_corroboration_is_capped(self):
        many = [self.OWN] + [dict(self._report("loaded", "high"),
                                  lat=41.36 + i * 0.001) for i in range(12)]
        self.assertLessEqual(self._sig(many), 1.0)

    def test_first_hand_outranks_secondhand_at_equal_strength(self):
        """Same sighting, same freshness, different reporter."""
        own_only = self._sig([self.OWN])
        rep_only = self._sig([dict(self.OWN, source="report",
                                   when="2026-08-29T18:00")])
        self.assertGreater(own_only, rep_only)
        self.assertLess(bait.SOURCE_TRUST["report"], bait.SOURCE_TRUST["own"])

    def test_a_lone_report_of_no_bait_is_still_negative(self):
        self.assertLess(self._sig([self._report("none", "high")]), 0)

    def test_report_sources_are_declared_and_robots_checked(self):
        report_sources = [k for k, v in fetch.SOURCES.items()
                          if v["kind"] == "report"]
        self.assertGreaterEqual(len(report_sources), 3)
        for k in report_sources:
            self.assertTrue(fetch.SOURCES[k]["url"].startswith("https://"), k)


class BirdsAreNotBait(unittest.TestCase):
    """Seeing bait is an observation. Seeing birds is a guess about bait."""

    # Deliberately a middling afternoon, not a perfect night. On ideal
    # conditions the score is already at the 100 ceiling and every modifier
    # comparison collapses -- which is how the first version of the
    # conjunction test passed while proving nothing.
    BASE = dict(month=8, water_temp_f=72, current_speed=0.6,
                light_phase="day", wind_kt=10, pressure_trend_3h=0.2,
                spring_strength=0.4)

    def _score(self, bait_sig, bird_sig):
        return score.score("striped_bass",
                           dict(self.BASE, bait_signal=bait_sig,
                                bird_signal=bird_sig))

    def test_a_weak_bird_never_dilutes_a_direct_sighting(self):
        """The original bug: birds were written into the bait log at a lower
        confidence, and one `trace` tern record pulled a `loaded` eyeball
        sighting of silversides from +0.56 to +0.44. Birds may now add to a
        sighting, but they must never subtract from one."""
        alone = self._score(0.8, 0.0)["score"]
        with_weak_bird = self._score(0.8, 0.1)["score"]
        self.assertGreaterEqual(with_weak_bird, alone)

    def test_bait_worked_by_birds_beats_either_alone(self):
        """Passive bait and bait being driven up are not the same water. Birds
        over bait means something is pushing it, so the conjunction says more
        than either half -- it is not double-counting, the two facts differ."""
        bait_only = self._score(0.8, 0.0)["score"]
        birds_only = self._score(0.0, 0.8)["score"]
        both = self._score(0.8, 0.8)["score"]
        self.assertGreater(both, bait_only)
        self.assertGreater(both, birds_only)
        self.assertIn("bait_worked_by_birds", self._score(0.8, 0.8)["modifiers"])

    def test_the_conjunction_is_capped(self):
        """A hand-set interaction must not run away."""
        from tiderace.bait import COMBINED_CAP, combined_modifier
        m, _ = combined_modifier(1.0, 1.0)
        self.assertLessEqual(m, COMBINED_CAP)
        self.assertLess(COMBINED_CAP, 1.7)

    def test_each_case_is_labelled_distinctly(self):
        from tiderace.bait import combined_modifier
        self.assertEqual(combined_modifier(0.8, 0.0)[1], "bait")
        self.assertEqual(combined_modifier(0.0, 0.8)[1], "birds")
        self.assertEqual(combined_modifier(0.8, 0.8)[1], "bait_worked_by_birds")
        self.assertEqual(combined_modifier(0.0, 0.0)[1], "")

    def test_birds_stand_in_when_nothing_was_seen(self):
        nothing = self._score(0.0, 0.0)
        birds_only = self._score(0.0, 0.6)
        self.assertGreater(birds_only["score"], nothing["score"])
        self.assertIn("birds", birds_only["modifiers"])

    def test_birds_are_discounted_against_a_real_sighting(self):
        self.assertLess(birds.BIRD_DISCOUNT, 1.0)
        same = self._score(0.6, 0.0)["score"]
        proxy = self._score(0.0, 0.6)["score"]
        self.assertLessEqual(proxy, same)

    def test_birds_are_never_written_to_the_bait_log(self):
        """They are recomputed on demand so they cannot pile up into something
        that later looks like evidence."""
        self.assertFalse(hasattr(birds, "sync_to_bait_log"))
        import inspect
        src = inspect.getsource(birds)
        self.assertNotIn("baitmod.record", src)

    def test_bird_species_imply_a_sensible_bait(self):
        m = birds.BIRD_IMPLIES_BAIT
        self.assertEqual(m["Common Tern"], "silversides")
        self.assertEqual(m["Northern Gannet"], "bunker")
        self.assertEqual(m["Great Shearwater"], "sand eels")
        self.assertIsNone(m["Parasitic Jaeger"])
        self.assertIsNone(m["Wilson's Storm-Petrel"])

    def test_implied_baits_exist_in_the_bait_model(self):
        for b in birds.BIRD_IMPLIES_BAIT.values():
            if b is None:
                continue
            self.assertTrue(any(b in rel for rel in bait.RELEVANCE.values()),
                            f"{b} is implied by a bird but unknown to the scorer")

    def test_abundance_uses_the_shared_vocabulary(self):
        prev = -1
        for w in (1, 20, 60, 400):
            a = birds._abundance(w)
            self.assertIn(a, bait.ABUNDANCE)
            self.assertGreaterEqual(bait.ABUNDANCE[a], prev)
            prev = bait.ABUNDANCE[a]

    def test_evaluate_can_remove_the_birds(self):
        base = {"current_speed": 1.2, "light_phase": "night", "month": 9,
                "water_temp_f": 62, "wind_kt": 8, "spring_strength": .6,
                "pressure_trend_3h": -.5, "exposed": False,
                "bait_signal": 0.0, "bird_signal": 0.8}
        rows = [{"species": "striped_bass", "count": n, "conditions": dict(base)}
                for n in (0, 1, 2, 3, 4)]
        self.assertIn("model_without_birds_rho", evaluate.evaluate(rows))


class SurfaceCurrent(unittest.TestCase):
    def test_offshore_uses_measured_radar_not_extrapolation(self):
        """The bay has measured current; offshore had none until HF radar.
        An extrapolated current seventeen miles out is a confident fiction."""
        from tiderace import offshore
        import inspect
        src = inspect.getsource(offshore.surface_current)
        self.assertIn("ucsdHfrE", offshore.HFRADAR)
        self.assertIn("measured", src)

    def test_no_data_is_reported_as_no_measurement(self):
        """Radar has real gaps. A null must not read as 'no current'."""
        from tiderace import offshore
        import inspect
        src = inspect.getsource(offshore.surface_current)
        self.assertIn('"measured": False', src)


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


class Coordinates(unittest.TestCase):
    """Parsing the formats that are actually on a phone and a chartplotter."""

    def test_equivalent_forms_agree(self):
        want = (41.4408, -71.4228)
        for text in ("41.4408,-71.4228", "41.4408 -71.4228",
                     "41.4408, -71.4228", "41 26.448 N, 71 25.368 W"):
            lat, lon = spots.parse_coord(text)
            self.assertAlmostEqual(lat, want[0], places=4, msg=text)
            self.assertAlmostEqual(lon, want[1], places=4, msg=text)

    def test_dms_with_hemispheres(self):
        lat, lon = spots.parse_coord("""41°26'26.9"N 71°25'22.1"W""")
        self.assertAlmostEqual(lat, 41.4408, places=3)
        self.assertAlmostEqual(lon, -71.4228, places=3)

    def test_west_is_negative_however_it_was_written(self):
        """A positive longitude in Rhode Island is a typo every time, and
        silently fishing the Yellow Sea is the worse failure."""
        self.assertLess(spots.parse_coord("41 26.448 N, 71 25.368 W")[1], 0)

    def test_garbage_is_refused(self):
        for bad in ("", "whale rock", "41.4408", "999,999"):
            with self.assertRaises(ValueError, msg=bad):
                spots.parse_coord(bad)


class LandGeometry(unittest.TestCase):
    """The land test is the whole reason coordinate binding is trustworthy,
    so it is checked on real chart data when the layer is cached."""

    def setUp(self):
        from tiderace import charts
        self.charts = charts
        if not charts.land_index():
            self.skipTest("land layer not cached — run: tiderace charts")

    def test_an_island_between_two_points_is_measured(self):
        """Aquidneck Island sits between the Sakonnet and the mid-bay. This is
        the case that made the whole test necessary."""
        span = self.charts.land_span_nm(41.5600, -71.2300, 41.5750, -71.2967)
        self.assertGreater(span, 1.0)
        self.assertTrue(self.charts.crosses_land(41.5600, -71.2300, 41.5750, -71.2967))

    def test_open_water_path_is_clear(self):
        self.assertFalse(self.charts.crosses_land(41.4408, -71.4228, 41.4256, -71.3611)
                         is True)

    def test_shore_marks_are_not_disqualified_by_their_own_shoreline(self):
        """Beavertail and Castle Hill are charted as land -- they are headlands
        you fish from. A naive edge test rejected every station for both."""
        for lat, lon in ((41.4494, -71.3997), (41.4622, -71.3628)):
            water = self.charts.nearest_water(lat, lon)
            self.assertIsNotNone(water, f"{lat},{lon}")
            self.assertLess(water["distance_nm"], 0.5)
            self.assertFalse(self.charts.on_land(water["lat"], water["lon"]))

    def test_open_water_needs_no_snapping(self):
        self.assertIsNone(self.charts.nearest_water(41.4408, -71.4228))

    def test_no_land_data_is_not_the_same_as_no_land(self):
        """None and False must never be conflated: one is 'nothing in the way',
        the other is 'I did not look'."""
        saved = self.charts._LAND_INDEX
        try:
            self.charts._LAND_INDEX = []
            self.assertIsNone(self.charts.crosses_land(41.56, -71.23, 41.57, -71.30))
            self.assertIsNone(self.charts.land_span_nm(41.56, -71.23, 41.57, -71.30))
            self.assertIsNone(self.charts.on_land(41.56, -71.23))
        finally:
            self.charts._LAND_INDEX = saved

    def test_depth_keys_are_not_mangled(self):
        """'depth_min_m'.replace('_m', '_ft') yields 'depth_ftin_ft', because
        str.replace also hits the '_m' inside '_min'."""
        gj = self.charts.load("depth_area")
        if not gj:
            self.skipTest("depth layer not cached")
        props = [f["properties"] for f in gj["features"][:200]]
        self.assertTrue(any("depth_min_ft" in p for p in props))
        self.assertFalse(any(k.startswith("depth_ftin") for p in props for k in p))

    def test_analysis_layers_are_not_offered_as_overlays(self):
        self.assertNotIn("land", self.charts.available())
        self.assertIn("land", self.charts.available(include_analysis=True))


class StationResolution(unittest.TestCase):
    def setUp(self):
        from tiderace import charts, stations
        self.stations, self.charts = stations, charts
        if not os.path.exists(stations.CATALOG_PATH):
            self.skipTest("no station catalog — run: tiderace stations --refresh")
        if not charts.land_index():
            self.skipTest("land layer not cached — run: tiderace charts")

    def test_reproduces_the_hand_verified_bindings(self):
        """Nineteen spots were bound to their current stations by hand and
        checked live against CO-OPS. The resolver has to agree with all of
        them, or it is not trustworthy anywhere else.

        Scoped to those nineteen. `spots.SPOTS` also carries whatever is in
        my_spots.json, and those marks were never part of the hand check -- a
        test that silently graded the resolver against a station the user typed
        would be measuring the wrong thing, and would break for anyone who
        cloned this and added a mark of their own.
        """
        wrong = []
        for sp in spots.SPOTS:
            if sp.private:
                continue
            got = self.stations.resolve(sp.lat, sp.lon)["current"]["id"]
            if got != sp.current_station:
                wrong.append(f"{sp.key}: hand={sp.current_station} got={got}")
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_a_mark_behind_a_barrier_beach_is_flagged_not_guessed(self):
        """Widening the chart box to include Charlestown gave the resolver
        coastline data it never had there, and it immediately said something
        true: the inside mark sits on charted land, and every current station
        is more than half a mile of barrier beach away. Ninigret Pond really is
        behind a barrier -- the only water connection is the breachway, narrower
        than the coastline layer resolves. The right behaviour is to say so.
        """
        from tiderace import charts, spots as spotsmod
        sp = spotsmod.get("charlestown_inside")
        if not charts.covers(sp.lat, sp.lon) or not charts.land_index():
            self.skipTest("land layer not cached for this area")
        r = self.stations.resolve(sp.lat, sp.lon)
        self.assertTrue(r["on_land"], "the pond mark reads as land on the chart")
        self.assertEqual(r["confidence"], "poor")
        self.assertTrue(any("land" in w.lower() for w in r["warnings"]),
                        "must say the current came from water elsewhere")

    def test_the_sakonnet_is_not_bound_across_aquidneck(self):
        """Nearest-by-distance picks a mid-bay station 0.1 nm closer, with a
        whole island in between. This is the failure the land test exists for,
        and it is silent: the forecast still looks perfectly reasonable."""
        res = self.stations.resolve(41.5600, -71.2300)
        self.assertTrue(res["current"]["name"].endswith("Sakonnet River"),
                        res["current"]["name"])
        self.assertTrue(any("Dyer" in r["name"] for r in res["current_rejected"]))

    def test_distance_alone_would_have_got_it_wrong(self):
        """Guards the premise. If the nearest station ever becomes the right
        answer here, the land test is no longer earning its complexity."""
        cands = self.stations.current_candidates(41.5600, -71.2300, limit=3)
        self.assertTrue(cands[0]["crosses_land"])

    def test_a_mark_on_land_is_reported_not_hidden(self):
        res = self.stations.resolve(41.5150, -71.3800)
        self.assertTrue(res["on_land"])
        self.assertTrue(any("charted land" in w for w in res["warnings"]))

    def test_confidence_degrades_with_distance(self):
        near = self.stations.resolve(41.5100, -71.4050)
        far = self.stations.resolve(41.5600, -71.2300)
        self.assertEqual(near["confidence"], "good")
        self.assertEqual(far["confidence"], "poor")

    def test_every_choice_is_explained(self):
        res = self.stations.resolve(41.5600, -71.2300)
        self.assertTrue(res["warnings"])
        for r in res["current_rejected"]:
            self.assertIsNotNone(r["land_span_nm"])


class AdHocSpots(unittest.TestCase):
    def setUp(self):
        from tiderace import stations
        if not os.path.exists(stations.CATALOG_PATH):
            self.skipTest("no station catalog")

    def test_a_typed_coordinate_never_joins_the_public_list(self):
        """A coordinate you typed is a mark. Marks do not go in SPOTS, and
        public_only() is the only set anything shareable is built from."""
        before = len(spots.SPOTS)
        spot, _ = spots.at_coord(41.4520, -71.4050)
        self.assertEqual(len(spots.SPOTS), before)
        self.assertNotIn(spot.key, spots.BY_KEY)
        self.assertTrue(spot.private)
        self.assertNotIn(spot.key, [s.key for s in spots.public_only()])

    def test_no_local_knowledge_is_invented(self):
        spot, _ = spots.at_coord(41.4520, -71.4050)
        self.assertEqual(spot.quality, {})
        self.assertIsNone(spot.best_stage)
        self.assertEqual(spot.prior("striped_bass"), 0.6)

    def test_thermometer_falls_back_to_the_tide_station(self):
        sp = spots.get("whale_rock")
        self.assertEqual(sp.thermometer, sp.tide_station)


class Windows(unittest.TestCase):
    """`windows` used to skip the first and last sample."""

    @staticmethod
    def _rows(n):
        base = datetime(2026, 8, 29, 1, 0)
        return [{"time": base + timedelta(minutes=30 * i)} for i in range(n)]

    def test_a_peak_at_the_start_is_still_a_window(self):
        """The most actionable window there is -- 'it is good right now and
        fading' -- always lands on sample zero. Excluding the endpoints
        reported a 68 at the top of the hour as no window at all, while
        happily reporting a 55 six hours out."""
        from tiderace.point import windows
        scores = [68.4, 68.0, 64.5, 58.2, 52.0, 48.4, 47.0, 46.9, 40.0, 38.0]
        rows = self._rows(len(scores))
        got = windows(rows, [{"score": v} for v in scores], threshold=45.0)
        self.assertTrue(got)
        self.assertEqual(got[0]["best"]["score"], 68.4)

    def test_nothing_below_threshold_is_reported(self):
        from tiderace.point import windows
        scores = [10.0] * 8
        got = windows(self._rows(8), [{"score": v} for v in scores], threshold=45.0)
        self.assertEqual(got, [])


class CatchLogCoordinates(unittest.TestCase):
    def test_entries_carry_coordinates(self):
        from tiderace import log as catchlog
        e = catchlog.Entry(spot="whale_rock", species="striped_bass",
                           started_at="2026-08-29T05:00", count=1)
        self.assertIsNone(e.lat)
        self.assertIn("lat", catchlog.EXTRACTION_SCHEMA)

    def test_a_known_spot_backfills_its_coordinate(self):
        """Spot keys can be renamed or retired; 41.4408,-71.4228 cannot. A log
        that only says 'whale_rock' cannot be grouped spatially later."""
        import json
        import tempfile
        from tiderace import log as catchlog
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.jsonl")
            e = catchlog.Entry(spot="whale_rock", species="striped_bass",
                               started_at="2026-08-29T05:00", count=0,
                               conditions={"current_speed": 1.0})
            catchlog.record(e, path)
            row = json.loads(open(path).read().strip())
            sp = spots.get("whale_rock")
            self.assertAlmostEqual(row["lat"], sp.lat)
            self.assertAlmostEqual(row["lon"], sp.lon)


class DepthLayer(unittest.TestCase):
    def setUp(self):
        from tiderace import charts
        self.charts = charts
        if not charts.load("depth_area"):
            self.skipTest("depth layer not cached — run: tiderace charts")

    def test_depth_survives_simplification(self):
        """The layer is simplified and sliver-filtered on write to keep the
        browser able to parse it. These bands are the check that the geometry
        is still describing the same water afterwards."""
        for lat, lon, lo, hi in ((41.4408, -71.4228, 49, 66),      # Whale Rock
                                 (41.4256, -71.3611, 66, 98),      # Brenton Reef
                                 (41.5750, -71.2967, 33, 49)):     # Dyer Island
            d = self.charts.depth_at(lat, lon)
            self.assertIsNotNone(d, f"{lat},{lon}")
            self.assertEqual((round(d["min_ft"]), round(d["max_ft"])), (lo, hi))

    def test_depth_is_an_overlay_but_land_is_not(self):
        self.assertIn("depth_area", self.charts.available())
        self.assertNotIn("land", self.charts.available())

    def test_simplification_keeps_rings_closed(self):
        gj = self.charts.load("depth_area")
        for f in gj["features"][:400]:
            for ring in f["geometry"]["coordinates"]:
                self.assertGreaterEqual(len(ring), 4)
                self.assertEqual(ring[0], ring[-1], "ring left open by simplify")

    def test_ramp_is_a_single_hue_stepped_light_to_dark(self):
        """The map's depth ramp is sequential, so it must be monotone in
        lightness -- a rainbow here would encode magnitude as identity."""
        import re
        html = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "tiderace", "web", "index.html")
        with open(html) as fh:
            src = fh.read()
        m = re.search(r"const DEPTH_RAMP = \[(.*?)\];", src, re.S)
        self.assertIsNotNone(m, "DEPTH_RAMP not found")
        ramp = re.findall(r"#([0-9A-Fa-f]{6})", m.group(1))
        self.assertEqual(len(ramp), 8)

        def lum(h):
            def lin(c):
                c /= 255
                return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

        lums = [lum(h) for h in ramp]
        self.assertEqual(lums, sorted(lums, reverse=True),
                         "depth ramp is not monotone light to dark")

class Reports(unittest.TestCase):
    """Third-party reports as seasonal evidence."""

    URL = "https://onthewater.com/fishing-reports/2026/08/ri-report"
    URL2 = "https://thefisherman.com/ri-report"

    def _rows(self, specs):
        """specs: (url, species_key, day[, who[, place]]) -> queue rows."""
        out = []
        for i, spec in enumerate(specs):
            u, k, d = spec[:3]
            who = spec[3] if len(spec) > 3 else ""
            place = spec[4] if len(spec) > 4 else "Point Judith"
            out.append({"kind": "catch_report", "species_key": k, "species_raw": k,
                        "observed_on": d, "source_url": u, "place": place,
                        "attributed_to": who, "queued_at": f"2026-08-28T00:00:{i:02d}",
                        "quote": "q", "confidence": "high"})
        return out

    def _load(self, specs):
        import unittest.mock as m
        with m.patch.object(reports.extract, "load_queue",
                            return_value=self._rows(specs)):
            return reports.catch_reports()

    def test_one_article_is_one_witness(self):
        # The invariant that matters. A weekly report naming a species in six
        # places is ONE observation, not six -- counting rows would manufacture
        # a consensus out of a single writer's week.
        # Six genuinely different places, one unattributed column: still one
        # witness, because one writer saw all six.
        rows = self._load([(self.URL, "tautog", "2026-08-27", "", p)
                           for p in ("a", "b", "c", "d", "e", "f")])
        self.assertEqual(len(rows), 6, "six distinct observations should load")
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 1, "one unattributed column is one witness")
        self.assertEqual(ev["observations"], 6)

    def test_separate_outlets_are_separate_witnesses(self):
        rows = self._load([(self.URL, "tautog", "2026-08-27"),
                           (self.URL2, "tautog", "2026-08-27")])
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 2)

    def test_undated_rows_are_dropped_not_defaulted(self):
        # Stamping an undated report with today would invent evidence about
        # exactly the thing this module exists to measure.
        rows = self._load([(self.URL, "tautog", None),
                           (self.URL, "scup", "2026-08-27")])
        self.assertEqual([r["species"] for r in rows], ["scup"])

    def test_silence_is_not_absence(self):
        rows = self._load([(self.URL, "scup", "2026-08-27")])
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 0)
        self.assertEqual(ev["verdict"], "no recent report")

    def test_stale_reports_do_not_describe_now(self):
        rows = self._load([(self.URL, "tautog", "2026-06-01")])
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 0, "a June report is not evidence about August")

    def test_species_normalization_maps_report_names(self):
        for name, want in (("summer flounder", "fluke"), ("Striped Bass", "striped_bass"),
                           ("porgies", "scup"), ("blackfish", "tautog"), ("tog", "tautog")):
            self.assertEqual(extract.normalize_species(name)[0], want, name)

    def test_one_column_can_hold_several_witnesses(self):
        # A single On The Water column quotes Ocean State Tackle in one
        # paragraph and The Saltwater Edge in the next. Keying on the publisher
        # would call that one witness; it is two.
        rows = self._load([(self.URL, "tautog", "2026-08-27", "Ocean State Tackle", "a"),
                           (self.URL, "tautog", "2026-08-27", "The Saltwater Edge", "b")])
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 2)

    def test_two_magazines_relaying_one_shop_is_one_witness(self):
        # The failure that actually matters: RI magazines all phone the same
        # shops, so counting publishers would manufacture agreement.
        rows = self._load([(self.URL, "tautog", "2026-08-27", "Snug Harbor Marina"),
                           (self.URL2, "tautog", "2026-08-27", "Snug Harbor")])
        ev = reports.corroborate("tautog", date(2026, 8, 28), rows)
        self.assertEqual(ev["witnesses"], 1, "same shop via two magazines is one witness")

    def test_person_at_shop_resolves_to_the_shop(self):
        rows = self._load([(self.URL, "scup", "2026-08-27", "Dave at Ocean State Tackle"),
                           (self.URL2, "scup", "2026-08-27", "Ocean State Tackle")])
        self.assertEqual(reports.corroborate("scup", date(2026, 8, 28), rows)["witnesses"], 1)

    def test_bare_first_names_do_not_merge_across_outlets(self):
        # Two different Daves would be false corroboration.
        rows = self._load([(self.URL, "scup", "2026-08-27", "Dave"),
                           (self.URL2, "scup", "2026-08-27", "Dave")])
        self.assertEqual(reports.corroborate("scup", date(2026, 8, 28), rows)["witnesses"], 2)

    def test_rescraping_an_article_does_not_add_witnesses(self):
        # The queue is append-only; a weekly re-run must not look like new
        # agreement from the same sentence.
        spec = (self.URL, "tautog", "2026-08-27", "Ocean State Tackle")
        ev = reports.corroborate("tautog", date(2026, 8, 28), self._load([spec, spec, spec]))
        self.assertEqual(ev["witnesses"], 1)
        self.assertEqual(ev["observations"], 1)

    def test_unmodelled_species_are_kept_not_dropped(self):
        # A bonito run is real information; the gap is in the scorer, not the report.
        rows = self._load([(self.URL, None, "2026-08-27")])
        rows[0]["species_raw"] = "bonito"
        self.assertEqual(reports.unmodelled(rows), {"bonito": 1})


class ReviewRegressions(unittest.TestCase):
    """Bugs found reviewing the coordinate-marks branch. Each one produced a
    plausible-looking answer rather than an obvious failure, which is why they
    survived to be found by reading rather than by running."""

    NOW = datetime(2026, 8, 28, 20, 0)

    def _row(self, days, source, abundance="decent"):
        return {"bait": "bunker", "lat": 41.44, "lon": -71.42,
                "when": (self.NOW - timedelta(days=days)).isoformat(),
                "abundance": abundance, "confidence": "high", "source": source}

    def test_the_two_corroboration_weights_stay_separate(self):
        """`CORROBORATION` was defined twice in bait.py: 0.10 for bait agreeing
        with bait, then 0.30 for bait agreeing with birds. The second silently
        replaced the first, so every corroborated bait signal was boosted by 3x
        the documented amount and the two could not be tuned apart."""
        self.assertAlmostEqual(bait.CORROBORATION, 0.10)
        self.assertAlmostEqual(bait.CONJUNCTION, 0.30)
        self.assertNotEqual(bait.CORROBORATION, bait.CONJUNCTION)

    def test_corroboration_is_bounded_by_its_own_weight(self):
        one = bait.bait_at(41.44, -71.42, self.NOW, "striped_bass",
                           [self._row(0, "own")])["signal"]
        two = bait.bait_at(41.44, -71.42, self.NOW, "striped_bass",
                           [self._row(0, "own"), self._row(0, "report")])["signal"]
        self.assertGreater(two, one)
        self.assertLessEqual(two, one * (1 + bait.CORROBORATION * bait.MAX_CORROBORATION))

    def test_only_witnesses_that_scored_are_named(self):
        """`sources` was built from every row in the log, including ones too
        old or too far to contribute. Provenance then reported 'you saw it +
        a report said so' when only the report carried any weight -- an
        agreement claim about evidence that was never used."""
        rows = [self._row(0, "report"), self._row(400, "own")]   # decayed away
        b = bait.bait_at(41.44, -71.42, self.NOW, "striped_bass", rows)
        self.assertEqual(b["sources"], ["report"])

        from tiderace import provenance
        ag = provenance.agreement({"bait_sources": b["sources"], "bird_signal": 0})
        self.assertFalse(ag["corroborated"])
        self.assertEqual(ag["count"], 1)

    def test_bird_signal_decays_across_the_horizon(self):
        """Birds were scored once against now() and stamped on all 96 rows, so
        a forecast two days out rested on undiscounted evidence from today
        while the bait beside it decayed properly."""
        derived = [{"bait": "bunker", "lat": 41.44, "lon": -71.42,
                    "when": self.NOW.isoformat(), "abundance": "loaded",
                    "confidence": "medium", "source": "ebird"}]
        now = birds.signal_at(41.44, -71.42, "striped_bass",
                              when=self.NOW, derived=derived)["signal"]
        later = birds.signal_at(41.44, -71.42, "striped_bass",
                                when=self.NOW + timedelta(days=2),
                                derived=derived)["signal"]
        self.assertGreater(now, 0)
        self.assertLess(later, now)

    def test_a_half_open_depth_range_does_not_crash(self):
        """S-57 carries DRVAL1 and DRVAL2 independently; the deepest area on a
        chart has no deep limit. Formatting the missing end raised TypeError
        and took out the whole `at` report, or rendered "30-0 ft"."""
        from tiderace.cli import _depth_range
        self.assertIsNone(_depth_range(None))
        self.assertIsNone(_depth_range({}))
        self.assertEqual(_depth_range({"min_ft": 12.4, "max_ft": 30.2}),
                         "12\u201330 ft")
        self.assertEqual(_depth_range({"min_ft": 30.2, "max_ft": None}), "30+ ft")
        self.assertEqual(_depth_range({"min_ft": None, "max_ft": 2.1}),
                         "less than 2 ft")

    def test_a_dropped_minus_sign_is_said_out_loud(self):
        """71.42 instead of -71.42 parsed clean, bound to whichever NOAA
        station was least far away, and produced a confident-looking forecast
        with nothing marking it as nonsense. It still parses -- somebody may
        really be somewhere else -- but it no longer passes quietly."""
        from tiderace import stations
        try:
            cat = stations.catalog()
        except stations.StationError:
            self.skipTest("station catalog not cached")
        lat, lon = spots.parse_coord("41.4408,71.4228")
        self.assertEqual(lon, 71.4228)                  # parsed, not refused

        res = stations.resolve(lat, lon, cat)
        self.assertTrue(res["no_stations_near"])
        self.assertEqual(res["confidence"], "poor")
        self.assertTrue(any("minus sign" in w for w in res["warnings"]),
                        res["warnings"])

    def test_a_mark_on_another_coast_still_works(self):
        """The bay is where the data is, not where the code stops. A mark
        outside it gets the nearest real stations, a poor confidence and a
        warning -- not an exception."""
        from tiderace import stations
        try:
            cat = stations.catalog()
        except stations.StationError:
            self.skipTest("station catalog not cached")
        res = stations.resolve(37.81, -122.45, cat)     # Golden Gate
        # NOAA is national, so there are real stations here -- what is missing
        # is the coastline, and only that should be complained about.
        self.assertTrue(res["off_chart"])
        self.assertFalse(res["no_stations_near"])
        self.assertIsNotNone(res["current"])
        self.assertLess(res["current"]["distance_nm"], 20)
        self.assertEqual(res["confidence"], "poor")
        # The RI-only land test must not claim knowledge it does not have.
        self.assertIsNone(res["on_land"])
        self.assertTrue(any("no coastline" in w for w in res["warnings"]),
                        res["warnings"])

    def test_off_chart_marks_skip_the_land_geometry(self):
        """Not just for speed: the chart layers cover one bay, so out there
        every land test can only return 'don't know' at a cost of seconds."""
        from tiderace import stations
        try:
            cat = stations.catalog()
        except stations.StationError:
            self.skipTest("station catalog not cached")
        self.assertLess(stations.FAR_NM, stations.NO_STATIONS_NM)
        import time
        t0 = time.monotonic()
        stations.resolve(35.0, 139.0, cat)              # Tokyo Bay
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_a_success_clears_the_negative_cache(self):
        """One transient timeout wrote a .miss marker that was never removed,
        so the URL stayed suppressed for 12 hours -- and the negcache was
        checked before the stale-body fallback, so a good cached scene was
        thrown away along with the bad news."""
        from tiderace import offshore
        import inspect
        src = inspect.getsource(offshore._get)
        self.assertIn('os.remove(p + ".miss")', src)
        neg = src.index("if _negcache(p):")
        raise_at = src.index('raise OffshoreError("recently unavailable', neg)
        self.assertIn("return fh.read()", src[neg:raise_at])

    def test_depth_polygons_survive_an_empty_ring(self):
        """land_index guarded `not poly`; depth_index did not, so a single
        empty coordinate array was an IndexError that killed every depth
        lookup on the map."""
        from tiderace import charts
        empty = charts._polygons({"type": "MultiPolygon", "coordinates": [[]]})
        self.assertEqual(empty, [[]])
        for poly in empty:                    # the guard, as the index runs it
            self.assertFalse(poly and len(poly[0]) >= 3)
        import inspect
        self.assertIn("if not poly or len(poly[0]) < 3:",
                      inspect.getsource(charts.depth_index))

    def test_chart_layers_are_parsed_once(self):
        """structure_near walks five layers per report and reparsed ~770 KB of
        GeoJSON every time."""
        from tiderace import charts
        if not charts.available():
            self.skipTest("no chart layers cached -- run: tiderace charts")
        name = charts.available()[0]
        self.assertIs(charts.load(name), charts.load(name))

    def test_one_ebird_query_serves_every_spot(self):
        """Twenty-one spots meant twenty-one round trips describing the same
        40 km of water. eBird answers for a 50 km radius in one request, so a
        spot far enough inside an existing circle reuses it."""
        calls = []
        real = birds._get
        birds._get = lambda path, **kw: (calls.append(kw), real(path, **kw))[1]
        try:
            birds.forget_regions()
            targets = list(spots.for_species("striped_bass"))
            self.assertGreater(len(targets), 10)
            if not birds.prime([(s.lat, s.lon) for s in targets]):
                self.skipTest("spots too spread out for one circle")
            before = len(calls)
            for sp in targets:
                birds.sightings_near(sp.lat, sp.lon)
            self.assertEqual(len(calls) - before, 0, "priming should have covered them")
            self.assertLessEqual(len(calls), 1)
        finally:
            birds._get = real
            birds.forget_regions()

    def test_a_reused_query_still_reaches_every_relevant_sighting(self):
        """The reuse margin is not a guess: bait stops counting past MAX_NM,
        so a spot within (radius - MAX_NM) of the centre sees exactly what a
        query centred on it would have."""
        self.assertAlmostEqual(birds.region_reuse_km(),
                               birds.REGION_KM - bait.MAX_NM * 1.852, places=6)
        self.assertGreater(birds.region_reuse_km(), 0)
        # A spot at the edge of the margin must not reuse a circle that would
        # miss bait on its far side.
        self.assertGreater(birds.REGION_KM - birds.region_reuse_km(),
                           bait.MAX_NM * 1.852 - 0.001)

    def test_a_wide_query_keeps_more_than_eight_hotspots(self):
        """Eight was fine for one spot's 25 km circle. Across the whole bay it
        would let a hotspot beside one spot be squeezed out by bigger ones
        beside another."""
        self.assertGreater(birds.REGION_LIMIT, 8)

    def test_the_region_cache_expires(self):
        """`tiderace serve` runs for days; a cache with no expiry would pin one
        afternoon's birds to every forecast after it."""
        import inspect
        src = inspect.getsource(birds.sightings_near)
        self.assertIn("CACHE_TTL", src)

    def test_no_chart_data_is_not_reported_as_clear_water(self):
        """'nothing charted within 500 yds' is a finding. Outside the cached
        bay there is no chart to be empty, and printing the finding anyway
        reads as clear water over a reef."""
        from tiderace import charts
        self.assertTrue(charts.covers(41.4408, -71.4228))
        self.assertFalse(charts.covers(37.81, -122.45))
        self.assertFalse(charts.covers(41.4408, 71.4228))
        import inspect
        from tiderace import cli
        self.assertIn("no chart data for this area", inspect.getsource(cli))
        with open(os.path.join(os.path.dirname(charts.__file__),
                               "web", "index.html")) as fh:
            self.assertIn("pl.charted === false", fh.read())

    def test_hms_staleness_honours_the_date_asked_about(self):
        """`when` was defaulted and then never used."""
        from tiderace import hms
        far = hms.status("bluefin",
                         hms.CHECKED_ON + timedelta(days=hms.STALE_AFTER_DAYS + 5))
        near = hms.status("bluefin", hms.CHECKED_ON + timedelta(days=1))
        self.assertTrue(far["stale"])
        self.assertFalse(near["stale"])
        self.assertEqual(near["days_since_checked"], 1)


class Whales(unittest.TestCase):
    """Cetaceans as a bait proxy, one notch stronger than birds."""

    def test_a_lunge_feeder_outranks_a_resident_dolphin(self):
        # The whole argument for the layer: a humpback does not commit to thin
        # bait, an inshore bottlenose eats scattered fish all day.
        self.assertGreater(whales.BAIT_WHALES["Humpback Whale"],
                           whales.BAIT_WHALES["Common Bottlenose Dolphin"])
        self.assertGreater(whales.BAIT_WHALES["Humpback Whale"],
                           whales.BAIT_WHALES["Common Minke Whale"])

    def test_whales_imply_more_bait_than_birds(self):
        self.assertGreater(whales.WHALE_DISCOUNT, birds.BIRD_DISCOUNT)
        self.assertLess(whales.WHALE_DISCOUNT, 1.0,
                        "still an inference, never a look at the bait")

    def test_every_weighted_animal_has_an_implied_bait_entry(self):
        for sp in whales.BAIT_WHALES:
            self.assertIn(sp, whales.WHALE_IMPLIES_BAIT, f"{sp} has no diet entry")

    def test_implied_baits_are_baits_the_model_knows(self):
        known = set()
        for d in bait.RELEVANCE.values():
            known |= set(d)
        for sp, b in whales.WHALE_IMPLIES_BAIT.items():
            if b is not None:
                self.assertIn(b, known, f"{sp} implies unknown bait {b}")

    def test_sharks_are_deliberately_not_a_taxon_we_query(self):
        # Checked, not assumed: the RI shark records are skates and rays.
        # Guard the decision so it is not quietly reinstated.
        for name in whales.BAIT_WHALES:
            self.assertNotIn("Shark", name)
        self.assertNotIn(47273, (whales.RORQUALS, whales.DOLPHINS))

    def test_right_whales_are_not_a_fishing_signal(self):
        self.assertNotIn("North Atlantic Right Whale", whales.BAIT_WHALES)
        self.assertNotIn(whales.RIGHT_WHALE, (whales.RORQUALS, whales.DOLPHINS))

    def test_proxies_rank_rather_than_add(self):
        # Birds and whales are two readings of one inference. Adding them would
        # manufacture confidence out of correlated evidence.
        both, kind = bait.proxy_signal(0.6, 0.6)
        self.assertLess(both, 1.2)
        self.assertGreater(both, 0.6, "two predators beat one")
        self.assertEqual(kind, "birds_and_whales")

    def test_proxy_is_symmetric_and_led_by_the_stronger(self):
        self.assertEqual(bait.proxy_signal(0.6, 0.2)[0],
                         bait.proxy_signal(0.2, 0.6)[0])
        self.assertEqual(bait.proxy_signal(0.0, 0.5)[1], "whales")
        self.assertEqual(bait.proxy_signal(0.5, 0.0)[1], "birds")

    def test_whales_share_the_bait_origin_with_birds(self):
        # Independence check: agreement between them must not read as two
        # separate witnesses converging.
        self.assertEqual(provenance.MODIFIERS["whales"][2],
                         provenance.MODIFIERS["birds"][2], "shared origin")
        self.assertEqual(provenance.MODIFIERS["birds_and_whales"][2], "bait")

    def test_obscured_records_are_dropped(self):
        import unittest.mock as m
        payload = {"results": [
            {"id": 1, "location": "41.1,-71.5", "obscured": True,
             "taxon": {"preferred_common_name": "Humpback Whale"},
             "observed_on": "2026-08-24", "quality_grade": "research"},
            {"id": 2, "location": "41.2,-71.6", "geoprivacy": "obscured",
             "taxon": {"preferred_common_name": "Fin Whale"},
             "observed_on": "2026-08-24", "quality_grade": "research"},
            {"id": 3, "location": "41.3,-71.7",
             "taxon": {"preferred_common_name": "Humpback Whale"},
             "observed_on": "2026-08-24", "quality_grade": "research"},
        ]}
        with m.patch.object(whales, "_get", return_value=payload):
            got = whales.sightings(41.2, -71.6, taxa=(whales.RORQUALS,))
        self.assertEqual([o["url"].rsplit("/", 1)[1] for o in got], ["3"])

    def test_unverified_records_are_low_confidence(self):
        import unittest.mock as m
        payload = {"results": [
            {"id": 9, "location": "41.3,-71.7",
             "taxon": {"preferred_common_name": "Humpback Whale"},
             "observed_on": "2026-08-24", "quality_grade": "needs_id"},
        ]}
        with m.patch.object(whales, "_get", return_value=payload):
            d = whales.derived_sightings(41.3, -71.7, taxa_days := 7)
        self.assertEqual(d[0]["confidence"], "low")
        self.assertEqual(d[0]["bait"], "sand eels")


class Protected(unittest.TestCase):
    """Right whale rules. Constraints, never inputs to a score."""

    WINDMILLS = (41.12, -71.50)
    CHARLESTOWN = (41.3720, -71.6390)

    def test_the_wind_farm_is_inside_the_block_island_sma(self):
        got = [a["name"] for a in protected.areas_at(*self.WINDMILLS)]
        self.assertIn("Block Island Sound", got)

    def test_the_bay_shore_is_outside_it(self):
        self.assertEqual(protected.areas_at(*self.CHARLESTOWN), [])

    def test_the_season_wraps_the_new_year(self):
        # Block Island Sound runs Nov 1 - Apr 30. A season that wraps is the
        # easy one to get backwards and it would read as always-off.
        for when, want in ((date(2026, 12, 15), True), (date(2026, 2, 1), True),
                           (date(2026, 4, 30), True), (date(2026, 8, 30), False),
                           (date(2026, 5, 1), False), (date(2026, 11, 1), True)):
            a = protected.advisory(*self.WINDMILLS, on=when)
            self.assertEqual(a["in_active_sma"], want, str(when))

    def test_an_out_of_season_area_is_reported_not_hidden(self):
        a = protected.advisory(*self.WINDMILLS, on=date(2026, 8, 30))
        self.assertFalse(a["in_active_sma"])
        self.assertTrue(a["areas"], "should still say you are in the polygon")
        self.assertIn("out of season", " ".join(protected.describe(a)))

    def test_the_approach_rule_applies_regardless_of_area_or_season(self):
        # 500 yards is the one that actually binds a small boat, everywhere.
        for lat, lon in (self.WINDMILLS, self.CHARLESTOWN, (25.0, -80.0)):
            a = protected.advisory(lat, lon, on=date(2026, 8, 30))
            self.assertEqual(a["approach_yards"], 500)
            self.assertIn("500 yards", a["rules"][0])

    def test_the_speed_rule_is_not_claimed_to_bind_a_small_boat(self):
        small = protected.advisory(*self.WINDMILLS, on=date(2026, 12, 15),
                                   vessel_loa_ft=28)
        big = protected.advisory(*self.WINDMILLS, on=date(2026, 12, 15),
                                 vessel_loa_ft=70)
        self.assertIs(small["speed_rule_binds"], False)
        self.assertIs(big["speed_rule_binds"], True)
        self.assertIn("not to yours", " ".join(small["rules"]))

    def test_unknown_vessel_size_does_not_guess(self):
        a = protected.advisory(*self.WINDMILLS, on=date(2026, 12, 15))
        self.assertIsNone(a["speed_rule_binds"])

    def test_right_whales_are_never_a_scoring_input(self):
        # The whole point of a separate module. A protected species must not be
        # able to raise a number anywhere.
        import inspect
        src = inspect.getsource(protected)
        for banned in ("PROFILES", "score(", "modifier", "signal_at"):
            self.assertNotIn(banned, src, f"protected.py must not touch {banned}")
        self.assertNotIn("right", str(whales.BAIT_WHALES).lower())


class Survey(unittest.TestCase):
    """Everything at one place and time, each value with its own footprint."""

    def test_zones_band_the_water(self):
        self.assertEqual(survey.zone(41.72, -71.34), survey.INSHORE)   # Conimicut
        self.assertEqual(survey.zone(41.44, -71.42), survey.MIDBAY)    # Whale Rock
        self.assertEqual(survey.zone(41.12, -71.50), survey.OFFSHORE)  # wind farm

    def test_a_shallow_southern_mark_is_not_called_offshore(self):
        # Depth overrides latitude: a 30 ft mark south of the line is still
        # bay-like water and river discharge is still irrelevant there.
        self.assertEqual(survey.zone(41.20, -71.60, depth_ft=30), survey.MIDBAY)
        self.assertEqual(survey.zone(41.20, -71.60, depth_ft=120), survey.OFFSHORE)

    def test_resolutions_span_orders_of_magnitude(self):
        # The reason every value carries a footprint at all.
        self.assertLess(survey.RES["sounding"], survey.RES["station"])
        self.assertLess(survey.RES["station"], survey.RES["nws_grid"])
        self.assertLess(survey.RES["nws_grid"], survey.RES["hf_radar"])
        self.assertGreater(survey.RES["hf_radar"] / survey.RES["sounding"], 1000)

    def test_a_layer_failing_does_not_take_the_survey_down(self):
        boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("satellite down"))
        val, err = survey._try(boom)
        self.assertIsNone(val)
        self.assertIn("satellite down", err)

    def test_a_missing_layer_is_reported_missing_not_zero(self):
        val, err = survey._try(lambda: (_ for _ in ()).throw(OSError("no net")))
        self.assertIsNone(val, "must be None, never 0 — a dead feed is not calm water")
        self.assertTrue(err)

    def test_every_datum_carries_its_source_and_footprint(self):
        d = survey._d(3.2, "NDBC", survey.RES["buoy"], "measured")
        self.assertEqual(set(d), {"value", "source", "resolution_m", "note", "when"})
        self.assertEqual(d["resolution_m"], 100)


class AtomicCache(unittest.TestCase):
    """A reader must never see a half-written cache file.

    This is not hypothetical: `tiderace serve` runs on the tailnet while you
    also use the CLI, and a reader catching an iNaturalist cache mid-write made
    the map's own /api/grid return a 500 with a JSON error at an 8 KB boundary.
    Nothing was wrong with the grid.
    """

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def test_a_reader_never_sees_a_partial_file(self):
        import json, os, threading
        path = os.path.join(self.dir, "c.json")
        cachemod.write_json(path, {"seq": 0, "pad": "x" * 5000})
        stop, seen = threading.Event(), []

        def reader():
            while not stop.is_set():
                try:
                    with open(path) as fh:
                        seen.append(json.load(fh)["seq"])
                except FileNotFoundError:
                    pass
                except ValueError:
                    seen.append("PARTIAL")

        t = threading.Thread(target=reader, daemon=True); t.start()
        for n in range(1, 60):
            cachemod.write_json(path, {"seq": n, "pad": "x" * (5000 + n)})
        stop.set(); t.join(timeout=3)
        self.assertNotIn("PARTIAL", seen, "a reader observed a torn write")

    def test_a_corrupt_file_reads_as_absent_not_an_exception(self):
        import os
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w") as fh:
            fh.write('{"truncated": ')
        self.assertIsNone(cachemod.read_json(path))
        self.assertEqual(cachemod.read_json(path, default={}), {})

    def test_a_failed_write_leaves_no_temp_litter(self):
        import os
        path = os.path.join(self.dir, "x.json")

        class Unserialisable:
            pass
        # default=str makes almost anything serialise, so force a real failure.
        boom = {"k": Unserialisable()}
        boom["self"] = boom                      # circular -> ValueError
        with self.assertRaises(ValueError):
            cachemod.write_json(path, boom)
        leftovers = [f for f in os.listdir(self.dir) if f.startswith(".tmp-")]
        self.assertEqual(leftovers, [], "temp file left behind after a failure")

    def test_every_cache_write_in_the_project_goes_through_here(self):
        # Guard against the pattern creeping back in.
        import pathlib, re
        root = pathlib.Path(__file__).parent / "tiderace"
        offenders = []
        for f in root.glob("*.py"):
            if f.name in ("cache.py", "log.py", "bait.py", "extract.py", "config.py"):
                continue                          # append-only logs, not caches
            src = f.read_text()
            if re.search(r'with open\([^)]*,\s*"w[b]?"\) as \w+:\s*\n\s*(json\.dump|\w+\.write)', src):
                offenders.append(f.name)
        self.assertEqual(offenders, [], "non-atomic cache write reintroduced")


class TilePolicy(unittest.TestCase):
    """The OSM tile usage policy, enforced in the repo rather than remembered.

    It forbids "any pre-emptive fetching of tiles other than those a user is
    actively viewing" and says violators are blocked without notice. A block
    would remove the basemap entirely, on the water -- far worse than having no
    offline tiles. So caching what was viewed is fine and pre-seeding is not,
    and that line is easy to erase later with one well-meaning loop.
    """

    def setUp(self):
        import pathlib
        self.sw = (pathlib.Path(__file__).parent
                   / "tiderace" / "web" / "sw.js").read_text()
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()

    def test_tiles_are_cached_but_never_prefetched(self):
        self.assertIn("TILES", self.sw, "tile cache should exist")
        self.assertIn("async function tile(", self.sw)
        # The offline bundle must not contain a tile URL template. If one ever
        # appears there, something is generating tile requests ahead of use.
        for marker in ("{z}/{x}/{y}", "tile.openstreetmap.org/", "tiles.openseamap.org/"):
            self.assertNotIn(
                marker, self.page.split("function saveForOffline")[-1][:4000],
                f"the dock bundle must not build tile URLs ({marker})")

    def test_the_policy_reason_is_written_down_not_just_obeyed(self):
        # A silent constraint gets removed by whoever does not know why.
        low = self.sw.lower()
        self.assertTrue("policy" in low and "pre-emptive" in low,
                        "sw.js should say why tiles are not pre-fetched")

    def test_tile_cache_is_bounded(self):
        import re
        m = re.search(r"TILE_MAX = (\d+)", self.sw)
        self.assertTrue(m, "tile cache must have a cap")
        self.assertLessEqual(int(m.group(1)), 8000, "cap too large for a phone")
        z = re.search(r"TILE_MAX_ZOOM = (\d+)", self.sw)
        self.assertTrue(z, "tile cache must have a zoom ceiling")
        # z16 over this bay is ~570 MB; the ceiling exists to make that
        # unreachable by accident.
        self.assertLessEqual(int(z.group(1)), 15)


class Basemap(unittest.TestCase):
    """The offline vector basemap and the range serving it depends on."""

    def test_range_parsing_covers_the_forms_pmtiles_uses(self):
        # PMTiles reads a header, then directory pages, then tiles -- all by
        # byte offset. Suffix ranges are used to find the footer.
        import re as _re
        pat = _re.compile(r"bytes=(\d*)-(\d*)$")
        for header, want in (("bytes=0-16383", ("0", "16383")),
                             ("bytes=100-", ("100", "")),
                             ("bytes=-2048", ("", "2048"))):
            m = pat.match(header)
            self.assertIsNotNone(m, header)
            self.assertEqual(m.groups(), want)
        self.assertIsNone(pat.match("bytes=abc-def"))
        self.assertIsNone(pat.match("items=0-10"))

    def test_the_archive_is_never_gzipped(self):
        # Ranges are byte offsets into the file. Compressing the body would
        # make every offset refer to something else, and the failure would look
        # like a corrupt archive rather than a server bug.
        import pathlib as _p
        src = (_p.Path(__file__).parent / "tiderace" / "server.py").read_text()
        body = src.split("def _pmtiles")[1].split("def _send_json")[0]
        # Strip the docstring: it says the word "gzip" precisely to explain why
        # the code must not call it, and matching prose is not a test.
        code = body.split('"""')[2] if body.count('"""') >= 2 else body
        self.assertNotIn("gzip", code, "the archive must be served uncompressed")
        self.assertIn("Accept-Ranges", body)
        self.assertIn("Content-Range", body)

    def test_the_page_gets_its_basemap_choice_synchronously(self):
        # The style must exist when the Map is constructed; awaiting a fetch
        # would race every layer added on 'load'.
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        self.assertIn("__TIDERACE_BASEMAP__", page)
        self.assertLess(page.index("const BASEMAP"), page.index("new maplibregl.Map"))

    def test_layer_anchor_works_for_both_basemaps(self):
        # The raster style has one layer called 'osm'; the vector style has ~70
        # from a Protomaps flavor. 'seamark' is the one both put on top.
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        fn = page.split("function ABOVE_BASEMAP")[1].split("\n}")[0]
        # Drop comment lines: they mention 'osm' precisely to explain why the
        # code no longer leads with it, and twice now I have written a test
        # that matched the prose instead of the logic.
        code = "\n".join(l for l in fn.splitlines()
                         if not l.strip().startswith("//"))
        self.assertIn("seamark", code, "anchor must not depend on the raster layer")
        self.assertLess(code.index("seamark"), code.index("'osm'"),
                        "seamark must be tried first — the vector style has no 'osm'")

    def test_a_missing_extract_is_a_normal_state(self):
        # A fresh clone has never run `tiderace basemap`. That must return None
        # so the map falls back to the hosted API, not raise.
        import unittest.mock as m
        from tiderace import server as srv
        with m.patch.object(srv, "BASEMAP_DEFAULT", "/nope/also-missing.pmtiles"):
            self.assertIsNone(srv._basemap_path({"pmtiles_path": "/nope/missing.pmtiles"}))
            self.assertIsNone(srv._basemap_path({}))

    def test_a_configured_extract_wins_over_the_default(self):
        import tempfile, unittest.mock as m
        from tiderace import server as srv
        with tempfile.NamedTemporaryFile(suffix=".pmtiles") as fh:
            with m.patch.object(srv, "BASEMAP_DEFAULT", "/nope/missing.pmtiles"):
                self.assertEqual(srv._basemap_path({"pmtiles_path": fh.name}),
                                 os.path.abspath(fh.name))


class SurveyRendering(unittest.TestCase):
    """Values that are dicts must be formatted, not stringified.

    `bottom` shipped to the phone as "[object Object]". The renderer treated a
    {bottom, quality, distance_nm} record as a scalar, and nothing caught it
    because the survey tests check the data layer and never the drawing.
    """

    def setUp(self):
        import pathlib
        root = pathlib.Path(__file__).parent
        self.page = (root / "tiderace" / "web" / "index.html").read_text()
        self.cli = (root / "tiderace" / "cli.py").read_text()

    def test_no_layer_whose_value_is_a_dict_is_rendered_raw(self):
        # Every survey layer that returns a record needs a field pulled out of
        # it. Passing the object itself is the bug that shipped.
        sheet = self.page.split("function render(d)")[1][:4000]
        for layer in ("bottom", "surface_current", "water_level_anomaly", "buoy"):
            self.assertNotRegex(
                sheet, r"row\('" + layer + r"',\s*(val\('" + layer + r"'\)|\w+),\s*res",
                f"{layer} looks like it is rendered as a bare object")

    def test_bottom_shows_its_distance(self):
        # "rock" underfoot and "rock" a fifth of a mile away are different
        # claims, and the survey is supposed to be honest about footprints.
        self.assertIn("distance_nm", self.page.split("const bt = val('bottom')")[1][:400])
        self.assertIn("distance_nm", self.cli.split('L.get("bottom")')[1][:400])


class CoordinateLogging(unittest.TestCase):
    """Logging a trip at a tapped coordinate, not just at a named spot.

    The coordinate is the scarce half of a log entry. A spot name drifts --
    "the reef" is four different rocks over a season -- but 41.4587,-71.3914
    does not, and a fitted model can only group on the number.
    """

    def test_a_bare_coordinate_becomes_a_stable_spot_key(self):
        from tiderace.server import Handler
        e = Handler._entry({"lat": 41.4587, "lon": -71.3914,
                            "species": "striped_bass", "count": 2})
        self.assertEqual(e.spot, "at:41.45870,-71.39140")
        self.assertEqual((e.lat, e.lon), (41.4587, -71.3914))

    def test_the_key_is_rounded_so_the_same_tap_groups_together(self):
        # Five decimal places is about a metre. Without rounding, two taps on
        # the same rock would be two different "spots" forever.
        from tiderace.server import Handler
        a = Handler._entry({"lat": 41.45870001, "lon": -71.39140002,
                            "species": "scup", "count": 0})
        b = Handler._entry({"lat": 41.4587, "lon": -71.3914,
                            "species": "scup", "count": 0})
        self.assertEqual(a.spot, b.spot)

    def test_a_named_spot_still_wins_over_the_coordinate(self):
        from tiderace.server import Handler
        e = Handler._entry({"spot": "whale_rock", "lat": 41.44, "lon": -71.42,
                            "species": "striped_bass", "count": 1})
        self.assertEqual(e.spot, "whale_rock")

    def test_an_entry_with_neither_is_refused(self):
        from tiderace.server import Handler
        with self.assertRaises(ValueError):
            Handler._entry({"species": "striped_bass", "count": 1})

    def test_the_sheet_posts_a_coordinate_not_a_spot_key(self):
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        # Whole function, not a fixed slice: I have now written this test three
        # times with a character window that later edits pushed the assertion
        # past, which fails green-to-red for no reason but the window.
        body = page.split("function wireLog")[1].split("\n  }")[0]
        self.assertIn("lat: d.lat", body)
        self.assertIn("lon: d.lon", body)
        self.assertNotIn("spot:", body,
                         "the sheet must not invent a spot key — the server mints it")

    def test_the_form_survives_being_offline(self):
        # A trip you did not record is gone; one that has not synced is fine.
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        body = page.split("function wireLog")[1].split("\n  }")[0]
        self.assertLess(body.index("queueAdd"), body.index("flushQueue"),
                        "must write to the phone before trying the network")

    def test_inputs_do_not_trigger_ios_zoom(self):
        # Below 16px Safari zooms the page on focus and the map goes with it.
        import pathlib as _p, re
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        # Wide enough to clear the comment explaining the rule; the browser
        # reports 16px, so a miss here is the window being too small.
        css = page.split("#slogform input")[1].split("}")[0]
        m = re.search(r"font-size:\s*(\d+)px", css)
        self.assertTrue(m, "log inputs need an explicit font-size")
        self.assertGreaterEqual(int(m.group(1)), 16)


class ChartCoverage(unittest.TestCase):
    """The box the chart layers are cut to, and the fields that survive."""

    def test_the_box_covers_the_water_actually_fished(self):
        from tiderace import charts
        x0, y0, x1, y1 = charts.BAY_BBOX
        for name, lat, lon in (("Charlestown Breachway", 41.372, -71.639),
                               ("Block Island wind farm", 41.12, -71.50),
                               ("Block Island", 41.17, -71.58),
                               ("Whale Rock", 41.44, -71.42),
                               ("Conimicut", 41.72, -71.34)):
            self.assertTrue(x0 <= lon <= x1 and y0 <= lat <= y1,
                            f"{name} falls outside the charted box")

    def test_soundings_carry_their_depth(self):
        # 25,895 soundings with no depth on any of them is what shipped:
        # _clean only read VALSOU, and the soundings layer uses Z.
        from tiderace import charts
        for field in ("VALSOU", "Z", "VALDCO"):
            # _clean returns a whole feature, not a bare property bag.
            props = charts._clean({"properties": {field: 10.0}})["properties"]
            self.assertEqual(props.get("depth_m"), 10.0, f"{field} not read")
            self.assertAlmostEqual(props.get("depth_ft"), 32.8, places=1)

    def test_line_geometry_is_thinned_like_polygons(self):
        # Contours were 6.4 MB because _thin knew about polygons and points
        # only, so line coordinates were never even rounded.
        from tiderace import charts
        gj = {"features": [{"geometry": {"type": "LineString",
              "coordinates": [[-71.123456789, 41.123456789],
                              [-71.223456789, 41.223456789]]}}]}
        out = charts._thin(gj, None)
        for x, y in out["features"][0]["geometry"]["coordinates"]:
            self.assertLessEqual(len(str(x).split(".")[1]), charts.COORD_PLACES)

    def test_the_heaviest_layers_are_not_fetched_on_boot(self):
        import pathlib as _p, re
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        self.assertIn("st.lazy && !CHART_ON[l.name]", page)
        # Both the ones that are off by default and large.
        for layer in ("soundings", "depth_area"):
            blk = page.split(f"  {layer}: {{")[1][:200]
            self.assertIn("lazy: true", blk, f"{layer} should be deferred")

    def test_contours_are_the_default_not_the_shading(self):
        """Depth areas paint a band -- "18 to 30 feet somewhere in here" -- and
        tile every square metre, hiding the basemap and the edges that matter.
        A contour is the edge, and carries its own number. Shading is also
        bounded to the original bay box, while contours come from the on-demand
        grid and follow you offshore."""
        import pathlib as _p, re
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        on = page.split("const CHART_ON = {")[1].split("};")[0]
        self.assertRegex(on, r"contours\s*:\s*true")
        self.assertRegex(on, r"depth_area\s*:\s*false")


class DoubleTap(unittest.TestCase):
    """A double-tap on save must not become two trips.

    This is not hypothetical. Two fluke were logged at Second Beach and a blank
    landed at the same coordinate three seconds later, in a catch log that had
    three entries in it -- a third of the scarcest data in the project, created
    by one stray tap.
    """

    def setUp(self):
        import tempfile, os
        self.path = os.path.join(tempfile.mkdtemp(), "log.jsonl")

    def _entry(self, count, spot="at:41.45040,-71.31600", species="fluke"):
        from tiderace import log as catchlog
        return catchlog.Entry(spot=spot, species=species, count=count,
                              started_at="2026-08-30T22:00", conditions={"x": 1})

    def test_the_exact_incident_is_refused(self):
        from tiderace import log as catchlog
        catchlog.record(self._entry(2), self.path)
        with self.assertRaises(catchlog.DuplicateEntry):
            catchlog.record(self._entry(0), self.path)     # the accidental blank
        self.assertEqual(len(catchlog.load(self.path)), 1)

    def test_count_is_not_part_of_the_match(self):
        # A rule keyed on matching counts would have missed the only case it
        # exists to catch: the stray tap wrote 0 where the real trip wrote 2.
        from tiderace import log as catchlog
        catchlog.record(self._entry(2), self.path)
        for n in (0, 1, 2, 7):
            with self.assertRaises(catchlog.DuplicateEntry):
                catchlog.record(self._entry(n), self.path)

    def test_a_different_species_at_the_same_spot_is_a_real_trip(self):
        from tiderace import log as catchlog
        catchlog.record(self._entry(2), self.path)
        catchlog.record(self._entry(1, species="scup"), self.path)
        self.assertEqual(len(catchlog.load(self.path)), 2)

    def test_two_drifts_an_hour_apart_both_survive(self):
        # The guard must not eat a genuine second session on the same water.
        from datetime import datetime, timedelta
        from tiderace import log as catchlog
        catchlog.record(self._entry(2), self.path)
        rows = catchlog.load(self.path)
        rows[-1]["logged_at"] = (datetime.now() - timedelta(hours=1)).isoformat(
            timespec="seconds")
        import json
        with open(self.path, "w") as fh:
            fh.write(json.dumps(rows[-1]) + "\n")
        catchlog.record(self._entry(3), self.path)
        self.assertEqual(len(catchlog.load(self.path)), 2)

    def test_the_window_is_short_enough_to_be_a_tap_not_a_trip(self):
        from tiderace import log as catchlog
        self.assertLessEqual(catchlog.DUPLICATE_WINDOW_S, 120)
        self.assertGreaterEqual(catchlog.DUPLICATE_WINDOW_S, 10)

    def test_a_blank_needs_a_deliberate_second_press(self):
        import pathlib as _p, re
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        body = page.split("function wireLog")[1].split("\n  }")[0]
        self.assertIn("Confirm: no fish", body)
        # The arming delay has to be longer than a double-tap, which on a boat
        # is two deliberate presses rather than the 300ms a browser means.
        m = re.search(r"armedAt < (\d+)", body)
        self.assertTrue(m, "the arming window must be enforced in code")
        self.assertGreaterEqual(int(m.group(1)), 700)

    def test_a_second_submit_while_saving_is_dropped(self):
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        body = page.split("function wireLog")[1].split("\n  }")[0]
        self.assertIn("if (submitting) return;", body)



def comments_only(page):
    """Just the commentary, with the code taken out.

    The inverse of strip_comments, and the thing an assertion must NOT be
    satisfiable by on its own.
    """
    out = re.findall(r"/\*.*?\*/", page, re.S)
    out += re.findall(r"(?m)^\s*//.*$", page)
    out += re.findall(r"<!--.*?-->", page, re.S)
    return "\n".join(out)


def strip_comments(page):
    """A page with its comments removed.

    Every assertion below has at some point matched the word it was looking
    for inside a comment explaining the bug, and passed while the code was
    still wrong.
    """
    js = re.sub(r"/\*.*?\*/", " ", page, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", js)


class ResponsiveLayout(unittest.TestCase):
    """Which layout you get is decided by what you point with, not by width.

    Keyed on max-width:900px alone, the sidebar stayed on a real phone and the
    conditions sheet rendered as a 420px panel beside it -- two surfaces
    fighting over the screen, which is exactly what the mobile layout existed
    to remove. A device can report well over 900 CSS pixels and still be held
    in one hand: a foldable, a tablet, a browser set to "desktop site".
    """

    def setUp(self):
        import pathlib
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()


    def test_touch_gets_the_touch_layout_at_any_width(self):
        self.assertIn("@media (max-width:900px), (pointer:coarse){", self.page)

    def test_the_desktop_rule_requires_a_real_pointer(self):
        # Without the pointer clause these two overlap on a wide touch screen
        # and both apply, which is how the sheet became a sidebar.
        self.assertIn("@media (min-width:901px) and (pointer:fine){", self.page)

    def test_the_script_and_the_stylesheet_agree(self):
        # If CSS hides the panel while JS declines to move it into the sheet,
        # its contents disappear from the app entirely rather than relocating.
        import re
        js = re.search(r"matchMedia\(\s*'([^']*)'\s*\)\s*\.matches", 
                       self.page.split("const MOBILE")[1])
        self.assertTrue(js, "MOBILE() must test a media query")
        self.assertEqual(js.group(1), "(max-width:900px), (pointer:coarse)",
                         "MOBILE() must match the CSS breakpoint exactly")

    def test_there_are_only_the_two_breakpoints(self):
        # A third width-only query would reintroduce the same split-brain.
        import re
        qs = [q.strip() for q in re.findall(r"@media ([^{]+)\{", self.page)]
        # Accessibility queries are not layout breakpoints. A
        # prefers-reduced-motion rule is not a third way for the page to lay
        # itself out, and counting it here would forbid honouring the setting.
        # Distinct queries, not distinct blocks. Repeating a breakpoint to keep
        # a rule beside the thing it styles is fine; what would reintroduce the
        # split brain is a THIRD way for the page to lay itself out.
        layout = {q for q in qs if "width" in q or "pointer" in q}
        self.assertEqual(sorted(layout),
                         sorted(["(max-width:900px), (pointer:coarse)",
                                 "(min-width:901px) and (pointer:fine)"]))

    def test_the_touch_block_is_last_in_the_stylesheet(self):
        """Source order, not specificity, decides between `.srow .v` in the
        base styles and `.srow .v` in the media query -- they are identical.

        The touch block originally sat above the sheet's own styles, so every
        sheet override in it lost silently. The text stayed small through a
        round of "fixing" it, and nothing was wrong with the rules themselves.
        """
        css = self.page[self.page.index("<style>"):self.page.index("</style>")]
        touch = css.index("@media (max-width:900px), (pointer:coarse)")
        # Every base rule the touch block overrides must come before it.
        for sel in (".srow{", ".srow .v{", ".sgroup{", "#sheethead b{",
                    ".rank button{", ".ph{"):
            self.assertLess(css.index(sel), touch,
                            f"{sel} is defined after the touch block, so the "
                            f"touch override for it cannot win")


class MapLabels(unittest.TestCase):
    """Spot labels are DOM and land wherever the marker does -- including
    under the control bar and behind the conditions sheet, where they stack
    into each other and read as noise."""

    def setUp(self):
        import pathlib
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()

    def test_labels_are_clamped_to_the_visible_map(self):
        self.assertIn("function clampLabels()", self.page)
        fn = self.page.split("function clampLabels()")[1].split("\n}")[0]
        self.assertIn("barBottom", fn)
        self.assertIn("sheetTop", fn)

    def test_the_sheet_only_counts_when_it_is_up(self):
        # Its rect still has a top when translated off the bottom; using that
        # unconditionally would blank labels across half the map.
        fn = self.page.split("function clampLabels()")[1].split("\n}")[0]
        self.assertIn("classList.contains('up')", fn)

    def test_the_dot_survives_under_the_bar_but_not_behind_the_sheet(self):
        """Keeping the dot is right over the map and wrong over an opaque
        panel, where it is a circle floating on top of the readout -- which is
        what shipped and what showed up in the screenshot."""
        fn = self.page.split("function markerVisibility(")[1].split("\n}")[0]
        self.assertIn("marker: 'hidden'", fn, "behind the sheet hides the marker")
        self.assertIn("marker: '', label: 'hidden'", fn, "under the bar keeps the dot")

    def test_the_sheet_test_needs_both_edges(self):
        """The sheet is a bottom sheet on a phone and a right-hand panel on a
        desktop. Testing only the top edge would blank every marker in the
        lower half of a desktop map; only the left edge would blank the right
        half of a phone map."""
        fn = self.page.split("function markerVisibility(")[1].split("\n}")[0]
        self.assertIn("sheetTop", fn)
        self.assertIn("sheetLeft", fn)
        self.assertIn("&&", fn, "both edges must hold, not either")

    def test_the_decision_is_pure_so_it_can_be_checked(self):
        # Placing real markers needs a real map; the decision is the part worth
        # being sure of, so it takes numbers and returns a verdict.
        self.assertIn("function markerVisibility(box, barBottom, sheetTop, sheetLeft)",
                      self.page)
        fn = self.page.split("function markerVisibility(")[1].split("\n}")[0]
        for dom in ("document.", "getElementById", "getBoundingClientRect"):
            self.assertNotIn(dom, fn, "must not touch the DOM")

    def test_user_toggle_and_chrome_test_use_different_properties(self):
        # display for the checkbox, visibility for the clamp -- otherwise one
        # silently undoes the other.
        h = self.page.split("$('#labels').onchange")[1].split("};")[0]
        self.assertIn("style.display", h)
        self.assertIn("clampLabels()", h)

    def test_the_labels_handler_has_a_block_body(self):
        # A concise arrow body plus a second statement runs that statement once
        # at parse time and never on toggle, which is what shipped for a minute.
        head = self.page.split("$('#labels').onchange")[1][:40]
        self.assertIn("=> {", head, "handler must be a block, not a concise arrow")

    def test_it_reruns_when_the_view_changes(self):
        for hook in ("map.on('move', clampLabels)",
                     "map.on('moveend', clampLabels)",
                     "addEventListener('resize', clampLabels)"):
            self.assertIn(hook, self.page, hook)


class ViewportLies(unittest.TestCase):
    """Chrome's "Desktop site" reports 980 CSS px on a 412 px phone.

    Everything is then scaled by ~2.4x on the way to the glass, so 22px type
    arrives at nine and the app is unreadable while every measurement inside it
    insists the sizes are correct. Two rounds of "make the text bigger" changed
    nothing because nothing was wrong with the text.
    """

    def setUp(self):
        import pathlib
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()
        i = self.page.index("@media (max-width:900px), (pointer:coarse)")
        self.touch = self.page[i:self.page.index("</style>", i)]

    def test_the_meta_viewport_still_asks_for_the_device_width(self):
        # The page cannot override the browser setting, but it must not be the
        # one asking for a wide viewport.
        self.assertIn('name="viewport"', self.page)
        self.assertIn("width=device-width", self.page)

    def test_the_whole_chrome_scales_together(self):
        # Scaling font-size alone grew the text and left padding, gaps and radii
        # where they were. zoom scales layout, which is what was wanted.
        self.assertIn("zoom: var(--ui, 1)", self.page)
        for sel in ("#sheet", "#bar", "#here"):
            self.assertIn(sel, self.page.split("zoom: var(--ui, 1)")[0][-200:],
                          f"{sel} should be in the zoomed set")

    def test_zoomed_boxes_state_their_width_in_zoomed_units(self):
        # A zoomed fixed element resolves left/right against the UNZOOMED
        # viewport and then multiplies, so left:0;right:0 came out 586px wide
        # inside a 375px screen.
        self.assertIn("width:calc(100vw / var(--ui, 1))", self.page)
        self.assertIn("right:auto", self.page)

    def test_offsets_are_divided_by_the_zoom(self):
        # Offsets are multiplied too: a 12px inset landed at 29px.
        for rule in ("left:calc(12px / var(--ui, 1))",
                     "right:calc(14px / var(--ui, 1))"):
            self.assertIn(rule, self.page)

    def test_the_map_is_not_zoomed(self):
        # It works in its own pixel space; zooming it would break hit-testing
        # and the label clamp.
        zoomed = self.page.split("zoom: var(--ui, 1)")[0][-200:]
        self.assertNotIn("#map", zoomed)

    def test_the_scale_is_derived_from_the_real_screen(self):
        fn = self.page.split("function uiScale()")[1].split("\n}")[0]
        self.assertIn("screen.width", fn)
        self.assertIn("innerWidth", fn)
        self.assertIn("pointer:coarse", fn,
                      "a mouse-driven wide window must not be scaled up")

    def test_the_scale_is_clamped(self):
        import re
        fn = self.page.split("function uiScale()")[1].split("\n}")[0]
        self.assertIn("Math.min", fn)
        self.assertIn("Math.max(1", fn)
        # Never below 1: an honest viewport must come out unchanged.
        m = re.search(r"Math\.min\(([\d.]+)", fn)
        self.assertTrue(m and float(m.group(1)) <= 3.0, "clamp too permissive")

    def test_the_cause_is_reported_not_just_papered_over(self):
        # Compensating silently would leave a blurry app and no way to know why.
        # Against the stripped page: the comment above the clamp says
        # "Desktop site" too, and would satisfy this on its own.
        self.assertIn("Desktop site", strip_comments(self.page))


class ChartCells(unittest.TestCase):
    """Chart data for water far wider than one bay, fetched a cell at a time.

    Montauk to the Cape with the shelf included is 37,000 square nautical miles
    against Narragansett Bay's 2,100 -- seventeen times the area, and the
    bundled layers are already 17 MB. Shipping that whole is a quarter of a
    gigabyte to a phone.
    """

    def test_the_grid_key_is_exact(self):
        from tiderace import charts
        # Integers, not floats: neighbouring requests must land on the same key
        # or every pan re-fetches water it already has.
        a = charts.cell_key(41.1234, -71.5678)
        b = charts.cell_key(41.1299, -71.5601)
        self.assertEqual(a, b)
        self.assertTrue(all(isinstance(v, int) for v in a))

    def test_a_cell_bbox_round_trips_to_its_own_key(self):
        from tiderace import charts
        for lat, lon in ((41.12, -71.50), (40.25, -70.90), (42.4, -70.1)):
            iy, ix = charts.cell_key(lat, lon)
            w, s_, e, n = charts.cell_bbox(iy, ix)
            self.assertTrue(w <= lon < e and s_ <= lat < n)
            self.assertEqual(charts.cell_key((s_ + n) / 2, (w + e) / 2), (iy, ix))

    def test_a_wide_view_is_capped(self):
        from tiderace import charts
        # A zoomed-out view spans hundreds of cells; fetching them all would
        # hammer NOAA for data drawn two pixels wide.
        many = charts.cells_for((-74.2, 39.5, -69.8, 42.6), limit=12)
        self.assertLessEqual(len(many), 12)

    def test_cells_come_back_centre_first(self):
        from tiderace import charts
        bbox = (-72.0, 41.0, -71.0, 42.0)
        cells = charts.cells_for(bbox, limit=4)
        cy, cx = 41.5, -71.5
        import math
        d = [math.hypot((charts.cell_bbox(iy, ix)[1] + charts.cell_bbox(iy, ix)[3]) / 2 - cy,
                        (charts.cell_bbox(iy, ix)[0] + charts.cell_bbox(iy, ix)[2]) / 2 - cx)
             for iy, ix in cells]
        self.assertEqual(d, sorted(d), "nearest the middle of the screen first")

    def test_requests_outside_the_served_water_are_empty(self):
        from tiderace import charts
        self.assertEqual(charts.cells_for((-130, 30, -120, 40)), [])

    def test_depth_layers_fall_through_the_bands(self):
        from tiderace import charts
        # The harbour band has thousands of soundings off Montauk and NOTHING
        # on the shelf; coastal and general are the opposite. One band cannot
        # serve someone who runs offshore.
        self.assertEqual(charts.BAND_ORDER[0], "enc_harbour")
        self.assertIn("enc_coastal", charts.BAND_ORDER)
        for band in charts.BAND_ORDER:
            self.assertIn("soundings", charts.BAND_LAYERS[band])
            self.assertIn("contours", charts.BAND_LAYERS[band])

    def test_the_band_is_never_swapped_through_a_global(self):
        # The server is threaded; two cells can be in flight at once, and
        # mutating a module-level BAND would hand one request the other's band.
        import inspect
        from tiderace import charts
        src = inspect.getsource(charts.fetch_banded)
        self.assertNotIn("global BAND", src)
        # The band travels as an argument. Asserting the intent rather than a
        # literal: the previous version of this test pinned "band=band" and
        # went red when the variable was renamed, while the property it cared
        # about never changed.
        self.assertRegex(src, r"fetch\([^)]*band=\w+")
        self.assertNotRegex(src, r"^\s*BAND\s*=", "must not assign to BAND")

    def test_the_richest_band_wins_not_the_first(self):
        """Bands overlap. Off Block Island the harbour band has 13 contours in
        a cell where general has 16, and taking the first non-empty band picked
        the 13."""
        import inspect
        from tiderace import charts
        src = inspect.getsource(charts.fetch_banded)
        self.assertIn("best_n", src)
        self.assertIn("> best_n", src, "strict compare keeps ties on the finer band")

    def test_the_cell_route_precedes_the_generic_one(self):
        # startswith("/charts/") is a prefix match and swallowed
        # /charts/cell/... as a layer name, so every cell 404ed.
        import pathlib as _p
        src = (_p.Path(__file__).parent / "tiderace" / "server.py").read_text()
        self.assertLess(src.index('startswith("/charts/cell/")'),
                        src.index('url.path.startswith("/charts/"):'))


class Bathymetry(unittest.TestCase):
    """Contours generated from an elevation model, for water charts generalise.

    ENC carries 475 depth contours in a mid-bay cell and 5 on the shelf --
    not because the detail was lost, but because no chart-maker draws a canyon
    edge for a ship passing over it in 200 m. An angler needs exactly that edge.
    """

    def test_a_sloping_plane_contours_to_a_straight_line(self):
        n = 40
        grid = [[-100.0 * i / (n - 1) for i in range(n)] for _ in range(n)]
        gj = bathy.contours((-71.0, 40.0, -70.0, 41.0), levels=(50,), n=n, grid=grid)
        self.assertEqual(len(gj["features"]), 1)
        xs = [x for f in gj["features"] for x, _ in f["geometry"]["coordinates"]]
        # Halfway down a linear slope, to within a grid step.
        self.assertAlmostEqual(min(xs), -70.5, places=3)
        self.assertAlmostEqual(max(xs), -70.5, places=3)

    def test_a_cone_contours_to_a_closed_ring(self):
        import math
        n, mid = 40, 19.5
        grid = [[-(math.hypot(i - mid, j - mid) / mid) * 100 for i in range(n)]
                for j in range(n)]
        gj = bathy.contours((-71.0, 40.0, -70.0, 41.0), levels=(50,), n=n, grid=grid)
        pts = gj["features"][0]["geometry"]["coordinates"]
        self.assertEqual(pts[0], pts[-1], "a closed depression must close")
        self.assertGreater(len(pts), 20)

    def test_flat_bottom_produces_nothing(self):
        grid = [[-40.0] * 20 for _ in range(20)]
        gj = bathy.contours((-71.0, 40.0, -70.9, 40.1), levels=(50,), n=20, grid=grid)
        self.assertEqual(gj["features"], [])

    def test_gaps_in_the_model_are_not_treated_as_flat(self):
        # A None is "no data", not "sea level" -- interpolating through one
        # would draw a contour across a hole in the survey.
        self.assertEqual(bathy._cell_segments(0, 0, 1, 1, -10, None, -80, -40, -50), [])

    def test_the_saddle_case_is_resolved(self):
        # A col between two deeps. Getting it backwards joins separate holes.
        segs = bathy._cell_segments(0, 0, 1, 1, -10, -90, -10, -90, -50)
        self.assertEqual(len(segs), 2, "a saddle emits two segments, not one")

    def test_every_feature_is_flagged_as_a_model(self):
        """A charted sounding is a survey somebody signed for; this is an
        interpolation. Whatever consumes it must not be able to mistake one for
        the other, so the flag is on each feature, not just in a header."""
        n = 20
        grid = [[-100.0 * i / (n - 1) for i in range(n)] for _ in range(n)]
        gj = bathy.contours((-71.0, 40.0, -70.9, 40.1), levels=(20, 50), n=n, grid=grid)
        self.assertTrue(gj["model"])
        self.assertIn("Not for navigation", gj["note"])
        for f in gj["features"]:
            self.assertTrue(f["properties"]["model"])
            self.assertIn("NCEI", f["properties"]["source"])

    def test_the_request_block_stays_under_the_service_cap(self):
        # getSamples truncates silently past 1000, which would drop the tail of
        # a grid rather than raising -- so blocks are sized to fit.
        self.assertLessEqual(bathy.BLOCK * bathy.BLOCK, bathy.MAX_SAMPLES)

    def test_it_is_drawn_differently_from_charted_contours(self):
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        blk = page.split("  bathy: {")[1].split("},")[0]
        self.assertIn("dash", blk, "must be visually distinct from a survey")
        self.assertIn("model: true", blk)


# --------------------------------------------------------------------------
# Massachusetts: does the reconciler travel?
#
# `reconcile.py` was written against RIDEM and claims to be format-agnostic
# because it consumes parsed dicts, not text. `madmf.py` is a second
# extractor built to test that claim against real DMF advisories. Two of
# these tests are expected failures: they describe what a correct reconciler
# would say, and they will start passing the day `reconcile` learns that a
# later notice can retire an earlier one without saying so.
# --------------------------------------------------------------------------

BSB_JULY = """
June 18, 2026
MarineFisheries Advisory
Summertime Commercial Black Sea Bass Fishery to Open on July 1
The summertime commercial fishery for black sea bass opens on Wednesday, July 1.
Commercial fishers who hold a black sea bass pot endorsement and are taking fish by
black sea bass pot are subject to a 500-pound daily trip limit that increases to 600
pounds on September 1 if at least 15% of the quota remains. For black sea bass
endorsement holders who are fishing with rod and reel gear or retaining fish caught as
bycatch in other pot gear, the daily trip limit begins at 250 pounds and similarly
increases to 300 pounds on September 1 if at least 15% of the quota remains. The
commercial minimum size is 12 inches as measured on the fish with its mouth closed.
"""

BSB_SEPT = """
August 28, 2026
MarineFisheries Advisory
Adjustments to Commercial Black Sea Bass Limits Effective September 1
Effective Tuesday, September 1, 2026, the commercial black sea bass possession and
landing limit and open fishing day schedule will change. The trip limit increases from
500 pounds to 600 pounds for pot fishers and from 250 pounds to 300 pounds for hook and
line fishers (and other non-trawl gear).
The Consecutive Daily Trip Limit Program remains in effect for the black sea bass pot
fishery throughout the remainder of the 2026 season. Consistent with this September 1
trip limit adjustment, potters with a valid Letter of Authorization will be able to
possess and land up to 1,200 pounds of black sea bass on any trip spanning two
consecutive calendar days provided no more than 600 pounds of black sea bass is retained
during any single calendar day.
"""

FLUKE_SEPT = """
August 28, 2026
MarineFisheries Advisory
Commercial Summer Flounder Limits to Increase on September 1
Effective Tuesday, September 1, 2026, the commercial summer flounder possession and
landing limit for all gear types will increase to 1,000 pounds. Unless otherwise
notified, the 1,000-pound trip limit will remain in effect from September 1 until the
start of the fall fishery on October 1. At that time, the trip limit may increase to
5,000 pounds if at least 10% of the quota remains available.
"""

BASS_CLOSE = """
August 4, 2026
MarineFisheries Advisory
2026 Commercial Striped Bass Fishery to Close Effective August 5
The Division of Marine Fisheries (DMF) is projecting that 100% of Massachusetts' 2026
commercial striped bass quota will be taken on Tuesday, August 4. Accordingly, DMF is
closing the 2026 commercial striped bass fishery effective at 0001 hours on Wednesday,
August 5 (Closure Notice). Unless otherwise notified, the commercial striped bass
fishery will remain closed until it is scheduled to reopen in 2027.
"""

BASS_OPEN = """
June 11, 2026
MarineFisheries Advisory
2026 Commercial Striped Bass Fishery to Open on June 16
Massachusetts' 2026 commercial striped bass fishery will open on Tuesday, June 16 with a
683,773-pound quota. The commercial minimum size is 35" total length. The daily limit is
15-fish for boat-based permit holders fishing onboard the vessel named on the permit, and
2-fish for all other commercial fishing activity.
"""


def _ma_corpus():
    out = []
    for doc in (BASS_OPEN, BSB_JULY, BASS_CLOSE, BSB_SEPT, FLUKE_SEPT):
        out += madmf.parse_advisory(doc)["notices"]
    return out


class MassachusettsExtractor(unittest.TestCase):
    def test_the_year_comes_from_the_dateline(self):
        """DMF writes "effective ... August 5" with no year. Guessing the
        current year works for ten months and is wrong every January."""
        self.assertEqual(madmf.dateline_year(BASS_CLOSE), 2026)
        n = madmf.parse_advisory(BASS_CLOSE)["notices"]
        self.assertEqual(n[0]["effective_date"], "2026-08-05")

    def test_one_sentence_two_gears_two_limits(self):
        """The pot and hook-and-line limits are set in one sentence. An
        earlier version consumed the "and from" joining them and recorded
        only the first."""
        got = {n["sub_fishery"]: n["amount"]["value"]
               for n in madmf.parse_advisory(BSB_SEPT)["notices"]
               if n["period"] != "per two days"}
        self.assertEqual(got.get("pot"), 600)
        self.assertEqual(got.get("hook_and_line"), 300)

    def test_non_trawl_is_not_trawl(self):
        """"hook and line fishers (and other non-trawl gear)" matched the
        bare `trawl` hint and reported 600 lb for trawlers, who get 100 lb
        incidental. Wrong by 6x in the direction that earns a citation."""
        for n in madmf.parse_advisory(BSB_SEPT)["notices"]:
            if n["sub_fishery"] == "trawl":
                self.fail(f"attributed to trawlers: {n['quote'][:80]}")

    def test_the_annual_quota_is_not_a_trip_limit(self):
        """"a 683,773-pound quota" is the size of the fishery."""
        for n in madmf.parse_advisory(BASS_OPEN)["notices"]:
            if n["amount"]:
                self.assertLess(n["amount"]["value"], 1000, n["quote"][:80])

    def test_a_conditional_future_change_is_not_a_current_limit(self):
        """"may increase to 5,000 pounds if at least 10% of the quota
        remains" is a forecast. Recording it as in force puts a 5x limit on
        the boat before anyone has decided it applies."""
        r = madmf.parse_advisory(FLUKE_SEPT)
        self.assertEqual([c["amount"]["value"] for c in r["conditional_changes"]], [5000])
        for n in r["notices"]:
            self.assertNotEqual(n["amount"]["value"], 5000)

    def test_no_amount_carries_a_cross_check(self):
        """The RI parser's best property -- "four hundred (400)" checking
        itself -- does not survive the border. DMF writes numbers once."""
        for n in _ma_corpus():
            if n["amount"]:
                self.assertFalse(n["amount"]["cross_checked"])

    def test_unmodelled_species_are_not_parse_failures(self):
        """DMF publishes menhaden, squid and scallop advisories. Not
        modelling a species is scope, not breakage, and filing it as
        `unparsed` buries the real failures."""
        r = madmf.parse_advisory(
            "June 5, 2026\nThe commercial limited access trip limit will be "
            "reduced from 120,000 pounds to 25,000 pounds effective Tuesday, June 9.")
        self.assertEqual(r["unparsed"], [])
        self.assertTrue(r["unmodelled_species"])


class MassachusettsReconcilePortability(unittest.TestCase):
    """What the RI reconciler does and does not survive."""

    def test_gear_keys_keep_separate_limits_apart(self):
        """The identity key already carries sub_fishery, so MA's gear
        dimension needs no reconciler change -- pot, hook-and-line and
        all-gear coexist."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        gears = {k[4] for k in st if k[0] == "black_sea_bass"}
        self.assertIn("pot", gears)
        self.assertIn("hook_and_line", gears)

    def test_the_consecutive_daily_limit_coexists_with_the_daily_one(self):
        """1,200 lb over two days and 600 lb in one day are both real and
        both in force. What keeps them distinct is that the Consecutive Daily
        programme is its own permit-gated fishery -- not that the units
        differ. Leaning on the period made a superseded daily limit immortal
        the moment DMF omitted the word "daily"."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        progs = {k[3] for k in st if k[0] == "black_sea_bass" and k[4] == "pot"}
        self.assertEqual(progs, {None, "consecutive_daily"})

    def test_upcoming_surfaces_changes_before_they_land(self):
        up = reconcile.upcoming(_ma_corpus(), date(2026, 8, 15))
        self.assertTrue(any(u["effective_date"] == "2026-09-01" for u in up))

    def test_promote_never_fires_because_ma_declares_no_successors(self):
        """The crux of the RI reconciler -- reconstructing the rule in force
        from a spent notice's tail -- is inert here. RIDEM buries the current
        rule inside a superseded notice; DMF gives every change its own
        advisory. That logic is a RIDEM house-style adaptation, not a
        universal pattern."""
        self.assertEqual(
            [n for n in _ma_corpus() if n.get("superseded_on") or n.get("successor")],
            [])

    def test_a_later_notice_retires_the_limit_it_replaces(self):
        """The 9/1 advisory raises pot from 500 to 600. MA never declares
        supersession -- it just states the new number -- so this used to
        report two contradictory pot limits as simultaneously in force."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        daily = [n["amount"]["value"] for k, n in st.items()
                 if k[0] == "black_sea_bass" and k[4] == "pot"
                 and k[3] != "consecutive_daily"]
        self.assertEqual(sorted(daily), [600])

    def test_the_retired_limit_is_kept_not_dropped(self):
        """"pot went 500 -> 600 on 1 Sep" is the finding a licence holder
        needs. Returning 600 alone tells them the number without telling
        them it moved."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        pot = next(n for k, n in st.items()
                   if k[0] == "black_sea_bass" and k[4] == "pot"
                   and k[3] != "consecutive_daily")
        self.assertEqual([r["amount"]["value"] for r in pot["retired"]], [500])

    def test_retired_history_does_not_accumulate_across_calls(self):
        """`retired` is assigned a fresh list every call. Appending to one
        left on the notice by an earlier run would grow history forever."""
        corpus = _ma_corpus()
        for _ in range(3):
            st = reconcile.effective_state(corpus, date(2026, 9, 15))
        pot = next(n for k, n in st.items()
                   if k[0] == "black_sea_bass" and k[4] == "pot"
                   and k[3] != "consecutive_daily")
        self.assertEqual(len(pot["retired"]), 1)

    def test_one_fishery_under_two_names_is_one_rule(self):
        """DMF writes "rod and reel gear" in July and "hook and line fishers"
        in September for the same black sea bass category. Keyed apart, the
        superseded 250 lb limit sat beside the 300 lb one that replaced it.
        The September notice settles it by saying "from 250 pounds to 300"."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        line = [n for k, n in st.items()
                if k[0] == "black_sea_bass" and k[4] == "hook_and_line"]
        self.assertEqual([n["amount"]["value"] for n in line], [300])
        self.assertEqual([r["amount"]["value"] for r in line[0]["retired"]], [250])
        self.assertNotIn("rod_and_reel", {k[4] for k in st})

    def test_a_closure_retires_the_opening_it_ends(self):
        """An opening and a closure are one rule stated from opposite ends.
        Keyed apart, the spent 6/16 opening outlived the 8/5 closure and
        striped bass read as open and closed at once. RI hid this because its
        closures carry a dated `reopens_on`; the MA closure runs "until it is
        scheduled to reopen in 2027" and has no date to pair on."""
        st = reconcile.effective_state(_ma_corpus(), date(2026, 9, 15))
        seasons = [n["change_type"] for k, n in st.items()
                   if k[0] == "striped_bass" and k[2] == "season"]
        self.assertEqual(seasons, ["season_close"])


class VoiceLog(unittest.TestCase):
    """Spoken trip notes into log fields.

    The catch log has two rows and it is not because trips go unfished -- it is
    that logging one means typing on a phone with a rod in the other hand. This
    is the piece that unblocks every other thing on the roadmap, so the parts a
    model can get wrong are pinned deterministically.
    """

    def test_a_size_in_words_is_read_exactly(self):
        # Dropped by the model about half the time. A number followed by
        # "inch" is not a judgement call, so it does not go to a model.
        for said, want in (("biggest about thirty two inches", 32.0),
                           ("maybe nineteen inches", 19.0),
                           ("a 28 inch fish", 28.0),
                           ("19-inch fluke", 19.0),
                           ("twenty six inches", 26.0)):
            self.assertEqual(voicelog._size_said(said), want, said)

    def test_a_depth_is_not_mistaken_for_a_fish(self):
        # "ninety inches" is not a striped bass.
        self.assertIsNone(voicelog._size_said("ninety inches"))
        self.assertIsNone(voicelog._size_said("no numbers here"))

    def test_the_species_you_said_beats_the_species_selected(self):
        """Saying "fluke" with the app set to striped bass would otherwise log
        a fluke trip as striped bass -- a quietly wrong row, and a wrong row is
        worse than a missing one because later it is indistinguishable from a
        real trip."""
        self.assertEqual(voicelog._species_said("a few fluke drifting sand"), "fluke")
        self.assertEqual(voicelog._species_said("couple of tog"), "tautog")
        self.assertIsNone(voicelog._species_said("good day out there"))

    def test_the_longest_fish_name_wins(self):
        # "sea bass" must beat "bass", or every sea bass becomes a striper.
        self.assertEqual(voicelog._species_said("four sea bass on the wreck"),
                         "black_sea_bass")

    def test_sizes_of_striped_bass_are_not_species(self):
        for word in ("schoolie", "schoolies", "keeper", "keepers", "linesider"):
            self.assertEqual(voicelog._species_said(f"two {word} tonight"),
                             "striped_bass", word)

    def test_a_spoken_blank_is_heard_as_a_blank(self):
        """The worst failure available here. Blanks are half the signal the
        evaluation harness has, and a blank misread as a catch puts a fish in
        the log that never existed."""
        for said in ("nothing today, not a touch", "no fish at all",
                     "got skunked", "didn't catch a thing", "blanked",
                     "never got a bite", "no luck out there"):
            self.assertTrue(voicelog._blank_said(said), said)

    def test_a_good_day_is_not_read_as_a_blank(self):
        for said in ("two schoolies on a live eel",
                     "four sea bass on the wreck",
                     "nothing but big ones today"):
            self.assertFalse(voicelog._blank_said(said), said)

    def test_the_transcript_is_kept_on_the_draft(self):
        # So a bad parse can be read back against what was actually said,
        # months later, when nobody remembers the trip.
        out = voicelog.parse("", species="scup")
        self.assertIn("transcript", out)

    def test_nothing_is_written_by_parsing(self):
        """It fills the form; a human presses save. A model that mishears
        "no fish" as "four fish" must not be able to write to the log."""
        import inspect
        src = inspect.getsource(voicelog)
        # Strip docstrings and comments: the prose here says the word "write"
        # precisely to explain why the module must not, and matching that is
        # testing the explanation rather than the code.
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        for block in re.findall(r'"""[\s\S]*?"""', code):
            code = code.replace(block, "")
        for banned in ("catchlog", "log.record", "open(", ".write("):
            self.assertNotIn(banned, code, f"voicelog must not persist ({banned})")

    def test_audio_never_leaves_the_device(self):
        """Transcription is the browser's; only the sentence is posted, and the
        coordinate came from the tap before anyone spoke."""
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        fn = page.split("function wireMic(")[1].split("\n  }")[0]
        self.assertIn("SpeechRecognition", fn)
        for banned in ("MediaRecorder", "getUserMedia", "audio/", "blob"):
            self.assertNotIn(banned, fn, f"no audio should be captured ({banned})")


class TripTracks(unittest.TestCase):
    """A trip recorded whether or not anybody remembered to log it.

    Nobody forgets to log four keepers. Everybody forgets the blank -- and
    blanks are half of what the evaluation harness has to work with, because a
    model trained only on good days learns every day is good.
    """

    def _trip(self):
        """Charlestown 40 min, run east 35, Whale Rock 55, run home."""
        from datetime import datetime, timedelta
        t = datetime(2026, 8, 31, 5, 0)
        pts = []
        def add(lat, lon, mins):
            nonlocal t
            for _ in range(mins):
                pts.append({"lat": lat, "lon": lon, "t": t.isoformat()})
                t += timedelta(minutes=1)
        def run(a, b, mins):
            nonlocal t
            for k in range(mins):
                f = k / mins
                pts.append({"lat": a[0] + (b[0]-a[0])*f,
                            "lon": a[1] + (b[1]-a[1])*f, "t": t.isoformat()})
                t += timedelta(minutes=1)
        A, B = (41.3745, -71.6390), (41.4408, -71.4228)
        add(*A, 40); run(A, B, 35); add(*B, 55); run(B, A, 35)
        return pts, A, B

    def test_dwells_are_where_you_stopped_not_where_you_drove(self):
        pts, A, B = self._trip()
        d = track.dwells(pts)
        self.assertEqual(len(d), 2, "two spots worked, two dwells")
        found = sorted((round(x["lat"], 3), round(x["lon"], 3)) for x in d)
        self.assertEqual(found, sorted([(round(A[0],3), round(A[1],3)),
                                        (round(B[0],3), round(B[1],3))]))

    def test_the_best_dwell_is_not_the_midpoint_of_the_track(self):
        """The midpoint of a Charlestown-to-Whale-Rock trip is somewhere in
        open water halfway along, which is where you drove."""
        pts, A, B = self._trip()
        s = track.summarise(pts)
        self.assertAlmostEqual(s["best"]["lat"], B[0], places=2)
        self.assertGreater(s["best"]["minutes"], 50)
        mid_lat = (A[0] + B[0]) / 2
        self.assertNotAlmostEqual(s["best"]["lat"], mid_lat, places=2)

    def test_transit_never_becomes_a_dwell(self):
        from datetime import datetime, timedelta
        t = datetime(2026, 8, 31, 5, 0)
        pts = [{"lat": 41.30 + k*0.004, "lon": -71.50,
                "t": (t + timedelta(minutes=k)).isoformat()} for k in range(60)]
        self.assertEqual(track.dwells(pts), [], "a straight run is not a spot")

    def test_a_wild_gps_fix_is_discarded_not_averaged(self):
        """Phone GPS throws the occasional fix a mile inland. Left in, one of
        those splits a session in two and hides the spot; averaged in, it drags
        the position off the piece."""
        from datetime import datetime, timedelta
        t = datetime(2026, 8, 31, 5, 0)
        pts = [{"lat": 41.4408, "lon": -71.4228,
                "t": (t + timedelta(minutes=k)).isoformat()} for k in range(20)]
        pts.insert(10, {"lat": 41.55, "lon": -71.55,
                        "t": (t + timedelta(minutes=10, seconds=30)).isoformat()})
        self.assertEqual(len(track.clean(pts)), 20)
        self.assertEqual(len(track.dwells(pts)), 1)

    def test_two_pieces_with_a_run_between_stay_two(self):
        """Rewritten: the old version teleported between two stationary spots
        in one minute, which under a speed model reads as a boat repositioning
        over the same structure -- and it is not obvious it should read as
        anything else. Two pieces are separated by an actual run."""
        import math
        from datetime import datetime, timedelta
        def leg(lat, lon, kt, mins, brg=0.0, t0=None):
            t = t0 or datetime(2026, 8, 31, 6, 0)
            pts = []
            for _ in range(mins):
                pts.append({"lat": lat, "lon": lon, "t": t.isoformat()})
                lat += (kt / 60) * math.cos(math.radians(brg)) / 60
                lon += ((kt / 60) * math.sin(math.radians(brg)) / 60
                        / math.cos(math.radians(lat)))
                t += timedelta(minutes=1)
            return pts, lat, lon, t
        a, lat, lon, t = leg(41.40, -71.45, 1.0, 20)
        b, lat, lon, t = leg(lat, lon, 12.0, 6, brg=90, t0=t)
        c, *_ = leg(lat, lon, 1.0, 20, t0=t)
        self.assertEqual(len(track.sessions(a + b + c)), 2)

    def test_the_rejoin_test_looks_at_ground_already_worked(self):
        # Not at where the session started: a drift is half a mile long, so
        # "near the start" is too strict at the far end of one and too loose
        # for a second wreck sitting near the first one's beginning.
        import inspect
        src = inspect.getsource(track.sessions)
        self.assertIn("for q in cur", src)

    def test_a_glance_is_not_a_session(self):
        from datetime import datetime, timedelta
        t = datetime(2026, 8, 31, 5, 0)
        pts = [{"lat": 41.44, "lon": -71.42,
                "t": (t + timedelta(minutes=k)).isoformat()} for k in range(3)]
        self.assertEqual(track.dwells(pts), [])

    def test_the_track_is_written_to_the_phone_before_the_network(self):
        """A track that only lives in a variable is lost to a backgrounded tab
        or a dead battery, and a day on the water is not recoverable the way a
        failed upload is."""
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        fn = page.split("function tripStart()")[1].split("\n}")[0]
        self.assertIn("tripSave", fn)
        stop = page.split("async function tripStop()")[1].split("\n}")[0]
        self.assertIn("tripSave(st)", stop, "a failed upload must not lose the day")

    def test_tracks_are_gitignored(self):
        import pathlib as _p
        ig = (_p.Path(__file__).parent / ".gitignore").read_text()
        self.assertIn("data/tracks.jsonl", ig)


class HowFishingActuallyWorks(unittest.TestCase):
    """Two corrections to models that were wrong about the activity itself.

    The first version of the track looked for a stationary boat, and nobody
    fishes standing still -- a fluke drift covers half a mile. The first
    version of the log allowed one species per trip, and a bottom-fishing
    afternoon produces three.
    """

    # ---- drifting and trolling are fishing, not travelling ----

    def _leg(self, lat, lon, kt, mins, brg=0.0, t0=None):
        import math
        from datetime import datetime, timedelta
        t = t0 or datetime(2026, 8, 31, 6, 0)
        pts = []
        for _ in range(mins):
            pts.append({"lat": lat, "lon": lon, "t": t.isoformat()})
            lat += (kt / 60) * math.cos(math.radians(brg)) / 60
            lon += ((kt / 60) * math.sin(math.radians(brg)) / 60
                    / math.cos(math.radians(lat)))
            t += timedelta(minutes=1)
        return pts, lat, lon, t

    def test_a_drift_is_one_session_not_a_gap(self):
        """A 25-minute fluke drift covers half a mile. The displacement-based
        version fragmented it into two dwells and lost the fishing entirely."""
        pts, *_ = self._leg(41.40, -71.45, 1.2, 25)
        ses = track.sessions(pts)
        self.assertEqual(len(ses), 1)
        self.assertEqual(ses[0]["kind"], "drift")
        self.assertGreater(ses[0]["distance_nm"], 0.3, "it really does move")

    def test_trolling_is_fishing(self):
        pts, *_ = self._leg(41.20, -71.50, 3.0, 40)
        ses = track.sessions(pts)
        self.assertEqual(len(ses), 1)
        self.assertEqual(ses[0]["kind"], "troll")

    def test_a_run_is_not_fishing(self):
        pts, *_ = self._leg(41.20, -71.50, 18.0, 30)
        self.assertEqual(track.sessions(pts), [])

    def test_drift_motor_back_drift_is_one_piece_of_structure(self):
        """The bottom-fishing sawtooth. Three segments, one spot."""
        a, lat, lon, t = self._leg(41.40, -71.45, 1.2, 25)
        b, lat, lon, t = self._leg(lat, lon, 6.0, 4, brg=180, t0=t)
        c, *_ = self._leg(lat, lon, 1.2, 25, t0=t)
        ses = track.sessions(a + b + c)
        self.assertEqual(len(ses), 1, "one piece worked twice is one session")
        self.assertGreater(ses[0]["minutes"], 45)

    def test_leaving_ends_the_session(self):
        a, lat, lon, t = self._leg(41.40, -71.45, 1.2, 25)
        b, lat, lon, t = self._leg(lat, lon, 18.0, 27, brg=90, t0=t)
        c, *_ = self._leg(lat, lon, 3.0, 40, brg=45, t0=t)
        ses = track.sessions(a + b + c)
        self.assertEqual([x["kind"] for x in ses], ["drift", "troll"])

    def test_speed_bands_are_ordered(self):
        self.assertLess(track.DRIFT_MAX_KT, track.TROLL_MAX_KT)
        self.assertEqual(track.kind_of(1.0), "drift")
        self.assertEqual(track.kind_of(3.0), "troll")
        self.assertEqual(track.kind_of(12.0), "run")

    def test_a_session_keeps_its_path_not_just_a_centre(self):
        """A half-mile drift reduced to its midpoint loses which end of the
        piece produced the fish."""
        pts, *_ = self._leg(41.40, -71.45, 1.2, 25)
        s = track.sessions(pts)[0]
        self.assertIn("path", s)
        self.assertGreater(len(s["path"]), 10)
        self.assertNotEqual(s["start"], s["end"])

    # ---- several species, one trip ----

    def test_a_bottom_trip_writes_a_row_per_species(self):
        import tempfile, os
        from tiderace import log as catchlog
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        mk = lambda sp, n: catchlog.Entry(
            spot="at:41.44000,-71.42000", species=sp, count=n,
            started_at="2026-08-31T10:00", conditions={"water_temp_f": 69})
        catchlog.record_trip([mk("black_sea_bass", 4), mk("scup", 6),
                              mk("tautog", 1)], path)
        rows = catchlog.load(path)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["trip_id"] for r in rows}), 1,
                         "three catches, one trip")

    def test_the_conditions_are_snapshotted_once_for_the_trip(self):
        """All three were caught in the same water at the same time. Three
        independent snapshots would differ by whatever the tide did while the
        loop ran."""
        import tempfile, os
        from tiderace import log as catchlog
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        mk = lambda sp: catchlog.Entry(
            spot="at:41.44000,-71.42000", species=sp, count=1,
            started_at="2026-08-31T10:00", conditions={"water_temp_f": 69.3})
        catchlog.record_trip([mk("scup"), mk("tautog")], path)
        rows = catchlog.load(path)
        self.assertEqual(rows[0]["conditions"], rows[1]["conditions"])

    def test_voice_hears_more_than_one_fish(self):
        import pathlib as _p
        src = (_p.Path(__file__).parent / "tiderace" / "voicelog.py").read_text()
        self.assertIn('"catch"', src)
        self.assertIn("one entry per species", src)

    def test_a_size_is_not_pinned_to_the_wrong_fish(self):
        """With three species in a sentence there is no way to know from a
        regex which one the nineteen inches belonged to."""
        import pathlib as _p
        src = (_p.Path(__file__).parent / "tiderace" / "voicelog.py").read_text()
        self.assertIn('if len(out["catch"]) == 1:', src)


# --------------------------------------------------------------------------
# Photos into draft trips.
#
# The fixtures are JPEGs with a hand-assembled EXIF block rather than files
# written by a library, for two reasons: the test suite stays dependency-free
# like the rest of the project, and the parser is then checked against bytes
# laid out from the TIFF spec rather than against its own assumptions. The
# coordinates below were cross-checked against an independent EXIF reader
# when the fixtures were built.
# --------------------------------------------------------------------------

def _exif_jpeg(when=None, lat=None, lon=None) -> bytes:
    """A minimal JPEG carrying a real APP1 Exif segment."""
    import struct

    def entry(tag, typ, cnt, payload, data, data_base):
        if len(payload) <= 4:
            val = payload + b"\x00" * (4 - len(payload))
        else:
            val = struct.pack(">I", data_base + len(data))
            data.extend(payload)
            if len(data) % 2:
                data.append(0)
        return struct.pack(">HHI", tag, typ, cnt) + val

    def ifd(spec, data, data_base):
        body = b"".join(entry(*e, data, data_base) for e in spec)
        return struct.pack(">H", len(spec)) + body + struct.pack(">I", 0)

    def rat3(v):
        v = abs(v); d = int(v); m = int((v - d) * 60); sec = ((v - d) * 60 - m) * 60
        return (struct.pack(">II", d, 1) + struct.pack(">II", m, 1)
                + struct.pack(">II", int(round(sec * 10000)), 10000))

    HDR = 8
    n0 = (1 if when else 0) * 2 + (1 if lat is not None else 0)
    ifd0_len = 2 + 12 * n0 + 4
    exif_len = (2 + 12 * 1 + 4) if when else 0
    gps_len = (2 + 12 * 4 + 4) if lat is not None else 0
    exif_at = HDR + ifd0_len
    gps_at = exif_at + exif_len
    data_base = gps_at + gps_len
    data = bytearray()

    spec0 = []
    if when:
        spec0.append((0x0132, 2, 20, when.encode() + b"\x00"))
        spec0.append((0x8769, 4, 1, struct.pack(">I", exif_at)))
    if lat is not None:
        spec0.append((0x8825, 4, 1, struct.pack(">I", gps_at)))
    spec0.sort(key=lambda e: e[0])

    tiff = b"MM\x00\x2a" + struct.pack(">I", HDR) + ifd(spec0, data, data_base)
    if when:
        tiff += ifd([(0x9003, 2, 20, when.encode() + b"\x00")], data, data_base)
    if lat is not None:
        tiff += ifd([
            (0x0001, 2, 2, (b"N" if lat >= 0 else b"S") + b"\x00"),
            (0x0002, 5, 3, rat3(lat)),
            (0x0003, 2, 2, (b"E" if lon >= 0 else b"W") + b"\x00"),
            (0x0004, 5, 3, rat3(lon)),
        ], data, data_base)
    tiff += bytes(data)

    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    # SOI, our APP1, a bare minimum of JPEG, EOI. The parser only walks
    # segments, so this need not decode as an image.
    return b"\xff\xd8" + app1 + b"\xff\xdb\x00\x04\x00\x00" + b"\xff\xd9"


class ExifReader(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="tiderace-exif-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, **kw):
        import os as _os
        p = _os.path.join(self.dir, name)
        with open(p, "wb") as fh:
            fh.write(_exif_jpeg(**kw))
        return p

    def test_a_west_longitude_comes_back_negative(self):
        """Rhode Island is west of Greenwich. An unsigned DMS triple read
        without its reference tag puts Whale Rock in Kazakhstan."""
        p = self._write("a.jpg", when="2026:08:30 05:41:12",
                        lat=41.4433, lon=-71.4222)
        got = exifmod.read(p)
        self.assertAlmostEqual(got["lat"], 41.4433, places=4)
        self.assertAlmostEqual(got["lon"], -71.4222, places=4)

    def test_exif_datetime_is_not_iso(self):
        """EXIF writes "2026:08:30 05:41:12" — colons in the date. Feeding
        that to fromisoformat raises, and a silent except would drop the
        capture time on every photo ever taken."""
        p = self._write("b.jpg", when="2026:08:30 05:41:12")
        self.assertEqual(exifmod.read(p)["taken_at"], "2026-08-30T05:41:12")

    def test_gps_enabled_but_unfixed_is_not_null_island(self):
        """A camera with GPS on and no lock writes 0/0 rather than omitting
        the tags. 0,0 is in the Gulf of Guinea."""
        p = self._write("c.jpg", when="2026:08:30 05:41:12", lat=0.0, lon=0.0)
        got = exifmod.read(p)
        self.assertIsNone(got["lat"])
        self.assertFalse(got["has_gps"])

    def test_a_photo_with_no_exif_says_so(self):
        import os as _os
        p = _os.path.join(self.dir, "d.jpg")
        with open(p, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xd9")
        with self.assertRaises(exifmod.NoExif):
            exifmod.read(p)

    def test_a_parsed_container_is_flagged_differently_from_a_scanned_one(self):
        p = self._write("e.jpg", when="2026:08:30 05:41:12")
        self.assertTrue(exifmod.read(p)["exact"])


class PhotoLog(unittest.TestCase):
    def setUp(self):
        import os as _os
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="tiderace-photolog-")
        self.paths = []
        for name, when, lat, lon in [
            ("dawn.jpg", "2026:08:30 05:41:12", 41.4433, -71.4222),
            ("fish1.jpg", "2026:08:30 06:12:40", 41.4437, -71.4219),
            ("fish2.jpg", "2026:08:30 07:05:03", 41.4431, -71.4225),
            ("evening.jpg", "2026:08:30 18:50:00", 41.3745, -71.6390),
            ("nogps.jpg", "2026:08:31 09:00:00", None, None),
            ("notime.jpg", None, None, None),
        ]:
            p = _os.path.join(self.dir, name)
            with open(p, "wb") as fh:
                fh.write(_exif_jpeg(when=when, lat=lat, lon=lon))
            self.paths.append(p)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _draft(self):
        return photolog.draft(self.paths, identify=False)

    def test_a_morning_of_photos_is_one_trip(self):
        d = self._draft()
        first = d["trips"][0]
        self.assertEqual(len(first["photos"]), 3)
        self.assertEqual(first["started_at"], "2026-08-30T05:41")

    def test_the_evening_run_is_a_different_trip(self):
        """Same day, three hours later, ten miles away. Merging them would
        attach the morning's tide to the evening's fish."""
        d = self._draft()
        self.assertGreaterEqual(len(d["trips"]), 2)
        self.assertEqual(d["trips"][1]["started_at"], "2026-08-30T18:50")

    def test_first_frame_to_last_frame_is_the_only_effort_measure_there_is(self):
        d = self._draft()
        self.assertEqual(d["trips"][0]["span_minutes"], 83)

    def test_a_single_photo_claims_no_duration(self):
        """One frame proves you were there, not how long for."""
        d = self._draft()
        lone = [t for t in d["trips"] if len(t["photos"]) == 1]
        self.assertTrue(lone)
        for t in lone:
            self.assertIsNone(t["span_minutes"])
            self.assertIsNone(t["ended_at"])

    def test_count_is_never_filled_in(self):
        """The safety property of the whole module. People photograph the
        good one, so any count inferred from a camera roll is biased upward
        exactly where the log needs honesty most."""
        for t in self._draft()["trips"]:
            for c in t["catch"]:
                self.assertIsNone(c["count"])

    def test_a_session_near_a_known_spot_inherits_it(self):
        d = self._draft()
        self.assertEqual(d["trips"][0]["spot"], "whale_rock")

    def test_a_session_with_no_fix_says_so_rather_than_guessing(self):
        d = self._draft()
        nofix = [t for t in d["trips"] if t["lat"] is None]
        self.assertTrue(nofix)
        self.assertIsNone(nofix[0]["spot"])
        self.assertTrue(nofix[0]["warnings"])

    def test_a_photo_with_no_timestamp_is_skipped_with_a_reason(self):
        d = self._draft()
        self.assertTrue(any("notime" in s["file"] for s in d["skipped"]))
        self.assertTrue(all(s["why"] for s in d["skipped"]))

    def test_the_species_enum_only_offers_fish_we_model(self):
        """A grammar cannot stop the model being wrong, but it can stop it
        naming a fish with no profile, no regulations and no thermal curve."""
        allowed = set(photolog.SCHEMA["properties"]["species"]["enum"])
        self.assertEqual(allowed - {"unknown", "other"}, set(score.PROFILES))

    def test_the_prompt_forbids_counting_and_measuring(self):
        low = photolog.SYSTEM.lower()
        self.assertIn("never estimate a length", low)
        self.assertIn("never estimate how many", low)


class PhotoPrivacy(unittest.TestCase):
    def test_a_hosted_backend_refuses_images(self):
        """A catch photo carries the coordinate it was taken at. That is the
        one thing this project has never sent anywhere, so the refusal is in
        the backend rather than in a caller's good intentions."""
        from tiderace import llm
        with self.assertRaises(llm.BackendUnavailable) as e:
            llm.Anthropic().complete("s", "u", {}, images=["Zm9v"])
        self.assertIn("locally", str(e.exception))

    def test_the_vision_default_is_not_the_model_that_returns_nothing(self):
        """qwen3-vl:30b answers an empty string to any request carrying a
        format schema — measured, see the note in llm.py."""
        from tiderace import llm
        self.assertNotIn("qwen3-vl", llm.DEFAULT_VISION_MODEL)


class SpeciesRegistry(unittest.TestCase):
    """What you can log and what the model will forecast are different lists.

    They used to be one list, and the consequence was that the catch log --
    the scarcest thing in the project -- silently refused most of what comes
    over the rail. You cannot log a bonito if the registry is the set of fish
    the forecast has an opinion about.
    """

    def test_you_can_log_far_more_than_the_model_scores(self):
        self.assertGreater(len(speciesmod.loggable()), 25)
        self.assertEqual(len(speciesmod.scored()), 6)

    def test_every_scored_species_is_in_the_registry(self):
        from tiderace import score
        for key in score.PROFILES:
            self.assertIn(key, speciesmod.BY_KEY, f"{key} scored but unlisted")

    def test_the_longest_name_wins(self):
        # "sea bass" must beat "bass", "bluefin tuna" must beat "bluefin".
        self.assertEqual(speciesmod.resolve("four sea bass"), "black_sea_bass")
        self.assertEqual(speciesmod.resolve("a bass"), "striped_bass")
        self.assertEqual(speciesmod.resolve("bluefin tuna"), "bluefin")

    def test_an_ambiguous_name_resolves_to_nothing(self):
        # "tuna" is three different fish with three different federal rules.
        # Guessing one would put the wrong permit category on the entry.
        self.assertIsNone(speciesmod.resolve("caught a tuna"))

    def test_the_names_people_actually_use(self):
        for said, want in (("albie", "false_albacore"), ("bones", "bonito"),
                           ("squeteague", "weakfish"), ("tog", "tautog"),
                           ("tinkers", "atlantic_mackerel"),
                           ("dorado", "mahi"), ("schoolie", "striped_bass")):
            self.assertEqual(speciesmod.resolve(said), want, said)

    def test_an_unverified_rule_says_so_rather_than_staying_silent(self):
        """A wrong size limit is not a bad forecast, it is a fine -- and under
        a commercial licence it is worse than a fine. Absence of a rule here
        means nobody checked, and the app has to say that out loud rather than
        let silence read as "no limit"."""
        w = speciesmod.unregulated_warning("bonito")
        self.assertTrue(w)
        self.assertIn("not modelled", w)
        self.assertIn("not that there are none", w)

    def test_a_modelled_species_gets_no_warning(self):
        self.assertIsNone(speciesmod.unregulated_warning("striped_bass"))

    def test_hms_species_are_flagged_as_federal(self):
        w = speciesmod.unregulated_warning("bluefin")
        self.assertIn("HMS", w)
        self.assertIn("permit", w)
        self.assertTrue(speciesmod.get("bluefin").hms)

    def test_no_regulatory_numbers_were_invented(self):
        """The registry carries names and aliases, never a size or a season.
        Those live in regs.py and only when read out of an actual notice."""
        import inspect, re
        src = inspect.getsource(speciesmod)
        body = src.split("SPECIES: tuple")[1].split("BY_KEY")[0]
        for word in ("min_inches", "bag", "limit=", "season=", "slot"):
            self.assertNotIn(word, body, f"registry must not carry rules ({word})")

    def test_the_log_form_picks_species_separately_from_the_forecast(self):
        import pathlib as _p
        page = (_p.Path(__file__).parent / "tiderace" / "web" / "index.html").read_text()
        self.assertIn('id="slogsp"', page)
        body = page.split("function wireLog")[1].split("\n  }")[0]
        self.assertIn("spSel", body, "the log must post its own species")


class SheetStructure(unittest.TestCase):
    """One sheet was doing the job of four screens.

    Measured before this: 2,590px of content in an 812px viewport -- 3.2
    screens of scrolling, 23 concatenated blocks, 14 buttons, and a 1,075px
    slab of the old desktop sidebar dropped at the bottom. On a boat that
    means scrolling past what you need while the drift goes by.
    """

    def setUp(self):
        import pathlib
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()

    def _script(self):
        return strip_comments(self.page)

    def test_there_are_four_views(self):
        import re
        views = re.findall(r'data-view="(\w+)"', self.page)
        self.assertEqual(views, ["now", "log", "spots", "trips"])

    def test_the_tabs_are_a_thumb_target(self):
        import re
        css = self.page.split("#tabs button{")[1].split("}")[0]
        m = re.search(r"min-height:\s*(\d+)px", css)
        self.assertTrue(m and int(m.group(1)) >= 48)

    def test_the_panel_is_no_longer_moved_into_the_sheet(self):
        """Relocating it was quietly destructive: render() rebuilds the sheet
        with innerHTML, which deleted the moved nodes rather than returning
        them, so the sidebar came back empty on a resize to desktop."""
        self.assertNotIn("function adoptPanel", self.page)
        self.assertNotIn("appendChild(adopted)", self.page)

    def test_rules_are_folded_rather_than_inline(self):
        # 135px of legal text in the middle of a conditions readout.
        self.assertIn('<details class="fold">', self.page)
        self.assertIn("rules &amp; protected species", self.page)

    def test_the_log_view_does_not_need_a_second_tap_to_open(self):
        body = self.page.split("function renderLog()")[1].split("\n  }")[0]
        self.assertIn("classList.add('open')", body)

    def test_view_code_runs_before_it_is_called(self):
        """setTab and nowEmpty close over `VIEW`; calling them above its
        declaration hit the temporal dead zone and took the whole script
        down, which is how showConditions stopped existing at all."""
        decl = self.page.index("let VIEW = 'now'")
        boot = self.page.index("if (MOBILE()){")
        self.assertLess(decl, boot, "boot must come after the declarations")

    def test_the_sheet_does_not_block_its_own_scrolling(self):
        """touch-action intersects up the ancestor chain, so `none` on #sheet
        also stopped #sheetbody -- the scrolling region holding every
        reading -- from moving under a finger. It belongs on the handle."""
        css = self._script().split("#sheet{")[1].split("}")[0]
        self.assertNotIn("touch-action", css,
                         "touch-action on #sheet disables the sheet's own scroller")
        grip = self._script().split("#sheetgrip{")[1].split("}")[0]
        self.assertIn("touch-action:none", grip)

    def test_only_one_place_moves_the_sheet(self):
        """Callers used to add 'up' and remove 'peek' by hand and the pair was
        not always complete, so the sheet could hold both at once and which
        rule won came down to stylesheet source order."""
        js = self._script()
        setter = js.index("function setSheet(state)")
        end = js.index("function sheetState()")
        for cls in ("'up'", "'peek'"):
            for m in re.finditer(r"classList\.(add|remove)\(([^)]*)\)", js):
                if cls in m.group(2):
                    self.assertTrue(setter <= m.start() < end,
                                    "sheet class touched outside setSheet: " + m.group(0))

    def test_a_tap_on_the_handle_closes_the_sheet(self):
        """It was drag-only, with a 40px threshold, which is the wrong ask
        with wet hands on a boat -- and nothing said the bar was a button."""
        js = self._script()
        self.assertIn("STEP_DOWN", js)
        self.assertIn("full:'peek'", js.replace(" ", ""))
        self.assertIn("peek:'shut'", js.replace(" ", ""))
        self.assertIn("gcue", self.page)

    def test_a_cancelled_drag_does_not_strand_the_sheet(self):
        """pointercancel fires instead of pointerup when the gesture is taken
        away; without a handler the sheet stays mid-drag with transitions
        off, which reads as the app having frozen."""
        self.assertIn("pointercancel", self._script())

    def test_the_sheet_setter_is_reachable_from_boot(self):
        """Boot sits above the setter, so it cannot go through the window
        alias (assigned later) and the setter cannot lean on a const arrow
        that is still in its dead zone at that point."""
        js = self._script()
        self.assertIn("function reclamp()", js,
                      "reclamp must hoist; boot calls setSheet above it")
        boot = js.index("if (MOBILE()){")
        line = js[boot:js.index("\n", js.index("setSheet", boot))]
        self.assertNotIn("window.setSheet", line,
                         "boot runs before the window alias exists")


class PotentialSurface(unittest.TestCase):
    """Scoring a lattice, and refusing to claim more than it knows."""

    def test_elevation_becomes_depth_in_the_right_units_and_sign(self):
        """bathy returns seafloor ELEVATION in metres, negative down. Reading
        it as depth in feet put the bottom of Narragansett Bay at 2125 ft --
        absurd enough to catch, which a subtler mix-up would not have been."""
        from tiderace import heat
        self.assertAlmostEqual(heat._depth_ft(-20.0), 65.6, places=1)
        self.assertAlmostEqual(heat._depth_ft(-30.0), 98.4, places=1)
        # Land and the waterline are not shallow water; a 0 would paint them
        # as the shallowest, most attractive cells on the map.
        self.assertIsNone(heat._depth_ft(0.0))
        self.assertIsNone(heat._depth_ft(12.5))
        self.assertIsNone(heat._depth_ft(None))
        self.assertIsNone(heat._depth_ft("shoal"))

    def test_bathy_is_called_with_its_own_bbox_order(self):
        """This module carries (south, west, north, east); bathy takes
        (west, south, east, north). Crossing them samples the wrong ocean."""
        import inspect
        from tiderace import heat
        src = inspect.getsource(heat.surface)
        call = src.split("bathy.sample_grid(")[1].split(")")[0]
        self.assertIn("west, south, east, north", call.replace("(", ""))

    def test_depth_is_reported_but_never_scored(self):
        """No species profile carries a depth preference and none may be
        guessed in. That needs published numbers per species, the way the
        temperature bands were done."""
        from tiderace import score
        for key, prof in score.PROFILES.items():
            self.assertNotIn("depth", prof.weights,
                             "%s gained a depth weight without literature" % key)
            self.assertFalse(hasattr(prof, "depth"),
                             "%s gained a depth band without literature" % key)
        import inspect
        self.assertNotIn("depth", inspect.getsource(score.score))

    def test_the_cache_does_not_write_into_the_working_directory(self):
        """A bare filename writes wherever the process happens to be, which
        for the server is the repo root. That is how 142 cache files were
        once swept into a commit by `git add -A`."""
        import os
        from tiderace import heat
        key = heat._key("striped_bass", (41.4, -71.4, 41.6, -71.2), 8,
                        __import__("datetime").datetime(2026, 9, 2, 15))
        self.assertTrue(os.path.isabs(key) or os.sep in key,
                        "cache key %r is a bare filename" % key)
        self.assertIn("cache", key.replace(os.sep, "/"),
                      "heat surfaces must cache under the gitignored data/cache")

    def test_the_limiting_factor_is_the_one_costing_most_points(self):
        """A number invites "the app says 41 here". The factor behind it
        invites "the tide is wrong, come back on the ebb"."""
        from tiderace import heat
        weights = {"current": 0.28, "light": 0.22, "temp": 0.15}
        # current is only slightly down but carries the most weight
        self.assertEqual(
            heat._limiting({"current": 0.5, "light": 0.9, "temp": 0.95}, weights),
            "current")
        # a term at full value costs nothing, however heavy
        self.assertEqual(
            heat._limiting({"current": 1.0, "light": 0.2, "temp": 1.0}, weights),
            "light")
        self.assertIsNone(heat._limiting({"current": 1.0}, weights))

    def test_the_surface_admits_its_own_resolution(self):
        """The current at a cell IS the nearest station's prediction, so cells
        sharing a station are identical by construction. A smooth raster would
        be drawing the interpolation rather than the ocean."""
        import inspect
        from tiderace import heat
        src = inspect.getsource(heat)
        self.assertIn("resolution_note", src)
        self.assertIn("depth_scored", src)
        # every cell carries its confidence, so a station miles away cannot be
        # painted as though you were sitting on it
        cell = inspect.getsource(heat.surface).split("cells.append(")[1]
        self.assertIn("confidence", cell)


class ZoomedChromeStaysOnTheGlass(unittest.TestCase):
    """A viewport unit on a zoomed element is not the size you asked for.

    `zoom` multiplies computed lengths, and vh/vw resolve against the
    UNZOOMED viewport first -- so the result is scaled twice. This was
    already known for width (`left:0;right:0` came out 2.4x wider than the
    screen) and the fix was written down in a comment, but only ever applied
    to the horizontal axis.

    The vertical case cost more. `max-height:92vh` computed to 1826px, zoom
    2.379 multiplied it to 2256 visual px in a 1985px viewport, and because
    the sheet is anchored `bottom:0` the 271px of overflow went off the TOP
    -- carrying the drag handle 269px above the screen. Every report was
    "I can't pull the panel down", and the panel was fine: the handle was
    not on the glass. Measured, not inferred.
    """

    def setUp(self):
        import pathlib
        self.page = (pathlib.Path(__file__).parent
                     / "tiderace" / "web" / "index.html").read_text()

    def test_no_bare_viewport_unit_on_a_zoomed_element(self):
        css = strip_comments(self.page)

        # Who is zoomed. Read it, do not hardcode it, or a new zoomed
        # element joins the stylesheet unguarded.
        m = re.search(r"([^{}]+)\{[^{}]*zoom:\s*var\(--ui\s*[,)]", css)
        self.assertTrue(m, "found no `zoom: var(--ui...)` rule to guard")
        zoomed = {sel.strip() for sel in m.group(1).split(",") if sel.strip()}
        self.assertTrue(zoomed, "no zoomed selectors parsed")

        offenders, scanned = [], 0
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            sel, body = rule.group(1), rule.group(2)
            if not any(z in sel for z in zoomed):
                continue
            for decl in body.split(";"):
                if not re.search(r"\d\s*v[hw]\b", decl):
                    continue
                scanned += 1
                if not re.search(r"var\(--ui\s*[,)]", decl):
                    offenders.append(sel.strip() + " {" + decl.strip() + "}")

        # The floor: a rename of --ui, or of the selectors, would leave this
        # walking an empty set and reporting success.
        self.assertGreater(scanned, 2,
                           "examined %d viewport-unit declarations on zoomed "
                           "elements; the walk has stopped matching" % scanned)
        self.assertEqual(offenders, [],
                         "vh/vw on a zoomed element must be divided by "
                         "var(--ui, 1) or it is scaled twice: "
                         + "; ".join(offenders))


class AssertionsCannotPassOnProse(unittest.TestCase):
    """A check that matched only a comment has not passed.

    Carried over from poindexter's "a check that scanned nothing has not
    passed" (`scripts/ci/lib_scan_floor.py`), earned there when an audit
    copied every lint into an empty tree and ten of twelve printed "clean"
    and exited 0. The mechanism differs; the failure is identical.

    Every assertion about index.html is a string search over a file that
    also carries the comments explaining the bug the assertion guards.
    Search for "touch-action" to prove touch-action is gone and you find
    the paragraph saying it must be gone -- green test, broken app. That
    has now happened four times here: "gzip", "write", "osm", and
    "touch-action", the last of them in the commit that added this class.

    So: an assertion whose needle also occurs in the commentary must run
    against `strip_comments(...)`, which removes the place it could hide.
    """

    def test_no_page_assertion_is_satisfiable_by_commentary(self):
        import ast
        import pathlib
        here = pathlib.Path(__file__)
        page = (here.parent / "tiderace" / "web" / "index.html").read_text()
        prose = comments_only(page)
        self.assertTrue(prose.strip(), "found no comments; the check would be vacuous")

        tree = ast.parse(here.read_text())
        offenders, checked = [], 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("assertIn", "assertNotIn")
                    and len(node.args) >= 2):
                continue
            # only raw-page assertions; a stripped page is already safe
            hay = node.args[1]
            if not (isinstance(hay, ast.Attribute) and hay.attr == "page"):
                continue
            needle = node.args[0]
            if not (isinstance(needle, ast.Constant)
                    and isinstance(needle.value, str)):
                continue
            checked += 1
            if needle.value in prose:
                offenders.append("tests.py:%d %r" % (node.lineno, needle.value[:60]))

        # The floor. If the walk stopped matching -- a rename, a refactor --
        # this passes while checking nothing, which is the very fault it exists
        # to catch.
        self.assertGreater(checked, 8,
                           "examined %d page assertions; the walk has stopped "
                           "finding them" % checked)
        self.assertEqual(offenders, [],
                         "these can be satisfied by comment text alone; run them "
                         "against strip_comments(): " + "; ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
