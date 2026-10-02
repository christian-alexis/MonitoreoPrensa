"""
Autenticación vía AWS Cognito (OAuth2 / OIDC, Authorization Code flow).

Se activa cuando la variable de entorno AUTH_PROVIDER=cognito (ver
app.py). Requiere cognito_config.yaml (plantilla en
cognito_config.example.yaml) con los datos del User Pool y App Client.
El usuario/contraseña y el 2FA (TOTP) los gestiona Cognito por completo
en su Hosted UI; esta app solo recibe el código de autorización, lo
cambia por tokens y valida el ID token. Ver AWS_COGNITO.md.
"""
import os
import urllib.parse
from typing import Optional

import jwt as pyjwt
import requests
import streamlit as st
import yaml
from jwt import PyJWKClient

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cognito_config.yaml"
)

_jwks_client_cache: dict = {}


def _cargar_config() -> Optional[dict]:
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _issuer(cfg: dict) -> str:
    return f"https://cognito-idp.{cfg['region']}.amazonaws.com/{cfg['user_pool_id']}"


def _jwks_client(cfg: dict) -> PyJWKClient:
    issuer = _issuer(cfg)
    if issuer not in _jwks_client_cache:
        _jwks_client_cache[issuer] = PyJWKClient(f"{issuer}/.well-known/jwks.json")
    return _jwks_client_cache[issuer]


def login_url() -> str:
    """URL de la Hosted UI de Cognito (login + registro TOTP si aplica)."""
    cfg = _cargar_config()
    params = {
        "client_id": cfg["client_id"],
        "response_type": "code",
        "scope": "openid email",
        "redirect_uri": cfg["redirect_uri"],
        "lang": "es",  # Hosted UI en español
    }
    return f"https://{cfg['domain']}/oauth2/authorize?{urllib.parse.urlencode(params)}"


def logout_url() -> str:
    """URL que cierra la sesión de Cognito y regresa a la app."""
    cfg = _cargar_config()
    params = {
        "client_id": cfg["client_id"],
        "logout_uri": cfg["redirect_uri"],
    }
    return f"https://{cfg['domain']}/logout?{urllib.parse.urlencode(params)}"


def _intercambiar_codigo(cfg: dict, code: str) -> Optional[dict]:
    """Cambia el código de autorización por tokens (id_token, access_token, refresh_token)."""
    try:
        resp = requests.post(
            f"https://{cfg['domain']}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": cfg["client_id"],
                "code": code,
                "redirect_uri": cfg["redirect_uri"],
            },
            auth=(cfg["client_id"], cfg["client_secret"]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def _verificar_id_token(cfg: dict, id_token: str) -> Optional[dict]:
    """Valida firma, emisor y audiencia del ID token; retorna sus claims o None."""
    try:
        signing_key = _jwks_client(cfg).get_signing_key_from_jwt(id_token)
        return pyjwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=cfg["client_id"],
            issuer=_issuer(cfg),
        )
    except pyjwt.PyJWTError:
        return None


def procesar_login() -> Optional[dict]:
    """Si la URL trae ?code=..., lo canjea y valida. Retorna los claims del usuario o None."""
    cfg = _cargar_config()
    if cfg is None:
        st.error(
            "No se encontró `cognito_config.yaml`. Configúralo según "
            "`cognito_config.example.yaml` (ver AWS_COGNITO.md)."
        )
        st.stop()

    code = st.query_params.get("code")
    if not code:
        return None

    tokens = _intercambiar_codigo(cfg, code)
    st.query_params.clear()
    if tokens is None or "id_token" not in tokens:
        return None

    return _verificar_id_token(cfg, tokens["id_token"])
