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

from tiderace import (astro, bait, evaluate, extract, fetch, gso, llm, reconcile,
                      regs, ridem, score, spots)

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
