from typing import List, Tuple, Optional
from rapidfuzz import process, fuzz

# Default dictionary of major world airports and cities
AIRPORT_DATA = [
    ("ATH", "Athens Eleftherios Venizelos", "Greece"),
    ("LHR", "London Heathrow", "United Kingdom"),
    ("LGW", "London Gatwick", "United Kingdom"),
    ("STN", "London Stansted", "United Kingdom"),
    ("LON", "London All Airports", "United Kingdom"),
    ("CDG", "Paris Charles de Gaulle", "France"),
    ("ORY", "Paris Orly", "France"),
    ("PAR", "Paris All Airports", "France"),
    ("FRA", "Frankfurt Airport", "Germany"),
    ("BER", "Berlin Brandenburg", "Germany"),
    ("JFK", "New York John F Kennedy", "United States"),
    ("EWR", "New York Newark", "United States"),
    ("LAX", "Los Angeles International", "United States"),
    ("DXB", "Dubai International", "United Arab Emirates"),
    ("FCO", "Rome Fiumicino", "Italy"),
    ("MAD", "Madrid Barajas", "Spain"),
    ("BCN", "Barcelona El Prat", "Spain"),
    ("AMS", "Amsterdam Schiphol", "Netherlands"),
]

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
        # Direct exact match on IATA code first
        for iata, name, country in self.data:
            if iata == query_clean:
                return [(iata, name, country, 100.0)]

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

        return matches
