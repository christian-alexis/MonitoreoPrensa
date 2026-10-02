"""Utilidades compartidas por los scripts de administración de usuarios
para activar Google Authenticator (TOTP) por línea de comandos.
"""
import os

import pyotp
import qrcode


def generar_secreto() -> str:
    return pyotp.random_base32()


def mostrar_qr(username: str, secret: str, destino_dir: str) -> str:
    """Genera el QR de vinculación, lo guarda como PNG y muestra la clave manual.

    Devuelve la ruta del archivo PNG generado.
    """
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="Monitoreo de Prensa SHCP"
    )
    ruta = os.path.join(destino_dir, f"qr_{username}.png")
    qrcode.make(uri).save(ruta)
    try:
        os.chmod(ruta, 0o600)  # solo el dueño del proceso puede leerlo (no-op en Windows)
    except OSError:
        pass

    print(f"\nCódigo QR guardado en: {ruta}")
    print("Compártelo por un canal seguro y BÓRRALO en cuanto el usuario lo escanee:")
    print(f"  rm {ruta}")
    print("(o con: python scripts/limpiar_qrs.py, para borrar todos los pendientes)")
    print("Si no puede escanearlo, puede ingresar esta clave manualmente en su app:")
    print(f"  {secret}\n")
    return ruta
