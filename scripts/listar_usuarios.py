"""
Lista los usuarios registrados en auth_config.yaml (solo lectura).

Uso:
    python scripts/listar_usuarios.py
"""
import os

import yaml

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_config.yaml"
)


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"No existe {CONFIG_PATH}. Aún no hay usuarios registrados en esta máquina.")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    usuarios = config.get("credentials", {}).get("usernames", {})
    if not usuarios:
        print("No hay usuarios registrados.")
        return

    print(f"Usuarios en {CONFIG_PATH}:\n")
    for username, datos in usuarios.items():
        if not datos.get("otp_secret"):
            estado_2fa = "sin 2FA"
        elif datos.get("otp_confirmed"):
            estado_2fa = "2FA activo"
        else:
            estado_2fa = "2FA pendiente de confirmar"
        print(f"  - {username}")
        print(f"      Nombre : {datos.get('name', '')}")
        print(f"      Correo : {datos.get('email', '')}")
        print(f"      2FA    : {estado_2fa}")
    print(f"\nTotal: {len(usuarios)} usuario(s).")


if __name__ == "__main__":
    main()
