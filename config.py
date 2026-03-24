import os
from dotenv import load_dotenv

load_dotenv()

# MercadoLibre site
SITE_ID = "MLA"  # Argentina
MOTO_CATEGORY = "MLA1744"  # Motos y Cuatriciclos
BASE_URL = "https://api.mercadolibre.com"

# Optional: App credentials for higher rate limits
ML_APP_ID = os.getenv("ML_APP_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_ACCESS_TOKEN = os.getenv("ML_ACCESS_TOKEN", "")
ML_REFRESH_TOKEN = os.getenv("ML_REFRESH_TOKEN", "")

# Brands to search
BRANDS = ["Honda", "Yamaha", "Kawasaki", "KTM", "Ducati"]

# Price analysis
PRICE_BELOW_MARKET_THRESHOLD = float(os.getenv("PRICE_BELOW_THRESHOLD", "0.20"))  # 20% below median
MIN_PRICE_ARS = int(os.getenv("MIN_PRICE_ARS", "800000"))  # Filtra repuestos y anticipos irrisorios

# Pagination — ML's hard limit is offset+limit <= 1000. Se buscan 'used' y 'new'
# por separado para maximizar cobertura (~2000 resultados por marca).
API_PAGE_SIZE = 50  # MercadoLibre max items por request

# Rate limiting (seconds between requests)
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.4"))

# Keywords that suggest urgency/opportunity
URGENCY_KEYWORDS = [
    "urgente", "urgente", "liquido", "liquido", "líquido", "liquidó",
    "oportunidad", "oport.", "vendo ya", "necesito vender",
    "apurado", "apurada", "ganga", "oferta", "precio final",
    "último precio", "ultimo precio", "acepto ofertas",
]

# Keywords that indicate anticipo / advance payment (filter these OUT)
ANTICIPO_KEYWORDS = [
    "anticipo", "seña", "seña", "señas", "reserva", "entrada",
    "cuota inicial", "cuota de entrada", "primera cuota",
    "pago inicial", "50%", "50 %", "adelanto",
]

# Output
EXPORT_CSV = os.getenv("EXPORT_CSV", "true").lower() == "true"
CSV_OUTPUT_FILE = os.getenv("CSV_OUTPUT_FILE", "resultados.csv")
