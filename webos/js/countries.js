// Recognise the country or language of channels, groups and titles, the same rules as Zono for Windows
// (countries.py): "BE | VTM", "NL: NPO 1", "|FR| TF1", "[UK] Sky", a group called "BELGIË", or a known channel ("VRT 1").
(function (root) {
  "use strict";
  // code: [words that point to it]
  var WORDS = {
    BE: ["BELGI", "BELGIQUE", "VLAAMS", "VLAANDEREN", "FLEMISH", "WALLONIE"], NL: ["NEDERLAND", "NETHERLANDS", "HOLLAND", "DUTCH", "NEDERLANDS"],
    FR: ["FRANCE", "FRANKRIJK", "FRENCH", "FRANCAIS", "FRANÇAIS"], DE: ["GERMANY", "DEUTSCH", "DUITS", "GERMAN"],
    UK: ["UNITED KINGDOM", "BRITISH", "ENGLAND"], US: ["USA", "UNITED STATES", "AMERICA"], EN: ["ENGLISH", "ENGELS"],
    ES: ["SPAIN", "ESPANA", "ESPAÑA", "SPANISH", "SPAANS"], IT: ["ITALY", "ITALIA", "ITALIAN"], PT: ["PORTUGAL", "PORTUGUES"],
    BR: ["BRASIL", "BRAZIL"], TR: ["TURKEY", "TURKIYE", "TÜRKIYE", "TURKISH", "TURKS"], PL: ["POLAND", "POLSKA", "POLISH"],
    AR: ["ARABIC", "ARAB", "ARABISCH"], MA: ["MAROC", "MOROCCO", "MAROKKO"], DZ: ["ALGERIE", "ALGERIA"], TN: ["TUNISIE", "TUNISIA"],
    IN: ["INDIA", "HINDI", "INDIAN"], PK: ["PAKISTAN", "URDU"], AL: ["ALBANIA", "SHQIP"], RO: ["ROMANIA"], RU: ["RUSSIA", "RUSSIAN"],
    GR: ["GREECE", "GREEK", "HELLAS"], SE: ["SWEDEN", "SVERIGE"], DK: ["DENMARK", "DANMARK"], NO: ["NORWAY", "NORGE"], FI: ["FINLAND", "SUOMI"],
    CH: ["SWITZERLAND", "SCHWEIZ", "SUISSE"], AT: ["AUSTRIA", "ÖSTERREICH", "OSTERREICH"], IE: ["IRELAND"], CA: ["CANADA"], AU: ["AUSTRALIA"],
    MX: ["MEXICO"], LAT: ["LATINO", "LATIN"], AFR: ["AFRICA", "AFRIQUE"], EXYU: ["EX-YU", "EXYU", "BALKAN"], CZ: ["CZECH"],
    HU: ["HUNGARY", "MAGYAR"], BG: ["BULGARIA"], KU: ["KURD"], IR: ["IRAN", "PERSIAN", "FARSI"], CN: ["CHINA", "CHINESE"], PH: ["PHILIPPINES", "FILIPINO"],
  };
  var ORDER = Object.keys(WORDS);
  var ALIASES = { GB: "UK", ENG: "EN", VL: "BE", FL: "BE", BEL: "BE", NED: "NL", FRA: "FR", GER: "DE", ITA: "IT", ESP: "ES", TUR: "TR",
    POL: "PL", ARA: "AR", USA: "US", YU: "EXYU", LA: "LAT", PER: "IR", FA: "IR" };
  var BRANDS = {
    BE: ["VRT", "VTM", "EEN", "CANVAS", "KETNET", "PLAY4", "PLAY 4", "PLAY5", "PLAY 5", "PLAY6", "PLAY 6", "PLAY7", "PLAY 7", "PLAY SPORTS", "VIER",
      "VIJF", "ZES", "RTBF", "LA UNE", "TIPIK", "RTL-TVI", "RTL TVI", "CLUB RTL", "PLUG RTL", "CAZ", "KANAAL Z", "LN24", "ATV", "ROB-TV", "TV OOST",
      "FOCUS-WTV", "NOTELE", "ELEVEN PRO", "ELEVEN SPORTS BE", "DOBBIT", "ACTUA TV", "TVL", "BRUZZ", "RINGTV"],
    NL: ["NPO", "RTL 4", "RTL4", "RTL 5", "RTL5", "RTL 7", "RTL7", "RTL 8", "RTL8", "RTL Z", "SBS6", "SBS 6", "SBS9", "NET5", "NET 5", "VERONICA",
      "ZIGGO", "VIDEOLAND", "AT5", "OMROEP", "TV WEST", "RTV", "ESPN NL"],
    FR: ["TF1", "FRANCE 2", "FRANCE 3", "FRANCE 5", "M6", "CANAL+", "ARTE FR", "BFM", "TMC"],
    DE: ["ARD", "ZDF", "PRO7", "PROSIEBEN", "SAT.1", "SAT1", "RTL2", "VOX", "KABEL 1", "KABEL EINS"],
    UK: ["BBC", "ITV", "SKY", "CHANNEL 4", "CHANNEL 5"],
  };
  var SKIP = { HD: 1, FHD: 1, UHD: 1, SD: 1, "4K": 1, "8K": 1, VIP: 1, ALL: 1, MULTI: 1, VOD: 1, TV: 1, NEW: 1, TOP: 1, PPV: 1, LIVE: 1,
    "24/7": 1, "247": 1, XXX: 1, HEVC: 1, H265: 1, RAW: 1, SUB: 1, DUB: 1 };
  var LABEL = /(?:^|[\[\(|])\s*([A-Z]{2,4})\s*(?:[\]\)|:]|\s[-–»|]\s?|\s*$)/g;
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  var BRAND_RX = {};
  Object.keys(BRANDS).forEach(function (code) {
    BRAND_RX[code] = new RegExp("(^|[^A-Z0-9])(" + BRANDS[code].map(esc).join("|") + ")(?![A-Z0-9])");
  });

  function code(token) {
    token = token.toUpperCase().replace(/-/g, "");
    token = ALIASES[token] || token;
    return WORDS[token] && !SKIP[token] ? token : "";
  }
  var cache = {}, cached = 0;
  /** Country code for a group name or title, or "" when it cannot be told. */
  function detectText(text, brands, words) {
    if (!text) return "";
    var upper = String(text).toUpperCase(), key = upper + (brands ? "|b" : "") + (words === false ? "|n" : "");
    if (key in cache) return cache[key];
    var found = "", m;
    LABEL.lastIndex = 0;
    var head = upper.slice(0, 40);
    while (!found && (m = LABEL.exec(head))) { found = code(m[1]); if (m.index === LABEL.lastIndex) LABEL.lastIndex++; }
    if (!found && words !== false) {
      for (var i = 0; i < ORDER.length && !found; i++) if (WORDS[ORDER[i]].some(function (w) { return upper.indexOf(w) >= 0; })) found = ORDER[i];
    }
    if (!found && brands) for (var c in BRAND_RX) if (BRAND_RX[c].test(upper)) { found = c; break; }
    if (++cached > 50000) { cache = {}; cached = 0; }
    cache[key] = found;
    return found;
  }
  /** Country of a library item: from its group first, then its title, then (channels) a known channel name. */
  function detect(item) {
    return detectText(item.group) || detectText(item.raw || item.title, item.kind === "live", false);
  }

  var NAMES = {
    BE: ["Belgium", "België", "Belgique", "Belgien"], NL: ["Netherlands", "Nederland", "Pays-Bas", "Niederlande"],
    FR: ["France / French", "Frankrijk / Frans", "France / français", "Frankreich / Französisch"], DE: ["Germany / German", "Duitsland / Duits", "Allemagne / allemand", "Deutschland / Deutsch"],
    UK: ["United Kingdom", "Verenigd Koninkrijk", "Royaume-Uni", "Vereinigtes Königreich"], US: ["United States", "Verenigde Staten", "États-Unis", "USA"],
    EN: ["English", "Engels", "Anglais", "Englisch"], ES: ["Spain / Spanish", "Spanje / Spaans", "Espagne / espagnol", "Spanien / Spanisch"],
    IT: ["Italy / Italian", "Italië / Italiaans", "Italie / italien", "Italien / Italienisch"], PT: ["Portugal", "Portugal", "Portugal", "Portugal"],
    BR: ["Brazil", "Brazilië", "Brésil", "Brasilien"], TR: ["Turkey / Turkish", "Turkije / Turks", "Turquie / turc", "Türkei / Türkisch"],
    PL: ["Poland / Polish", "Polen / Pools", "Pologne / polonais", "Polen / Polnisch"], AR: ["Arabic", "Arabisch", "Arabe", "Arabisch"],
    MA: ["Morocco", "Marokko", "Maroc", "Marokko"], DZ: ["Algeria", "Algerije", "Algérie", "Algerien"], TN: ["Tunisia", "Tunesië", "Tunisie", "Tunesien"],
    IN: ["India", "India", "Inde", "Indien"], PK: ["Pakistan", "Pakistan", "Pakistan", "Pakistan"], AL: ["Albania", "Albanië", "Albanie", "Albanien"],
    RO: ["Romania", "Roemenië", "Roumanie", "Rumänien"], RU: ["Russia / Russian", "Rusland / Russisch", "Russie / russe", "Russland / Russisch"],
    GR: ["Greece", "Griekenland", "Grèce", "Griechenland"], SE: ["Sweden", "Zweden", "Suède", "Schweden"], DK: ["Denmark", "Denemarken", "Danemark", "Dänemark"],
    NO: ["Norway", "Noorwegen", "Norvège", "Norwegen"], FI: ["Finland", "Finland", "Finlande", "Finnland"], CH: ["Switzerland", "Zwitserland", "Suisse", "Schweiz"],
    AT: ["Austria", "Oostenrijk", "Autriche", "Österreich"], IE: ["Ireland", "Ierland", "Irlande", "Irland"], CA: ["Canada", "Canada", "Canada", "Kanada"],
    AU: ["Australia", "Australië", "Australie", "Australien"], MX: ["Mexico", "Mexico", "Mexique", "Mexiko"], LAT: ["Latin America", "Latijns-Amerika", "Amérique latine", "Lateinamerika"],
    AFR: ["Africa", "Afrika", "Afrique", "Afrika"], EXYU: ["Ex-Yugoslavia", "Ex-Joegoslavië", "Ex-Yougoslavie", "Ex-Jugoslawien"], CZ: ["Czechia", "Tsjechië", "Tchéquie", "Tschechien"],
    HU: ["Hungary", "Hongarije", "Hongrie", "Ungarn"], BG: ["Bulgaria", "Bulgarije", "Bulgarie", "Bulgarien"], KU: ["Kurdish", "Koerdisch", "Kurde", "Kurdisch"],
    IR: ["Iran / Persian", "Iran / Perzisch", "Iran / persan", "Iran / Persisch"], CN: ["China", "China", "Chine", "China"], PH: ["Philippines", "Filipijnen", "Philippines", "Philippinen"],
  };
  function name(code, lang) { var n = NAMES[code]; return n ? n[{ en: 0, nl: 1, fr: 2, de: 3 }[lang] || 0] : code; }

  /** Rank for sorting: the chosen countries first, in the order chosen; everything else after. */
  function rank(cc, chosen) { var i = chosen.indexOf(cc); return i < 0 ? chosen.length : i; }

  var api = { detectText: detectText, detect: detect, name: name, rank: rank, codes: ORDER };
  if (typeof module !== "undefined") module.exports = api; else root.Countries = api;
})(this);
