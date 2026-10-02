# app.R ----------------------------------------------------------
suppressPackageStartupMessages({
  library(shiny)
  library(bslib)
  library(rvest)
  library(xml2)
  library(dplyr)
  library(purrr)
  library(stringr)
  library(lubridate)
  library(tibble)
  library(DT)
  library(httr)
  library(htmltools)
  library(pagedown)
  library(digest)
  library(later)
})

# =========================================================
# 1) HTTP
# =========================================================
ua <- "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
`%||%` <- function(a, b) if (!is.null(a) && length(a) > 0 && !is.na(a)) a else b

safe_read_html <- function(url, timeout_sec = 20) {
  tryCatch({
    resp <- httr::GET(
      url,
      httr::user_agent(ua),
      httr::timeout(timeout_sec),
      httr::add_headers(
        `Accept` = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        `Accept-Language` = "es-MX,es;q=0.9,en;q=0.8",
        `Cache-Control` = "no-cache",
        `Pragma` = "no-cache"
      )
    )
    if (is.null(resp)) return(NULL)
    if (httr::status_code(resp) >= 400) return(NULL)
    
    html_txt <- httr::content(resp, as = "text", encoding = "UTF-8")
    if (is.null(html_txt) || !nzchar(html_txt)) return(NULL)
    
    read_html(html_txt, options = c("RECOVER", "NOERROR", "NOBLANKS"))
  }, error = function(e) NULL)
}

html_text_trim <- function(x) {
  if (is.null(x) || length(x) == 0 || all(is.na(x))) return(character())
  out <- tryCatch(rvest::html_text2(x), error = function(e) rvest::html_text(x))
  stringr::str_trim(out)
}

get_meta_prop <- function(doc, prop) {
  if (is.null(doc)) return(NA_character_)
  val <- doc |>
    html_elements(xpath = sprintf("//meta[@property='%s']/@content", prop)) |>
    html_text_trim()
  if (length(val) > 0) return(val[[1]])
  NA_character_
}

get_meta_name <- function(doc, name) {
  if (is.null(doc)) return(NA_character_)
  val <- doc |>
    html_elements(xpath = sprintf("//meta[@name='%s']/@content", name)) |>
    html_text_trim()
  if (length(val) > 0) return(val[[1]])
  NA_character_
}

# =========================================================
# 1.1) Parse de fechas
# =========================================================
parse_datetime_guess <- function(x) {
  if (is.na(x) || !nzchar(x)) return(NA)
  
  x0 <- stringr::str_trim(x)
  x1 <- x0
  x1 <- stringr::str_replace_all(x1, "\\.", "-")
  x1 <- stringr::str_replace_all(x1, "/", "-")
  
  out <- suppressWarnings(lubridate::ymd_hms(x0, quiet = TRUE, tz = "UTC"))
  if (!is.na(out)) return(out)
  
  out <- suppressWarnings(lubridate::ymd_hms(x1, quiet = TRUE, tz = "UTC"))
  if (!is.na(out)) return(out)
  
  out <- suppressWarnings(lubridate::ymd(x0, quiet = TRUE, tz = "UTC"))
  if (!is.na(out)) return(as.POSIXct(out))
  
  out <- suppressWarnings(lubridate::ymd(x1, quiet = TRUE, tz = "UTC"))
  if (!is.na(out)) return(as.POSIXct(out))
  
  out2 <- suppressWarnings(lubridate::dmy_hm(x0, tz = "UTC"))
  if (!is.na(out2)) return(out2)
  
  out2 <- suppressWarnings(lubridate::dmy_hm(x1, tz = "UTC"))
  if (!is.na(out2)) return(out2)
  
  out3 <- suppressWarnings(lubridate::dmy(x0, tz = "UTC"))
  if (!is.na(out3)) return(as.POSIXct(out3))
  
  out3 <- suppressWarnings(lubridate::dmy(x1, tz = "UTC"))
  if (!is.na(out3)) return(as.POSIXct(out3))
  
  NA
}

# =========================================================
# 1.2) Extraer fecha desde HTML
# =========================================================
extract_date_from_html_regex <- function(doc) {
  if (is.null(doc)) return(NA_character_)
  raw <- tryCatch(as.character(doc), error = function(e) "")
  if (!nzchar(raw)) return(NA_character_)
  
  m <- stringr::str_extract_all(raw, "\\b\\d{2}[\\./-]\\d{2}[\\./-]\\d{4}\\b")[[1]]
  m <- unique(m)
  if (length(m) == 0) return(NA_character_)
  m[[1]]
}

# =========================================================
# 1.3) Extraer fecha/hora desde HTML (EL UNIVERSAL)
# =========================================================
extract_datetime_eluniversal <- function(doc) {
  if (is.null(doc)) return(NA_character_)
  
  dt_attr <- tryCatch({
    doc |>
      html_elements(xpath = "//time[@datetime]/@datetime") |>
      html_text_trim()
  }, error = function(e) character())
  
  if (length(dt_attr) > 0 && nzchar(dt_attr[[1]])) return(dt_attr[[1]])
  
  raw <- tryCatch(as.character(doc), error = function(e) "")
  if (!nzchar(raw)) return(NA_character_)
  
  m_dt <- stringr::str_extract_all(raw, "\\b\\d{2}/\\d{2}/\\d{4}\\s+\\d{2}:\\d{2}\\b")[[1]]
  m_dt <- unique(m_dt)
  if (length(m_dt) > 0) return(m_dt[[1]])
  
  m_d <- stringr::str_extract_all(raw, "\\b\\d{2}/\\d{2}/\\d{4}\\b")[[1]]
  m_d <- unique(m_d)
  if (length(m_d) > 0) return(m_d[[1]])
  
  NA_character_
}

# =========================================================
# 2) Extractor de links
# =========================================================
extract_links <- function(list_url, must_contain, exclude_exact = NULL) {
  doc <- safe_read_html(list_url)
  if (is.null(doc)) return(character())
  
  hrefs <- doc |>
    html_elements("a") |>
    html_attr("href") |>
    na.omit() |>
    unique()
  
  abs <- purrr::map_chr(hrefs, function(h) {
    h2 <- str_trim(h)
    
    if (!nzchar(h2) || h2 %in% c("#", "/") ||
        str_detect(h2, "^mailto:") ||
        str_detect(h2, "^javascript:")) {
      return(NA_character_)
    }
    
    h2 <- str_replace(h2, "\\?.*$", "")
    h2 <- str_replace(h2, "#.*$", "")
    
    if (!str_detect(h2, "^https?://"))
      return(xml2::url_absolute(h2, list_url))
    
    h2
  }) |>
    na.omit() |>
    unique()
  
  abs <- abs[str_detect(abs, must_contain)]
  if (!is.null(exclude_exact)) abs <- setdiff(abs, exclude_exact)
  
  abs <- abs[!str_detect(
    abs,
    "facebook|twitter|x\\.com|whatsapp|instagram|ads|doubleclick|mailto:|javascript:"
  )]
  
  unique(abs)
}

# =========================================================
# 3) Lee un cartón (1 URL)
# =========================================================
pick_fallback_img <- function(doc, base_url) {
  if (is.null(doc)) return(NA_character_)
  
  tw <- get_meta_name(doc, "twitter:image")
  if (!is.na(tw) && nzchar(tw)) return(xml2::url_absolute(tw, base_url))
  
  imgs <- doc |>
    html_elements("img") |>
    html_attr("src") |>
    na.omit() |>
    unique()
  
  if (length(imgs) == 0) return(NA_character_)
  
  imgs <- purrr::map_chr(imgs, ~ xml2::url_absolute(.x, base_url))
  imgs <- imgs[!str_detect(imgs, "^data:")]
  imgs <- imgs[!str_detect(imgs, "logo|sprite|icon|avatar|ads|doubleclick|pixel")]
  if (length(imgs) == 0) return(NA_character_)
  
  imgs[[1]]
}

read_cartoon_from_url <- function(source, url) {
  doc <- safe_read_html(url)
  if (is.null(doc)) return(NULL)
  
  img <- get_meta_prop(doc, "og:image")
  if (is.na(img) || !nzchar(img)) img <- pick_fallback_img(doc, url)
  if (!is.na(img) && nzchar(img)) img <- xml2::url_absolute(img, url)
  
  ttl <- get_meta_prop(doc, "og:title")
  if (is.na(ttl) || !nzchar(ttl)) ttl <- get_meta_name(doc, "title")
  if (is.na(ttl) || !nzchar(ttl)) ttl <- "(sin título)"
  
  published <- get_meta_prop(doc, "article:published_time")
  if (is.na(published) || !nzchar(published)) published <- get_meta_prop(doc, "og:updated_time")
  if (is.na(published) || !nzchar(published)) published <- get_meta_name(doc, "date")
  
  if (identical(source, "Milenio") && (is.na(published) || !nzchar(published))) {
    published <- extract_date_from_html_regex(doc)
  }
  if (identical(source, "El Universal") && (is.na(published) || !nzchar(published))) {
    published <- extract_datetime_eluniversal(doc)
  }
  
  tibble(
    id     = paste0("c_", digest::digest(url)),
    fuente = source,
    titulo = ttl,
    fecha  = parse_datetime_guess(published),
    url    = url,
    img    = img
  )
}

# =========================================================
# 3.1) Validación REAL de imágenes
# =========================================================
img_reachable <- function(url, timeout_sec = 12) {
  if (is.na(url) || !nzchar(url)) return(FALSE)
  
  ok <- tryCatch({
    h <- httr::HEAD(
      url,
      httr::user_agent(ua),
      httr::timeout(timeout_sec),
      httr::add_headers(`Accept` = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
    )
    sc <- httr::status_code(h)
    ct <- httr::headers(h)[["content-type"]] %||% ""
    sc < 400 && grepl("^image/", tolower(ct))
  }, error = function(e) FALSE)
  
  if (ok) return(TRUE)
  
  tryCatch({
    g <- httr::GET(
      url,
      httr::user_agent(ua),
      httr::timeout(timeout_sec),
      httr::add_headers(
        `Accept` = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        `Range`  = "bytes=0-20480"
      )
    )
    sc <- httr::status_code(g)
    ct <- httr::headers(g)[["content-type"]] %||% ""
    sc < 400 && grepl("^image/", tolower(ct))
  }, error = function(e) FALSE)
}

# =========================================================
# 4) Configuración de fuentes
# =========================================================
sources_cfg <- tribble(
  ~fuente,        ~list_url,                                              ~must_contain,                                      ~exclude_exact,
  
  "El Universal", "https://www.eluniversal.com.mx/carton/",
  "eluniversal\\.com\\.mx/carton/[^/?#]+/[^/?#]+/?$",
  "https://www.eluniversal.com.mx/carton/",
  
  "Vanguardia",   "https://vanguardia.com.mx/opinion/cartones",
  "vanguardia\\.com\\.mx/opinion/cartones/.+",
  "https://vanguardia.com.mx/opinion/cartones",
  
  "La Jornada",   "https://www.jornada.com.mx/categoria/cartones",
  "jornada\\.com\\.mx/.*/cartones/.+",
  "https://www.jornada.com.mx/categoria/cartones",
  
  "Milenio",      "https://www.milenio.com/opinion/moneros",
  "milenio\\.com/opinion/moneros/.+",
  "https://www.milenio.com/opinion/moneros"
)

# =========================================================
# 6) PDF (HTML directo + chrome_print)
# =========================================================
render_pdf <- function(df, out_pdf) {
  tmpdir   <- tempdir()
  html_out <- file.path(tmpdir, "cartones_del_dia.html")
  
  df2 <- df
  if ("img_ok" %in% names(df2)) df2 <- df2[df2$img_ok %in% TRUE, , drop = FALSE]
  df2 <- df2[!is.na(df2$img) & nzchar(df2$img), , drop = FALSE]
  if (nrow(df2) == 0) stop("Sin cartones con imagen válida para exportar.")
  
  esc <- htmltools::htmlEscape
  
  css <- paste0(
    "<style>",
    "@page { margin: 12mm 12mm 30mm 12mm; }",
    "@media print {",
    "  a[href]:after { content: '' !important; }",
    "  a[href^='mailto:']:after { content: '' !important; }",
    "  .carton-page { break-inside: avoid; page-break-inside: avoid; padding-bottom: 24mm; }",
    "  .carton-page { break-after: page; page-break-after: always; }",
    "  .carton-page:last-child { break-after: auto; page-break-after: auto; }",
    "}",
    ".carton-card { border: 1px solid #ddd; border-radius: 10px; padding: 10px; margin: 0; }",
    ".meta { font-size: 10.5px; color: #444; }",
    ".carton-img { width: 100%; max-height: calc(100vh - 70mm); object-fit: contain; display: block; margin-top: 8px; }",
    ".imss-footer-pdf {",
    "  position: fixed; left: 0; right: 0; bottom: 0;",
    "  background: #e9ecef; border-top: 1px solid #ced4da;",
    "  padding: 5px 10px; font-size: 8.8px; line-height: 1.15; color: #343a40;",
    "}",
    ".imss-footer-pdf .footer-inner {",
    "  max-width: 1400px; margin: 0 auto;",
    "  display: flex; flex-direction: column; gap: 2px;",
    "  align-items: center; text-align: center;",
    "}",
    "</style>"
  )
  
  footer_html <- paste0(
    "<div class='imss-footer-pdf'><div class='footer-inner'>",
    "<div>© 2026 SHCP - Coordinación de Fortalecimiento Institucional</div>",
    "<div> claudia_segovia@shcp.gob.mx | yazid_guzman@shcp.gob.mx</div>",
    "</div></div>"
  )
  
  body_parts <- character(0)
  for (i in seq_len(nrow(df2))) {
    fch <- if (is.na(df2$fecha[i])) "N/D" else format(df2$fecha[i], "%Y-%m-%d %H:%M")
    body_parts <- c(
      body_parts,
      "<div class='carton-page'>",
      "<div class='carton-card'>",
      sprintf("<div><b>%s</b></div>", esc(df2$titulo[i])),
      sprintf("<div class='meta'>Fuente: %s | Fecha: %s</div>", esc(df2$fuente[i]), esc(fch)),
      sprintf("<div class='meta'>Link: <a href='%s'>%s</a></div>", esc(df2$url[i]), esc(df2$url[i])),
      sprintf("<img class='carton-img' src='%s'/>", esc(df2$img[i])),
      "</div>",
      "</div>"
    )
  }
  
  html_doc <- paste0(
    "<!doctype html><html><head><meta charset='utf-8'>",
    css,
    "</head><body>",
    footer_html,
    paste0(body_parts, collapse = "\n"),
    "</body></html>"
  )
  
  writeLines(html_doc, html_out, useBytes = TRUE)
  
  chrome_path <- tryCatch(pagedown::find_chrome(), error = function(e) NULL)
  if (is.null(chrome_path) || !nzchar(chrome_path) || !file.exists(chrome_path)) {
    stop("No se encontró Chrome/Chromium para generar PDF. Instala Google Chrome y reinicia la app.")
  }
  
  pagedown::chrome_print(input = html_out, output = out_pdf, wait = TRUE, verbose = 0)
  
  if (!file.exists(out_pdf) || file.info(out_pdf)$size == 0) {
    stop("El PDF no se generó (archivo vacío).")
  }
  
  out_pdf
}

# =========================================================
# 7) UI / Server 
# =========================================================
ui <- page_fillable(
  theme = bs_theme(version = 5, bootswatch = "flatly"),
  
  tags$head(
    tags$style(HTML("
      body { padding-bottom: 62px; }
      .imss-footer {
        position: fixed;
        left: 0; right: 0; bottom: 0;
        z-index: 9999;
        background: #e9ecef;
        border-top: 1px solid #ced4da;
        padding: 6px 14px;
        font-size: 0.72rem;
        line-height: 1.15;
        color: #343a40;
      }
      .imss-footer .footer-inner{
        max-width: 1400px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 2px;
        align-items: center;
        text-align: center;
      }
      .status-row{
        display:flex; justify-content:space-between; gap:10px; padding:6px 0;
        border-bottom: 1px dashed rgba(0,0,0,.12);
      }
      .status-row:last-child{ border-bottom:none; }
      .badge-soft{
        padding: 0.25rem 0.5rem; border-radius: 999px; font-size: 0.78rem;
        background: #f1f3f5; color: #343a40;
      }
      .badge-ok{ background:#d3f9d8; color:#1b4332; }
      .badge-run{ background:#d0ebff; color:#0b3954; }
      .badge-err{ background:#ffe3e3; color:#7d0000; }
      .badge-cancel{ background:#e9ecef; color:#495057; }
    "))
  ),
  
  layout_sidebar(
    sidebar = sidebar(
      h4("Cartones del día (síntesis de prensa)"),
      actionButton("btn_fetch", "Actualizar", class = "btn-primary"),
      br(), br(),
      numericInput("n", "Cantidad", value = 20, min = 5, max = 50, step = 1),
      numericInput("lookback", "Lookback (días)", value = 1, min = 0, max = 30, step = 1),
      checkboxInput("verbose", "Mostrar logs en consola", value = TRUE),
      
      br(),
      actionButton("btn_delete", "Eliminar seleccionados", class = "btn-danger"),
      br(), br(),
      downloadButton("pdf", "Descargar PDF")
    ),
    card(
      card_header("Resultados (selecciona filas y elimina)"),
      uiOutput("processing"),
      DTOutput("tbl"),
      br(),
      uiOutput("note")
    )
  ),
  
  tags$footer(
    class = "imss-footer",
    div(
      class = "footer-inner",
      div("© 2026 SHCP - Coordinación de Fortalecimiento Institucional"),
      div("caludia_segovia@shcp.gob.mx | yazid_guzman@shcp.gob.mx")
    )
  )
)

server <- function(input, output, session) {
  
  fuentes <- unique(sources_cfg$fuente)
  
  rv <- reactiveValues(
    df = tibble(),
    running = FALSE,
    cancel = FALSE,
    phase = "idle",
    fuente_queue = character(),
    img_queue = character(),
    items_acc = tibble(),
    img_ok_map = list(),
    fuente_status = setNames(as.list(rep("Pendiente", length(fuentes))), fuentes),
    fuente_counts = setNames(as.list(rep(0L, length(fuentes))), fuentes),
    progress = 0
  )
  
  spinner_bs5 <- function(size_px = 16) {
    tags$span(
      class = "spinner-border spinner-border-sm",
      role  = "status",
      `aria-hidden` = "true",
      style = sprintf("width:%spx; height:%spx;", size_px, size_px)
    )
  }
  
  status_badge <- function(txt) {
    cls <- "badge-soft"
    if (identical(txt, "OK")) cls <- paste(cls, "badge-ok")
    if (identical(txt, "Procesando")) cls <- paste(cls, "badge-run")
    if (identical(txt, "Validando imágenes")) cls <- paste(cls, "badge-run")
    if (identical(txt, "Error")) cls <- paste(cls, "badge-err")
    if (identical(txt, "Cancelado")) cls <- paste(cls, "badge-cancel")
    span(class = cls, txt)
  }
  
  get_is <- function(expr) isolate(expr)
  
  output$processing <- renderUI({
    if (!isTRUE(rv$running)) return(NULL)
    
    prog_pct <- max(0, min(100, round(100 * (rv$progress %||% 0))))
    
    tagList(
      bslib::card(
        class = "mb-3",
        bslib::card_header(
          div(style = "display:flex; align-items:center; justify-content:space-between; gap:10px;",
              div(style="display:flex; align-items:center; gap:10px;",
                  spinner_bs5(16),
                  strong(if (isTRUE(rv$cancel)) "Cancelando…" else "Procesando…")
              ),
              span(class="badge-soft",
                   if (rv$phase == "sources") "Leyendo fuentes"
                   else if (rv$phase == "validate") "Validando imágenes"
                   else "Finalizando"
              )
          )
        ),
        bslib::card_body(
          div(class="progress", style="height:10px;",
              div(class="progress-bar", role="progressbar",
                  style = sprintf("width:%s%%;", prog_pct),
                  `aria-valuenow` = prog_pct, `aria-valuemin`="0", `aria-valuemax`="100"
              )
          ),
          div(style="margin-top:10px;",
              lapply(fuentes, function(f) {
                div(class="status-row",
                    div(strong(f)),
                    div(style="display:flex; gap:8px; align-items:center;",
                        span(style="font-size:0.85rem; color:#495057;",
                             if ((rv$fuente_status[[f]] %||% "") %in% c("OK","Error","Cancelado")) {
                               paste0(rv$fuente_counts[[f]] %||% 0L, " item(s)")
                             } else ""
                        ),
                        status_badge(rv$fuente_status[[f]] %||% "Pendiente")
                    )
                )
              })
          ),
          div(style="margin-top:10px; font-size:0.85rem; color:#495057;",
              "Tip: si vuelves a presionar ",
              tags$b("Actualizar"),
              " durante el procesamiento, se cancelará la ejecución en curso."
          )
        )
      )
    )
  })
  
  reset_run_state <- function() {
    isolate({
      rv$cancel <- FALSE
      rv$phase <- "idle"
      rv$fuente_queue <- character()
      rv$img_queue <- character()
      rv$items_acc <- tibble()
      rv$img_ok_map <- list()
      rv$progress <- 0
      rv$fuente_status <- setNames(as.list(rep("Pendiente", length(fuentes))), fuentes)
      rv$fuente_counts <- setNames(as.list(rep(0L, length(fuentes))), fuentes)
    })
  }
  
  fuente_order <- fuentes  
  
  quota_por_fuente <- function(target_n, fuente_order) {
    k <- length(fuente_order)
    base <- target_n %/% k
    rem  <- target_n %%  k
    q <- rep(base, k)
    if (rem > 0) q[seq_len(rem)] <- q[seq_len(rem)] + 1L
    setNames(as.list(as.integer(q)), fuente_order)
  }
  
  build_candidates_for_validation <- function(items_acc, lookback_days, target_n, fuente_order, buffer = 8L) {
    cutoff <- as.Date(Sys.Date() - lookback_days)
    
    base <- items_acc |>
      mutate(
        fecha_d = as.Date(fecha),
        ok_img  = !is.na(img) & nzchar(img)
      ) |>
      filter(ok_img) |>
      filter(is.na(fecha_d) | fecha_d >= cutoff)
    
    if (nrow(base) == 0) return(tibble())
    
    base <- base |>
      mutate(fuente = factor(fuente, levels = fuente_order)) |>
      arrange(fuente, desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC")))) |>
      distinct(img, .keep_all = TRUE) |>
      mutate(fuente = as.character(fuente))
    
    quotas <- quota_por_fuente(target_n, fuente_order)
    
    cand <- base |>
      group_by(fuente) |>
      group_modify(function(.x, .y) {
        f <- as.character(.y$fuente[[1]])
        n_take <- as.integer(quotas[[f]] %||% 0L) + as.integer(buffer)
        
        .x |>
          arrange(desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC")))) |>
          head(n_take)
      }) |>
      ungroup() |>
      arrange(factor(fuente, levels = fuente_order),
              desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC"))))
    
    cand
  }
  
  final_select_by_quota <- function(cand, target_n, fuente_order, img_ok_map) {
    if (is.null(cand) || !is.data.frame(cand) || nrow(cand) == 0) return(tibble())
    
    quotas <- quota_por_fuente(target_n, fuente_order)
    
    cand_ok <- cand |>
      mutate(
        img_ok = purrr::map_lgl(img, ~ isTRUE(img_ok_map[[.x]] %||% FALSE))
      ) |>
      filter(img_ok) |>
      arrange(factor(fuente, levels = fuente_order),
              desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC"))))
    
    if (nrow(cand_ok) == 0) return(tibble())
    
    picked <- cand_ok |>
      group_by(fuente) |>
      group_modify(function(.x, .y) {
        f <- as.character(.y$fuente[[1]])
        n_take <- as.integer(quotas[[f]] %||% 0L)
        
        .x |>
          arrange(desc(coalesce(fecha, as.POSIXct("1970-01-01", tz="UTC")))) |>
          head(n_take)
      }) |>
      ungroup()
    
    faltan <- as.integer(target_n) - nrow(picked)
    if (faltan > 0) {
      extras <- cand_ok |>
        anti_join(picked, by = "id") |>
        arrange(factor(fuente, levels = fuente_order),
                desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC"))))
      
      if (nrow(extras) > 0) {
        picked <- bind_rows(picked, head(extras, faltan))
      }
    }
    
    picked |>
      arrange(factor(fuente, levels = fuente_order),
              desc(coalesce(fecha, as.POSIXct("1970-01-01", tz = "UTC")))) |>
      head(target_n)
  }
  
  
  process_next_fuente <- function(lookback_days, target_n, verbose) {
    isolate({
      if (!isTRUE(rv$running)) return()
      
      if (isTRUE(rv$cancel)) {
        for (f in rv$fuente_queue) rv$fuente_status[[f]] <- "Cancelado"
        rv$fuente_queue <- character()
        rv$phase <- "idle"
        rv$running <- FALSE
        return()
      }
      
      if (length(rv$fuente_queue) == 0) {
        rv$phase <- "validate"
        
        cand <- build_candidates_for_validation(
          items_acc     = rv$items_acc,
          lookback_days = lookback_days,
          target_n      = target_n,
          fuente_order  = fuente_order,
          buffer        = 8L
        )
        
        if (nrow(cand) == 0) {
          rv$df <- tibble()
          rv$running <- FALSE
          rv$phase <- "idle"
          rv$progress <- 1
          return()
        }
        
        rv$df <- cand
        rv$img_queue <- unique(cand$img)
        rv$progress <- 0.7
        
        later::later(function() process_next_img(), 0.05)
        return()
      }
      
      
      f <- rv$fuente_queue[[1]]
      rv$fuente_queue <- rv$fuente_queue[-1]
      rv$fuente_status[[f]] <- "Procesando"
      
      cfg <- sources_cfg[sources_cfg$fuente == f, , drop = FALSE]
      
      res <- tryCatch({
        links <- extract_links(
          list_url      = cfg$list_url[1],
          must_contain  = cfg$must_contain[1],
          exclude_exact = cfg$exclude_exact[1] %||% NULL
        )
        
        links <- head(links, 60)
        if (isTRUE(verbose)) message(sprintf("[%s] links candidatos: %s", f, length(links)))
        
        items <- purrr::map(links, ~ read_cartoon_from_url(f, .x)) |>
          purrr::compact() |>
          dplyr::bind_rows()
        
        if (isTRUE(verbose)) message(sprintf("[%s] items leídos: %s", f, nrow(items)))
        items
      }, error = function(e) {
        if (isTRUE(verbose)) message(sprintf("[%s] ERROR: %s", f, e$message))
        NULL
      })
      
      if (is.null(res) || !is.data.frame(res)) {
        rv$fuente_status[[f]] <- "Error"
        rv$fuente_counts[[f]] <- 0L
      } else {
        rv$items_acc <- bind_rows(rv$items_acc, res)
        rv$fuente_status[[f]] <- "OK"
        rv$fuente_counts[[f]] <- nrow(res)
      }
      
      total_fuentes <- length(fuentes)
      done_fuentes <- sum(unlist(rv$fuente_status) %in% c("OK", "Error", "Cancelado"))
      rv$progress <- 0.7 * (done_fuentes / max(1, total_fuentes))
      
      later::later(function() process_next_fuente(lookback_days, target_n, verbose), 0.05)
    })
  }
  
  process_next_img <- function() {
    isolate({
      if (!isTRUE(rv$running)) return()
      
      if (isTRUE(rv$cancel)) {
        rv$phase <- "idle"
        rv$running <- FALSE
        return()
      }
      
      if (length(rv$img_queue) == 0) {
        
        target_n <- as.integer(input$n %||% 20)
        if (is.na(target_n) || target_n < 1) target_n <- 20
        
        df_final <- final_select_by_quota(
          cand         = rv$df,
          target_n     = target_n,
          fuente_order = fuente_order,
          img_ok_map   = rv$img_ok_map
        )
        
        rv$df <- df_final
        rv$phase <- "idle"
        rv$progress <- 1
        rv$running <- FALSE
        return()
      }
      
      img <- rv$img_queue[[1]]
      rv$img_queue <- rv$img_queue[-1]
      
      ok <- tryCatch(img_reachable(img), error = function(e) FALSE)
      rv$img_ok_map[[img]] <- ok
      
      total_imgs <- nrow(rv$df)
      done_imgs  <- length(rv$img_ok_map)
      rv$progress <- 0.7 + 0.3 * (done_imgs / max(1, total_imgs))
      
      later::later(function() process_next_img(), 0.01)
    })
  }
  
  # =========================================================
  # Botón Actualizar (iniciar o cancelar)
  # =========================================================
  observeEvent(input$btn_fetch, {
    
    if (isTRUE(rv$running)) {
      rv$cancel <- TRUE
      showNotification("Cancelación solicitada. Deteniendo procesamiento…", type = "warning", duration = 6)
      return()
    }
    
    reset_run_state()
    
    rv$running <- TRUE
    rv$phase <- "sources"
    rv$df <- tibble()
    
    lookback_days <- as.integer(input$lookback %||% 1)
    if (is.na(lookback_days) || lookback_days < 0) lookback_days <- 0
    
    target_n <- as.integer(input$n %||% 20)
    if (is.na(target_n) || target_n < 1) target_n <- 20
    
    rv$fuente_queue <- fuentes
    
    later::later(function() process_next_fuente(
      lookback_days = lookback_days,
      target_n      = target_n,
      verbose       = isTRUE(input$verbose)
    ), 0.05)
    
  }, ignoreInit = TRUE)
  
  # =========================================================
  # Tabla
  # =========================================================
  output$tbl <- renderDT({
    df <- rv$df
    if (is.null(df) || !is.data.frame(df) || nrow(df) == 0) {
      return(datatable(tibble(Mensaje = "Da clic en 'Actualizar' para cargar cartones.")))
    }
    
    df2 <- df |>
      mutate(
        mini = sprintf("<img src='%s' style='height:90px;'/>", img),
        link = sprintf("<a href='%s' target='_blank' rel='noopener noreferrer'>Abrir</a>", url),
        fecha = ifelse(is.na(fecha), "N/D", format(fecha, "%Y-%m-%d %H:%M"))
      ) |>
      select(mini, fuente, titulo, fecha, link)
    
    datatable(
      df2,
      escape = FALSE,
      rownames = FALSE,
      selection = list(mode = "multiple", target = "row"),
      options = list(pageLength = 10, autoWidth = TRUE)
    )
  }, server = FALSE)
  
  # =========================================================
  # Eliminar filas seleccionadas
  # =========================================================
  observeEvent(input$btn_delete, {
    df <- rv$df
    sel <- input$tbl_rows_selected
    
    if (is.null(df) || !is.data.frame(df) || nrow(df) == 0) {
      showNotification("No hay datos para eliminar.", type = "warning", duration = 6)
      return()
    }
    if (is.null(sel) || length(sel) == 0) {
      showNotification("No hay filas seleccionadas para eliminar.", type = "warning", duration = 6)
      return()
    }
    
    rv$df <- df[-sel, , drop = FALSE]
    showNotification(sprintf("Eliminadas %s fila(s).", length(sel)), type = "message", duration = 6)
  })
  
  output$note <- renderUI({
    df <- rv$df
    if (is.null(df) || !is.data.frame(df) || nrow(df) == 0) return(NULL)
    tagList(
      p(strong("Tip:"), "Selecciona 1 o más filas y da clic en “Eliminar seleccionados”."),
      p(strong("Exportación:"), "El PDF incluirá únicamente los cartones restantes (no eliminados)."),
      p(strong("Nota legal/uso justo:"), "se muestran cartones con atribución y liga a la fuente. Revisa Términos de cada sitio.")
    )
  })
  
  # =========================================================
  # Exportar PDF
  # =========================================================
  output$pdf <- downloadHandler(
    filename = function() sprintf("cartones_%s.pdf", format(Sys.Date(), "%Y%m%d")),
    content = function(file) {
      
      # FIX: Forzar la ruta de Google Chrome en macOS
      Sys.setenv(PAGEDOWN_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
      
      df <- rv$df
      
      if (isTRUE(rv$running)) {
        showNotification("Espera a que termine el procesamiento antes de exportar.", type = "warning", duration = 8)
        stop("Procesamiento en curso.")
      }
      
      if (is.null(df) || !is.data.frame(df) || nrow(df) == 0) {
        showNotification(
          "No hay cartones para exportar. Da clic en 'Actualizar' y/o no elimines todos.",
          type = "warning",
          duration = 8
        )
        stop("No hay cartones para exportar.")
      }
      
      df_export <- df
      if ("img_ok" %in% names(df_export)) {
        df_export <- df_export[df_export$img_ok %in% TRUE, , drop = FALSE]
      }
      df_export <- df_export[!is.na(df_export$img) & nzchar(df_export$img), , drop = FALSE]
      
      if (nrow(df_export) == 0) {
        showNotification(
          "No hay cartones con imagen válida para exportar (bloqueo/403/hotlink).",
          type = "error",
          duration = 10
        )
        stop("Sin imágenes válidas para PDF.")
      }
      
      tryCatch({
        render_pdf(df_export, file)
      }, error = function(e) {
        showNotification(paste("Error al exportar PDF:", e$message), type = "error", duration = 12)
        stop(e)
      })
    }
  )
}

shinyApp(ui, server)