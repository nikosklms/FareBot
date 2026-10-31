"""Turns what a user types ('athens', 'la', 'lossangeles', 'ATH') into likely airports."""
import unicodedata
from typing import Optional

from rapidfuzz import fuzz, process

from services.airports_data import ALL_AIRPORTS, MULTI_AIRPORT_CITIES

# Common short names that no airport name starts with.
ALIASES = {
    "la": "LAX", "ny": "NYC", "nyc": "NYC", "sf": "SFO", "dc": "WAS", "hk": "HKG",
    "athina": "ATH", "saloniki": "SKG", "salonica": "SKG", "kriti": "HER", "crete": "HER",
}

# Scores by how the text matched; fuzzy guesses are scaled below every direct match.
EXACT_CODE, ALIAS, NAME_START, WORD_START, UNLISTED_CODE, COUNTRY = 100, 99, 96, 92, 90, 85
FUZZY_WEIGHT = 0.9
CITY_BONUS = 1  # 'London All Airports' before 'London Heathrow'
# Shortcuts guess only above this: typos like 'londn' (72) pass, 'bari' -> Barcelona (69) doesn't.
MIN_GUESS_SCORE = 70

Match = tuple[str, str, str, float]


def normalize(text: str) -> str:
    """Lowercase, no accents or punctuation: 'Václav-Havel  Prague' -> 'vaclav havel prague'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in ascii_text.lower()).split())


class LocationResolver:
    def __init__(self, data: Optional[list[tuple[str, str, str]]] = None):
        self.data = data or ALL_AIRPORTS
        self._codes = {code for code, _, _ in self.data}
        self._names = [normalize(name) for _, name, _ in self.data]
        self._countries = [normalize(country) for _, _, country in self.data]
        self._search_text = [f"{name} {country}" for name, country in zip(self._names, self._countries, strict=True)]

    def resolve(self, query: str, limit: int = 5) -> list[Match]:
        """Best guesses for a typed place, best first. Always returns guesses for non-empty input.

        An exact airport code returns only that airport. A 3-letter code that isn't in the
        list is offered after name matches, since Google Flights knows far more airports than we do.
        """
        text = normalize(query)
        if not text:
            return []
        code = text.replace(" ", "").upper()
        if code in self._codes:
            index = next(i for i, (c, _, _) in enumerate(self.data) if c == code)
            return [self._match(index, EXACT_CODE)]

        scores: dict[int, float] = {}
        for index, (airport_code, _, _) in enumerate(self.data):
            score = self._direct_score(text, index, airport_code)
            if score:
                scores[index] = score
        for _, fuzzy_score, index in process.extract(text, self._search_text, scorer=fuzz.WRatio, limit=limit * 2):
            scores[index] = max(scores.get(index, 0), fuzzy_score * FUZZY_WEIGHT)

        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        matches = [self._match(i, scores[i]) for i in ranked]
        if len(code) == 3 and code.isalpha():
            unlisted = (code, f"Airport {code}", "code not in my list", float(UNLISTED_CODE))
            position = sum(1 for m in matches if m[3] > UNLISTED_CODE)
            matches.insert(position, unlisted)
        return matches[:limit]

    def best_guess(self, query: str) -> Optional[str]:
        """One airport code for command shortcuts, or None when nothing matches well enough.

        3 letters are taken as a code, unless they're a place name: the first word of exactly
        one airport's name ('kos' is Kos, not the code KOS; 'san' stays San Diego's code).
        """
        text = normalize(query)
        code = text.replace(" ", "").upper()
        if len(code) < 2:
            return None
        if len(code) == 3 and code.isalpha():
            if code in self._codes:
                return code
            named = [c for (c, _, _), name in zip(self.data, self._names, strict=True) if name.split()[0] == text]
            return named[0] if len(named) == 1 else code
        matches = self.resolve(query, limit=1)
        return matches[0][0] if matches and matches[0][3] >= MIN_GUESS_SCORE else None

    def _direct_score(self, text: str, index: int, airport_code: str) -> float:
        bonus = CITY_BONUS if airport_code in MULTI_AIRPORT_CITIES else 0
        name = self._names[index]
        if ALIASES.get(text) == airport_code:
            return ALIAS
        if name.startswith(text) or name.replace(" ", "").startswith(text.replace(" ", "")):
            return NAME_START + bonus
        if any(word.startswith(text) for word in name.split()):
            return WORD_START + bonus
        if any(word.startswith(text) for word in self._countries[index].split()):
            return COUNTRY + bonus
        return 0

    def _match(self, index: int, score: float) -> Match:
        code, name, country = self.data[index]
        return code, name, country, round(score, 1)
