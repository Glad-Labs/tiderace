"""Spoken trip notes into a structured log entry.

The catch log is the scarcest thing in this project and it has two rows in it,
and the reason is not that trips go unfished. It is that logging one means
typing on a phone with a rod in the other hand, on a moving boat, usually wet.
Every other data source here is public and free; this is the only one nobody
else can get, and it is the one blocked by a keyboard.

So: say it instead. "Two schoolies at the east side on a live eel, dropping
tide, plus a short one I let go." That sentence contains a count, a method, a
tide stage and a released fish, and a small local model can pull them out
reliably enough to fill a form.

Three decisions worth stating, because each was a real choice.

**Transcription happens in the browser, not here.** There is no Whisper on this
machine and no audio model in Ollama, so the alternative was uploading audio.
The Web Speech API turns speech into text on the device and hands over a
sentence -- so what leaves the phone is "two schoolies on a live eel", never a
recording, and never the coordinate. The position comes from the tap on the
map, which happened before anyone spoke. It is worth being plain that the
sentence does reach Google on Android; if that is not acceptable the button
simply is not used, and the form still takes typing.

**Extraction is local.** The transcript goes to Ollama on this machine. A
sentence about where fish were caught is exactly the kind of thing this project
has refused to send anywhere since the beginning.

**It fills the form; it does not save.** A model that mishears "no fish" as
"four fish" would otherwise write a lie into the one irreplaceable file here,
and a wrong row is worse than a missing one -- it is indistinguishable from a
real trip later. So this returns a draft, the form shows it, and you press
save. The transcript is kept on the entry too, so a bad parse can always be
read back against what was actually said.
"""

from __future__ import annotations

import re
from datetime import datetime

from . import llm, score

# What a spoken note can carry. Deliberately small: the conditions are
# snapshotted from the coordinate and the clock, so the only things worth
# hearing are the ones only you know.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["count", "confidence"],
    "properties": {
        "count": {"type": "integer"},
        "species": {"type": "string"},
        "biggest_in": {"type": "number"},
        "released": {"type": "integer"},
        "method": {"type": "string"},
        "bait_observed": {"type": "string"},
        "notes": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}

SYSTEM = """You turn a fisherman's spoken note into structured fields.

The speech has already been transcribed and may contain recognition errors.
Read it the way somebody who fishes would, and do not invent anything that is
not there.

Rules that matter:
* count is fish KEPT or caught, as a number. "A couple" is 2, "a few" is 3,
  "half a dozen" is 6. "Nothing", "no fish", "blank", "skunked" is 0.
* A trip with no fish is normal and important. Never round 0 up to 1 because
  the sentence sounds disappointed rather than empty.
* released is fish put back, counted separately. "Two keepers and I let three
  go" is count 2, released 3.
* biggest_in is inches. If someone says pounds, leave it out rather than
  converting -- a weight is not a length.
* method is how they were fishing: live eel, bucktail, tube and worm, jig,
  chunk, troll.
* bait_observed is bait they SAW in the water, not what they fished with.
* notes is anything else worth keeping, in their own words, short.
* confidence is yours in the parse. Say low when the transcript is garbled or
  the numbers are ambiguous.

Never guess a species you were not told. Leave it out instead.

Worked examples. These exist because the fields most often missed are the ones
buried mid-sentence -- the method and the size -- and a rule alone did not get
them out reliably.

  "two schoolies at the east side on a live eel dropping tide"
    {"count":2,"species":"striped_bass","method":"live eel",
     "notes":"east side, dropping tide","confidence":"high"}

  "got a few fluke drifting sand, biggest maybe nineteen inches, lots of shorts"
    {"count":3,"species":"fluke","biggest_in":19,"method":"drifting",
     "notes":"sand, lots of shorts","confidence":"medium"}

  "nothing today, fished two hours, not a touch"
    {"count":0,"notes":"fished two hours, not a touch","confidence":"high"}

  "kept two, put back four, all on bucktail"
    {"count":2,"released":4,"method":"bucktail","confidence":"high"}

Note what happens in the first two: a fish named anywhere in the sentence
becomes species, a number followed by "inches" becomes biggest_in, and how they
were fishing becomes method even when it arrives after the count."""


def _pre(text: str) -> str:
    """Small repairs speech recognition reliably needs.

    Recognisers write numbers as words at the start of a clause and mangle
    fishing vocabulary in consistent ways. Doing this before the model rather
    than hoping it copes makes the parse noticeably steadier on short notes,
    which is most of them.
    """
    t = " " + text.strip() + " "
    fixes = [
        # "schoolie" is not in anybody's language model
        (r"\bschooly\b", "schoolie"), (r"\bschool[- ]?ie\b", "schoolie"),
        (r"\bscoolie\b", "schoolie"),
        (r"\bstriper?s?\b", "striper"),
        (r"\bblue ?fish\b", "bluefish"),
        (r"\bsea ?bass\b", "sea bass"),
        (r"\bfluke?s\b", "fluke"),
        (r"\bblack ?fish\b", "blackfish"),
        (r"\btog\b", "tautog"),
        (r"\bporgy?s?\b", "scup"), (r"\bporgies\b", "scup"),
        # "bucktail" often lands as two words, "tube and worm" as "tuben worm"
        (r"\bbuck ?tail\b", "bucktail"),
        (r"\btube ?and ?worm\b", "tube and worm"),
        (r"\blive ?eel\b", "live eel"),
    ]
    for pat, rep in fixes:
        t = re.sub(pat, rep, t, flags=re.I)
    return t.strip()


# Spoken quantities the model gets wrong often enough to be worth pinning.
WORD_COUNTS = {
    "none": 0, "nothing": 0, "zero": 0, "no fish": 0, "blank": 0,
    "skunked": 0, "one": 1, "a": 1, "two": 2, "a couple": 2, "couple": 2,
    "three": 3, "a few": 3, "few": 3, "four": 4, "five": 5, "six": 6,
    "half a dozen": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a dozen": 12, "dozen": 12,
}


def _blank_said(text: str) -> bool:
    """Did they say, in words, that they caught nothing?

    Checked separately and trusted over the model. A blank misread as a catch
    is the single worst failure here: it puts a fish in the log that never
    existed, and the evaluation harness treats blanks as half its signal.
    """
    t = text.lower()
    # "nothing but big ones" is a very good day, and the first version of this
    # read it as a blank and would have zeroed a real catch. Anything of the
    # form "nothing but ..." or "no fish but ..." is the opposite of a blank,
    # so those are removed before the test rather than special-cased inside it.
    t = re.sub(r"\b(nothing|no fish|not a \w+)\s+(but|except|other than)\b.*",
               " ", t)
    return bool(re.search(
        r"\b(no fish|nothing|not a (thing|touch|bite)|zero|blank|blanked|"
        r"skunked|didn'?t (catch|get|touch)|never (got|caught)|"
        r"got nothing|no luck)\b", t))


# Spoken numbers, for the things a regex can settle without asking a model.
_NUMWORD = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50,
}


def _spoken_number(phrase: str) -> int | None:
    """"thirty two" -> 32. Recognisers write sizes as words, and a tens word
    followed by a units word is the only compound that turns up in practice."""
    words = re.findall(r"[a-z]+", phrase.lower())
    total, seen = 0, False
    for w in words:
        if w in _NUMWORD:
            v = _NUMWORD[w]
            total = total + v if (seen and total % 10 == 0 and v < 10) else v
            seen = True
    return total if seen else None


def _size_said(text: str) -> float | None:
    """A length stated in inches, digits or words.

    Done deterministically because it is unambiguous in the text and the model
    dropped it about half the time -- a number immediately followed by "inch"
    is not a judgement call.
    """
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:\-|\s)?\s*inch", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"((?:[a-z]+[\s\-]){1,3}?)inch", text, re.I)
    if m:
        n = _spoken_number(m.group(1))
        if n and 4 <= n <= 80:                # a fish, not a boat or a depth
            return float(n)
    return None


def _species_said(text: str) -> str | None:
    """A fish named anywhere in the note, matched against what we model.

    Deterministic for the same reason: saying "fluke" while the app is set to
    striped bass and having the trip logged as striped bass would be a quietly
    wrong row, and a wrong row is worse than a missing one.
    """
    from .extract import SPECIES_ALIASES
    t = " " + text.lower() + " "
    hits = []
    for alias, key in SPECIES_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"s?\b", t):
            hits.append((len(alias), key))
    for word, key in (("schoolie", "striped_bass"), ("keeper", "striped_bass"),
                      ("linesider", "striped_bass")):
        if re.search(r"\b" + word + r"s?\b", t):
            hits.append((len(word), key))
    if not hits:
        return None
    # Longest alias wins: "sea bass" must beat "bass".
    hits.sort(reverse=True)
    return hits[0][1]


def parse(transcript: str, species: str | None = None,
          backend: llm.Backend | None = None) -> dict:
    """Turn a spoken note into fields for the log form.

    Returns a draft, never a saved entry. `species` is what the app was already
    set to; the model may override it if the speaker names a different fish.
    """
    text = _pre(transcript)
    if not text:
        return {"count": 0, "confidence": "low", "transcript": transcript,
                "notes": "", "empty": True}

    backend = backend or llm.get_backend()
    user = (
        f"Transcribed note: {text!r}\n"
        f"The app is currently set to: {species or 'unspecified'}\n"
        f"Today: {datetime.now().date().isoformat()}\n\n"
        "Return the fields you can read from the note. Leave out anything "
        "that is not there."
    )
    out = backend.complete(SYSTEM, user, SCHEMA)

    # The transcript rides along on the entry so a bad parse can be read back
    # against what was actually said, months later.
    out["transcript"] = transcript

    # A spoken blank overrides the model. See _blank_said.
    if _blank_said(text) and out.get("count"):
        out["count"] = 0
        out["confidence"] = "low"
        out["overridden"] = ("heard an explicit blank, so the count was set to "
                             "zero over the model's reading")

    # The two things a regex settles better than a model. Both are exact in
    # the text, and both were being dropped often enough to matter: a size
    # about half the time, and a species whenever the app was already set to a
    # different one -- which would have logged a fluke trip as striped bass.
    said_size = _size_said(text)
    if said_size is not None and not out.get("biggest_in"):
        out["biggest_in"] = said_size
    said_species = _species_said(text)
    if said_species:
        out["species"] = said_species

    if out.get("species"):
        key = _species_key(out["species"])
        if key:
            out["species"] = key
        else:
            # Heard something we do not model -- keep the words in the notes
            # rather than dropping the only record that it was said.
            out["notes"] = ((out.get("notes") or "") +
                            f" (heard species: {out['species']})").strip()
            out.pop("species")
    return out


def _species_key(said: str) -> str | None:
    """Map a spoken fish name onto a profile key, via the report aliases."""
    from .extract import SPECIES_ALIASES
    s = (said or "").strip().lower()
    if s in score.PROFILES:
        return s
    if s in SPECIES_ALIASES:
        return SPECIES_ALIASES[s]
    # "schoolie" and "keeper" are sizes of striped bass, not species.
    if s in ("schoolie", "schoolies", "keeper", "keepers", "linesider"):
        return "striped_bass"
    for alias, key in SPECIES_ALIASES.items():
        if alias in s:
            return key
    return None
