from typing import List, Tuple, Optional
from rapidfuzz import process, fuzz
from services.airports_data import AIRPORT_DATA

class LocationResolver:
    def __init__(self, data: Optional[List[Tuple[str, str, str]]] = None):
        self.data = data or AIRPORT_DATA
        self.search_strings = [
            f"{iata} {name} {country}" for iata, name, country in self.data
        ]

    def resolve(self, query: str, limit: int = 5) -> List[Tuple[str, str, str, float]]:
        """
        Fuzzy search for airport or city name.
        Returns a list of tuples: (IATA, Name, Country, Score)
        """
        query_clean = query.strip().upper()
        query_lower = query.strip().lower()

        # 1. Direct exact match on IATA code first
        for iata, name, country in self.data:
            if iata == query_clean:
                return [(iata, name, country, 100.0)]

        # 2. Substring match on airport/city name or country
        direct_matches = []
        for iata, name, country in self.data:
            name_lower = name.lower()
            if query_lower in name_lower or name_lower in query_lower:
                direct_matches.append((iata, name, country, 95.0))

        if direct_matches:
            return direct_matches[:limit]

        # 3. Fuzzy matching against database for typos/misspellings
        results = process.extract(
            query,
            self.search_strings,
            scorer=fuzz.WRatio,
            limit=limit
        )

        matches = []
        for match_str, score, index in results:
            iata, name, country = self.data[index]
            matches.append((iata, name, country, float(score)))

        # 4. Fallback: If user entered an exact 3-letter IATA code not in static list
        if not matches and len(query_clean) == 3 and query_clean.isalpha():
            matches.append((query_clean, f"Airport ({query_clean})", "International", 100.0))

        return matches
