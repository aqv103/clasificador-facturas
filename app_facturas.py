# app_facturas.py
import streamlit as st
import pandas as pd
import re
import pdfplumber
from io import BytesIO

st.set_page_config(page_title="Clasificador de Facturas", page_icon="💸", layout="wide")

# =========================
# Helpers para lectura PDF
# =========================
def _parse_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    s = str(raw).strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def _infer_estado_from_text(txt_lower: str) -> str | None:
    pagadas = ["pagada", "pagado", "cobrada", "cobrado", "paid"]
    impagas = [
        "no pagada", "no pagado", "no cobrada", "no cobrado",
        "impaga", "pendiente", "vencida", "atrasada", "unpaid", "impago"
    ]
    for w in impagas:
        if w in txt_lower:
            return "No pagada"
    for w in pagadas:
        if w in txt_lower:
            return "Pagada"
    return None

def extract_invoice_from_pdf(fileobj) -> dict:
    with pdfplumber.open(fileobj) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    txt = full_text
    txt_lower = txt.lower()

    m_fact = re.search(
        r"(?:factura(?:\s*n[ºo]\.?|\s*no\.?)?\s*[:\-]?\s*)([a-z0-9\-\/\.]+)", txt_lower, re.IGNORECASE
    )
    factura = m_fact.group(1).strip().upper() if m_fact else None

    m_cli = re.search(r"(?:cliente|raz[oó]n\s*social)\s*[:\-]\s*(.+)", txt, re.IGNORECASE)
    cliente = m_cli.group(1).strip() if m_cli else None
    if cliente:
        cliente = cliente.splitlines()[0].strip()

    m_estado = re.search(r"(?:estado|situaci[oó]n|pago)\s*[:\-]\s*([^\n\r]+)", txt, re.IGNORECASE)
    estado_raw = m_estado.group(1).strip() if m_estado else None
    if estado_raw:
        inf = _infer_estado_from_text(estado_raw.lower())
        estado = inf if inf else estado_raw
    else:
        estado = _infer_estado_from_text(txt_lower) or "Desconocido"

    m_total = re.search(r"(?:total(?:\s*a\s*pagar)?|importe)\s*[:\-]?\s*([€$]?\s*[0-9\.\,]+)", txt, re.IGNORECASE)
    importe = _parse_amount(m_total.group(1)) if m_total else None

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

# =========================
# Interfaz
# =========================
st.title("💸 Clasificador de Facturas (CSV/Excel/PDF)")
st.write(
    "Sube **uno o varios** archivos en CSV, Excel o PDF. "
    "La app leerá los datos y clasificará automáticamente las facturas en **cobradas** y **no cobradas**."
)

archivos = st.file_uploader(
    "📤 Sube tus archivos (CSV, XLSX, XLS o PDF)",
    type=["csv", "xlsx", "xls", "pdf"],
    accept_multiple_files=True,
)

if not archivos:
    st.info("Sube al menos un archivo para comenzar.")
    st.stop()

# =========================
# Construir DataFrame unificado a partir de múltiples archivos
# =========================
filas = []
for f in archivos:
    nombre = f.name.lower()

    if nombre.endswith(".pdf"):
        try:
            row = extract_invoice_from_pdf(BytesIO(f.getvalue()))
            filas.append(row)
        except Exception as e:
            st.error(f"❌ Error leyendo PDF '{f.name}': {e}")

    elif nombre.endswith(".csv"):
        try:
            tmp = pd.read_csv(f, encoding="utf-8", sep=None, engine="python")
            tmp = tmp.rename(columns={
                "factura": "Factura",
                "número": "Factura", "numero": "Factura", "nº": "Factura",
                "cliente": "Cliente",
                "estado": "Estado", "pagada": "Estado", "pago": "Estado", "status": "Estado",
                "importe": "Importe", "total": "Importe", "monto": "Importe",
            })
            filas += tmp.to_dict(orient="records")
        except Exception as e:
            st.error(f"❌ Error leyendo CSV '{f.name}': {e}")

    elif nombre.endswith(".xlsx") or nombre.endswith(".xls"):
        try:
            tmp = pd.read_excel(f)
            tmp = tmp.rename(columns={
                "factura": "Factura",
                "número": "Factura", "numero": "Factura", "nº": "Factura",
                "cliente": "Cliente",
                "estado": "Estado", "pagada": "Estado", "pago": "Estado", "status": "Estado",
                "importe": "Importe", "total": "Importe", "monto": "Importe",
            })
            filas += tmp.to_dict(orient="records")
        except Exception as e:
            st.error(f"❌ Error leyendo Excel '{f.name}': {e}")

# DataFrame base con columnas estándar
df = pd.DataFrame(filas, columns=["Factura", "Cliente", "Estado", "Importe"]) if filas else pd.DataFrame(
    columns=["Factura", "Cliente", "Estado", "Importe"]
)

if df.empty:
    st.warning("No se han podido extraer datos de los archivos subidos.")
    st.stop()

st.subheader("📋 Vista previa")
st.dataframe(df.head(), use_container_width=True)

# =========================
# Normalización y clasificación
# =========================
serie = df["Estado"].astype(str).str.lower().str.strip()

valores_pagada = {"pagada", "pagado", "cobrada", "cobrado", "sí", "si", "true", "1", "y", "yes", "paid", "paga"}
valores_no = {"no", "impaga", "pendiente", "vencida", "atrasada", "unpaid", "impago", "no pagada", "no cobrada"}

def es_pagada(x: str) -> bool:
    # es cobrada si contiene alguna palabra de pagada y no contiene palabras negativas
    tiene_pos = any(p in x for p in valores_pagada)
    tiene_neg = any(n in x for n in valores_no)
    return tiene_pos and not tiene_neg

cobradas = df[serie.apply(es_pagada)].copy()
no_cobradas = df[~serie.apply(es_pagada)].copy()

# =========================
# Resumen
# =========================
st.subheader("📊 Resumen")
total = len(df)
total_c = len(cobradas)
total_nc = len(no_cobradas)

c1, c2, c3 = st.columns(3)
c1.metric("Total de facturas", total)
c2.metric("Cobradas", total_c)
c3.metric("No cobradas", total_nc)

st.bar_chart(
    pd.DataFrame({"Cobradas": [total_c], "No cobradas": [total_nc]}).T.rename(columns={0: "Cantidad"})
)

# =========================
# Tablas
# =========================
st.subheader("✅ Facturas cobradas")
st.dataframe(cobradas, use_container_width=True)

st.subheader("⛔ Facturas NO cobradas")
st.dataframe(no_cobradas, use_container_width=True)

# =========================
# Exportar
# =========================
st.subheader("💾 Exportar resultados")

if not cobradas.empty:
    st.download_button(
        "⬇️ Descargar cobradas (CSV)",
        cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_cobradas.csv",
        mime="text/csv",
    )

if not no_cobradas.empty:
    st.download_button(
        "⬇️ Descargar no cobradas (CSV)",
        no_cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_no_cobradas.csv",
        mime="text/csv",
    )

if not (cobradas.empty and no_cobradas.empty):
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

