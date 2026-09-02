"""Fetch Quran text (Uthmani) + English translation and cache into data/.

Sources:
  - api.alquran.cloud  (Quran text: quran-uthmani edition; translation: en.sahih)
  - Audio is NOT fetched here (per-ayah audio is resolved on demand at render time).

Output:
  data/surahs.json        - metadata for all 114 surahs
  data/verses/NNN.json    - per-surah ayah text + translations
  data/translations.json  - translation catalog with attribution
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
VERSES_DIR = DATA / "verses"

API = "https://api.alquran.cloud/v1"
ARABIC_EDITION = "quran-uthmani"
TRANSLATION_EDITION = "en.sahih"

SURAH_PREFIX_RE = re.compile(r"^سُورَةُ\s*")


def clean_arabic_name(raw: str) -> str:
    """'سُورَةُ الفَجۡرِ' -> 'الفجر' style display name (strip wrapping markup)."""
    name = SURAH_PREFIX_RE.sub("", raw).strip()
    # Remove Quranic-annotation style pause marks that appear inside surah names
    # only if present (e.g. ۡ), keeping the base letters.
    return name


def fetch_json(url: str, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"Failed to fetch {url}: {last}")


def main() -> None:
    VERSES_DIR.mkdir(parents=True, exist_ok=True)

    bismillah = None
    surahs_meta = []
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for number in range(1, 115):
        url = f"{API}/surah/{number}/editions/{ARABIC_EDITION},{TRANSLATION_EDITION}"
        payload = fetch_json(url)
        editions = payload["data"]
        ar_ed = next(e for e in editions if e["edition"]["format"] == "audio" or e["edition"]["identifier"] == ARABIC_EDITION)
        # editions returns objects; identifier check is authoritative
        ar_ed = next(e for e in editions if e["edition"]["identifier"] == ARABIC_EDITION)
        tr_ed = next(e for e in editions if e["edition"]["identifier"] == TRANSLATION_EDITION)

        ar_ayahs = ar_ed["ayahs"]
        tr_ayahs = tr_ed["ayahs"]
        assert len(ar_ayahs) == len(tr_ayahs), f"ayah count mismatch in surah {number}"

        if bismillah is None:
            bismillah = ar_ayahs[0]["text"].strip().lstrip("\ufeff").strip()

        ayahs = []
        for ar, tr in zip(ar_ayahs, tr_ayahs):
            text = ar["text"].strip().lstrip("\ufeff").strip()
            # alquran.cloud prefixes ayah 1 of every surah (except 1 & 9) with the
            # basmala. Keep verse text aligned with per-ayah audio by stripping it.
            if number not in (1, 9) and ar["numberInSurah"] == 1 and text.startswith(bismillah):
                text = text[len(bismillah):].strip()
            ayahs.append(
                {
                    "surah": number,
                    "ayah": ar["numberInSurah"],
                    "arabic": text,
                    "translations": {"en": tr["text"].strip()},
                }
            )

        surahs_meta.append(
            {
                "number": number,
                "arabicName": clean_arabic_name(ar_ed["name"]),
                "englishName": ar_ed["englishName"],
                "englishNameTranslation": ar_ed["englishNameTranslation"],
                "revelationType": ar_ed["revelationType"],
                "ayahCount": ar_ed["numberOfAyahs"],
            }
        )

        out = {
            "surah": number,
            "fetchedAt": fetched_at,
            "source": {
                "arabic": f"alquran.cloud edition '{ARABIC_EDITION}' (Tanzil.net Uthmani text)",
                "translation": f"alquran.cloud edition '{TRANSLATION_EDITION}'",
            },
            "bismillahStripped": number not in (1, 9),
            "ayahs": ayahs,
        }
        (VERSES_DIR / f"{number:03d}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"surah {number:3d} ok ({len(ayahs)} ayahs)")
        time.sleep(0.25)

    (DATA / "surahs.json").write_text(
        json.dumps(
            {
                "fetchedAt": fetched_at,
                "source": "api.alquran.cloud surah metadata",
                "count": len(surahs_meta),
                "surahs": surahs_meta,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    (DATA / "translations.json").write_text(
        json.dumps(
            {
                "translations": [
                    {
                        "id": "none",
                        "name": "No Translation",
                        "language": "—",
                        "languageCode": None,
                        "direction": "ltr",
                        "translator": None,
                    },
                    {
                        "id": "en-sahih",
                        "name": "English (Saheeh International)",
                        "language": "English",
                        "languageCode": "en",
                        "direction": "ltr",
                        "translator": "Saheeh International",
                        "attribution": "Translation: Saheeh International, served via alquran.cloud",
                    },
                ]
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    total = sum(s["ayahCount"] for s in surahs_meta)
    print(f"\nDone. 114 surahs, {total} ayahs cached under data/verses/")


if __name__ == "__main__":
    sys.exit(main())
