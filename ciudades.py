"""Código IATA -> (nombre a mostrar, país, ciudad donde buscar alojamiento)."""

AEROPUERTOS: dict[str, tuple[str, str, str]] = {
    # España
    "LCG": ("A Coruña", "España", "A Coruña"),
    "ALC": ("Alicante", "España", "Alicante"),
    "LEI": ("Almería", "España", "Almería"),
    "OVD": ("Asturias", "España", "Oviedo"),
    "BCN": ("Barcelona", "España", "Barcelona"),
    "BIO": ("Bilbao", "España", "Bilbao"),
    "IBZ": ("Ibiza", "España", "Ibiza"),
    "MAD": ("Madrid", "España", "Madrid"),
    "PMI": ("Palma de Mallorca", "España", "Palma de Mallorca"),
    "PNA": ("Pamplona", "España", "Pamplona"),
    "EAS": ("San Sebastián", "España", "San Sebastián"),
    "SDR": ("Santander", "España", "Santander"),
    "SCQ": ("Santiago de Compostela", "España", "Santiago de Compostela"),
    "VLC": ("Valencia", "España", "Valencia"),
    "VIT": ("Vitoria", "España", "Vitoria-Gasteiz"),
    "FUE": ("Fuerteventura", "España", "Fuerteventura"),
    "LPA": ("Gran Canaria", "España", "Las Palmas de Gran Canaria"),
    "ACE": ("Lanzarote", "España", "Lanzarote"),
    "TFN": ("Tenerife Norte", "España", "Tenerife"),
    "MLN": ("Melilla", "España", "Melilla"),
    # Portugal y Francia
    "LIS": ("Lisboa", "Portugal", "Lisboa"),
    "OPO": ("Oporto", "Portugal", "Oporto"),
    "BOD": ("Burdeos", "Francia", "Burdeos"),
    "BES": ("Brest", "Francia", "Brest"),
    "LYS": ("Lyon", "Francia", "Lyon"),
    "MRS": ("Marsella", "Francia", "Marsella"),
    "MPL": ("Montpellier", "Francia", "Montpellier"),
    "NTE": ("Nantes", "Francia", "Nantes"),
    "BVA": ("París-Beauvais (85 km de París)", "Francia", "París"),
    "CDG": ("París-Charles de Gaulle", "Francia", "París"),
    "ORY": ("París-Orly", "Francia", "París"),
    "RNS": ("Rennes", "Francia", "Rennes"),
    "TLS": ("Toulouse", "Francia", "Toulouse"),
    "BSL": ("Basilea-Mulhouse", "Suiza/Francia", "Basilea"),
    # Reino Unido e Irlanda
    "BHX": ("Birmingham", "Reino Unido", "Birmingham"),
    "BRS": ("Bristol", "Reino Unido", "Bristol"),
    "EDI": ("Edimburgo", "Reino Unido", "Edimburgo"),
    "LPL": ("Liverpool", "Reino Unido", "Liverpool"),
    "LHR": ("Londres-Heathrow", "Reino Unido", "Londres"),
    "LGW": ("Londres-Gatwick", "Reino Unido", "Londres"),
    "LTN": ("Londres-Luton", "Reino Unido", "Londres"),
    "STN": ("Londres-Stansted", "Reino Unido", "Londres"),
    "MAN": ("Mánchester", "Reino Unido", "Mánchester"),
    "DUB": ("Dublín", "Irlanda", "Dublín"),
    "ORK": ("Cork", "Irlanda", "Cork"),
    # Europa central y norte
    "AMS": ("Ámsterdam", "Países Bajos", "Ámsterdam"),
    "EIN": ("Eindhoven", "Países Bajos", "Eindhoven"),
    "RTM": ("Róterdam", "Países Bajos", "Róterdam"),
    "BRU": ("Bruselas", "Bélgica", "Bruselas"),
    "CRL": ("Bruselas-Charleroi (60 km de Bruselas)", "Bélgica", "Bruselas"),
    "FKB": ("Karlsruhe/Baden-Baden", "Alemania", "Baden-Baden"),
    "BER": ("Berlín", "Alemania", "Berlín"),
    "CGN": ("Colonia/Bonn", "Alemania", "Colonia"),
    "DUS": ("Düsseldorf", "Alemania", "Düsseldorf"),
    "NRN": ("Düsseldorf-Weeze (80 km de Düsseldorf)", "Alemania", "Düsseldorf"),
    "FRA": ("Fráncfort", "Alemania", "Fráncfort"),
    "HAM": ("Hamburgo", "Alemania", "Hamburgo"),
    "MUC": ("Múnich", "Alemania", "Múnich"),
    "NUE": ("Núremberg", "Alemania", "Núremberg"),
    "GVA": ("Ginebra", "Suiza", "Ginebra"),
    "ZRH": ("Zúrich", "Suiza", "Zúrich"),
    "CPH": ("Copenhague", "Dinamarca", "Copenhague"),
    # Italia
    "BRI": ("Bari", "Italia", "Bari"),
    "BLQ": ("Bolonia", "Italia", "Bolonia"),
    "CAG": ("Cagliari (Cerdeña)", "Italia", "Cagliari"),
    "CTA": ("Catania (Sicilia)", "Italia", "Catania"),
    "MXP": ("Milán-Malpensa", "Italia", "Milán"),
    "BGY": ("Milán-Bérgamo", "Italia", "Bérgamo"),
    "PSA": ("Pisa (cerca de Florencia)", "Italia", "Pisa"),
    "FCO": ("Roma-Fiumicino", "Italia", "Roma"),
    "TSF": ("Venecia-Treviso", "Italia", "Venecia"),
    "TRS": ("Trieste", "Italia", "Trieste"),
    "TRN": ("Turín", "Italia", "Turín"),
    "VCE": ("Venecia-Marco Polo", "Italia", "Venecia"),
    # Europa del Este
    "BEG": ("Belgrado", "Serbia", "Belgrado"),
    "OTP": ("Bucarest", "Rumanía", "Bucarest"),
    "BUD": ("Budapest", "Hungría", "Budapest"),
    "KRK": ("Cracovia", "Polonia", "Cracovia"),
    "PRG": ("Praga", "Chequia", "Praga"),
    "WAW": ("Varsovia", "Polonia", "Varsovia"),
    "WRO": ("Breslavia (Wrocław)", "Polonia", "Wrocław"),
    # Marruecos y Turquía
    "CMN": ("Casablanca", "Marruecos", "Casablanca"),
    "ESU": ("Esauira", "Marruecos", "Esauira"),
    "RAK": ("Marrakech", "Marruecos", "Marrakech"),
    "RBA": ("Rabat", "Marruecos", "Rabat"),
    "IST": ("Estambul", "Turquía", "Estambul"),
    "SAW": ("Estambul-Sabiha Gökçen", "Turquía", "Estambul"),
}


def nombre(codigo: str) -> str:
    return AEROPUERTOS.get(codigo, (codigo, "", codigo))[0]


def pais(codigo: str) -> str:
    return AEROPUERTOS.get(codigo, (codigo, "", codigo))[1]


def ciudad_hotel(codigo: str) -> str:
    return AEROPUERTOS.get(codigo, (codigo, "", codigo))[2]
