# Global Region Airport Expansion Design

## Overview
Expand the gateway hub coverage in `services/airports_data.py` (`GLOBAL_REGIONS_AIRPORTS`) across Asia, North America, Latin America, Africa, and Middle East with primary capital/cultural hub airports.

## Proposed Airport Additions

### 1. `asia`
- **NRT**: Tokyo Narita (Japan)
- **KIX**: Osaka Kansai (Japan)
- **TPE**: Taipei Taoyuan (Taiwan)
- **PEK**: Beijing Capital (China)
- **CGK**: Jakarta Soekarno-Hatta (Indonesia)
- **HAN**: Hanoi Noi Bai (Vietnam)
- **CNX**: Chiang Mai (Thailand)

### 2. `north_america`
- **EWR**: New York Newark Liberty (United States)
- **SEA**: Seattle Tacoma (United States)
- **DFW**: Dallas/Fort Worth (United States)
- **MCO**: Orlando International (United States)
- **YUL**: Montreal Trudeau (Canada)

### 3. `latin_america`
- **GIG**: Rio de Janeiro Galeão (Brazil)
- **MDE**: Medellín José María Córdova (Colombia)
- **GDL**: Guadalajara (Mexico)
- **MVD**: Montevideo Carrasco (Uruguay)
- **HAV**: Havana José Martí (Cuba)

### 4. `africa`
- **ZNZ**: Zanzibar Abeid Amani Karume (Tanzania)
- **SEZ**: Seychelles International (Seychelles)
- **SSH**: Sharm El-Sheikh (Egypt)
- **HRG**: Hurghada (Egypt)
- **DKR**: Dakar Blaise Diagne (Senegal)

### 5. `middle_east`
- **IST**: Istanbul Airport (Turkey)
- **SAW**: Istanbul Sabiha Gökçen (Turkey)
- **BEY**: Beirut Rafic Hariri (Lebanon)
- **MED**: Madinah Prince Mohammad bin Abdulaziz (Saudi Arabia)

## Verification Plan
- Update `services/airports_data.py` with unique codes and correct country labels.
- Run `pytest tests/test_airports_data.py` and the full test suite to ensure structure and mappings pass.
