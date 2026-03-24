#!/usr/bin/env python3
"""
Autenticación con MercadoLibre — ejecutar una sola vez.

Abre el browser para que apruebes la app, luego copiás el código de la URL
y este script intercambia el código por un Access Token que queda en .env.
"""
import os
import sys
import webbrowser

import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("ML_APP_ID", "")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
REDIRECT_URI = "https://www.google.com"


def update_env(key: str, value: str):
    """Actualiza o agrega una variable en el archivo .env."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


def main():
    if not APP_ID or not CLIENT_SECRET:
        print("ERROR: ML_APP_ID o ML_CLIENT_SECRET no están en .env")
        sys.exit(1)

    auth_url = (
        f"https://auth.mercadolibre.com.ar/authorization"
        f"?response_type=code&client_id={APP_ID}&redirect_uri={REDIRECT_URI}"
        f"&scope=read%20write%20offline_access"
    )

    print("\n🏍️  Autenticación Moto Oportunidades — MercadoLibre\n")
    print("Abriendo browser para que apruebes la app...")
    webbrowser.open(auth_url)

    print("\nDespués de aprobar, vas a ser redirigido a Google.")
    print("La URL va a tener un parámetro 'code', por ejemplo:")
    print("  https://www.google.com/?code=TG-123456789-XXXXXXXX\n")
    code = input("Pegá el valor del 'code' acá: ").strip()

    if not code:
        print("ERROR: no ingresaste ningún código.")
        sys.exit(1)

    print("\nIntercambiando código por token...")
    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": APP_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )

    if response.status_code != 200:
        print(f"ERROR al obtener token ({response.status_code}): {response.json()}")
        sys.exit(1)

    data = response.json()
    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")

    update_env("ML_ACCESS_TOKEN", access_token)
    update_env("ML_REFRESH_TOKEN", refresh_token)

    print(f"\n✅ Token guardado en .env")
    print(f"   Access Token:  {access_token[:30]}...")
    print(f"   Refresh Token: {refresh_token[:30] if refresh_token else 'N/A'}...")
    print("\nReiniciá la app: python app.py --port 5001\n")


if __name__ == "__main__":
    main()
