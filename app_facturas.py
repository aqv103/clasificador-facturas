# app_facturas.py
import re
import pdfplumber
from io import BytesIO
# --- Helpers para PDFs -------------------------------------------------
import re
import pdfplumber

# Convierte números con coma o punto a float (e.g. "1.234,56" -> 1234.56)
def _parse_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    s = str(raw).strip().replace(" ", "")
    # normaliza separadores: quita miles y deja '.' como decimal
    if "," in s and "." in s:
        # "1.234,56" -> "1234.56"
        s = s.replace(".", "").replace(",", ".")
    else:
        # "1,23" -> "1.23"    "1234" -> "1234"
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

# Detecta si el texto sugiere "pagada" o "no pagada"
def _infer_estado_from_text(txt_lower: str) -> str | None:
    pagadas = ["pagada", "pagado", "cobrada", "cobrado", "paid"]
    impagas = ["no pagada", "no pagado", "no cobrada", "no cobrado",
               "impaga", "pendiente", "vencida", "atrasada", "unpaid"]
    # chequea primero frases con "no ..."
    for w in impagas:
        if w in txt_lower:
            return "No pagada"
    for w in pagadas:
        if w in txt_lower:
            return "Pagada"
    return None

# Extrae campos básicos de un PDF de factura (1 factura por PDF)
def extract_invoice_from_pdf(fileobj) -> dict:
    with pdfplumber.open(fileobj) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    txt = full_text
    txt_lower = txt.lower()

    # Nº de factura (patrón flexible)
    m_fact = re.search(r"(?:factura(?:\s*n[ºo]\.?|\s*no\.?)?\s*[:\-]?\s*)([a-z0-9\-\/\.]+)",
                       txt_lower, re.IGNORECASE)
    factura = m_fact.group(1).strip().upper() if m_fact else None

    # Cliente (línea tras "Cliente:" o "Razón social:")
    m_cli = re.search(r"(?:cliente|raz[oó]n\s*social)\s*[:\-]\s*(.+)", txt, re.IGNORECASE)
    cliente = m_cli.group(1).strip() if m_cli else None
    if cliente:
        cliente = cliente.splitlines()[0].strip()

    # Estado (intenta "Estado: X"; si no, infiere por palabras)
    m_estado = re.search(r"(?:estado|situaci[oó]n|pago)\s*[:\-]\s*([^\n\r]+)", txt, re.IGNORECASE)
    estado_raw = m_estado.group(1).strip() if m_estado else None
    if estado_raw:
        inf = _infer_estado_from_text(estado_raw.lower())
        estado = inf if inf else estado_raw
    else:
        estado = _infer_estado_from_text(txt_lower) or "Desconocido"

    # Importe (Total/Importe)
    m_total = re.search(r"(?:total(?:\s*a\s*pagar)?|importe)\s*[:\-]?\s*([€$]?\s*[0-9\.\,]+)",
                        txt, re.IGNORECASE)
    importe = _parse_amount(m_total.group(1)) if m_total else None

    # Valores por defecto si faltan
    if not factura:
        factura = "SIN_NUMERO"
    if not cliente:
        cliente = "DESCONOCIDO"
    if importe is None:
        importe = 0.0

    return {
        "Factura": factura,
        "Cliente": cliente,
        "Estado": estado,
        "Importe": importe,
        "Fuente": "PDF",
    }


import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Clasificador de Facturas", page_icon="💸", layout="wide")

# Título y descripción
st.title("💸 Clasificador de Facturas Cobradas y No Cobradas")
st.write(
    "Esta aplicación te permite cargar un archivo de facturas (CSV o Excel) y clasificarlas "
    "automáticamente en **cobradas** y **no cobradas**. Solo necesitas que el archivo tenga alguna "
    "columna que indique el estado del pago (por ejemplo, *Estado*, *Pagada*, *Cobrado*, etc.)."
)

# 1) Subida de archivo
archivo = st.file_uploader("📤 Sube tu archivo de facturas", type=["csv", "xlsx"])

# Si no hay archivo, mostramos info y salimos (así evitamos NameError)
if archivo is None:
    st.info("Sube un archivo CSV o Excel para comenzar.")
    st.stop()

# 2) Leer archivo
try:
    if archivo.name.lower().endswith(".csv"):
        df = pd.read_csv(archivo, encoding="utf-8", sep=None, engine="python")
    else:
        df = pd.read_excel(archivo)
except Exception as e:
    st.error(f"❌ Error al leer el archivo: {e}")
    st.stop()

# Vista previa
st.subheader("📋 Vista previa de los datos")
st.dataframe(df.head())

if df.empty:
    st.warning("El archivo está vacío.")
    st.stop()

# 3) Detectar posibles columnas relacionadas con el estado de pago
candidatas = [c for c in df.columns if any(x in c.lower() for x in ["estado", "pag", "cob", "paid", "status"])]
if not candidatas:
    st.error(
        "⚠️ No se detectó ninguna columna relacionada con el pago. "
        "Asegúrate de tener una columna llamada por ejemplo 'Estado', 'Pagada' o 'Cobrado'."
    )
    st.stop()

columna_estado = st.selectbox("🧭 Selecciona la columna que indica si la factura está pagada:", candidatas)

# 4) Normalizar valores y clasificar
serie = df[columna_estado].astype(str).str.lower().str.strip()

# Palabras que indican cobro o no cobro
valores_pagada = {"pagada", "cobrada", "sí", "si", "true", "1", "y", "yes", "paga", "paid"}
valores_no_pagada = {"no", "pendiente", "falta", "impaga", "no pagada", "sin"}

# Clasificación más robusta
cobradas = df[serie.apply(lambda x: any(p in x for p in valores_pagada) and not any(n in x for n in valores_no_pagada))].copy()
no_cobradas = df[~serie.apply(lambda x: any(p in x for p in valores_pagada) and not any(n in x for n in valores_no_pagada))].copy()

# 5) Resumen
st.subheader("📊 Resumen general")
total = len(df)
total_cobradas = len(cobradas)
total_no_cobradas = len(no_cobradas)

c1, c2, c3 = st.columns(3)
c1.metric("Total de facturas", total)
c2.metric("Cobradas", total_cobradas)
c3.metric("No cobradas", total_no_cobradas)

st.bar_chart(
    pd.DataFrame(
        {"Cobradas": [total_cobradas], "No cobradas": [total_no_cobradas]}
    ).T.rename(columns={0: "Cantidad"})
)

# 6) Mostrar tablas
st.subheader("✅ Facturas cobradas")
st.dataframe(cobradas, use_container_width=True)

st.subheader("⛔ Facturas NO cobradas")
st.dataframe(no_cobradas, use_container_width=True)

# 7) Exportar resultados
st.subheader("💾 Exportar resultados")

# CSV cobradas
if not cobradas.empty:
    st.download_button(
        "⬇️ Descargar cobradas (CSV)",
        cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_cobradas.csv",
        mime="text/csv",
    )

# CSV no cobradas
if not no_cobradas.empty:
    st.download_button(
        "⬇️ Descargar no cobradas (CSV)",
        no_cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_no_cobradas.csv",
        mime="text/csv",
    )

# Excel con ambas hojas (opcional)
if not cobradas.empty or not no_cobradas.empty:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if not cobradas.empty:
            cobradas.to_excel(writer, index=False, sheet_name="Cobradas")
        if not no_cobradas.empty:
            no_cobradas.to_excel(writer, index=False, sheet_name="No cobradas")
    buffer.seek(0)
    st.download_button(
        "⬇️ Descargar Excel (2 hojas)",
        data=buffer,
        file_name="clasificacion_facturas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )




