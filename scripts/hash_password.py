"""
Crea o actualiza auth_config.yaml con un usuario y su contraseña
hasheada (bcrypt) para el login de la aplicación.

Uso:
    python scripts/hash_password.py
"""
import getpass
import os
import secrets

import yaml
import streamlit_authenticator as stauth

from _totp_helpers import generar_secreto, mostrar_qr

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_config.yaml"
)


def _cargar_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    config.setdefault("credentials", {})
    config["credentials"].setdefault("usernames", {})
    config.setdefault("cookie", {
        "name": "shcp_monitoreo_auth",
        "key": secrets.token_hex(32),
        "expiry_days": 7,
    })
    return config


def main():
    config = _cargar_config()

    username = input("Usuario (sin espacios, ej. jperez): ").strip()
    name = input("Nombre completo: ").strip()
    email = input("Correo: ").strip()
    password = getpass.getpass("Contraseña: ")
    password_confirm = getpass.getpass("Confirma la contraseña: ")

    if not username:
        print("El usuario no puede estar vacío. Cancelado.")
        return
    if password != password_confirm:
        print("Las contraseñas no coinciden. Cancelado.")
        return
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres. Cancelado.")
        return

    es_nuevo = username not in config["credentials"]["usernames"]
    usuario = config["credentials"]["usernames"].setdefault(username, {})
    usuario["name"] = name
    usuario["email"] = email
    usuario["password"] = stauth.Hasher.hash(password)

    if es_nuevo:
        activar_2fa = input("¿Activar Google Authenticator (2FA) para este usuario? (s/n): ").strip().lower()
        if activar_2fa == "s":
            secret = generar_secreto()
            usuario["otp_secret"] = secret
            usuario["otp_confirmed"] = False

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"Usuario '{username}' guardado en {CONFIG_PATH}")

    if es_nuevo and usuario.get("otp_secret"):
        mostrar_qr(username, usuario["otp_secret"], os.path.dirname(CONFIG_PATH))


if __name__ == "__main__":
    main()
