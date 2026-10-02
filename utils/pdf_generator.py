"""
Generador de PDF con xhtml2pdf + PyMuPDF.
Header (logo + titulo) se sobrepone en cada pagina via fitz.
Footer solo en la ultima pagina.
"""
import html as html_module
import re
import os
import io
import numbers
import requests
from typing import Optional
from datetime import datetime
from utils.date_helpers import TZ_MX
from config import LOGO_PATH, COPYRIGHT, CONTACTO_EMAILS
from xhtml2pdf import pisa
import fitz
from PIL import Image, ImageOps

_SESSION = requests.Session()


CSS_BODY = """
body {
    font-family: Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 0;
    color: #333;
    font-size: 12px;
}
"""


def _esc(text: str) -> str:
    return html_module.escape(str(text)) if text else ""


def _add_header_overlay(doc: fitz.Document, titulo: str = "") -> None:
    """Add header (logo + text) on every page of the PDF."""
    if not LOGO_PATH or not os.path.exists(LOGO_PATH):
        return
    GREEN = (0.047, 0.137, 0.118)
    GOLD = (0.737, 0.584, 0.361)
    H = 52
    for page in doc:
        w = page.rect.width
        # Green background bar
        page.draw_rect(fitz.Rect(0, 0, w, H), color=GREEN, fill=GREEN, width=0)
        # Logo at top-left
        logo_w = w * 0.35
        page.insert_image(fitz.Rect(6, 4, logo_w, H - 4), filename=LOGO_PATH, keep_proportion=True)
        # Text right-aligned on top-right
        text_right = w - 14
        lines = [
            ("UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS", 9),
            ("COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL", 9),
            (titulo, 7.5),
        ]
        y = 12
        for text, size in lines:
            if not text:
                continue
            tw = fitz.get_text_length(text, fontname="helv", fontsize=size)
            page.insert_text(
                (text_right - tw, y),
                text,
                fontname="helv",
                fontsize=size,
                color=GOLD,
            )
            y += size * 1.3


def _add_footer_overlay(doc: fitz.Document) -> None:
    GREEN = (0.047, 0.137, 0.118)
    GOLD = (0.737, 0.584, 0.361)
    H = 40
    for page in doc:
        if page.number != doc.page_count - 1:
            continue
        w = page.rect.width
        h = page.rect.height
        page_bottom = h - 10
        page.draw_rect(
            fitz.Rect(0, page_bottom - H, w, page_bottom),
            color=GREEN, fill=GREEN, width=0,
        )
        lines = [
            (COPYRIGHT, 8.5),
            (CONTACTO_EMAILS, 7.5),
        ]
        y_offset = page_bottom - H + 12
        for text, size in lines:
            tw = fitz.get_text_length(text, fontname="helv", fontsize=size)
            x = (w - tw) / 2
            page.insert_text(
                (x, y_offset),
                text,
                fontname="helv",
                fontsize=size,
                color=GOLD,
            )
            y_offset += size * 1.4


# =========================================================
# PDF DE CONFERENCIA DE PRENSA MATUTINA
# =========================================================
def generar_pdf_conferencia(
    resumen: str,
    output_path: str,
    titulo_personalizado: str = "",
    link_fuente: str = "",
) -> str:
    now = datetime.now(TZ_MX).strftime("%d/%m/%Y %H:%M")

    def _linea_a_html(linea_escapada: str) -> str:
        linea_escapada = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", linea_escapada)
        linea_escapada = re.sub(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
            r'<a href="\2" target="_blank">\1</a>',
            linea_escapada,
        )
        return linea_escapada

    titulo = (titulo_personalizado or "").strip() or "ANÁLISIS DE NOTAS"

    # Link dinámico: el usuario escribe [[LINK]] (o [LINK] / {{LINK}})
    # en cualquier parte del resumen y aquí se sustituye por la palabra
    # "Link" clicable. Si no hay URL, el marcador simplemente se elimina.
    link = (link_fuente or "").strip()
    if link and not re.match(r"^https?://", link, re.IGNORECASE):
        link = "https://" + link
    _link_url_esc = _esc(link)
    _link_pattern = re.compile(r"\[\[LINK\]\]|\[LINK\]|\{\{LINK\}\}", re.IGNORECASE)

    def _insertar_link(linea_escapada: str) -> str:
        if link:
            return _link_pattern.sub(
                f'<a href="{_link_url_esc}">Link</a>', linea_escapada
            )
        return _link_pattern.sub("", linea_escapada)

    SECTION_HEADERS = [
        "Resumen general:", "Temas abordados:",
        "Puntos relevantes:", "Análisis y relevancia para la SHCP:",
        "**Resumen general:**", "**Temas abordados:**",
        "**Puntos relevantes:**", "**Análisis y relevancia para la SHCP:**",
    ]

    html_resumen = ""
    in_list = False
    for linea in resumen.split("\n"):
        linea_html = _esc(linea)
        stripped = linea.strip()
        if stripped in SECTION_HEADERS:
            if in_list:
                html_resumen += "</ul>\n"
                in_list = False
            text = stripped.strip("*")
            html_resumen += f"<h3>{_esc(text)}</h3>\n"
        elif linea_html.startswith("## "):
            if in_list:
                html_resumen += "</ul>\n"
                in_list = False
            html_resumen += f"<h2>{_linea_a_html(_insertar_link(linea_html[3:]))}</h2>\n"
        elif linea_html.startswith("### "):
            if in_list:
                html_resumen += "</ul>\n"
                in_list = False
            html_resumen += f"<h3>{_linea_a_html(_insertar_link(linea_html[4:]))}</h3>\n"
        elif linea_html.startswith("- ") or linea_html.startswith("* "):
            if not in_list:
                html_resumen += "<ul>\n"
                in_list = True
            html_resumen += f"<li>{_linea_a_html(_insertar_link(linea_html[2:]))}</li>\n"
        elif linea_html == "":
            if in_list:
                html_resumen += "</ul>\n"
                in_list = False
            html_resumen += "<br>\n"
        else:
            if in_list:
                html_resumen += "</ul>\n"
                in_list = False
            html_resumen += f"<p>{_linea_a_html(_insertar_link(linea_html))}</p>\n"
    if in_list:
        html_resumen += "</ul>\n"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        {CSS_BODY}
        @page {{
            size: A4 portrait;
            margin: 75px 20mm 25mm 20mm;
        }}
        .contenido {{
            text-align: justify;
            line-height: 1.6;
            font-size: 11pt;
        }}
        .contenido a {{
            color: #10312B;
            font-weight: bold;
            text-decoration: underline;
        }}
        h2 {{
            color: #10312B;
            border-bottom: 2px solid #BC955C;
            padding-bottom: 5px;
            font-size: 14pt;
            margin-top: 15px;
            text-align: left;
        }}
        h3 {{
            color: #10312B;
            font-size: 12pt;
            margin-top: 14px;
            margin-bottom: 4px;
            font-weight: bold;
            text-align: left;
        }}
        p {{
            margin: 5px 0;
            text-align: justify;
        }}
        li {{
            margin: 3px 0 3px 20px;
            text-align: justify;
        }}
        .date-info {{
            text-align: right;
            font-size: 10pt;
            color: #666;
            margin-bottom: 10px;
        }}
    </style>
</head>
<body>
    <div class="contenido">
        <div class="date-info">Generado el: {now}</div>
        {html_resumen}
    </div>
</body>
</html>"""

    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w+b") as output_file:
        status = pisa.CreatePDF(html_content, dest=output_file)
        if status.err:
            os.remove(tmp_path)
            raise RuntimeError(f"Error al generar PDF: {status.err}")

    doc = fitz.open(tmp_path)
    _add_header_overlay(doc, titulo)
    _add_footer_overlay(doc)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    os.remove(tmp_path)
    return output_path


# =========================================================
# PDF DE SÍNTESIS DE NOTICIAS
# =========================================================
def generar_pdf_sintesis(df, output_path: str) -> str:
    if df is None or df.empty:
        raise ValueError("No hay noticias para exportar")

    cols_display = ["Título", "Resumen Ejecutivo", "Fuente", "Enfoque", "Fecha", "Enlace"]
    available_cols = [c for c in cols_display if c in df.columns]

    now = datetime.now(TZ_MX).strftime("%d/%m/%Y %H:%M")

    col_widths = {
        "Título": "20%",
        "Resumen Ejecutivo": "40%",
        "Fuente": "10%",
        "Enfoque": "10%",
        "Fecha": "10%",
        "Enlace": "10%",
    }
    header_row = ""
    for c in available_cols:
        width = col_widths.get(c, "auto")
        header_row += f'<th style="width:{width}">{_esc(c)}</th>'

    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for col in available_cols:
            val = row.get(col, "")
            if col == "Título":
                cells.append(f'<td class="titulo">{_esc(str(val))}</td>')
            elif col == "Resumen Ejecutivo":
                cells.append(f'<td class="resumen">{_esc(str(val))}</td>')
            elif col == "Enlace":
                match = re.search(r'href="([^"]+)"', str(val))
                href = match.group(1) if match else "#"
                if href == "#" or not href:
                    cells.append('<td class="enlace">No disponible</td>')
                else:
                    cells.append(
                        f'<td class="enlace"><a href="{_esc(href)}" target="_blank">IR</a></td>'
                    )
            else:
                val_str = _formatear_fecha(val) if col == "Fecha" else str(val)
                cells.append(f"<td>{_esc(val_str)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        {CSS_BODY}
        @page {{
            size: A4 landscape;
            margin: 95px 15mm 20mm 15mm;
        }}
        .contenido h3 {{
            margin: 0 0 5px 0;
            padding-bottom: 4px;
            border-bottom: 2px solid #BC955C;
            color: #10312B;
            font-size: 13px;
        }}
        .contenido table.data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 5px;
            table-layout: fixed;
        }}
        .contenido th {{
            background-color: #10312B;
            color: #BC955C;
            text-align: left;
            padding: 8px 6px;
            font-size: 10px;
            font-weight: bold;
            border-bottom: 2px solid #BC955C;
        }}
        .contenido td {{
            padding: 8px 6px;
            border-bottom: 1px solid #ddd;
            font-size: 9px;
            vertical-align: top;
            word-wrap: break-word;
        }}
        .contenido td.titulo {{ font-weight: bold; font-size: 9px; }}
        .contenido td.resumen {{ text-align: justify; line-height: 1.4; font-size: 9px; }}
        .contenido td.enlace {{ text-align: center; font-size: 8px; }}
        .contenido td.enlace a {{
            color: #10312B; font-weight: bold;
            padding: 2px 6px; border: 1px solid #10312B;
            border-radius: 3px; text-decoration: none; font-size: 8px;
        }}
        .contenido tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .date-info {{
            text-align: right;
            font-size: 11px;
            color: #666;
            margin-bottom: 5px;
        }}
    </style>
</head>
<body>
    <div class="contenido">
        <h3>Reporte de Noticias Relevantes</h3>
        <div class="date-info">Generado el: {now}</div>
        <table class="data-table">
            <thead><tr>{header_row}</tr></thead>
            <tbody>{"".join(body_rows)}</tbody>
        </table>
    </div>
</body>
</html>"""

    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w+b") as output_file:
        status = pisa.CreatePDF(html_content, dest=output_file)
        if status.err:
            os.remove(tmp_path)
            raise RuntimeError(f"Error al generar PDF: {status.err}")

    doc = fitz.open(tmp_path)
    _add_header_overlay(doc, "SÍNTESIS DE PRENSA")
    _add_footer_overlay(doc)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    os.remove(tmp_path)
    return output_path


def _descargar_imagen(url: str, timeout: int = 20, intentos: int = 3) -> Optional[bytes]:
    """Descarga una imagen con headers de navegador, valida que sea imagen
    real y reintenta con backoff (algunos CDN fallan intermitentemente)."""
    import time

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": url,
    }
    _SESSION.headers.update(headers)
    backoff = [4, 12, 25]
    for intento in range(intentos):
        try:
            resp = _SESSION.get(url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.content
                try:
                    Image.open(io.BytesIO(data)).verify()
                    return data
                except Exception:
                    pass
        except Exception:
            pass
        if intento < intentos - 1:
            time.sleep(backoff[intento] if intento < len(backoff) else 30)
    return None


def _preparar_imagen(data: bytes, max_px: int = 1800) -> Optional[bytes]:
    """Normaliza una imagen: aplica orientación EXIF, aplana transparencia
    sobre blanco, convierte a RGB y re-encodea como JPEG para reducir peso."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return None


def _insert_wrapped(
    page: fitz.Page,
    text: str,
    x: float,
    xmax: float,
    y: float,
    size: float,
    font: str = "helv",
    color=None,
    max_lines: Optional[int] = None,
) -> float:
    """Inserta texto con ajuste de línea y regresa la y final."""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if fitz.get_text_length(test, fontname=font, fontsize=size) <= (xmax - x):
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if max_lines:
        lines = lines[:max_lines]
    leading = size * 1.3
    for line in lines:
        page.insert_text((x, y), line, fontname=font, fontsize=size, color=color or (0, 0, 0))
        y += leading
    return y


def _formatear_fecha(val) -> str:
    """Formatea un valor de fecha a YYYY-MM-DD HH:MM.
    Acepta datetime/Timestamp o epoch en milisegundos (df.to_json() serializa las
    fechas como ms y read_json no las reconstruye como datetime)."""
    if val is None:
        return "N/D"
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M")
    if isinstance(val, numbers.Number):
        try:
            return datetime.fromtimestamp(float(val) / 1000, tz=TZ_MX).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            return str(val)
    return str(val)


# =========================================================
# PDF DE CARTONES
# =========================================================
def generar_pdf_cartones(df, output_path: str) -> str:
    if df is None or df.empty:
        raise ValueError("No hay cartones para exportar")

    df_valid = df[df["img"].notna() & (df["img"] != "")].copy()
    if df_valid.empty:
        raise ValueError("No hay cartones con imagen válida para exportar")

    doc = fitz.open()
    PAGE_W, PAGE_H = fitz.paper_size("a4")
    MARGIN = 36.0
    LEFT = MARGIN
    RIGHT = PAGE_W - MARGIN
    TOP = 70.0
    BOTTOM = PAGE_H - 28.0

    GREEN = (0.047, 0.137, 0.118)
    GRAY = (0.35, 0.35, 0.35)
    GOLD = (0.737, 0.584, 0.361)

    for _, row in df_valid.iterrows():
        page = doc.new_page(width=PAGE_W, height=PAGE_H)

        titulo = str(row.get("titulo", "") or "")
        fuente = str(row.get("fuente", "") or "")
        fecha_str = _formatear_fecha(row.get("fecha", None))
        url = str(row.get("url", "") or "")

        y = TOP

        y = _insert_wrapped(page, titulo, LEFT, RIGHT, y, 14.0, color=GREEN, max_lines=3)
        meta1 = f"Fuente: {fuente} | Fecha: {fecha_str}"
        y = _insert_wrapped(page, meta1, LEFT, RIGHT, y, 9.5, color=GRAY)
        if len(url) > 100:
            url_mostrar = url[:97] + "..."
        else:
            url_mostrar = url
        y = _insert_wrapped(page, "Link: " + url_mostrar, LEFT, RIGHT, y, 8.5, color=GRAY)
        y += 8

        page.draw_line((LEFT, y), (RIGHT, y), color=GOLD, width=1.2)
        y += 12

        img_url = str(row.get("img", ""))
        img_data = _preparar_imagen(_descargar_imagen(img_url)) if img_url else None
        if img_data:
            with Image.open(io.BytesIO(img_data)) as pil:
                iw, ih = pil.size
            avail_w = RIGHT - LEFT
            avail_h = BOTTOM - y
            scale = min(avail_w / iw, avail_h / ih)
            w = iw * scale
            h = ih * scale
            x = LEFT + (avail_w - w) / 2
            y_img = y + (avail_h - h) / 2
            rect = fitz.Rect(x, y_img, x + w, y_img + h)
            page.insert_image(rect, stream=img_data, keep_proportion=False)
        else:
            page.insert_textbox(
                fitz.Rect(LEFT, y, RIGHT, y + 40),
                "Imagen no disponible",
                fontname="helv",
                fontsize=12,
                color=GRAY,
                align=1,
            )

    _add_header_overlay(doc, "CARTONES DEL DÍA")
    _add_footer_overlay(doc)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return output_path
