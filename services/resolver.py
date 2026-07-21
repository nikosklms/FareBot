from typing import List, Tuple, Optional
from rapidfuzz import process, fuzz

# Comprehensive list of major Greek, European, and Global Airports
AIRPORT_DATA = [
    # Greece
    ("ATH", "Athens Eleftherios Venizelos", "Greece"),
    ("SKG", "Thessaloniki Makedonia Airport", "Greece"),
    ("HER", "Heraklion Nikos Kazantzakis", "Greece"),
    ("CHQ", "Chania Ioannis Daskalogiannis", "Greece"),
    ("RHO", "Rhodes Diagoras Airport", "Greece"),
    ("CFU", "Corfu Ioannis Kapodistrias", "Greece"),
    ("JMK", "Mykonos Island National", "Greece"),
    ("JTR", "Santorini Thira Airport", "Greece"),
    ("KGS", "Kos International Airport", "Greece"),
    ("ZTH", "Zakynthos International", "Greece"),
    ("KTT", "Kalamata Captain Vassilis Constantakopoulos", "Greece"),

    # United Kingdom
    ("LON", "London All Airports", "United Kingdom"),
    ("LHR", "London Heathrow", "United Kingdom"),
    ("LGW", "London Gatwick", "United Kingdom"),
    ("STN", "London Stansted", "United Kingdom"),
    ("LTN", "London Luton", "United Kingdom"),
    ("MAN", "Manchester Airport", "United Kingdom"),
    ("EDI", "Edinburgh Airport", "United Kingdom"),
    ("GLA", "Glasgow Airport", "United Kingdom"),

    # Europe
    ("CDG", "Paris Charles de Gaulle", "France"),
    ("ORY", "Paris Orly", "France"),
    ("PAR", "Paris All Airports", "France"),
    ("NCE", "Nice Cote d'Azur", "France"),
    ("FRA", "Frankfurt Airport", "Germany"),
    ("MUC", "Munich Airport", "Germany"),
    ("BER", "Berlin Brandenburg", "Germany"),
    ("HAM", "Hamburg Airport", "Germany"),
    ("FCO", "Rome Fiumicino", "Italy"),
    ("MXP", "Milan Malpensa", "Italy"),
    ("BGY", "Milan Bergamo", "Italy"),
    ("VCE", "Venice Marco Polo", "Italy"),
    ("MAD", "Madrid Barajas", "Spain"),
    ("BCN", "Barcelona El Prat", "Spain"),
    ("AGP", "Malaga Costa del Sol", "Spain"),
    ("PMI", "Palma de Mallorca", "Spain"),
    ("AMS", "Amsterdam Schiphol", "Netherlands"),
    ("BRU", "Brussels Airport", "Belgium"),
    ("VIE", "Vienna International", "Austria"),
    ("ZRH", "Zurich Airport", "Switzerland"),
    ("GVA", "Geneva Airport", "Switzerland"),
    ("LIS", "Lisbon Humberto Delgado", "Portugal"),
    ("OPO", "Porto Francisco Sa Carneiro", "Portugal"),
    ("DUB", "Dublin Airport", "Ireland"),
    ("CPH", "Copenhagen Airport", "Denmark"),
    ("OSL", "Oslo Gardermoen", "Norway"),
    ("ARN", "Stockholm Arlanda", "Sweden"),
    ("HEL", "Helsinki Vantaa", "Finland"),
    ("WAW", "Warsaw Chopin", "Poland"),
    ("PRG", "Václav Havel Prague", "Czech Republic"),
    ("BUD", "Budapest Ferenc Liszt", "Hungary"),
    ("IST", "Istanbul Airport", "Turkey"),
    ("SAW", "Istanbul Sabiha Gokcen", "Turkey"),

    # Americas & Middle East / Asia
    ("JFK", "New York John F Kennedy", "United States"),
    ("EWR", "New York Newark", "United States"),
    ("LGA", "New York LaGuardia", "United States"),
    ("LAX", "Los Angeles International", "United States"),
    ("ORD", "Chicago O'Hare", "United States"),
    ("MIA", "Miami International", "United States"),
    ("SFO", "San Francisco International", "United States"),
    ("BOS", "Boston Logan", "United States"),
    ("YYZ", "Toronto Pearson", "Canada"),
    ("YVR", "Vancouver International", "Canada"),
    ("DXB", "Dubai International", "United Arab Emirates"),
    ("DOH", "Doha Hamad International", "Qatar"),
    ("AUH", "Abu Dhabi International", "United Arab Emirates"),
    ("HND", "Tokyo Haneda", "Japan"),
    ("NRT", "Tokyo Narita", "Japan"),
    ("SIN", "Singapore Changi", "Singapore"),
    ("SYD", "Sydney Kingsford Smith", "Australia"),
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

        # Fuzzy matching against database
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

        # Fallback: If user entered an exact 3-letter IATA code not in static list
        if not matches and len(query_clean) == 3 and query_clean.isalpha():
            matches.append((query_clean, f"Airport ({query_clean})", "International", 100.0))

        return matches
