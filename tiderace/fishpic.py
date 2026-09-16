"""A reference photograph of each fish, from iNaturalist, with its licence.

Matt asked for "an image of the fish for reference" on the species card. The
whole difficulty is one word in that sentence: *the* fish. A photograph of the
wrong animal on a card headed "Tautog" is worse than no photograph, because a
card is where somebody goes to check.

This project has made that mistake once already and written it down.
`whales.py`: "An earlier pass used 47178 for sharks and got mummichogs and
gobies, which is exactly the sort of wrong that looks fine in aggregate." The
fix there was to verify each taxon id against the taxa endpoint rather than
guess it. The same rule applies here and costs more, because there are
thirty-seven of them.

So nothing here trusts a search result:

  * The query is the species' own name and its aliases, restricted to
    `rank=species` and to the classes a fish can be in. A free-text search
    without those returns genera, families and the occasional insect.
  * A result is only ACCEPTED when the taxon's own common name matches the
    name or an alias we asked for, compared with punctuation and case
    stripped. iNaturalist's `matched_term` is not enough on its own: it
    reports what matched the query string, which for "pollock" is happily
    satisfied by a different Pollachius.
  * Every accepted match records the scientific name it resolved to, what it
    matched on, and the date. `dossier` puts that binomial on the card, so a
    wrong fish is something a person can see rather than something buried in
    a cache.
  * No confident match means no photograph, and the card says the match was
    not confident. A blank is a fine answer here.

The licence is the second constraint and it is not negotiable. iNaturalist
photos are somebody's work: some are Creative Commons and some are
all-rights-reserved, and the API says which in `license_code`. Only the CC
ones are downloaded, the attribution string is stored beside the file, and
`dossier` will not emit a photo without one. This repository is AGPL and
somebody else may run it; shipping an unlicensed photograph would be the same
class of mistake as inventing a size limit.

Nothing is committed. The images live in the gitignored `data/species_photos/`
next to every other regenerable cache, and 3.8 MB of blobs are already in this
project's pushed history from one careless `git add -A`.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import cache

TAXA = "https://api.inaturalist.org/v1/taxa"
UA = "tiderace/0.1 (+https://github.com/Glad-Labs/tiderace)"

PHOTO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "species_photos")
MANIFEST = os.path.join(PHOTO_DIR, "manifest.json")

# The classes a fish in this app can belong to. Without this the taxa search
# for "bonito" returns a genus, and the one for "blue shark" has returned
# beetles in other people's bug reports.
CLASSES = ("Actinopterygii", "Elasmobranchii", "Chondrichthyes",
           "Teleostei", "Cephalopoda", "Myxini")

# Creative Commons only. `None` means all rights reserved, which is most of
# iNaturalist and none of this. cc-by-nd and cc-by-nc-nd are included because
# the app displays the photograph unmodified and credits it, which is what
# NoDerivatives permits.
OPEN_LICENCES = ("cc0", "cc-by", "cc-by-nc", "cc-by-sa", "cc-by-nc-sa",
                 "cc-by-nd", "cc-by-nc-nd")

# iNaturalist asks for no more than 1 request/second sustained.
PAUSE = 1.1


def _norm(s: str) -> str:
    """Names compared with case, punctuation and spacing taken out, so
    "False Albacore" matches "false albacore" and "Little Tunny (False
    Albacore)" does not accidentally fail on a bracket."""
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _get(url: str, params: dict) -> dict:
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _by_scientific(binomial: str) -> dict | None:
    """Look a taxon up by the name a document printed. No ambiguity to
    resolve: either iNaturalist knows this binomial or it does not.

    A genus revision is the one thing that can miss -- NMFS-NE-146 calls the
    longfin squid *Loligo pealeii* and the current combination is
    *Doryteuthis pealeii*. iNaturalist keeps the old name as a synonym and
    returns the accepted taxon, which is why the RETURNED name is recorded
    rather than the one we asked with.
    """
    try:
        data = _get(TAXA, {"q": binomial, "rank": "species",
                           "is_active": "true", "per_page": 5})
    except (urllib.error.URLError, OSError, ValueError):
        return None
    want = _norm(binomial)
    for t in data.get("results", []):
        names = {_norm(t.get("name"))}
        for syn in (t.get("synonyms") or []):
            names.add(_norm(syn))
        # Genus revisions: accept a taxon whose species epithet matches and
        # whose genus differs, but only when nothing matched outright.
        if want in names:
            return {"taxon_id": t.get("id"), "scientific": t.get("name"),
                    "common": t.get("preferred_common_name") or "",
                    "matched_on": binomial, "verified": "scientific name"}
    epithet = binomial.split()[-1].lower()
    for t in data.get("results", []):
        parts = (t.get("name") or "").split()
        if len(parts) == 2 and parts[1].lower() == epithet:
            return {"taxon_id": t.get("id"), "scientific": t.get("name"),
                    "common": t.get("preferred_common_name") or "",
                    "matched_on": binomial,
                    "verified": "scientific name (genus revised since the "
                                "document was written)"}
    return None


def resolve(name: str, aliases=(), binomial: str = "") -> dict | None:
    """Find the taxon for a fish, or return None rather than a guess.

    A sourced binomial wins outright and is the only fully safe route: a
    common name is not a key. "Monkfish" resolved by common name alone
    returned *Lophiodes naresi*, an Indo-Pacific fish that also answers to
    "Goosefish", where the document this project read says *Lophius
    americanus*.

    Without one, falls back to matching the taxon's OWN common name against
    the display name and the aliases -- and records that it did, because the
    two are not equally trustworthy and the card says which was used.
    """
    if binomial:
        hit = _by_scientific(binomial)
        if hit:
            return hit
        time.sleep(PAUSE)
        # Deliberately falls through rather than giving up: a name can be
        # absent from iNaturalist entirely, and a verified common-name match
        # is still better than no card image. It is labelled as the weaker
        # thing it is.
    wanted = {_norm(name)} | {_norm(a) for a in aliases}
    bare = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if bare:
        wanted.add(_norm(bare))
    # Also each half of a parenthesised pair: "Scup (Porgy)" is "Scup" to
    # iNaturalist and "Porgy" to a person.
    for part in re.findall(r"\(([^)]*)\)", name):
        wanted.add(_norm(part))
    wanted.discard("")

    for query in ([bare or name] + list(aliases))[:4]:
        try:
            data = _get(TAXA, {"q": query, "rank": "species",
                               "is_active": "true", "per_page": 10})
        except (urllib.error.URLError, OSError, ValueError):
            return None
        for t in data.get("results", []):
            if t.get("iconic_taxon_name") and \
                    t["iconic_taxon_name"] not in CLASSES + ("Animalia",):
                continue
            common = t.get("preferred_common_name") or ""
            # The taxon's OWN name has to match, not merely the query. iNat's
            # `matched_term` reports what matched the string we sent, which
            # for "pollock" is satisfied by a different Pollachius.
            if _norm(common) not in wanted:
                continue
            return {"taxon_id": t.get("id"),
                    "scientific": t.get("name"),
                    "common": common,
                    "matched_on": query,
                    "verified": "common name"}
        time.sleep(PAUSE)
    return None


def _photo_of(taxon: dict) -> dict | None:
    """The taxon's default photo, if its licence lets us keep a copy."""
    p = taxon.get("default_photo") or {}
    lic = (p.get("license_code") or "").lower()
    if lic not in OPEN_LICENCES:
        return None
    # `medium_url` is about 500px on the long edge -- enough for a card and
    # small enough that thirty-seven of them are a couple of megabytes.
    url = p.get("medium_url") or p.get("url")
    if not url:
        return None
    return {"url": url, "licence": lic,
            "attribution": p.get("attribution") or "",
            "photo_id": p.get("id")}


def load() -> dict:
    """The manifest, or an empty one. `cache.read_json` treats a corrupt file
    as absent, which is the deliberate exception to this project's no-silent-
    fallbacks rule: a truncated write should cost one refetch, not an
    exception on a boat with no signal."""
    return cache.read_json(MANIFEST, default={}) or {}


def get(key: str) -> dict | None:
    """What the card should show for this fish, or None.

    None covers three different situations and the caller is expected to say
    which: nothing has been fetched yet, no confident taxon match was found,
    or the only photograph is all-rights-reserved. `entry()` gives the reason.
    """
    e = load().get(key) or {}
    if not e.get("file"):
        return None
    if not os.path.exists(os.path.join(PHOTO_DIR, e["file"])):
        return None
    return {
        "url": "/species-photo/" + e["file"],
        "scientific": e.get("scientific"),
        # A condition of use, not decoration. `dossier` will not emit a photo
        # without it and the page renders it beneath the image.
        "credit": "%s · iNaturalist (%s)" % (e.get("attribution") or "unknown",
                                             e.get("licence") or "?"),
    }


def entry(key: str) -> dict:
    return load().get(key) or {}


def photo_path(request_path: str) -> str | None:
    """Absolute path to a photograph THIS APP fetched, or None.

    The filename is never joined onto the photo directory. The species key is
    taken out of the request, looked up in the manifest, and the stored
    filename is what builds the path -- so the only files reachable are ones
    the fetch wrote down, and a request cannot contribute a path component at
    all.

    `os.path.basename` would in fact stop a traversal on its own, and CodeQL
    flagging the first version of this was a false positive on that point. It
    is still the right thing to change: "basename cannot traverse" is an
    argument a reader has to follow and re-check every time the line moves,
    where "the path comes out of our own manifest" is a property you can see.
    The manifest lives in this directory too, which the first version needed a
    separate extension check to avoid serving; a key lookup cannot reach it.
    """
    name = os.path.basename(str(request_path or ""))
    key = name.rsplit(".", 1)[0]
    stored = (load().get(key) or {}).get("file")
    if not stored:
        return None
    return os.path.join(PHOTO_DIR, stored)


def fetch_all(species_list, refresh: bool = False, log=print) -> dict:
    """Resolve and download a photo for each fish. Returns a small report.

    Deliberately not called by the server or by any forecast path: this makes
    thirty-seven network round trips at a polite one per second, and a boat
    asking for a card should never wait on it. `tiderace species --photos` is
    the only caller.
    """
    os.makedirs(PHOTO_DIR, exist_ok=True)
    man = load()
    report = {"matched": 0, "downloaded": 0, "no_match": [], "no_licence": [],
              "kept": 0}

    for sp in species_list:
        have = man.get(sp.key) or {}
        if have.get("file") and not refresh and \
                os.path.exists(os.path.join(PHOTO_DIR, have["file"])):
            report["kept"] += 1
            continue

        from . import species as speciesmod
        hit = resolve(sp.name, sp.aliases, speciesmod.scientific(sp.key))
        time.sleep(PAUSE)
        if not hit:
            # Recorded, not silently skipped. "Nobody looked" and "looked and
            # could not be sure" are different facts and the card says which.
            man[sp.key] = {"resolved": False,
                           "checked_on": time.strftime("%Y-%m-%d")}
            report["no_match"].append(sp.key)
            log("  %-22s no confident match" % sp.key)
            continue
        report["matched"] += 1

        try:
            full = _get(TAXA + "/" + str(hit["taxon_id"]), {})
            taxon = (full.get("results") or [{}])[0]
        except (urllib.error.URLError, OSError, ValueError):
            taxon = {}
        time.sleep(PAUSE)
        photo = _photo_of(taxon)
        if not photo:
            man[sp.key] = dict(hit, resolved=True, file=None,
                               checked_on=time.strftime("%Y-%m-%d"),
                               why="no Creative Commons photo on this taxon")
            report["no_licence"].append(sp.key)
            log("  %-22s %-28s photo is all rights reserved"
                % (sp.key, hit["scientific"]))
            continue

        ext = ".jpg" if ".png" not in photo["url"].lower() else ".png"
        fname = sp.key + ext
        try:
            req = urllib.request.Request(photo["url"],
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as fh:
                blob = fh.read()
        except (urllib.error.URLError, OSError):
            log("  %-22s download failed" % sp.key)
            continue
        # Through `cache`, not hand-rolled. It already owns atomic writes and
        # a test walks this package looking for anybody who decided to do it
        # themselves -- which is how this line was written the first time.
        cache.write_bytes(os.path.join(PHOTO_DIR, fname), blob)
        man[sp.key] = dict(hit, resolved=True, file=fname,
                           licence=photo["licence"],
                           attribution=photo["attribution"],
                           photo_id=photo["photo_id"],
                           bytes=len(blob),
                           checked_on=time.strftime("%Y-%m-%d"))
        report["downloaded"] += 1
        log("  %-22s %-28s %s  %d KB"
            % (sp.key, hit["scientific"], photo["licence"], len(blob) // 1024))
        time.sleep(PAUSE)

    cache.write_json(MANIFEST, man)
    return report
