"""AT-5 — the closed sets a column's values can belong to.

This file is DATA, and it exists because of one measured false positive: `^[A-Z]{2}$`
matched `Customer State` (`UT`, `MD`, `GA`) as an ISO-3166 country code. A pattern describes
a SHAPE, and every two-letter code has the same shape — Utah and Moldova are indistinguishable
to a regex and trivially separable by a list. So the rule for this whole layer is:

    membership in a real set, never a pattern that resembles one.

The separation is measurable on the column that produced the defect. Of `Customer State`'s
46 distinct values, 44 are US state codes (96%) and about 20 are also ISO-3166 country codes
(43%). One list accepts it, the other refuses it, and the share is the discriminator.

**Normalisation is part of the data.** `EE. UU.` is how Spanish writes "USA", `Myanmar
(Birmania)` carries a parenthetical, `SudAfrica` is missing its accent, and `Níger` has one.
Comparing those to a vocabulary requires folding away everything that is not a letter or a
digit, on both sides, with the same function — so `normalize` is the only way in and out.

**Coverage is honest about its edges.** English and Spanish country names are complete
enough for the corpus AT-0 measured (data_co's `Order Country` holds 164 Spanish names);
French, German, Portuguese and Italian are covered only for the countries whose names
survive normalisation from one of those two, plus the weekday and month names below, which
are complete in six languages because they are twelve words each. Partial coverage costs
RECALL and never precision: a column of French country names scores below the threshold and
is refused, which is the correct answer for a list that does not contain them.
"""
from __future__ import annotations

import unicodedata


def normalize(value) -> str:
    """Fold a value to its comparison key: no case, no accents, no punctuation, no spaces.

    `EE. UU.` → `eeuu`; `Papúa Nueva Guinea` → `papuanuevaguinea`; `Myanmar (Birmania)` →
    `myanmarbirmania`. Both the vocabulary and the column's values go through this, so a
    fold that loses information loses it symmetrically.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text.lower() if c.isalnum() and not unicodedata.combining(c))


def _fold(raw: str) -> frozenset:
    return frozenset(normalize(t) for t in raw.split() if t)


# ── ISO 3166-1 alpha-2 ────────────────────────────────────────────────────────
ISO3166_ALPHA2 = _fold("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ
BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM
DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS
GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN
KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ
MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM
PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV
SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI
VN VU WF WS YE YT ZA ZM ZW
""")

# ── ISO 3166-1 alpha-3 ────────────────────────────────────────────────────────
ISO3166_ALPHA3 = _fold("""
AND ARE AFG ATG AIA ALB ARM AGO ATA ARG ASM AUT AUS ABW ALA AZE BIH BRB BGD BEL BFA BGR BHR
BDI BEN BLM BMU BRN BOL BES BRA BHS BTN BVT BWA BLR BLZ CAN CCK COD CAF COG CHE CIV COK CHL
CMR CHN COL CRI CUB CPV CUW CXR CYP CZE DEU DJI DNK DMA DOM DZA ECU EST EGY ESH ERI ESP ETH
FIN FJI FLK FSM FRO FRA GAB GBR GRD GEO GUF GGY GHA GIB GRL GMB GIN GLP GNQ GRC SGS GTM GUM
GNB GUY HKG HMD HND HRV HTI HUN IDN IRL ISR IMN IND IOT IRQ IRN ISL ITA JEY JAM JOR JPN KEN
KGZ KHM KIR COM KNA PRK KOR KWT CYM KAZ LAO LBN LCA LIE LKA LBR LSO LTU LUX LVA LBY MAR MCO
MDA MNE MAF MDG MHL MKD MLI MMR MNG MAC MNP MTQ MRT MSR MLT MUS MDV MWI MEX MYS MOZ NAM NCL
NER NFK NGA NIC NLD NOR NPL NRU NIU NZL OMN PAN PER PYF PNG PHL PAK POL SPM PCN PRI PSE PRT
PLW PRY QAT REU ROU SRB RUS RWA SAU SLB SYC SDN SWE SGP SHN SVN SJM SVK SLE SMR SEN SOM SUR
SSD STP SLV SXM SYR SWZ TCA TCD ATF TGO THA TJK TKL TLS TKM TUN TON TUR TTO TUV TWN TZA UKR
UGA UMI USA URY UZB VAT VCT VEN VGB VIR VNM VUT WLF WSM YEM MYT ZAF ZMB ZWE
""")

# ── ISO 4217 currency codes ───────────────────────────────────────────────────
ISO4217 = _fold("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP
BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP
GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS
KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR
MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF
SAR SBD SCR SDG SEK SGD SHP SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD
TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL
""")

# ── US states, DC and territories ─────────────────────────────────────────────
US_STATE_CODES = _fold("""
AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ
NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC AS GU MP PR VI UM
""")

# ── Country names, English ────────────────────────────────────────────────────
_COUNTRIES_EN = """
Afghanistan Albania Algeria Andorra Angola Antigua Argentina Armenia Australia Austria
Azerbaijan Bahamas Bahrain Bangladesh Barbados Belarus Belgium Belize Benin Bhutan Bolivia
Bosnia Botswana Brazil Brunei Bulgaria Burkina-Faso Burundi Cambodia Cameroon Canada
Cape-Verde Central-African-Republic Chad Chile China Colombia Comoros Congo Costa-Rica
Croatia Cuba Cyprus Czechia Czech-Republic Denmark Djibouti Dominica Dominican-Republic
Ecuador Egypt El-Salvador Equatorial-Guinea Eritrea Estonia Eswatini Ethiopia Fiji Finland
France French-Guiana Gabon Gambia Georgia Germany Ghana Greece Grenada Guadeloupe Guatemala
Guinea Guinea-Bissau Guyana Haiti Honduras Hong-Kong Hungary Iceland India Indonesia Iran
Iraq Ireland Israel Italy Ivory-Coast Jamaica Japan Jordan Kazakhstan Kenya Kiribati Kuwait
Kyrgyzstan Laos Latvia Lebanon Lesotho Liberia Libya Liechtenstein Lithuania Luxembourg
Macedonia Madagascar Malawi Malaysia Maldives Mali Malta Martinique Mauritania Mauritius
Mexico Moldova Monaco Mongolia Montenegro Morocco Mozambique Myanmar Burma Namibia Nepal
Netherlands New-Zealand Nicaragua Niger Nigeria North-Korea Norway Oman Pakistan Panama
Papua-New-Guinea Paraguay Peru Philippines Poland Portugal Puerto-Rico Qatar Romania Russia
Rwanda Samoa San-Marino Saudi-Arabia Senegal Serbia Seychelles Sierra-Leone Singapore
Slovakia Slovenia Somalia South-Africa South-Korea South-Sudan Spain Sri-Lanka Sudan
Suriname Swaziland Sweden Switzerland Syria Taiwan Tajikistan Tanzania Thailand Togo Tonga
Trinidad Tunisia Turkey Turkmenistan Uganda Ukraine United-Arab-Emirates United-Kingdom
United-States Uruguay Uzbekistan Vanuatu Vatican Venezuela Vietnam Western-Sahara Yemen
Zambia Zimbabwe
"""

# ── Country names, Spanish ────────────────────────────────────────────────────
# The 164 spellings data_co's `Order Country` actually carries, plus the rest of the world.
# `EE. UU.` and `Myanmar (Birmania)` are in here as written; `normalize` folds them.
_COUNTRIES_ES = """
Afganistán Albania Alemania Andorra Angola Arabia-Saudí Argelia Argentina Armenia Australia
Austria Azerbaiyán Bahamas Bangladés Barbados Baréin Bélgica Belice Benín Bielorrusia
Birmania Bolivia Bosnia-y-Herzegovina Botsuana Brasil Brunéi Bulgaria Burkina-Faso Burundi
Bután Cabo-Verde Camboya Camerún Canada Canadá Catar Chad Chile China Chipre Colombia
Comoras Corea-del-Norte Corea-del-Sur Costa-de-Marfil Costa-Rica Croacia Cuba Dinamarca
Dominica Ecuador Egipto El-Salvador Emiratos-Árabes-Unidos Eritrea Eslovaquia Eslovenia
España Estados-Unidos Estonia Etiopía Filipinas Finlandia Fiyi Francia Gabón Georgia Ghana
Grecia Granada Guadalupe Guatemala Guayana-Francesa Guinea Guinea-Bissau Guinea-Ecuatorial
Guyana Haití Honduras Hong-Kong Hungría India Indonesia Irak Irán Irlanda Islandia Israel
Italia Jamaica Japón Jordania Kazajistán Kenia Kirguistán Kiribati Kuwait Laos Lesoto
Letonia Líbano Liberia Libia Liechtenstein Lituania Luxemburgo Macedonia Madagascar Malasia
Malaui Maldivas Mali Malí Malta Marruecos Martinica Mauricio Mauritania México Moldavia
Mónaco Mongolia Montenegro Mozambique Myanmar Namibia Nepal Nicaragua Níger Nigeria Noruega
Nueva-Zelanda Omán Países-Bajos Pakistán Panamá Papúa-Nueva-Guinea Paraguay Perú Polonia
Portugal Puerto-Rico Qatar Reino-Unido República-Centroafricana República-Checa
República-de-Gambia República-del-Congo República-Democrática-del-Congo
República-Dominicana Ruanda Rumania Rusia Sáhara-Occidental Samoa San-Marino Senegal
Serbia Seychelles Sierra-Leona Singapur Siria Somalia Sri-Lanka SudAfrica Sudáfrica Sudán
Sudán-del-Sur Suecia Suiza Surinam Suazilandia Tailandia Taiwán Tanzania Tayikistán Togo
Tonga Trinidad-y-Tobago Túnez Turkmenistán Turquía Ucrania Uganda Uruguay Uzbekistán
Vanuatu Vaticano Venezuela Vietnam Yemen Yibuti Zambia Zimbabue
"""

# The two-word forms the corpus writes with spaces rather than hyphens, and the
# abbreviations. Kept separate so the lists above stay readable as country lists.
_COUNTRIES_EXTRA = """
EE.UU. USA UK UAE Myanmar(Birmania) Cote-d-Ivoire Holanda Gran-Bretaña
"""

COUNTRY_NAMES = _fold(_COUNTRIES_EN) | _fold(_COUNTRIES_ES) | _fold(_COUNTRIES_EXTRA)

# ── Weekday and month names — complete in six languages ───────────────────────
WEEKDAY_NAMES = _fold("""
Monday Tuesday Wednesday Thursday Friday Saturday Sunday
Mon Tue Tues Wed Thu Thurs Fri Sat Sun
Lunes Martes Miércoles Jueves Viernes Sábado Domingo
Lundi Mardi Mercredi Jeudi Vendredi Samedi Dimanche
Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag
Segunda-feira Terça-feira Quarta-feira Quinta-feira Sexta-feira Sábado Domingo
Lunedì Martedì Mercoledì Giovedì Venerdì Sabato Domenica
""")

MONTH_NAMES = _fold("""
January February March April May June July August September October November December
Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec
Enero Febrero Marzo Abril Mayo Junio Julio Agosto Septiembre Octubre Noviembre Diciembre
Janvier Février Mars Avril Mai Juin Juillet Août Septembre Octobre Novembre Décembre
Januar Februar März Juni Juli August September Oktober November Dezember
Janeiro Fevereiro Março Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro
Gennaio Febbraio Marzo Aprile Maggio Giugno Luglio Agosto Settembre Ottobre Novembre
Dicembre
""")


#: Every list this module publishes. Deliberately WITHOUT the concept each supports: that
#: mapping lives in `shape._SETS`, next to the code that emits the witness, and a copy here
#: is a copy that drifts. It already did — this tuple shipped naming `code.country`,
#: `geo.us_state` and `geo.country_name`, three concepts nothing emits and the operations
#: vocabulary has no rows for, in the one file the coverage ratchet does not read.
#: A vocabulary module publishes vocabulary.
ALL_SETS: tuple = (
    ISO3166_ALPHA2, ISO3166_ALPHA3, ISO4217, US_STATE_CODES,
    COUNTRY_NAMES, WEEKDAY_NAMES, MONTH_NAMES,
)


def membership(values, vocabulary) -> float:
    """Share of DISTINCT normalised values that are in `vocabulary`.

    Distinct, not rows: a column where one value repeats 10,000 times would otherwise pass
    on the strength of a single match. Empty input scores 0.0 — an absent answer, never a
    perfect one.
    """
    keys = {normalize(v) for v in (values or ())}
    keys.discard("")
    if not keys:
        return 0.0
    return round(sum(1 for k in keys if k in vocabulary) / len(keys), 4)
