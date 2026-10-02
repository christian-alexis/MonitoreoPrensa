"""
Configuración centralizada del proyecto SHCP.
Fuentes, categorías, keywords y constantes.
"""
from dotenv import load_dotenv

# Carga .env (si existe) al proceso una sola vez; app.py y todas las
# páginas importan config, así que las variables quedan disponibles en
# os.environ desde el primer import. No falla si el archivo no existe
# (por ejemplo, cuando las claves se pasan con -e en `docker run`).
load_dotenv()

# =========================================================
# USER AGENT
# =========================================================
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# =========================================================
# CATEGORÍAS DE PALABRAS CLAVE (Síntesis de Noticias)
# =========================================================
CATEGORIAS_KEYWORDS = {
    "Núcleo presupuestario": [
        "presupuesto", "gasto", "egresos", "subejercicio"
    ],
    "Planeación y política pública": [
        "políticas", "programas", "planeación", "desarrollo",
        "evaluación", "indicadores", "resultados", "impacto",
        "eficiencia", "transparencia"
    ],
    "Anexos transversales": [
        "anexos transversales", "anexo transversal"
    ],
    "Control y rendición de cuentas": [
        "auditoría", "fiscalización", "ASF", "control",
        "seguimiento", "monitoreo", "cumplimiento"
    ],
    "Contexto económico": [
        "inflación", "crecimiento", "PIB", "inversión",
        "empleo", "subsidios"
    ],
    # ============ ANEXOS TRANSVERSALES (AT_PEF) ============
    "Anexo 10 PEF": [
        "Anexo 10 PEF", "comunidades indígenas PEF",
        "pueblos indígenas presupuesto PEF", "afromexicanos PEF",
        "desarrollo integral indígena PEF",
    ],
    "Anexo 11 PEF": [
        "Anexo 11 PEF", "desarrollo rural sustentable PEF",
        "programa especial concurrente PEF", "campo mexicano PEF",
        "alimentación rural PEF",
    ],
    "Anexo 12 PEF": [
        "Anexo 12 PEF", "humanidades ciencias y tecnologías PEF",
        "investigación científica PEF", "innovación tecnológica PEF",
        "programa de humanidades PEF",
    ],
    "Anexo 13 PEF": [
        "Anexo 13 PEF", "erogaciones para la igualdad PEF",
        "igualdad entre mujeres y hombres PEF", "presupuesto igualdad de género PEF",
        "presupuesto de mujeres PEF",
    ],
    "Anexo 14 PEF": [
        "Anexo 14 PEF", "grupos vulnerables PEF",
        "atención a grupos vulnerables presupuesto PEF", "recursos para grupos vulnerables PEF",
        "programas vulnerables PEF",
    ],
    "Anexo 15 PEF": [
        "Anexo 15 PEF", "transición energética PEF",
        "estrategia nacional de transición energética PEF", "energías limpias presupuesto PEF",
        "inversión energética PEF",
    ],
    "Anexo 16 PEF": [
        "Anexo 16 PEF", "cambio climático PEF",
        "adaptación al cambio climático PEF", "mitigación de emisiones presupuesto PEF",
        "recursos climáticos PEF",
    ],
    "Anexo 17 PEF": [
        "Anexo 17 PEF", "desarrollo de los jóvenes PEF",
        "presupuesto para jóvenes PEF", "jóvenes programas PEF",
        "erogaciones juventud PEF",
    ],
    "Anexo 18 PEF": [
        "Anexo 18 PEF", "niñas niños y adolescentes PEF",
        "presupuesto para la niñez PEF", "primera infancia PEF",
        "programas infantiles PEF",
    ],
    "Anexo 19 PEF": [
        "Anexo 19 PEF", "prevención del delito PEF",
        "combate a las adicciones PEF", "rescate de espacios públicos PEF",
        "proyectos productivos PEF", "seguridad ciudadana presupuesto PEF",
    ],
    "Anexo 30 PEF": [
        "Anexo 30 PEF", "combate a la corrupción PEF",
        "anticorrupción presupuesto PEF", "sanción de hechos de corrupción PEF",
        "fiscalización y control PEF",
    ],
    "Anexo 31 PEF": [
        "Anexo 31 PEF", "sociedad de cuidados PEF",
        "sistema nacional de cuidados PEF", "política de cuidados presupuesto PEF",
        "trabajo de cuidados PEF",
    ],
    "Anexo 32 PEF": [
        "Anexo 32 PEF", "movilidad y seguridad vial PEF",
        "movilidad urbana presupuesto PEF", "seguridad vial PEF",
        "transporte público presupuesto PEF",
    ],
    "Anexo 33 PEF": [
        "Anexo 33 PEF", "diversidad sexual y de género PEF",
        "población LGBTI+ PEF", "presupuesto diversidad PEF",
        "derechos LGBTI+ presupuesto PEF",
    ],
}

# =========================================================
# FUENTES CONFIABLES (Síntesis de Noticias)
# =========================================================
FUENTES_CONFIABLES = [
    "El Universal", "El Financiero", "Reforma", "La Jornada",
    "Milenio", "Forbes México", "Animal Político", "Expansión",
    "BBC Mundo", "CNN en Español", "The New York Times",
    "Washington Post", "Aristegui Noticias", "Sin Embargo",
    "El País", "El País México", "Excélsior",
    "MVS Noticias", "La Crónica de Hoy",
    "El Sol de México", "El Economista",
]

# =========================================================
# FUENTES DE CARTONES
# =========================================================
SOURCES_CFG = [
    {
        "fuente": "El Universal",
        "list_url": "https://www.eluniversal.com.mx/carton/",
        "must_contain": r"eluniversal\.com\.mx/carton/[^/?#]+/[^/?#]+/?$",
        "exclude_exact": "https://www.eluniversal.com.mx/carton/",
    },
    {
        "fuente": "Vanguardia",
        "list_url": "https://vanguardia.com.mx/opinion/cartones",
        "must_contain": r"vanguardia\.com\.mx/opinion/cartones/.+",
        "exclude_exact": "https://vanguardia.com.mx/opinion/cartones",
    },
    {
        "fuente": "Milenio",
        "list_url": "https://www.milenio.com/opinion/moneros",
        "must_contain": r"milenio\.com/opinion/moneros/[^/]+/.+",
        "exclude_exact": "https://www.milenio.com/opinion/moneros",
    },
    {
        "fuente": "El Sol de México",
        "list_url": "https://oem.com.mx/elsoldemexico/cartones/",
        "must_contain": r"elsoldemexico/cartones/[^/]+-id\d+/?$",
        "exclude_exact": "https://oem.com.mx/elsoldemexico/cartones/",
    },
]

# =========================================================
# GOOGLE NEWS RSS (Síntesis de Noticias)
# =========================================================
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_PARAMS = {
    "hl": "es-419",
    "gl": "MX",
    "ceid": "MX:es",
}

# =========================================================
# TIMEZONE
# =========================================================
TIMEZONE_MX = "America/Mexico_City"

# =========================================================
# LOGO SHCP (local, no depende de URLs externas)
# =========================================================
import os

_LOGO_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(_LOGO_DIR, "assets", "logo_shcp.png")
LOGO_UPER_PATH = os.path.join(_LOGO_DIR, "assets", "logo_uper.png")
FAVICON_PATH = os.path.join(_LOGO_DIR, "assets", "favicon_db.png")

# =========================================================
# CONTACTO
# =========================================================
CONTACTO_EMAILS = "claudia_segovia@shcp.gob.mx | yazid_guzman@shcp.gob.mx"
COPYRIGHT = "© 2026 SHCP - Coordinación de Fortalecimiento Institucional"
