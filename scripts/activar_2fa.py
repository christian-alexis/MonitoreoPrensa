"""
Activa (o reinicia) Google Authenticator para un usuario ya existente
en auth_config.yaml. Útil para habilitar 2FA en cuentas creadas antes
de esta función, o para volver a vincular si el usuario perdió su
teléfono.

Reiniciar el secreto invalida el código QR/clave anterior: el usuario
deberá volver a escanear el nuevo código en su próximo inicio de sesión.

Uso:
    python scripts/activar_2fa.py
"""
import os

import yaml

from _totp_helpers import generar_secreto, mostrar_qr

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_config.yaml"
)


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"No existe {CONFIG_PATH}. Crea un usuario primero con hash_password.py.")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    usuarios = config.get("credentials", {}).get("usernames", {})
    if not usuarios:
        print("No hay usuarios registrados.")
        return

    print("Usuarios actuales:")
    for u, datos in usuarios.items():
        estado = "2FA activo" if datos.get("otp_secret") else "sin 2FA"
        print(f"  - {u} ({estado})")

    username = input("\nUsuario para activar/reiniciar 2FA: ").strip()
    if username not in usuarios:
        print(f"'{username}' no existe. Cancelado.")
        return

    if usuarios[username].get("otp_secret"):
        confirmar = input(
            "Este usuario ya tiene 2FA activo. Reiniciarlo invalida su vínculo "
            "actual (tendrá que volver a escanear). ¿Continuar? (escribe 'si'): "
        ).strip().lower()
        if confirmar != "si":
            print("Cancelado.")
            return

    secret = generar_secreto()
    usuarios[username]["otp_secret"] = secret
    usuarios[username]["otp_confirmed"] = False

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"2FA activado para '{username}'. Deberá escanear el código en su próximo login.")
    mostrar_qr(username, secret, os.path.dirname(CONFIG_PATH))


if __name__ == "__main__":
    main()
