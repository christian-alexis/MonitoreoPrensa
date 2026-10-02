"""
Registro de auditoría: qué usuario hizo qué acción, cuándo y con qué
resultado. Se imprime como una línea JSON a stdout.

Docker (con el logging driver `awslogs`) captura esa salida y la envía
a Amazon CloudWatch Logs, donde se puede consultar con Logs Insights,
convertir en métricas con Metric Filters, graficar en un Dashboard, o
exportar para analizarla con Amazon Athena. Ver AWS_MONITOREO.md.
"""
import json
import logging
import sys
from typing import Optional

from utils.date_helpers import TZ_MX
from datetime import datetime

_logger = logging.getLogger("auditoria")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False


def registrar(
    usuario: Optional[str],
    modulo: str,
    accion: str,
    exito: bool = True,
    detalle: Optional[dict] = None,
) -> None:
    """Escribe un evento de auditoría como línea JSON en stdout.

    usuario: nombre de usuario de la sesión (o None si aún no hay sesión).
    modulo: "login", "sintesis_noticias", "cartones" o "mananera".
    accion: identificador corto de la acción (ej. "buscar_noticias").
    exito: si la acción se completó correctamente.
    detalle: datos adicionales relevantes (conteos, filtros, etc.), sin
        incluir nunca contraseñas, claves de API ni códigos 2FA.
    """
    evento = {
        "tipo": "auditoria",
        "timestamp": datetime.now(TZ_MX).isoformat(),
        "usuario": usuario or "anonimo",
        "modulo": modulo,
        "accion": accion,
        "exito": bool(exito),
        "detalle": detalle or {},
    }
    _logger.info(json.dumps(evento, ensure_ascii=False))
