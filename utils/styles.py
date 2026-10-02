"""
Estilos compartidos para toda la aplicación SHCP.
Diseño moderno, minimalista e intuitivo.
"""

GLOBAL_CSS = """
<style>
    /* ========================================
       BASE: TAMAÑO GENERAL
       ======================================== */
    .stApp {
        font-size: 17px;
    }

    /* ========================================
       INDICADOR DE CARGA
       ======================================== */
    /* Ocultar el indicador por defecto de Streamlit */
    [data-testid="stStatusWidget"] {
        display: none !important;
    }
    /* Ocultar el botón "Deploy" de la barra superior */
    [data-testid="stAppDeployButton"] {
        display: none !important;
    }
    /* Ocultar el menú de tres puntos (Print, Record screen, "Made with Streamlit") */
    [data-testid="stMainMenu"] {
        display: none !important;
    }
    .loading-overlay {
        position: fixed;
        top: calc(var(--hdr-h) + 6px);
        right: 52px;
        z-index: 999999;
        display: none;
        align-items: center;
        gap: 7px;
        padding: 5px 12px;
        background: rgba(16, 49, 43, 0.92);
        border: 1px solid rgba(188, 149, 92, 0.5);
        border-radius: 999px;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.28);
        backdrop-filter: blur(4px);
    }
    @media (max-width: 767px) {
        .loading-overlay {
            top: 6px;
        }
    }
    div[data-testid="stApp"]:has([data-testid="stStatusWidget"]) .loading-overlay {
        display: flex;
    }
    .loading-spinner {
        width: 13px;
        height: 13px;
        border-radius: 50%;
        border: 2.5px solid rgba(188, 149, 92, 0.25);
        border-top-color: #BC955C;
        animation: shcp-spin 0.8s linear infinite;
    }
    .loading-text {
        color: #ffffff;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        white-space: nowrap;
    }
    @keyframes shcp-spin {
        to { transform: rotate(360deg); }
    }

    /* ========================================
       FONDO Y TIPOGRAFÍA
       ======================================== */
    .stApp {
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
        overflow-x: hidden;
    }
    [data-testid="stMainBlockContainer"] {
        padding-top: 0;
    }

    /* ========================================
       BARRA SUPERIOR DE STREAMLIT
       (menú lateral + Deploy + tres puntos) → se coloca debajo del header
       ======================================== */
    :root {
        --hdr-h: 150px;
        --toolbar-h: 44px;
    }
    /* Colapsa los contenedores previos al header institucional
       (CSS global, overlay de carga y componente de cookies) para que
       el header quede pegado hasta arriba. */
    [data-testid="stElementContainer"]:has(style) {
        display: none !important;
    }
    [data-testid="stElementContainer"]:has(iframe[data-testid="stCustomComponentV1"]) {
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
    }
    @media (min-width: 768px) {
        [data-testid="stHeader"] {
            position: fixed !important;
            top: var(--hdr-h) !important;
            left: 0;
            right: 0;
            height: var(--toolbar-h);
            min-height: var(--toolbar-h);
            background: #F8F9FA !important;
            border-bottom: 1px solid #d5dbe1;
            z-index: 1001;
        }
        /* El contenido principal inicia debajo del header y la barra */
        [data-testid="stMainBlockContainer"] {
            padding-top: calc(var(--hdr-h) + var(--toolbar-h)) !important;
        }
        /* El menú lateral se despliega por debajo del header y la barra.
           Permanece como flex item (relative) para que el contenido principal
           siga corriéndose a la derecha al abrirlo.
           Sin z-index propio: al no traslaparse con el header/barra, evita
           crear un contexto de apilamiento que bloquee el botón de cerrar. */
        section[data-testid="stSidebar"] {
            top: calc(var(--hdr-h) + var(--toolbar-h)) !important;
            height: calc(100vh - var(--hdr-h) - var(--toolbar-h)) !important;
            z-index: auto !important;
        }
        /* Quita el relleno superior que Streamlit usa para librar la barra */
        [data-testid="stSidebarUserContent"] {
            padding-top: 0 !important;
        }
        /* Hace estático el contenedor del menú para que el sidebar sea el
           containing block del botón de cerrar y así quede anclado al borde
           derecho real (sea cual sea su ancho, ya que es redimensionable). */
        [data-testid="stSidebarContent"] {
            position: static !important;
        }
        /* Botón para cerrar el menú: se coloca en la barra superior, anclado
           al borde derecho del ancho real del menú lateral. */
        section[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] {
            position: absolute !important;
            top: calc(8px - var(--toolbar-h)) !important;
            right: 0 !important;
            left: auto !important;
            z-index: 1005 !important;
            visibility: visible !important;
        }
    }

    /* ========================================
       HEADER INSTITUCIONAL
       ======================================== */
    .shcp-header {
        background: linear-gradient(135deg, #10312B 0%, #1a4a3f 100%);
        padding: 30px 3rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-radius: 0;
        margin: 0;
        box-shadow: 0 4px 15px rgba(16, 49, 43, 0.2);
    }
    @media (min-width: 768px) {
        .shcp-header {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            width: 100% !important;
            height: var(--hdr-h);
            box-sizing: border-box;
            padding: 0 3rem;
            overflow: hidden;
            z-index: 1002;
            margin: 0 !important;
        }
    }
    .shcp-header img {
        max-height: 64px;
        width: auto;
    }
    .shcp-header-text {
        flex: 1;
        text-align: right;
        padding-left: 24px;
    }
    .shcp-header-text h2,
    .shcp-title-line1 {
        margin: 0;
        color: #BC955C;
        font-size: 24px;
        font-weight: 700;
        line-height: 1.3;
        letter-spacing: 0.5px;
    }
    .shcp-header-text h3,
    .shcp-title-line2 {
        margin: 4px 0 0 0;
        color: #BC955C;
        font-size: 16px;
        font-weight: 400;
        line-height: 1.4;
        opacity: 0.9;
    }
    .shcp-header-text p {
        margin: 4px 0 0 0;
        color: #BC955C;
        font-size: 13px;
        line-height: 1.4;
        opacity: 0.8;
    }
    /* En pantallas menores a 768px Streamlit usa padding lateral de 1.25rem */
    @media (max-width: 767px) {
        .shcp-header {
            width: calc(100% + 2.5rem);
            margin-left: -1.25rem;
        }
    }

    /* ========================================
       TARJETAS DE SERVICIOS
       ======================================== */
    .service-card {
        background: white;
        border: none;
        border-radius: 16px;
        padding: 30px 25px;
        text-align: center;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        height: 280px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .service-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 25px rgba(16, 49, 43, 0.15);
        border-color: #BC955C;
    }
    .service-icon {
        font-size: 3.5rem;
        margin-bottom: 15px;
        padding: 15px;
        background: linear-gradient(135deg, #f0f4f8 0%, #e2e8f0 100%);
        border-radius: 50%;
        width: 90px;
        height: 90px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .service-card h3 {
        color: #10312B;
        margin: 10px 0 8px 0;
        font-size: 1.2rem;
        font-weight: 600;
    }
    .service-card p {
        color: #64748b;
        font-size: 0.9rem;
        line-height: 1.5;
        margin: 0;
    }

    /* ========================================
       BOTONES PRINCIPALES
       ======================================== */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #10312B 0%, #1a4a3f 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 14px 28px;
        font-weight: 600;
        font-size: 16px;
        transition: all 0.3s ease;
        box-shadow: 0 2px 8px rgba(16, 49, 43, 0.2);
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(16, 49, 43, 0.3);
    }
    .stButton > button {
        font-size: 15px;
    }

    /* ========================================
       INPUTS
       ======================================== */
    [data-baseweb="input"] {
        border-radius: 10px;
        transition: all 0.25s ease;
    }
    [data-baseweb="input"]:focus-within {
        border-color: #BC955C !important;
        box-shadow: 0 0 0 3px rgba(188, 149, 92, 0.18) !important;
    }

    /* ========================================
       CONTENEDORES Y TARJETAS
       ======================================== */
    .stContainer {
        background: white;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }

    /* ========================================
       SIDEBAR - NAVEGACIÓN
       ======================================== */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #10312B 0%, #1a4a3f 100%);
    }
    /* Texto general del sidebar */
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown li,
    section[data-testid="stSidebar"] .stMarkdown span,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stNumberInput label,
    section[data-testid="stSidebar"] .stCheckbox label {
        color: #BC955C !important;
        font-size: 15px !important;
    }
    /* Títulos del sidebar */
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3,
    section[data-testid="stSidebar"] header {
        color: #BC955C !important;
        font-size: 18px !important;
    }
    /* Menú de navegación - todo el texto */
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] *,
    section[data-testid="stSidebar"] nav * {
        color: #BC955C !important;
        font-size: 15px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
    section[data-testid="stSidebar"] nav a {
        color: #BC955C !important;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 16px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
    section[data-testid="stSidebar"] nav a:hover {
        background-color: rgba(188, 149, 92, 0.25) !important;
        color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-selected="true"],
    section[data-testid="stSidebar"] nav a[aria-selected="true"] {
        background-color: rgba(188, 149, 92, 0.4) !important;
        color: #FFFFFF !important;
        font-weight: 600;
    }
    /* Forzar color dorado en todo elemento del sidebar */
    section[data-testid="stSidebar"] div,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] a {
        color: #BC955C;
    }
    /* Caption en sidebar */
    section[data-testid="stSidebar"] .stCaption {
        font-size: 15px !important;
        font-weight: 600 !important;
        color: #FFD700 !important;
    }
    /* Inputs del sidebar */
    section[data-testid="stSidebar"] [data-baseweb="input"] {
        background-color: rgba(255,255,255,0.15);
        color: #BC955C;
    }
    section[data-testid="stSidebar"] [data-baseweb="tag"] {
        background-color: rgba(188, 149, 92, 0.3);
        color: #BC955C;
    }
    section[data-testid="stSidebar"] hr {
        border-color: rgba(188, 149, 92, 0.3);
    }
    /* Botón hamburguesa - siempre visible */
    button[title="Close sidebar"],
    button[title="Open sidebar"] {
        background-color: #10312B !important;
        color: #BC955C !important;
        border: 2px solid #BC955C !important;
        border-radius: 8px !important;
        padding: 4px 8px !important;
        font-size: 16px !important;
    }
    button[title="Close sidebar"]:hover,
    button[title="Open sidebar"]:hover {
        background-color: #BC955C !important;
        color: #10312B !important;
    }

    /* ========================================
       TABS
       ======================================== */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: #e8ecf0;
        padding: 5px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 500;
        font-size: 15px;
    }
    .stTabs [aria-selected="true"] {
        background: white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }

    /* ========================================
       TABLAS
       ======================================== */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        font-size: 15px;
    }
    .stDataFrame td, .stDataFrame th {
        font-size: 15px;
        padding: 10px 12px !important;
    }

    /* ========================================
       FORMULARIOS
       ======================================== */
    .stForm {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border: 1px solid #e2e8f0;
    }

    /* ========================================
       MENSAJES Y ALERTAS
       ======================================== */
    .stAlert {
        border-radius: 10px;
        border-left-width: 4px;
    }

    /* ========================================
       EXPANDERS
       ======================================== */
    .streamlit-expanderHeader {
        font-weight: 600;
        color: #10312B;
        font-size: 16px;
    }

    /* ========================================
       FOOTER
       ======================================== */
    .footer-main {
        text-align: center;
        font-size: 14px;
        color: #94a3b8;
        padding: 20px;
        border-top: 1px solid #e2e8f0;
        margin-top: 40px;
    }

    /* ========================================
       BADGES DE RELEVANCIA
       ======================================== */
    .badge-relevancia {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 13px;
    }
    .badge-alta { background: #fee2e2; color: #dc2626; }
    .badge-media { background: #fef3c7; color: #d97706; }
    .badge-baja { background: #d1fae5; color: #059669; }
    .badge-none { background: #f1f5f9; color: #64748b; }

    /* ========================================
       TARJETA DE NOTICIA
       ======================================== */
    .noticia-card {
        background: white;
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 12px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        border-left: 4px solid #10312B;
        transition: all 0.2s ease;
    }
    .noticia-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateX(3px);
    }

    /* ========================================
       LOGIN
       ======================================== */
    /* Tarjeta del formulario de inicio de sesión */
    div[data-testid="stMainBlockContainer"]:has(.login-page) div[data-testid="stForm"] {
        background: linear-gradient(160deg, #0f2b25 0%, #1a4a3f 100%);
        border: 1px solid rgba(188, 149, 92, 0.35);
        border-top: 4px solid #BC955C;
        border-radius: 16px;
        padding: 26px 30px 30px;
        max-width: 400px;
        margin: 0 auto;
        box-shadow: 0 14px 45px rgba(16, 49, 43, 0.35);
    }
    /* Título del formulario */
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stHeading"] {
        text-align: center;
        margin-bottom: 8px;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stHeading"] h2,
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stHeading"] h3 {
        color: #FFFFFF !important;
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stHeading"]::after {
        content: "";
        display: block;
        width: 48px;
        height: 3px;
        margin: 10px auto 6px;
        background: linear-gradient(90deg, #BC955C, #d4b17a);
        border-radius: 2px;
    }
    /* Etiquetas de los campos */
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stWidgetLabel"] p {
        color: #BC955C !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px;
        margin-bottom: 4px !important;
    }
    /* Campos de texto */
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.08);
        border: 1.5px solid rgba(188, 149, 92, 0.4);
        border-radius: 10px;
        transition: all 0.25s ease;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-baseweb="input"]:hover {
        border-color: #BC955C;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-baseweb="input"]:focus-within {
        border-color: #BC955C;
        background-color: rgba(255, 255, 255, 0.14);
        box-shadow: 0 0 0 3px rgba(188, 149, 92, 0.25);
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-baseweb="input"] input,
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-baseweb="input"] input::placeholder {
        color: #000000;
    }
    /* Botón de ingreso */
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stFormSubmitButton"] button {
        width: 100%;
        margin-top: 8px;
        background: linear-gradient(135deg, #d4b17a 0%, #BC955C 100%);
        color: #10312B;
        border: none;
        border-radius: 10px;
        padding: 13px 20px;
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        box-shadow: 0 4px 14px rgba(188, 149, 92, 0.35);
        transition: all 0.3s ease;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stFormSubmitButton"] button:hover {
        background: linear-gradient(135deg, #e0c088 0%, #caa767 100%);
        transform: translateY(-2px);
        box-shadow: 0 8px 22px rgba(188, 149, 92, 0.45);
        color: #0d2823;
    }
    div[data-testid="stMainBlockContainer"]:has(.login-page) [data-testid="stFormSubmitButton"] button:active {
        transform: translateY(0);
    }
    /* Aviso debajo del encabezado del login */
    .login-note {
        text-align: center;
        color: #64748b;
        font-size: 0.95rem;
        margin: 14px 0 24px;
    }
    .login-footer {
        text-align: center;
        color: #94a3b8;
        font-size: 0.85rem;
        margin-top: 28px;
    }

    /* ========================================
       RESPONSIVE
       ======================================== */
    @media (max-width: 768px) {
        .shcp-header {
            flex-direction: column;
            text-align: center;
        }
        .shcp-header-text {
            text-align: center;
            margin-top: 15px;
            padding-left: 0;
        }
    }
</style>
"""


def _logo() -> str:
    """Devuelve el logo SHCP en base64 desde el archivo local."""
    import base64
    from config import LOGO_PATH
    try:
        with open(LOGO_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{b64}"


def _logo_uper() -> tuple:
    """Devuelve (data_uri, ancho, alto) del logo UPER recortado a su arte.

    El PNG original trae amplios márgenes blancos; se recorta a la zona no
    blanca (con un pequeño margen) para que luzca bien en la card de login.
    """
    import base64
    import io
    from config import LOGO_UPER_PATH
    try:
        from PIL import Image
        with Image.open(LOGO_UPER_PATH) as im:
            gray = im.convert("L")
            mask = gray.point(lambda v: 255 if v < 245 else 0)
            bbox = mask.getbbox()
            if not bbox:
                return "", 0, 0
            pad = 14
            rgba = im.convert("RGBA")
            box = (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(rgba.width, bbox[2] + pad),
                min(rgba.height, bbox[3] + pad),
            )
            rgba = rgba.crop(box)
            buf = io.BytesIO()
            rgba.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}", rgba.width, rgba.height
    except (OSError, ImportError):
        return "", 0, 0


def get_login_uper_logo_bytes() -> bytes:
    """Logo UPER recortado, como bytes PNG listos para st.image()."""
    import base64
    data_uri, _, _ = _logo_uper()
    if not data_uri:
        return b""
    return base64.b64decode(data_uri.split(",", 1)[1])


def get_header_html(titulo: str = "") -> str:
    """Retorna el HTML del header institucional con título de página."""
    logo = _logo()
    titulo_html = f'<p>{titulo}</p>' if titulo else ""
    return (
        '<div class="shcp-header">'
        '<div style="flex:0 0 auto"><img src="' + logo + '" alt="Logo SHCP"></div>'
        '<div class="shcp-header-text">'
        '<div class="shcp-title-line1">UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS</div>'
        '<div class="shcp-title-line2">COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL</div>'
        + titulo_html +
        '</div></div>'
    )


def get_header_html_home() -> str:
    """Retorna el HTML del header institucional (sin título de página)."""
    logo = _logo()
    return (
        '<div class="shcp-header">'
        '<div style="flex:0 0 auto"><img src="' + logo + '" alt="Logo SHCP"></div>'
        '<div class="shcp-header-text">'
        '<div class="shcp-title-line1">UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS</div>'
        '<div class="shcp-title-line2">COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL</div>'
        '</div></div>'
    )


def get_login_header_html() -> str:
    """Retorna el HTML del encabezado institucional para la página de login."""
    logo = _logo()
    return (
        '<div class="shcp-header login-page">'
        '<div style="flex:0 0 auto"><img src="' + logo + '" alt="Logo SHCP"></div>'
        '<div class="shcp-header-text">'
        '<div class="shcp-title-line1">Sistema de Monitoreo de Prensa</div>'
        '<div class="shcp-title-line2">UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS · '
        'COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL</div>'
        '</div></div>'
    )


def get_login_uper_logo_css() -> str:
    """Retorna un bloque <style> que coloca el logo UPER a la izquierda de la
    card del login (dentro del formulario de usuario/contraseña), con el
    contenido del formulario a su derecha.

    Debe inyectarse con st.markdown(..., unsafe_allow_html=True) en una llamada
    SEPARADA del header: los contenedores que incluyen <style> se ocultan con
    display:none (regla en GLOBAL_CSS), lo que dejaría invisible al header si
    compartieran la misma llamada.
    """
    logo_uper, w, h = _logo_uper()
    if not logo_uper or not w or not h:
        return ""
    base = (
        'div[data-testid="stMainBlockContainer"]:has(.login-page) '
        'div[data-testid="stForm"]:has(input[type="password"])'
    )
    return (
        '<style>'
        f'{base} {{'
        'position: relative !important;'
        'max-width: 560px !important;'
        'padding: 30px 32px 30px 250px !important;'
        'overflow: hidden !important;'
        '}'
        f'{base}::before {{'
        'content: "";'
        'position: absolute;'
        'left: 0;'
        'top: 0;'
        'bottom: 0;'
        'width: 220px;'
        'margin: 0;'
        'background: #ffffff url("' + logo_uper + '") center / 78% auto no-repeat;'
        'border-right: 1px solid rgba(16, 49, 43, 0.1);'
        '}'
        '/* Botón de ingreso a todo lo ancho del área derecha */'
        'div[data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]),'
        'div[data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]) > div {'
        'width: 100% !important;'
        '}'
        '[data-testid="stFormSubmitButton"] {'
        'width: 100% !important;'
        '}'
        '[data-testid="stFormSubmitButton"] button {'
        'width: 100% !important;'
        '}'
        '@media (max-width: 767px) {'
        f'{base} {{ max-width: 400px !important; padding: 26px 30px 30px !important; overflow: visible !important; }}'
        f'{base}::before {{'
        'position: static;'
        'width: auto;'
        'height: 120px;'
        'border-right: none;'
        'margin: 0 auto 18px;'
        'background-size: 55% auto;'
        '}'
        '}'
        '</style>'
    )


def get_login_cognito_card_css() -> str:
    """Card de login para el flujo Cognito (logo UPER + botón "Ingresar" en
    columnas nativas de Streamlit), con el mismo estilo de tarjeta oscura
    que usa el login local. Se aplica al st.container(key="cognito_login_box")
    que envuelve las columnas en app.py.

    A diferencia de get_login_uper_logo_css() (que superpone el logo con un
    ::before sobre el <form> del login local), aquí el logo se renderiza con
    st.image() dentro de una columna real — un ::before sobre
    st.container(key=...) resultó frágil por cómo Streamlit anida los divs
    internos de ese contenedor.
    """
    base = 'div[class*="st-key-cognito_login_box"]'
    return (
        '<style>'
        f'{base} {{'
        'background: #ffffff;'
        'border: 1px solid rgba(188, 149, 92, 0.35);'
        'border-top: 4px solid #BC955C;'
        'border-radius: 16px;'
        'max-width: 320px !important;'
        'margin: 0 auto;'
        'padding: 22px 26px;'
        'box-shadow: 0 14px 45px rgba(16, 49, 43, 0.18);'
        '}'
        f'{base} img {{ border-radius: 8px; }}'
        f'{base} [data-testid="stLinkButton"] {{ width: 100% !important; }}'
        f'{base} [data-testid="stLinkButton"] a {{'
        'width: 100% !important;'
        'display: flex !important;'
        'align-items: center;'
        'justify-content: center !important;'
        'background: linear-gradient(135deg, #d4b17a 0%, #BC955C 100%) !important;'
        'color: #ffffff !important;'
        'border: none !important;'
        'border-radius: 10px !important;'
        'padding: 13px 20px !important;'
        'font-size: 0.95rem !important;'
        'font-weight: 700 !important;'
        'letter-spacing: 1px !important;'
        'text-transform: uppercase !important;'
        'box-shadow: 0 4px 14px rgba(188, 149, 92, 0.35) !important;'
        'transition: all 0.3s ease !important;'
        '}'
        f'{base} [data-testid="stLinkButton"] a:hover {{'
        'background: linear-gradient(135deg, #e0c088 0%, #caa767 100%) !important;'
        'transform: translateY(-2px);'
        'box-shadow: 0 8px 22px rgba(188, 149, 92, 0.45);'
        'color: #ffffff !important;'
        '}'
        '</style>'
    )


def get_loading_overlay_html() -> str:
    """Retorna el HTML del indicador de carga pequeño (arriba a la derecha)."""
    return (
        '<div class="loading-overlay">'
        '<div class="loading-spinner"></div>'
        '<div class="loading-text">Cargando&hellip;</div>'
        '</div>'
    )