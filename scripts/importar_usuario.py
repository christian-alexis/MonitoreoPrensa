"""
Agrega un usuario a auth_config.yaml a partir de un hash bcrypt ya
generado en otra máquina (por ejemplo con hash_password.py corrido
localmente por alguien sin acceso a este servidor).

No pide ni necesita la contraseña en texto plano: solo el hash.

Uso:
    python scripts/importar_usuario.py
"""
import os
import secrets

import yaml

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
    password_hash = input("Hash bcrypt (empieza con $2b$...): ").strip()

    if not username:
        print("El usuario no puede estar vacío. Cancelado.")
        return
    if not password_hash.startswith("$2b$") and not password_hash.startswith("$2a$"):
        print("Eso no parece un hash bcrypt válido (debería empezar con $2b$ o $2a$). Cancelado.")
        return

    config["credentials"]["usernames"][username] = {
        "name": name,
        "email": email,
        "password": password_hash,
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"Usuario '{username}' importado en {CONFIG_PATH}")


if __name__ == "__main__":
    main()
