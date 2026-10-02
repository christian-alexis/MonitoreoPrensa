"""
Borra los códigos QR de vinculación (qr_*.png) que hayan quedado sueltos
en la raíz del proyecto. Cada uno contiene el secreto TOTP de un usuario
en texto plano, así que no deben quedarse en el servidor una vez que la
persona correspondiente ya escaneó su código.

Uso:
    python scripts/limpiar_qrs.py
"""
import glob
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    archivos = sorted(glob.glob(os.path.join(RAIZ, "qr_*.png")))
    if not archivos:
        print("No hay códigos QR pendientes de borrar.")
        return

    print("Se van a borrar estos archivos:")
    for a in archivos:
        print(f"  - {os.path.basename(a)}")

    confirmar = input(f"\n¿Borrar los {len(archivos)} archivo(s)? (escribe 'si'): ").strip().lower()
    if confirmar != "si":
        print("Cancelado.")
        return

    for a in archivos:
        os.remove(a)
    print(f"Borrados {len(archivos)} archivo(s).")


if __name__ == "__main__":
    main()
