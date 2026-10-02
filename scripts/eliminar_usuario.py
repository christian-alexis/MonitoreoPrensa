"""
Elimina un usuario de auth_config.yaml.

Uso:
    python scripts/eliminar_usuario.py
"""
import os

import yaml

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_config.yaml"
)


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"No existe {CONFIG_PATH}. No hay usuarios que eliminar.")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    usuarios = config.get("credentials", {}).get("usernames", {})
    if not usuarios:
        print("No hay usuarios registrados.")
        return

    print("Usuarios actuales:")
    for u, datos in usuarios.items():
        print(f"  - {u} ({datos.get('name', '')}, {datos.get('email', '')})")

    username = input("\nUsuario a eliminar: ").strip()

    if username not in usuarios:
        print(f"'{username}' no existe. Cancelado.")
        return

    if len(usuarios) == 1:
        confirmar = input(
            f"'{username}' es el único usuario. Si lo eliminas, nadie podrá "
            "iniciar sesión hasta crear otro. ¿Continuar? (escribe 'si'): "
        ).strip().lower()
        if confirmar != "si":
            print("Cancelado.")
            return

    del usuarios[username]

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"Usuario '{username}' eliminado de {CONFIG_PATH}")


if __name__ == "__main__":
    main()
