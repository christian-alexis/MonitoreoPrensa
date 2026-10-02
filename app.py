"""
Sistema de Monitoreo de Prensa - SHCP
Punto de entrada principal.
"""
import io
import os
import time

import streamlit as st
import streamlit.components.v1 as components
import yaml
import pyotp
import qrcode
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities import Hasher
from config import COPYRIGHT, CONTACTO_EMAILS, FAVICON_PATH
from utils.styles import (
    GLOBAL_CSS,
    get_header_html_home,
    get_loading_overlay_html,
    get_login_header_html,
    get_login_uper_logo_css,
)
from utils.audit_log import registrar

# =========================================================
# CONFIGURACIÓN DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="Sistema de Monitoreo de Prensa - SHCP",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
st.markdown(get_loading_overlay_html(), unsafe_allow_html=True)

# =========================================================
# LOGIN
# =========================================================
# AUTH_PROVIDER=local (por defecto): usuario/contraseña + 2FA propios,
#   gestionados en auth_config.yaml (streamlit-authenticator + pyotp).
# AUTH_PROVIDER=cognito: delega todo (contraseña, 2FA, recuperación) a
#   AWS Cognito Hosted UI. Requiere cognito_config.yaml y un dominio
#   HTTPS ya configurado — ver AWS_COGNITO.md antes de activarlo.
# El sistema local NO se eliminó: sigue siendo el respaldo por defecto.
AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "local").strip().lower()


def _sin_sesion():
    """Oculta el menú lateral y detiene la ejecución cuando no hay sesión activa."""
    st.session_state.totp_verified = False
    st.navigation([st.Page(lambda: None, title="Login")], position="hidden").run()
    st.stop()


if AUTH_PROVIDER == "cognito":
    # ---------------------------------------------------------------
    # AWS Cognito (Hosted UI, OAuth2/OIDC)
    # ---------------------------------------------------------------
    from utils.cognito_auth import login_url, logout_url, procesar_login

    if not st.session_state.get("authentication_status"):
        _claims = procesar_login()
        if _claims:
            st.session_state.authentication_status = True
            # El User Pool usa email como inicio de sesión, así que
            # "cognito:username" es un UUID interno sin valor para
            # auditoría/lectura humana; se prioriza el correo.
            st.session_state.username = _claims.get("email") or _claims.get("cognito:username")
            st.session_state.name = _claims.get("email", st.session_state.username)
            registrar(st.session_state.username, "login", "login_success")
            st.rerun()

    if not st.session_state.get("authentication_status"):
        # Redirección automática e inmediata a la Hosted UI de Cognito: no
        # se renderiza la tarjeta de "Acceso restringido" en absoluto (ni
        # el header, ni el logo, ni el botón), para que no se alcance a
        # ver ni un instante. Mismo mecanismo ya probado en el logout.
        st.markdown(
            f'<meta http-equiv="refresh" content="0;url={login_url()}">',
            unsafe_allow_html=True,
        )
        _sin_sesion()

    _username_antes_logout = st.session_state.get("username")
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        st.session_state.authentication_status = None
        st.session_state.username = None
        registrar(_username_antes_logout, "login", "logout")
        # Redirección del navegador al endpoint de logout de Cognito, para
        # cerrar también su sesión (no solo la local).
        st.markdown(
            f'<meta http-equiv="refresh" content="0;url={logout_url()}">',
            unsafe_allow_html=True,
        )
        st.stop()
    st.sidebar.caption(f"Conectado como **{st.session_state.get('name', '')}**")

else:
    # ---------------------------------------------------------------
    # Login local (usuario/contraseña + 2FA opcional con Google
    # Authenticator) — respaldo mientras se configura AWS Cognito.
    # ---------------------------------------------------------------
    AUTH_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_config.yaml")

    if not os.path.exists(AUTH_CONFIG_PATH):
        st.error(
            "No se encontró `auth_config.yaml`. Genera uno corriendo "
            "`python scripts/hash_password.py` (ver `auth_config.example.yaml` para el formato)."
        )
        st.stop()

    with open(AUTH_CONFIG_PATH, "r", encoding="utf-8") as _f:
        _auth_config = yaml.safe_load(_f)

    authenticator = stauth.Authenticate(
        _auth_config["credentials"],
        _auth_config["cookie"]["name"],
        _auth_config["cookie"]["key"],
        _auth_config["cookie"]["expiry_days"],
    )

    @st.dialog("Acceso denegado", width="small")
    def dialog_error_login():
        """Ventana emergente con el mensaje de credenciales incorrectas."""
        st.markdown(
            """
            <div style="text-align:center; padding: 8px 4px 4px;">
                <div style="font-size:2.6rem; margin-bottom:8px;">🔒</div>
                <div style="font-size:1.05rem; font-weight:700; color:#10312B;">
                    Usuario o contraseña incorrectos
                </div>
                <div style="color:#64748b; font-size:0.95rem; margin-top:6px; line-height:1.5;">
                    Verifica tus credenciales e inténtalo de nuevo.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Intentar de nuevo", type="primary", use_container_width=True):
            st.session_state.authentication_status = None
            st.rerun()

    @st.dialog("Código incorrecto", width="small")
    def dialog_error_totp():
        """Ventana emergente con el mensaje de código TOTP incorrecto."""
        st.markdown(
            """
            <div style="text-align:center; padding: 8px 4px 4px;">
                <div style="font-size:2.6rem; margin-bottom:8px;">🔐</div>
                <div style="font-size:1.05rem; font-weight:700; color:#10312B;">
                    Código incorrecto o expirado
                </div>
                <div style="color:#64748b; font-size:0.95rem; margin-top:6px; line-height:1.5;">
                    Verifica el código en tu app de autenticación e inténtalo de nuevo.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Intentar de nuevo", type="primary", use_container_width=True):
            st.rerun()

    def _confirmar_totp(username: str) -> None:
        """Marca el 2FA de este usuario como confirmado y lo persiste en auth_config.yaml."""
        _auth_config["credentials"]["usernames"][username]["otp_confirmed"] = True
        with open(AUTH_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(_auth_config, f, default_flow_style=False, allow_unicode=True)

    def totp_view(username: str, secret: str, confirmado: bool):
        """Segundo factor: verifica el código de Google Authenticator del usuario ya autenticado."""
        st.markdown(get_login_header_html(), unsafe_allow_html=True)
        st.markdown(
            '<div class="login-note">Verificación en dos pasos · SHCP</div>',
            unsafe_allow_html=True,
        )

        if not confirmado:
            st.info(
                "Primera vez con este usuario: escanea el código con Google Authenticator "
                "(o tu app de autenticación) y confírmalo con el código de 6 dígitos."
            )
            uri = pyotp.TOTP(secret).provisioning_uri(
                name=username, issuer_name="Monitoreo de Prensa SHCP"
            )
            buffer = io.BytesIO()
            qrcode.make(uri).save(buffer, format="PNG")
            col_qr, _ = st.columns([1, 2])
            with col_qr:
                st.image(buffer.getvalue(), caption="Escanea con tu app de autenticación", width=220)
            with st.expander("¿No puedes escanear el código?"):
                st.caption("Ingresa esta clave manualmente en tu app:")
                st.code(secret, language=None)

        with st.form("totp_form"):
            codigo = st.text_input("Código de 6 dígitos", max_chars=6)
            enviar = st.form_submit_button("Verificar", type="primary", use_container_width=True)

        if enviar:
            if pyotp.TOTP(secret).verify(codigo, valid_window=1):
                st.session_state.totp_verified = True
                if not confirmado:
                    _confirmar_totp(username)
                registrar(username, "login", "totp_success")
                st.rerun()
            else:
                registrar(username, "login", "totp_failed", exito=False)
                dialog_error_totp()

        st.markdown(
            f'<div class="login-footer">{COPYRIGHT}</div>',
            unsafe_allow_html=True,
        )

    def login_view():
        """Página de inicio de sesión con encabezado institucional y formulario estilizado."""
        if st.session_state.get("authentication_status"):
            return

        st.markdown(get_login_header_html(), unsafe_allow_html=True)
        st.markdown(
            '<div class="login-note">Acceso restringido a personal autorizado · SHCP</div>',
            unsafe_allow_html=True,
        )
        st.markdown(get_login_uper_logo_css(), unsafe_allow_html=True)

        _usuarios = _auth_config.get("credentials", {}).get("usernames", {})

        def _verificar_login(usuario: str, contrasena: str) -> bool:
            """Valida usuario/contraseña contra auth_config.yaml (bcrypt).

            Evita el formulario de `streamlit-authenticator` (que además del
            `form_submit_button` hace `time.sleep(0.7)`, lee cookies con
            `st.context.cookies` y escribe una cookie con JS de
            `extra-streamlit-components`, inyectando un rerun extra): con ese
            formulario, en algunos navegadores el primer envío se "perdía" y
            había que ingresar las credenciales dos veces. Este formulario es
            determinístico: valida, setea `authentication_status` y hace
            `st.rerun()` en el mismo run.
            """
            usuario = (usuario or "").strip().lower()
            contrasena = contrasena or ""
            if not usuario or not contrasena:
                return False
            _clave = _usuarios.get(usuario, {}).get("password", "")
            if not _clave:
                return False
            try:
                return Hasher.check_pw(contrasena, _clave)
            except (TypeError, ValueError):
                return False

        with st.form(key="login_shcp"):
            st.subheader("Iniciar sesión")
            _usr = st.text_input("Usuario", autocomplete="off")
            _pwd = st.text_input("Contraseña", type="password", autocomplete="off")
            if st.form_submit_button(
                "Ingresar", type="primary", use_container_width=True
            ):
                _usr = (_usr or "").strip().lower()
                if _verificar_login(_usr, _pwd):
                    _perfil = _usuarios.get(_usr, {})
                    registrar(_usr, "login", "login_success")
                    st.session_state.authentication_status = True
                    st.session_state.username = _usr
                    st.session_state.name = _perfil.get("name", _usr)
                    st.session_state.email = _perfil.get("email")
                    st.session_state.roles = _perfil.get("roles")
                    st.rerun()
                else:
                    registrar(None, "login", "login_failed", exito=False)
                    st.session_state.authentication_status = None
                    dialog_error_login()

        st.markdown(
            f'<div class="login-footer">{COPYRIGHT}</div>',
            unsafe_allow_html=True,
        )

    login_view()

    if not st.session_state.get("authentication_status"):
        _sin_sesion()

    # =====================================================
    # SEGUNDO FACTOR (Google Authenticator) — solo si el usuario lo tiene
    # activado. Debe resolverse ANTES de dibujar cualquier cosa en el
    # sidebar (logout, etc.): _sin_sesion() oculta la navegación, pero no
    # borra contenido ya renderizado en el sidebar en este mismo run.
    # =====================================================
    _username_actual = st.session_state.get("username", "")
    _user_data = _auth_config["credentials"]["usernames"].get(_username_actual, {})
    _otp_secret = _user_data.get("otp_secret")

    if _otp_secret and not st.session_state.get("totp_verified"):
        totp_view(_username_actual, _otp_secret, _user_data.get("otp_confirmed", False))
        if not st.session_state.get("totp_verified"):
            _sin_sesion()

    _username_antes_logout = st.session_state.get("username")
    authenticator.logout("Cerrar sesión", "sidebar")
    st.sidebar.caption(f"Conectado como **{st.session_state.get('name', '')}**")

    if not st.session_state.get("authentication_status"):
        # El botón de cerrar sesión se acaba de presionar en este mismo run.
        registrar(_username_antes_logout, "login", "logout")
        _sin_sesion()

# =========================================================
# CIERRE DE SESIÓN POR INACTIVIDAD (30 minutos)
# =========================================================
TIEMPO_INACTIVIDAD_SEG = 30 * 60

# Cualquier ejecución completa del script (clic en un widget, envío de
# formulario, cambio de página, etc.) llega hasta aquí, así que esto marca
# "hubo actividad real". El fragmento de abajo se reejecuta solo (sin
# intervención del usuario) y por eso NO pasa por esta línea al revisar el
# reloj periódicamente.
st.session_state.ultima_actividad = time.time()

# Puente JS -> Python: hacer scroll, mover el mouse o teclear en la página
# NO dispara un rerun de Streamlit por sí solo (solo lo hacen los widgets),
# así que sin esto la sesión podía cerrarse aunque el usuario siguiera
# activo leyendo/navegando. Este botón invisible se "clickea" desde
# JavaScript cuando detecta esos eventos, forzando un rerun real que
# actualiza `ultima_actividad` arriba.
st.markdown(
    '<style>div[class*="st-key-_ping_actividad"] { display: none !important; }</style>',
    unsafe_allow_html=True,
)
st.button("actividad", key="_ping_actividad")
components.html(
    """
    <script>
    (function() {
        var doc = window.parent.document;
        function encontrarBoton() {
            var wrap = doc.querySelector('div[class*="st-key-_ping_actividad"]');
            return wrap ? wrap.querySelector('button') : null;
        }
        var ultimoPing = 0;
        function onActividad() {
            var ahora = Date.now();
            if (ahora - ultimoPing < 45000) return;
            var btn = encontrarBoton();
            if (!btn) return;
            ultimoPing = ahora;
            btn.click();
        }
        ['scroll', 'mousemove', 'mousedown', 'keydown', 'touchstart'].forEach(function(ev) {
            doc.addEventListener(ev, onActividad, {passive: true});
        });
    })();
    </script>
    """,
    height=0,
)


@st.fragment(run_every=30)
def _vigilar_inactividad():
    inactivo = time.time() - st.session_state.get("ultima_actividad", time.time())
    if inactivo > TIEMPO_INACTIVIDAD_SEG:
        _usuario_inactivo = st.session_state.get("username")
        if AUTH_PROVIDER == "cognito":
            st.session_state.authentication_status = None
            st.session_state.username = None
        else:
            authenticator.logout(location="unrendered")
        registrar(_usuario_inactivo, "login", "logout_inactividad")
        st.rerun(scope="app")


_vigilar_inactividad()

# =========================================================
# INITIAL STATE & API KEYS
# =========================================================
if "api_key_groq" not in st.session_state:
    st.session_state.api_key_groq = os.environ.get("GROQ_API_KEY", "")
if "api_key_openrouter" not in st.session_state:
    st.session_state.api_key_openrouter = os.environ.get("OPENROUTER_API_KEY", "")
if "api_key_gemini" not in st.session_state:
    st.session_state.api_key_gemini = os.environ.get("GEMINI_API_KEY", "")
if "api_key_anthropic" not in st.session_state:
    st.session_state.api_key_anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
if "api_key_cerebras" not in st.session_state:
    st.session_state.api_key_cerebras = os.environ.get("CEREBRAS_API_KEY", "")


# =========================================================
# NAVEGACIÓN PERSONALIZADA
# =========================================================
sinte_page = st.Page("pages/1_Sintesis_de_Noticias.py", title="Síntesis de Noticias", icon="📰")
carto_page = st.Page("pages/2_Cartones.py", title="Cartones Editoriales", icon="🎨")
confe_page = st.Page("pages/3_Conferencia_Prensa_Matutina.py", title="Conferencia de Prensa (Mañanera)", icon="🎙️")


# =========================================================
# PÁGINA PRINCIPAL (HOME)
# =========================================================
def home():
    st.markdown(get_header_html_home(), unsafe_allow_html=True)

    st.markdown(
        """
        <div style='text-align: center; margin: 30px 0;'>
            <h1 style='color: #10312B; font-size: 2rem; font-weight: 700; margin-bottom: 8px;'>Sistema de Monitoreo de Prensa</h1>
            <p style='color: #64748b; font-size: 1.1rem; margin: 0;'>Selecciona un servicio para comenzar</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            """
            <div class="service-card">
                <div class="service-icon">📰</div>
                <h3>Síntesis de Noticias</h3>
                <p>Scraping de noticias de fuentes confiables mexicanas.<br>
                   Filtrado por categoría y exportación PDF.<br>
                   <span style="color:#BC955C;font-weight:600;">🤖 IA: relevancia, sentimiento y resumen ejecutivo</span></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Ir a Síntesis de Noticias",
            type="primary",
            key="btn_sintesis",
            use_container_width=True,
        ):
            st.switch_page(sinte_page)

    with col2:
        st.markdown(
            """
            <div class="service-card">
                <div class="service-icon">🖼️</div>
                <h3>Cartones del Día</h3>
                <p>Recopilación de cartones editoriales de El Universal,
                   Vanguardia y Milenio.<br>
                   <span style="color:#BC955C;font-weight:600;">🤖 IA: análisis del contexto de cada cartón</span></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Ir a Cartones del Día",
            type="primary",
            key="btn_cartones",
            use_container_width=True,
        ):
            st.switch_page(carto_page)

    with col3:
        st.markdown(
            """
            <div class="service-card">
                <div class="service-icon">🎙️</div>
                <h3>Conferencia de Prensa Matutina (Mañanera) / Análisis de notas</h3>
                <p>Resumen ejecutivo desde la versión estenográfica oficial o desde la URL de cualquier nota de prensa.<br>
                   <span style="color:#BC955C;font-weight:600;">🤖 IA: resumen ejecutivo y análisis SHCP</span></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Ir a Conferencia de Prensa Matutina (Mañanera)",
            type="primary",
            key="btn_conferencia",
            use_container_width=True,
        ):
            st.switch_page(confe_page)

    st.markdown("<br>", unsafe_allow_html=True)

    with st.expander("Información acerca de este sistema"):
        st.markdown("""
        ### Descripción
        Este sistema permite monitorear la prensa mexicana de dos formas:

        1. **Síntesis de Noticias**: Busca automáticamente noticias en Google News RSS
           de fuentes confiables como El Universal, Reforma, La Jornada, Milenio, etc.

        2. **Cartones del Día**: Recopila cartones editoriales de las principales
           fuentes mexicanas, validando que las imágenes estén disponibles.

        3. **Conferencia de Prensa Matutina (Mañanera)**: Genera un resumen ejecutivo
           desde la versión estenográfica oficial, con análisis de temas relevantes
           para la SHCP.

        ### Funcionalidades
        - Scraping automatizado de múltiples fuentes
        - Filtrado por categoría y fuente confiable
        - Exportación a PDF con formato institucional
        - Edición manual de registros
        - **Asistente IA** (Ollama local) para análisis y resúmenes

        ### Contacto
        - claudia_segovia@shcp.gob.mx
        - yazid_guzman@shcp.gob.mx
        """)

    st.markdown(
        f"""
        <div class="footer-main">
            <strong>{COPYRIGHT}</strong><br>
            {CONTACTO_EMAILS}
        </div>
        """,
        unsafe_allow_html=True,
    )


pg = st.navigation(
    {
        "Inicio": [st.Page(home, title="Inicio", icon="🏠", default=True)],
        "Servicios": [sinte_page, carto_page, confe_page],
    },
    position="sidebar",
)

pg.run()
