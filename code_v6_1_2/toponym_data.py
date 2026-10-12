"""Frozen word lists for toponym rule t3 (v6).

COUNTRY_NAMES: ISO 3166-1 country names (pycountry 24.6.1), normalised (lower case, ASCII, punctuation -> space).
HOME_ADMIN1: top-level ISO 3166-2 subdivision names of the study countries (pycountry 24.6.1), normalised.
COMMON_WORDS: per language, every word of wordfreq 3.1.1's "best" list with Zipf frequency >= 4.5 that is purely
    alphabetic and at least 4 characters long once normalised. Rebuilt from the pinned package at import and
    checked against the SHA-256 of the lists used when rule t3 was fixed, so a different wordfreq release can
    never change the rule silently."""
import hashlib
import json
import re
import unicodedata

COMMON_WORDS_SHA256 = "f5b12ab0757c3aa3089b05f3e5b4c23bf8d186a057c1e59ef641343537cef325"
COMMON_WORDS_LANGS = ("ca", "en", "es", "id", "it", "pt")
WORDFREQ_VERSION = "3.1.1"

COUNTRY_NAMES = frozenset((
    'afghanistan', 'aland islands', 'albania', 'algeria', 'american samoa', 'andorra', 'angola', 'anguilla',
    'antarctica', 'antigua and barbuda', 'arab republic of egypt', 'argentina', 'argentine republic',
    'armenia', 'aruba', 'ascension and tristan da cunha saint helena', 'australia', 'austria', 'azerbaijan',
    'bahamas', 'bahrain', 'bangladesh', 'barbados', 'belarus', 'belgium', 'belize', 'benin', 'bermuda',
    'bhutan', 'bolivarian republic of venezuela', 'bolivia', 'bolivia plurinational state of',
    'bonaire sint eustatius and saba', 'bosnia and herzegovina', 'botswana', 'bouvet island', 'brazil',
    'british indian ocean territory', 'british virgin islands', 'brunei darussalam', 'bulgaria',
    'burkina faso', 'burundi', 'cabo verde', 'cambodia', 'cameroon', 'canada', 'cayman islands',
    'central african republic', 'chad', 'chile', 'china', 'christmas island', 'cocos islands', 'colombia',
    'commonwealth of dominica', 'commonwealth of the bahamas', 'commonwealth of the northern mariana islands',
    'comoros', 'congo', 'congo the democratic republic of the', 'cook islands', 'costa rica', 'cote d ivoire',
    'croatia', 'cuba', 'curacao', 'cyprus', 'czech republic', 'czechia',
    'democratic people s republic of korea', 'democratic republic of sao tome and principe',
    'democratic republic of timor leste', 'democratic socialist republic of sri lanka', 'denmark', 'djibouti',
    'dominica', 'dominican republic', 'eastern republic of uruguay', 'ecuador', 'egypt', 'el salvador',
    'equatorial guinea', 'eritrea', 'estonia', 'eswatini', 'ethiopia', 'falkland islands', 'faroe islands',
    'federal democratic republic of ethiopia', 'federal democratic republic of nepal',
    'federal republic of germany', 'federal republic of nigeria', 'federal republic of somalia',
    'federated states of micronesia', 'federative republic of brazil', 'fiji', 'finland', 'france',
    'french guiana', 'french polynesia', 'french republic', 'french southern territories', 'gabon',
    'gabonese republic', 'gambia', 'georgia', 'germany', 'ghana', 'gibraltar', 'grand duchy of luxembourg',
    'greece', 'greenland', 'grenada', 'guadeloupe', 'guam', 'guatemala', 'guernsey', 'guinea', 'guinea bissau',
    'guyana', 'haiti', 'hashemite kingdom of jordan', 'heard island and mcdonald islands', 'hellenic republic',
    'holy see', 'honduras', 'hong kong', 'hong kong special administrative region of china', 'hungary',
    'iceland', 'independent state of papua new guinea', 'independent state of samoa', 'india', 'indonesia',
    'iran', 'iran islamic republic of', 'iraq', 'ireland', 'islamic republic of afghanistan',
    'islamic republic of iran', 'islamic republic of mauritania', 'islamic republic of pakistan',
    'isle of man', 'israel', 'italian republic', 'italy', 'jamaica', 'japan', 'jersey', 'jordan', 'kazakhstan',
    'kenya', 'kingdom of bahrain', 'kingdom of belgium', 'kingdom of bhutan', 'kingdom of cambodia',
    'kingdom of denmark', 'kingdom of eswatini', 'kingdom of lesotho', 'kingdom of morocco',
    'kingdom of norway', 'kingdom of saudi arabia', 'kingdom of spain', 'kingdom of sweden',
    'kingdom of thailand', 'kingdom of the netherlands', 'kingdom of tonga', 'kiribati',
    'korea democratic people s republic of', 'korea republic of', 'kuwait', 'kyrgyz republic', 'kyrgyzstan',
    'lao people s democratic republic', 'laos', 'latvia', 'lebanese republic', 'lebanon', 'lesotho', 'liberia',
    'libya', 'liechtenstein', 'lithuania', 'luxembourg', 'macao',
    'macao special administrative region of china', 'madagascar', 'malawi', 'malaysia', 'maldives', 'mali',
    'malta', 'marshall islands', 'martinique', 'mauritania', 'mauritius', 'mayotte', 'mexico',
    'micronesia federated states of', 'moldova', 'moldova republic of', 'monaco', 'mongolia', 'montenegro',
    'montserrat', 'morocco', 'mozambique', 'myanmar', 'namibia', 'nauru', 'nepal', 'netherlands',
    'new caledonia', 'new zealand', 'nicaragua', 'niger', 'nigeria', 'niue', 'norfolk island', 'north korea',
    'north macedonia', 'northern mariana islands', 'norway', 'oman', 'pakistan', 'palau', 'palestine state of',
    'panama', 'papua new guinea', 'paraguay', 'people s democratic republic of algeria',
    'people s republic of bangladesh', 'people s republic of china', 'peru', 'philippines', 'pitcairn',
    'plurinational state of bolivia', 'poland', 'portugal', 'portuguese republic', 'principality of andorra',
    'principality of liechtenstein', 'principality of monaco', 'province of china taiwan', 'puerto rico',
    'qatar', 'republic of albania', 'republic of angola', 'republic of armenia', 'republic of austria',
    'republic of azerbaijan', 'republic of belarus', 'republic of benin', 'republic of bosnia and herzegovina',
    'republic of botswana', 'republic of bulgaria', 'republic of burundi', 'republic of cabo verde',
    'republic of cameroon', 'republic of chad', 'republic of chile', 'republic of colombia',
    'republic of costa rica', 'republic of cote d ivoire', 'republic of croatia', 'republic of cuba',
    'republic of cyprus', 'republic of djibouti', 'republic of ecuador', 'republic of el salvador',
    'republic of equatorial guinea', 'republic of estonia', 'republic of fiji', 'republic of finland',
    'republic of ghana', 'republic of guatemala', 'republic of guinea', 'republic of guinea bissau',
    'republic of guyana', 'republic of haiti', 'republic of honduras', 'republic of iceland',
    'republic of india', 'republic of indonesia', 'republic of iraq', 'republic of kazakhstan',
    'republic of kenya', 'republic of kiribati', 'republic of korea', 'republic of latvia',
    'republic of liberia', 'republic of lithuania', 'republic of madagascar', 'republic of malawi',
    'republic of maldives', 'republic of mali', 'republic of malta', 'republic of mauritius',
    'republic of moldova', 'republic of mozambique', 'republic of myanmar', 'republic of namibia',
    'republic of nauru', 'republic of nicaragua', 'republic of north macedonia', 'republic of palau',
    'republic of panama', 'republic of paraguay', 'republic of peru', 'republic of poland',
    'republic of san marino', 'republic of senegal', 'republic of serbia', 'republic of seychelles',
    'republic of sierra leone', 'republic of singapore', 'republic of slovenia', 'republic of south africa',
    'republic of south sudan', 'republic of suriname', 'republic of tajikistan', 'republic of the congo',
    'republic of the gambia', 'republic of the marshall islands', 'republic of the niger',
    'republic of the philippines', 'republic of the sudan', 'republic of trinidad and tobago',
    'republic of tunisia', 'republic of turkiye', 'republic of uganda', 'republic of uzbekistan',
    'republic of vanuatu', 'republic of yemen', 'republic of zambia', 'republic of zimbabwe', 'reunion',
    'romania', 'russian federation', 'rwanda', 'rwandese republic', 'saint barthelemy',
    'saint helena ascension and tristan da cunha', 'saint kitts and nevis', 'saint lucia', 'saint martin',
    'saint pierre and miquelon', 'saint vincent and the grenadines', 'samoa', 'san marino',
    'sao tome and principe', 'saudi arabia', 'senegal', 'serbia', 'seychelles', 'sierra leone', 'singapore',
    'sint eustatius and saba bonaire', 'sint maarten', 'slovak republic', 'slovakia', 'slovenia',
    'socialist republic of viet nam', 'solomon islands', 'somalia', 'south africa',
    'south georgia and the south sandwich islands', 'south korea', 'south sudan', 'spain', 'sri lanka',
    'state of israel', 'state of kuwait', 'state of palestine', 'state of qatar', 'sudan', 'sultanate of oman',
    'suriname', 'svalbard and jan mayen', 'sweden', 'swiss confederation', 'switzerland', 'syria',
    'syrian arab republic', 'taiwan', 'taiwan province of china', 'tajikistan', 'tanzania',
    'tanzania united republic of', 'thailand', 'the democratic republic of the congo', 'the state of eritrea',
    'the state of palestine', 'timor leste', 'togo', 'togolese republic', 'tokelau', 'tonga',
    'trinidad and tobago', 'tunisia', 'turkiye', 'turkmenistan', 'turks and caicos islands', 'tuvalu',
    'u s virgin islands', 'uganda', 'ukraine', 'union of the comoros', 'united arab emirates',
    'united kingdom', 'united kingdom of great britain and northern ireland', 'united mexican states',
    'united republic of tanzania', 'united states', 'united states minor outlying islands',
    'united states of america', 'uruguay', 'uzbekistan', 'vanuatu', 'venezuela',
    'venezuela bolivarian republic of', 'viet nam', 'vietnam', 'virgin islands british',
    'virgin islands of the united states', 'virgin islands u s', 'wallis and futuna', 'western sahara',
    'yemen', 'zambia', 'zimbabwe',
))

HOME_ADMIN1 = {
    'BR': frozenset((
        'acre', 'alagoas', 'amapa', 'amazonas', 'bahia', 'ceara', 'distrito federal', 'espirito santo',
        'goias', 'maranhao', 'mato grosso', 'mato grosso do sul', 'minas gerais', 'para', 'paraiba', 'parana',
        'pernambuco', 'piaui', 'rio de janeiro', 'rio grande do norte', 'rio grande do sul', 'rondonia',
        'roraima', 'santa catarina', 'sao paulo', 'sergipe', 'tocantins',
    )),
    'ES': frozenset((
        'andalucia', 'aragon', 'asturias principado de', 'canarias', 'cantabria', 'castilla la mancha',
        'castilla y leon', 'cataluna', 'catalunya', 'ceuta', 'comunidad de madrid', 'comunidad valenciana',
        'euskal herria', 'extremadura', 'galicia', 'illes balears', 'islas baleares', 'la rioja',
        'madrid comunidad de', 'melilla', 'murcia region de', 'nafarroako foru komunitatea',
        'principado de asturias', 'region de murcia', 'valenciana comunidad',
    )),
    'GB': frozenset((
        'cymru gb cym', 'england', 'northern ireland', 'scotland', 'wales',
    )),
    'ID': frozenset((
        'jawa', 'kalimantan', 'maluku', 'nusa tenggara', 'papua', 'sulawesi', 'sumatera',
    )),
    'IN': frozenset((
        'andaman and nicobar islands', 'andhra pradesh', 'arunachal pradesh', 'assam', 'bihar', 'chandigarh',
        'chhattisgarh', 'dadra and nagar haveli and daman and diu', 'delhi', 'goa', 'gujarat', 'haryana',
        'himachal pradesh', 'jammu and kashmir', 'jharkhand', 'karnataka', 'kerala', 'ladakh', 'lakshadweep',
        'madhya pradesh', 'maharashtra', 'manipur', 'meghalaya', 'mizoram', 'nagaland', 'odisha', 'puducherry',
        'punjab', 'rajasthan', 'sikkim', 'tamil nadu', 'telangana', 'tripura', 'uttar pradesh', 'uttarakhand',
        'west bengal',
    )),
    'IT': frozenset((
        'abruzzo', 'basilicata', 'calabria', 'campania', 'emilia romagna', 'friuli venezia giulia', 'lazio',
        'liguria', 'lombardia', 'marche', 'molise', 'piemonte', 'puglia', 'sardegna', 'sicilia', 'toscana',
        'trentino alto adige', 'umbria', 'val d aoste', 'veneto',
    )),
    'US': frozenset((
        'alabama', 'alaska', 'american samoa', 'arizona', 'arkansas', 'california', 'colorado', 'connecticut',
        'delaware', 'district of columbia', 'florida', 'georgia', 'guam', 'hawaii', 'idaho', 'illinois',
        'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana', 'maine', 'maryland', 'massachusetts', 'michigan',
        'minnesota', 'mississippi', 'missouri', 'montana', 'nebraska', 'nevada', 'new hampshire', 'new jersey',
        'new mexico', 'new york', 'north carolina', 'north dakota', 'northern mariana islands', 'ohio',
        'oklahoma', 'oregon', 'pennsylvania', 'puerto rico', 'rhode island', 'south carolina', 'south dakota',
        'tennessee', 'texas', 'u s virgin islands', 'united states minor outlying islands', 'utah', 'vermont',
        'virgin islands u s', 'virginia', 'washington', 'west virginia', 'wisconsin', 'wyoming',
    )),
}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def _build_common_words():
    try:
        import importlib.metadata as im
        from wordfreq import iter_wordlist, zipf_frequency
        ver = im.version("wordfreq")
    except Exception as e:  # noqa: BLE001
        raise ImportError(f"toponym rule t3 needs wordfreq=={WORDFREQ_VERSION} (pip install wordfreq=={WORDFREQ_VERSION}): {e}")
    out = {}
    for lang in COMMON_WORDS_LANGS:
        words = set()
        for w in iter_wordlist(lang, "best"):
            if zipf_frequency(w, lang) < 4.5:
                break
            n = _norm(w)
            if w.isalpha() and len(n) >= 4:
                words.add(n)
        out[lang] = frozenset(words)
    h = hashlib.sha256(json.dumps({k: sorted(v) for k, v in sorted(out.items())}).encode()).hexdigest()
    if h != COMMON_WORDS_SHA256:
        raise RuntimeError(f"common-word lists from wordfreq {ver} differ from the pre-registered ones (SHA {h[:12]} vs "
                           f"{COMMON_WORDS_SHA256[:12]}): install wordfreq=={WORDFREQ_VERSION}")
    return out


COMMON_WORDS = _build_common_words()
