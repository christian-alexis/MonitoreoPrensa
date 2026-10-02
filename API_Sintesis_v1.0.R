# BLOQUE 1: CONFIGURACIÓN Y FUNCIONES AUXILIARES
library(shiny)
library(bslib)
library(dplyr)
library(httr)
library(jsonlite)
library(stringr)
library(DT)
library(shinyjs)
library(xml2)
library(htmltools)
library(pagedown)
library(lubridate)

# Operador auxiliar robusto (soporta vectores y NA)
`%||%` <- function(a, b) {
  if (is.null(a) || length(a) == 0) return(b)
  a1 <- a[[1]]
  if (is.na(a1)) return(b)
  if (is.character(a1) && !nzchar(a1)) return(b)
  a1
}

# Categorías de palabras clave predefinidas
CATEGORIAS_KEYWORDS <- list(
  "Núcleo presupuestario" = c("presupuesto", "gasto", "egresos", "subejercicio"),
  "Planeación y política pública" = c("políticas", "programas", "planeación", "desarrollo",
                                       "evaluación", "indicadores", "resultados", "impacto",
                                       "eficiencia", "transparencia"),
  "Ejes transversales / enfoque social" = c("transversalidad", "género", "inclusión", "igualdad",
                                              "derechos", "sostenibilidad", "ambiental", "social",
                                              "bienestar", "equidad"),
  "Control y rendición de cuentas" = c("auditoría", "fiscalización", "ASF", "control",
                                        "seguimiento", "monitoreo", "cumplimiento"),
  "Contexto económico" = c("inflación", "crecimiento", "PIB", "inversión", "empleo", "subsidios")
)

# Configuración de fuentes confiables
FUENTES_CONFIABLES <- c(
  "El Universal", "El Financiero", "Reforma", "La Jornada",
  "Milenio", "Forbes México", "Animal Político", "Expansión",
  "BBC Mundo", "CNN en Español", "The New York Times", "Washington Post",
  "Aristegui Noticias", "Sin Embargo", "El País", "El País México", "Excélsior",
  "MVS Noticias", "La Crónica de Hoy"
)

# Vectorizada: devuelve un lógico por cada fuente
es_fuente_confiable <- function(fuente) {
  if (is.null(fuente)) return(logical(0))
  fuente <- as.character(fuente)
  patron <- regex(paste(FUENTES_CONFIABLES, collapse = "|"), ignore_case = TRUE)
  str_detect(fuente, patron)
}

# Parseo de fecha (corrige desfase de 1 día):
# - Si la cadena tiene hora, se interpreta en UTC y se convierte a America/Mexico_City.
# - Si la cadena es SOLO fecha (sin hora), se interpreta directamente en America/Mexico_City, sin conversión adicional.
parsear_fecha <- function(fecha, return_date = FALSE) {
  if (is.null(fecha) || is.na(fecha) || !nzchar(fecha)) {
    if (return_date) return(Sys.Date())
    return(format(Sys.Date(), "%d/%m/%Y"))
  }
  fecha_clean <- trimws(gsub(" [+-][0-9]{4}$| GMT$| UTC$| [A-Z]{3,}$", "", fecha))
  tiene_hora <- grepl("\\d{1,2}:\\d{2}", fecha_clean) || grepl("T\\d{2}:\\d{2}", fecha_clean)
  
  orders <- c(
    "a d b Y H:M:S z","a d b Y H:M:S","a d b Y H:M z","a d b Y H:M",
    "Y-m-d H:M:S z","Y-m-d H:M:S","Y-m-d H:M z","Y-m-d H:M",
    "Y-m-d","d/m/Y","m/d/Y","d-m-Y","m-d-Y","a d b Y","d b Y H:M:S","d b Y"
  )
  
  parsed <- parse_date_time(
    fecha_clean,
    orders = orders,
    tz = if (tiene_hora) "UTC" else "America/Mexico_City",
    quiet = TRUE
  )
  
  if (is.na(parsed)) {
    formatos_base <- c(
      "%a, %d %b %Y %H:%M:%S %Z","%a, %d %b %Y %H:%M:%S %z","%a, %d %b %Y %H:%M:%S",
      "%Y-%m-%dT%H:%M:%SZ","%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%m/%d/%Y %H:%M:%S",
      "%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%a, %d %b %Y","%d %b %Y"
    )
    for (fmt in formatos_base) {
      parsed_base <- try(
        as.POSIXct(
          fecha_clean,
          format = fmt,
          tz = if (tiene_hora) "UTC" else "America/Mexico_City"
        ),
        silent = TRUE
      )
      if (!inherits(parsed_base, "try-error") && !is.na(parsed_base)) { parsed <- parsed_base; break }
    }
  }
  
  if (!is.na(parsed)) {
    if (tiene_hora) {
      local_time <- with_tz(parsed, "America/Mexico_City")
      if (return_date) as.Date(local_time) else format(local_time, "%d/%m/%Y")
    } else {
      # Fecha sin hora: ya está en MX; no convertir para evitar retroceder un día
      if (return_date) as.Date(parsed) else format(as.Date(parsed), "%d/%m/%Y")
    }
  } else {
    message("No se pudo parsear la fecha: ", fecha)
    if (return_date) Sys.Date() else format(Sys.Date(), "%d/%m/%Y")
  }
}

# ---- Decodificar URL real desde ID base64 de Google News RSS ----
decodificar_url_gn <- function(url_gn) {
  if (is.null(url_gn) || is.na(url_gn) || !nzchar(url_gn)) return(url_gn)
  if (!str_detect(url_gn, "news\\.google\\.com")) return(url_gn)
  tryCatch({
    m <- str_match(url_gn, "/articles/([^?/]+)")
    if (is.na(m[1, 1])) return(url_gn)
    article_id <- m[1, 2]
    # base64url → base64 estándar con padding
    b64 <- gsub("-", "+", gsub("_", "/", article_id))
    padding <- (4 - nchar(b64) %% 4) %% 4
    b64 <- paste0(b64, strrep("=", padding))
    # Decodificar y buscar la URL dentro de los bytes
    decoded_raw <- jsonlite::base64_dec(b64)
    decoded_str <- rawToChar(decoded_raw, multiple = FALSE)
    url_real <- str_extract(decoded_str, "https?://[^\\x00-\\x1f\\s]+")
    if (!is.na(url_real) && nzchar(url_real)) url_real else url_gn
  }, error = function(e) url_gn)
}

# ---- Utilidades: fecha desde URL y formateo dd/mm/YYYY ----
extraer_fecha_de_url <- function(url) {
  if (is.null(url) || is.na(url) || !nzchar(url)) return(NA)
  m <- stringr::str_match(url, "(\\d{4})[/-](\\d{2})[/-](\\d{2})")
  if (is.na(m[1,1])) return(NA)
  suppressWarnings(as.Date(sprintf("%s-%s-%s", m[1,2], m[1,3], m[1,4])))
}
formatear_fecha_dmy <- function(d) {
  if (length(d) == 0 || all(is.na(d))) return(format(Sys.Date(), "%d/%m/%Y"))
  format(as.Date(d), "%d/%m/%Y")
}

# ==============================
# BÚSQUEDA "ESTILO GOOGLE NOTICIAS" (últimos 2 días)
# ==============================
obtener_noticias_confiables <- function(query = "Presupuesto", solo_confiables = TRUE) {
  tryCatch({
    solo_confiables <- isTRUE(solo_confiables[1])
    
    # Construir query tipo (kw1) OR ("kw con espacios") + ventana 2 días
    palabras <- str_split(query, ",\\s*")[[1]]
    palabras <- palabras[nzchar(palabras)]
    if (length(palabras) == 0) palabras <- c(query)
    wrap_kw <- function(k) { k <- trimws(k); if (str_detect(k, "\\s")) sprintf('"%s"', k) else k }
    q_string <- paste(sapply(palabras, wrap_kw), collapse = " OR ")
    q_final <- paste(q_string, "when:2d")
    
    # RSS de Google News MX
    resp <- GET(
      url = "https://news.google.com/rss/search",
      query = list(q = q_final, hl = "es-419", gl = "MX", ceid = "MX:es"),
      add_headers(
        `User-Agent` = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        `Accept` = "application/xml"
      ),
      timeout(30)
    )
    if (status_code(resp) != 200) { message("Error HTTP en Google News RSS: ", status_code(resp)); return(NULL) }
    doc <- try(read_xml(content(resp, "text", encoding = "UTF-8")), silent = TRUE)
    if (inherits(doc, "try-error")) return(NULL)
    
    items <- xml_find_all(doc, "//item")
    if (length(items) == 0) return(NULL)
    
    df <- lapply(items, function(item) {
      titulo_raw <- xml_text(xml_find_first(item, "title")) %||% ""
      enlace_gn <- xml_text(xml_find_first(item, "link")) %||% ""
      fecha <- xml_text(xml_find_first(item, "pubDate")) %||% ""
      fuente <- xml_text(xml_find_first(item, "source")) %||% ""
      # Eliminar " - Nombre Fuente" al final del título (patrón de Google News RSS)
      titulo <- if (nzchar(fuente)) {
        suffix <- paste0(" - ", fuente)
        if (endsWith(titulo_raw, suffix)) {
          str_trim(substr(titulo_raw, 1, nchar(titulo_raw) - nchar(suffix)))
        } else {
          titulo_raw
        }
      } else {
        titulo_raw
      }
      desc_raw <- xml_text(xml_find_first(item, "description")) %||% ""
      
      # Intentar obtener enlace original desde description
      enlace_final <- enlace_gn
      if (nzchar(desc_raw[1])) {
        h <- try(read_html(paste0("<div>", desc_raw, "</div>")), silent = TRUE)
        if (!inherits(h, "try-error")) {
          hrefs <- xml_attr(xml_find_all(h, ".//a"), "href")
          hrefs <- hrefs[!is.na(hrefs)]
          hrefs_ext <- hrefs[!str_detect(hrefs, "news\\.google\\.com")]
          if (length(hrefs_ext) >= 1) enlace_final <- hrefs_ext[1]
        }
      }
      # Si sigue siendo URL de Google News, decodificar el ID base64
      if (str_detect(enlace_final, "news\\.google\\.com")) {
        enlace_final <- decodificar_url_gn(enlace_final)
      }
      
      data.frame(
        title = titulo,
        url = enlace_final,
        publishedAt = fecha,
        source_name = fuente,
        confiable = isTRUE(es_fuente_confiable(fuente)[1]),
        stringsAsFactors = FALSE
      )
    })
    df <- do.call(rbind, df)
    if (is.null(df) || nrow(df) == 0) return(NULL)
    
    if (solo_confiables) df <- df[isTRUE(df$confiable) | df$confiable %in% TRUE, , drop = FALSE]
    if (nrow(df) == 0) return(NULL)
    
    # Fecha correcta: priorizar fecha del URL; si no hay, usar pubDate (con regla de hora)
    fecha_url <- sapply(df$url, extraer_fecha_de_url)
    fecha_pub <- as.Date(sapply(df$publishedAt, parsear_fecha, return_date = TRUE))
    df$fecha_procesada <- fecha_pub
    idx_url <- !is.na(fecha_url)
    df$fecha_procesada[idx_url] <- fecha_url[idx_url]
    
    # Filtrar últimos 2 días (respecto a CDMX)
    hoy <- as.Date(lubridate::with_tz(Sys.time(), "America/Mexico_City"))
    df <- df[df$fecha_procesada %in% seq(hoy - 2, hoy, by = "day"), , drop = FALSE]
    
    df <- df[!duplicated(df[, c("title", "url")]), ]
    df <- df[order(df$fecha_procesada, decreasing = TRUE), ]
    df
  }, error = function(e) { message("Error al obtener noticias (Google News): ", e$message); NULL })
}

# BLOQUE 2: INTERFAZ DE USUARIO
ui <- page_sidebar(
  theme = bs_theme(bootswatch = "flatly"),
  useShinyjs(),
  
  div(
    style = "display: flex; align-items: center; justify-content: space-between; background-color: #10312B; color: #BC955C; padding: 15px; width: 100%;",
    img(src = "https://i.ibb.co/RTC79g2q/HORIZONTAL-HACIENDA-BLANCO.png",
        height = "100px", alt = "Logo"),
    div(
      style = "text-align: right;",
      h4("UNIDAD DE POLÍTICA Y ESTRATEGIA PARA RESULTADOS", style = "margin: 0;"),
      h6("SÍNTESIS DE PRENSA", style = "margin: 5px 0;")
    )
  ),
  
  sidebar = sidebar(
    title = "Filtros Avanzados",
    checkboxGroupInput(
      "categorias_sel",
      "Categorías de búsqueda:",
      choices = names(CATEGORIAS_KEYWORDS),
      selected = names(CATEGORIAS_KEYWORDS)
    ),
    numericInput("num_noticias", "Número de noticias:", value = 10, min = 1, max = 100),
    checkboxInput("solo_confiables", "Solo fuentes confiables", value = TRUE),
    actionButton("buscar", "Buscar noticias", class = "btn-primary w-100"),
    hr(),
    actionButton("nuevo_registro", "Agregar registro manual", class = "btn-info w-100"),
    hr(),
    div(
      h6("Fuentes confiables:"),
      tags$small(HTML(paste(FUENTES_CONFIABLES, collapse = "<br>")))
    )
  ),
  
  card(
    card_header(
      class = "d-flex justify-content-between align-items-center",
      "Noticias relevantes y verificadas",
      div(
        actionButton("eliminar", "Eliminar seleccionadas", class = "btn-danger btn-sm", disabled = TRUE),
        downloadButton("exportar_pdf", "Exportar PDF", class = "btn-success btn-sm ml-2")
      )
    ),
    DTOutput("tabla_noticias"),
    card_footer("Actualizado: ", textOutput("fecha_actualizacion", inline = TRUE))
  ),
  
  div(
    style = "background-color: #10312B; color: #BC955C; padding: 10px; text-align: center; font-size: 12px; margin-top: 20px;",
    div("© 2026 SHCP - Coordinación de Fortalecimiento Institucional"),
    div("claudia_segovia@shcp.gob.mx | yazid_guzman@shcp.gob.mx")
  )
)

# BLOQUE 3: LÓGICA DEL SERVIDOR
server <- function(input, output, session) {
  edit_row_index <- reactiveVal(NULL)
  
  initial_df <- data.frame(
    ID = integer(0),
    Seleccionado = logical(0),
    Orden = integer(0),
    Titulo = character(0),
    Resumen_Ejecutivo = character(0),
    Fuente = character(0),
    Categoria = character(0),
    Verificacion = character(0),
    Enfoque = character(0),
    Fecha = character(0),
    Enlace = character(0),
    Acciones = character(0),
    Fecha_Ordenable = as.Date(character(0)),
    stringsAsFactors = FALSE
  )
  names(initial_df) <- c("ID", "Seleccionado", "Orden", "Título", "Resumen Ejecutivo",
                         "Fuente", "Categoría", "Verificación", "Enfoque", "Fecha", "Enlace", "Acciones", "Fecha_Ordenable")
  noticias_data <- reactiveVal(initial_df)
  
  observeEvent(input$buscar, {
    withProgress(message = 'Buscando noticias...', {
      req(input$categorias_sel)
      noticias_data(initial_df)
      tryCatch({
        # Buscar por categoría para evitar queries demasiado largas
        cats_sel <- input$categorias_sel
        n_cats <- length(cats_sel)
        resultados_lista <- lapply(seq_along(cats_sel), function(i) {
          setProgress(value = i / n_cats,
                      message = paste0("Buscando categoría ", i, " de ", n_cats, "..."))
          cat_nombre <- cats_sel[i]
          keywords_cat <- CATEGORIAS_KEYWORDS[[cat_nombre]]
          query_cat <- paste(keywords_cat, collapse = ", ")
          res <- obtener_noticias_confiables(query_cat, solo_confiables = input$solo_confiables)
          if (!is.null(res)) res$categoria <- cat_nombre
          res
        })
        resultados_lista <- Filter(Negate(is.null), resultados_lista)
        df <- if (length(resultados_lista) > 0) {
          df_combinado <- do.call(rbind, resultados_lista)
          df_combinado[!duplicated(df_combinado[, c("title", "url")]), ]
        } else { NULL }
        if (!is.null(df) && nrow(df) > 0) {
          df$fecha_procesada <- as.Date(df$fecha_procesada)
          df <- df %>% arrange(desc(fecha_procesada))
          num_items <- min(nrow(df), input$num_noticias)
          
          # Fecha mostrada y fecha ordenable (con la regla URL>pubDate)
          fechas_procesadas <- formatear_fecha_dmy(df$fecha_procesada[1:num_items])
          fechas_ordenables <- as.Date(df$fecha_procesada[1:num_items])
          
          # Verificación por fila
          verif_vec <- ifelse(es_fuente_confiable(df$source_name[1:num_items]),
                              '<span class="badge bg-success">Verificada</span>',
                              '<span class="badge bg-warning">No verificada</span>')
          
          resultado <- data.frame(
            ID = 1:num_items,
            Seleccionado = FALSE,
            Orden = 1:num_items,
            Titulo = df$title[1:num_items],
            Resumen_Ejecutivo = rep("Resumen no disponible", num_items),
            Fuente = df$source_name[1:num_items],
            Categoria = df$categoria[1:num_items],
            Verificacion = verif_vec,
            Enfoque = rep("Positivo", num_items),
            Fecha = fechas_procesadas,
            Enlace = paste0('<a href="', df$url[1:num_items],
                            '" target="_blank" class="btn btn-sm btn-outline-primary">Ver</a>'),
            Acciones = rep('<button class="btn btn-sm btn-warning">Editar</button>', num_items),
            Fecha_Ordenable = fechas_ordenables,
            stringsAsFactors = FALSE
          )
          colnames(resultado) <- c("ID", "Seleccionado", "Orden", "Título", "Resumen Ejecutivo",
                                   "Fuente", "Categoría", "Verificación", "Enfoque", "Fecha", "Enlace", "Acciones", "Fecha_Ordenable")
          noticias_data(resultado)
          showNotification(
            paste0("Se encontraron ", num_items, " noticias en ", length(cats_sel), " categoría(s)"),
            type = "message"
          )
        } else {
          showNotification("No se encontraron noticias para las fechas especificadas. Intente ajustar los filtros.", type = "warning")
        }
      }, error = function(e) {
        showNotification(paste("Error:", e$message), type = "error")
      })
    })
  })
  
  # Actualiza orden
  observeEvent(input$tabla_noticias_cell_edited, {
    info <- input$tabla_noticias_cell_edited
    if (!is.null(info) && identical(info$col, 2L)) {
      df <- noticias_data()
      nuevo_valor <- suppressWarnings(as.integer(info$value[1]))
      if (!is.na(nuevo_valor) && nuevo_valor > 0) {
        df[info$row + 1, "Orden"] <- nuevo_valor
        df <- df %>% arrange(Orden)
        df$ID <- seq_len(nrow(df))
        noticias_data(df)
      } else {
        showNotification("El valor de orden debe ser un número entero positivo", type = "error")
      }
    }
  })
  
  # Nuevo registro (manual)
  observeEvent(input$nuevo_registro, {
    showModal(modalDialog(
      title = "Agregar Nuevo Registro",
      numericInput("nuevo_orden", "Orden:", value = nrow(noticias_data()) + 1, min = 1),
      textInput("nuevo_titulo", "Título:"),
      textAreaInput("nuevo_resumen", "Resumen Ejecutivo:", rows = 3),
      textInput("nuevo_fuente", "Fuente:"),
      selectInput("nuevo_categoria", "Categoría:",
                  choices = c(names(CATEGORIAS_KEYWORDS), "Otra")),
      selectInput("nuevo_verificacion", "Verificación:",
                  choices = c("Verificada", "No verificada")),
      selectInput("nuevo_enfoque", "Enfoque:", 
                  choices = c("Positivo", "Neutral", "Negativo")),
      dateInput("nuevo_fecha", "Fecha:", value = Sys.Date()),
      textInput("nuevo_enlace", "Enlace:", placeholder = "https://..."),
      footer = tagList(
        modalButton("Cancelar"),
        actionButton("guardar_nuevo", "Guardar", class = "btn-primary")
      )
    ))
  })
  
  observeEvent(input$guardar_nuevo, {
    req(input$nuevo_titulo)
    df_actual <- noticias_data()
    nuevo_id <- if(nrow(df_actual) > 0) max(df_actual$ID) + 1 else 1
    fecha_date <- as.Date(input$nuevo_fecha %||% Sys.Date())
    nueva_fila <- data.frame(
      ID = nuevo_id,
      Seleccionado = FALSE,
      Orden = as.integer(input$nuevo_orden %||% nuevo_id),
      Titulo = input$nuevo_titulo,
      Resumen_Ejecutivo = input$nuevo_resumen %||% "",
      Fuente = input$nuevo_fuente %||% "",
      Categoria = input$nuevo_categoria %||% "Otra",
      Verificacion = ifelse(identical(input$nuevo_verificacion, "Verificada"),
                            '<span class="badge bg-success">Verificada</span>',
                            '<span class="badge bg-warning">No verificada</span>'),
      Enfoque = input$nuevo_enfoque %||% "Positivo",
      Fecha = format(fecha_date, "%d/%m/%Y"),
      Enlace = if(!is.null(input$nuevo_enlace) && input$nuevo_enlace != "") {
        paste0('<a href="', input$nuevo_enlace,
               '" target="_blank" class="btn btn-sm btn-outline-primary">Ver</a>')
      } else { "" },
      Acciones = '<button class="btn btn-sm btn-warning">Editar</button>',
      Fecha_Ordenable = fecha_date,
      stringsAsFactors = FALSE
    )
    colnames(nueva_fila) <- c("ID", "Seleccionado", "Orden", "Título", "Resumen Ejecutivo",
                              "Fuente", "Categoría", "Verificación", "Enfoque", "Fecha", "Enlace", "Acciones", "Fecha_Ordenable")
    df_actual <- rbind(df_actual, nueva_fila) %>% arrange(Orden)
    df_actual$ID <- seq_len(nrow(df_actual))
    noticias_data(df_actual)
    removeModal()
    showNotification("Registro agregado exitosamente", type = "message")
  })
  
  # Editar registro
  observeEvent(input$tabla_noticias_cell_clicked, {
    info <- input$tabla_noticias_cell_clicked
    if (!is.null(info) && !is.null(info$col) && !is.na(info$col) && identical(info$col, 11L)) {
      df <- noticias_data()
      if (nrow(df) > 0 && !is.null(info$row) && !is.na(info$row) && info$row <= nrow(df)) {
        fila <- df[info$row, ]
        edit_row_index(info$row)
        enlace_extraido <- ""
        if (!is.null(fila$Enlace) && !is.na(fila$Enlace[1]) && fila$Enlace[1] != "") {
          match_result <- str_match(fila$Enlace[1], 'href="([^"]+)"')
          if (!is.na(match_result[1,1]) && ncol(match_result) >= 2) enlace_extraido <- match_result[1,2]
        }
        verificacion_actual <- "No verificada"
        if (!is.null(fila$Verificación) && !is.na(fila$Verificación[1])) {
          if (grepl("success", fila$Verificación[1])) verificacion_actual <- "Verificada"
        }
        showModal(modalDialog(
          title = "Editar Registro",
          numericInput("edit_orden", "Orden:", value = fila$Orden %||% 1, min = 1),
          textInput("edit_titulo", "Título:", value = fila$Título %||% ""),
          textAreaInput("edit_resumen", "Resumen Ejecutivo:", 
                        value = fila$`Resumen Ejecutivo` %||% "", rows = 3),
          textInput("edit_fuente", "Fuente:", value = fila$Fuente %||% ""),
          selectInput("edit_categoria", "Categoría:",
                      choices = c(names(CATEGORIAS_KEYWORDS), "Otra"),
                      selected = fila$Categoría %||% "Otra"),
          selectInput("edit_verificacion", "Verificación:",
                      choices = c("Verificada", "No verificada"),
                      selected = verificacion_actual),
          selectInput("edit_enfoque", "Enfoque:", 
                      choices = c("Positivo", "Neutral", "Negativo"),
                      selected = fila$Enfoque %||% "Positivo"),
          dateInput("edit_fecha", "Fecha:", 
                    value = tryCatch({
                      if ("Fecha_Ordenable" %in% names(fila)) as.Date(fila$Fecha_Ordenable) else parsear_fecha(fila$Fecha[1], return_date = TRUE)
                    }, error = function(e) Sys.Date())),
          textInput("edit_enlace", "Enlace:", value = enlace_extraido),
          footer = tagList(
            modalButton("Cancelar"),
            actionButton("guardar_edicion", "Guardar Cambios", class = "btn-primary")
          )
        ))
      }
    }
  })
  
  observeEvent(input$guardar_edicion, {
    idx <- edit_row_index()
    if (!is.null(idx)) {
      df <- noticias_data()
      fecha_edit <- as.Date(input$edit_fecha %||% Sys.Date())
      df[idx, "Orden"] <- as.integer(input$edit_orden %||% idx)
      df[idx, "Título"] <- input$edit_titulo %||% ""
      df[idx, "Resumen Ejecutivo"] <- input$edit_resumen %||% ""
      df[idx, "Fuente"] <- input$edit_fuente %||% ""
      df[idx, "Categoría"] <- input$edit_categoria %||% "Otra"
      df[idx, "Verificación"] <- ifelse(identical(input$edit_verificacion, "Verificada"),
                                        '<span class="badge bg-success">Verificada</span>',
                                        '<span class="badge bg-warning">No verificada</span>')
      df[idx, "Enfoque"] <- input$edit_enfoque %||% "Positivo"
      df[idx, "Fecha"] <- format(fecha_edit, "%d/%m/%Y")
      df[idx, "Fecha_Ordenable"] <- fecha_edit
      df[idx, "Enlace"] <- if(!is.null(input$edit_enlace) && input$edit_enlace != "") {
        paste0('<a href="', input$edit_enlace, 
               '" target="_blank" class="btn btn-sm btn-outline-primary">Ver</a>')
      } else { "" }
      df <- df %>% arrange(Orden)
      df$ID <- seq_len(nrow(df))
      noticias_data(df)
      removeModal()
      edit_row_index(NULL)
      showNotification("Registro actualizado exitosamente", type = "message")
    }
  })
  
  # Eliminar seleccionadas
  observeEvent(input$tabla_noticias_rows_selected, {
    updateActionButton(session, "eliminar", disabled = is.null(input$tabla_noticias_rows_selected))
  })
  observeEvent(input$eliminar, {
    if (!is.null(input$tabla_noticias_rows_selected)) {
      df <- noticias_data()
      df_filtrado <- df[-input$tabla_noticias_rows_selected, ] %>% arrange(Orden)
      df_filtrado$ID <- seq_len(nrow(df_filtrado))
      noticias_data(df_filtrado)
      showNotification("Registros eliminados", type = "message")
    }
  })
  
  # Tabla (no volver a parsear fechas; usar las ya calculadas)
  output$tabla_noticias <- renderDT({
    df <- noticias_data()
    if (nrow(df) > 0) {
      df <- df %>%
        mutate(
          Acciones = '<button class="btn btn-sm btn-warning">Editar Registro</button>'
        ) %>%
        arrange(Orden)
      datatable(
        df,
        escape = FALSE,
        selection = list(mode = 'multiple', target = 'row'),
        rownames = FALSE,
        extensions = c('Buttons'),
        editable = list(target = 'cell', disable = list(columns = c(0,1,3:12))),
        options = list(
          pageLength = input$num_noticias,
          dom = 'Btip',
          language = list(url = '//cdn.datatables.net/plug-ins/1.10.25/i18n/Spanish.json'),
          columnDefs = list(
            list(targets = 0, visible = FALSE),
            list(targets = 1, visible = FALSE),
            list(targets = 2, width = '60px'),
            list(targets = 3, width = '60px'),
            list(targets = which(names(df) == "Resumen Ejecutivo")-1, width = '600px'),
            list(targets = 5, width = '120px'),
            list(targets = 6, width = '150px'),
            list(targets = 7, width = '120px'),
            list(targets = 8, width = '120px'),
            list(targets = 9, width = '120px'),
            list(targets = 10, width = '120px'),
            list(targets = 11, width = '120px'),
            list(targets = which(names(df) == "Fecha_Ordenable")-1, visible = FALSE),
            list(targets = 11, orderable = FALSE)
          ),
          order = list(list(2, 'asc'))
        )
      )
    } else {
      datatable(
        data.frame(Mensaje = "No se encontraron noticias con los criterios actuales"),
        options = list(dom = 't'),
        rownames = FALSE
      )
    }
  }, server = TRUE)
  
  # Timestamp
  output$fecha_actualizacion <- renderText({
    format(Sys.time(), "%d/%m/%Y %H:%M:%S")
  })
  
  # ==========
  # EXPORTAR PDF (usa Fecha_Ordenable para evitar desfases)
  # ==========
  output$exportar_pdf <- downloadHandler(
    filename = function() {
      paste0("sintesis_prensa_", format(Sys.time(), "%Y%m%d_%H%M%S"), ".pdf")
    },
    content = function(file) {
      tryCatch({
        df <- noticias_data()
        if (nrow(df) == 0) {
          showNotification("No hay noticias para exportar", type = "warning")
          return()
        }
        
        # Usar Fecha_Ordenable (Date) para generar la cadena dd/mm/YYYY
        if ("Fecha_Ordenable" %in% names(df)) {
          df$Fecha <- formatear_fecha_dmy(df$Fecha_Ordenable)
        } else {
          # Respaldo: no reprocesar con tz; usar parseo "suave"
          df$Fecha <- sapply(df$Fecha, function(x) formatear_fecha_dmy(parsear_fecha(x, return_date = TRUE)))
        }
        
        export_df <- df %>%
          select(-ID, -Seleccionado, -Acciones, -Verificación, -Orden, -Fecha_Ordenable, -Categoría)
        
        # Crear archivo HTML temporal
        temp_html <- tempfile(fileext = ".html")
        
        # HTML para PDF
        html_content <- paste0('
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                @page { size: A4 landscape; margin: 15mm; }
                body { font-family: Arial, sans-serif; margin: 0; padding: 0; color: #333; font-size: 12px; }
                .header { background-color: #10312B; color: #BC955C; padding: 15px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
                .header-text { text-align: right; }
                .header-text h1 { margin: 0; font-size: 14px; }
                .header-text h2 { margin: 5px 0 0 0; font-size: 12px; }
                .content { padding: 0 10px; }
                h3 { color: #10312B; border-bottom: 2px solid #BC955C; padding-bottom: 5px; font-size: 16px; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; page-break-inside: auto; }
                th { background-color: #10312B; color: #BC955C; text-align: left; padding: 8px; font-size: 11px; font-weight: bold; }
                td { padding: 8px; border-bottom: 1px solid #ddd; font-size: 10px; vertical-align: top; word-wrap: break-word; }
                td.titulo { max-width: 50px; word-wrap: break-word; }
                td.resumen { text-align: justify; line-height: 1.3; max-width: 600px; }
                td.enlace { word-break: break-all; max-width: 150px; text-align: center; }
                td.enlace a { color: #10312B; font-weight: bold; padding: 3px 8px; border: 1px solid #10312B; border-radius: 3px; text-decoration: none; }
                td.enlace a:hover { background-color: #10312B; color: #FFFFFF; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .footer { margin-top: 20px; padding: 10px; background-color: #f5f5f5; font-size: 10px; text-align: center; border-top: 1px solid #ddd; }
                .date-info { text-align: right; font-size: 11px; color: #666; margin-bottom: 15px; }
                .logo-container { margin-right: 20px; }
                .logo-container img { max-height: 100px; width: auto; }
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo-container">
                    <img src="https://i.ibb.co/RTC79g2q/HORIZONTAL-HACIENDA-BLANCO.png" alt="Logo SHCP">
                </div>
                <div class="header-text">
                    <h1>UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS</h1>
                    <h1>COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL</h1>
                    <h2>SÍNTESIS DE PRENSA</h2>
                </div>
            </div>
            <div class="content">
                <h3>Reporte de Noticias Relevantes</h3>
                <div class="date-info">
                    Generado el: ', format(Sys.time(), "%d/%m/%Y %H:%M"), '
                </div>
                
                <table>
                    <thead>
                        <tr>',
                               paste(sapply(names(export_df), function(col) {
                                 paste0('<th>', htmltools::htmlEscape(col), '</th>')
                               }), collapse = ''),
                               '</tr>
                    </thead>
                    <tbody>',
                               paste(sapply(seq_len(nrow(export_df)), function(i) {
                                 paste0('<tr>',
                                        paste(sapply(names(export_df), function(col) {
                                          class_name <- if(col == "Resumen Ejecutivo") "resumen" else if(col == "Enlace") "enlace" else ""
                                          content <- if(col == "Enlace") {
                                            enlace_html <- as.character(export_df[[col]][i])
                                            href <- stringr::str_extract(enlace_html, '(?<=href=")[^"]+')
                                            if(is.na(href) || href == "#" || href == "") {
                                              "No disponible"
                                            } else {
                                              paste0('<a href="', href, '" target="_blank">IR</a>')
                                            }
                                          } else {
                                            htmltools::htmlEscape(as.character(export_df[[col]][i]))
                                          }
                                          paste0('<td class="', class_name, '">', content, '</td>')
                                        }), collapse = ''),
                                        '</tr>')
                               }), collapse = ''),
                               '</tbody>
                </table>
            </div>
            
            <div class="footer">
                <div>© 2026 SHCP - Coordinación de Fortalecimiento Institucional</div>
                <div style="margin-top: 5px;">
                    Contacto: claudia_segovia@shcp.gob.mx | yazid_guzman@shcp.gob.mx
                </div>
            </div>
        </body>
        </html>')
        
        writeLines(html_content, temp_html, useBytes = TRUE)
        
        pagedown::chrome_print(
          input = temp_html, 
          output = file,
          extra_args = c(
            "--no-sandbox", 
            "--disable-dev-shm-usage", 
            "--disable-gpu",
            "--enable-local-file-accesses",
            "--allow-file-access-from-files"
          ),
          timeout = 60
        )
        
        unlink(temp_html)
        
      }, error = function(e) {
        showNotification(paste("Error al generar PDF:", e$message), type = "error")
        cat("Error en la generación del PDF", file = file)
      })
    }
  )
  
  # Auto-búsqueda al cargar
  observeEvent(input$query, {
    if (!is.null(input$query) && !is.na(input$query) && input$query != "") {
      if (nrow(noticias_data()) == 0) {
        click("buscar")
      }
    }
  }, once = TRUE)
}

# Ejecutar la aplicación
shinyApp(ui = ui, server = server)
