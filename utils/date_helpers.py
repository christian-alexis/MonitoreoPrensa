"""
Funciones auxiliares para parseo y formateo de fechas.
"""
from typing import Optional
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from dateutil.tz import gettz

from config import TIMEZONE_MX


TZ_MX = gettz(TIMEZONE_MX)
TZ_UTC = timezone.utc


def parsear_fecha(fecha_str: Optional[str], return_date: bool = False) -> Optional[datetime]:
    """
    Parsea una cadena de fecha de forma robusta.
    Si la cadena tiene hora, se interpreta en UTC y se convierte a America/Mexico_City.
    Si es solo fecha (sin hora), se interpreta directamente en America/Mexico_City.

    Args:
        fecha_str: Cadena de fecha
        return_date: Si True, retorna solo la fecha (sin hora)

    Returns:
        datetime o date, o None si no se puede parsear
    """
    if not fecha_str or not isinstance(fecha_str, str) or not fecha_str.strip():
        return None

    fecha_clean = fecha_str.strip()
    # Remover offset, GMT, UTC, etc.
    import re
    fecha_clean = re.sub(r'\s+[+-]\d{4}$|\s+GMT$|\s+UTC$|\s+[A-Z]{3,}$', '', fecha_clean)

    tiene_hora = bool(re.search(r'\d{1,2}:\d{2}', fecha_clean)) or 'T' in fecha_clean

    try:
        parsed = dateutil_parser.parse(
            fecha_clean,
            fuzzy=False,
            tzinfos={"UTC": TZ_UTC, "GMT": TZ_UTC},
        )
    except (ValueError, OverflowError):
        # Intentar con fuzzy
        try:
            parsed = dateutil_parser.parse(fecha_clean, fuzzy=True)
        except (ValueError, OverflowError):
            return None

    # Si no tiene timezone y tiene hora, asumir UTC
    if parsed.tzinfo is None and tiene_hora:
        parsed = parsed.replace(tzinfo=TZ_UTC)

    # Convertir a zona horaria de México
    if tiene_hora and parsed.tzinfo is not None:
        parsed_mx = parsed.astimezone(TZ_MX)
    elif parsed.tzinfo is None and tiene_hora:
        parsed_mx = parsed.replace(tzinfo=TZ_UTC).astimezone(TZ_MX)
    else:
        # Solo fecha: asumir en MX directamente
        parsed_mx = parsed.replace(tzinfo=TZ_MX)

    if return_date:
        return parsed_mx.date()
    return parsed_mx


def extraer_fecha_de_url(url: str) -> Optional[datetime]:
    """
    Intenta extraer una fecha de una URL (formato YYYY/MM/DD o YYYY-MM-DD).
    """
    if not url:
        return None
    import re
    match = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', url)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)),
                        tzinfo=TZ_MX).date()
    except ValueError:
        return None


def formatear_fecha_dmy(d) -> str:
    """
    Formatea una fecha como dd/mm/YYYY.
    Acepta datetime, date o None.
    """
    if d is None:
        return datetime.now(TZ_MX).strftime("%d/%m/%Y")
    if isinstance(d, datetime):
        return d.strftime("%d/%m/%Y")
    if hasattr(d, "strftime"):
        return d.strftime("%d/%m/%Y")
    return datetime.now(TZ_MX).strftime("%d/%m/%Y")


def hoy_mx() -> datetime:
    """Retorna la fecha y hora actual en zona horaria de México."""
    return datetime.now(TZ_MX)


def dias_atras(n: int) -> datetime:
    """Retorna la fecha de hace n días en zona horaria de México."""
    return hoy_mx() - timedelta(days=n)
