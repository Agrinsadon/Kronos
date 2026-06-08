# ============================================
# KRONOS PAPER TRADER — AGGRESSIIVINEN TILA
# Tavoite: 500€ → 5000€ kuukaudessa
# ⚠️  Korkea riski — vain paper trading!
# ============================================

# Telegram — täytä nämä!
TELEGRAM_TOKEN = "8721829065:AAF1iNreZ3QktzyoMxWTmwXNiXndDH-pHL0"
TELEGRAM_CHAT_ID = "5885331518"

# Kaupankäynti
STARTING_BALANCE = 500.0
TARGET_BALANCE = 5000.0
TRADE_ALLOCATION = 0.99        # Käytetään lähes kaikki käteinen

# ── Osakeseulonta ──────────────────────────────────────────────────────────────
MIN_PRICE = 5.0                # Alennettu — sallii enemmän volatiileja osakkeita
MIN_VOLUME_USD = 5_000_000    # Alennettu — sallii pienempiä osakkeita
MAX_SCAN = 200                 # Skannataan enemmän osakkeita
MAX_POSITIONS = 5              # Max 5 positiota samanaikaisesti (hajautus + volyymi)

# ── Kronos-asetukset ───────────────────────────────────────────────────────────
LOOKBACK = 60
PRED_LEN = 3                   # Ennuste 3 päivää (lyhyempi = reagoi nopeammin)
KRONOS_MODEL = "NeoQuasar/Kronos-small"
KRONOS_TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
DEVICE = "mps"

# ── Kaupankäyntikynnykset (aggressiivinen) ────────────────────────────────────
BUY_THRESHOLD = 0.02           # Osta jos ennuste +2% (tiukempi = paremmat signaalit)
SELL_THRESHOLD = -0.003        # Myy herkemmin jos trendi kääntyy
STOP_LOSS = -0.04              # Stop-loss -4% (tiukempi suoja)
TAKE_PROFIT = 0.06             # Take-profit +6% (nopea voitto)

# ── Volatiliteettibonus ───────────────────────────────────────────────────────
# Priorisoi osakkeet joilla on korkea volatiliteetti (enemmän liikettä = enemmän mahdollisuuksia)
PREFER_VOLATILE = True
MIN_VOLATILITY = 0.015         # Minimipäivävolatiliteetti 1.5%

# Tiedostot
STATE_FILE = "trading_state.json"
LOG_FILE = "trading_log.csv"
UNIVERSE_CACHE = "universe_cache.json"