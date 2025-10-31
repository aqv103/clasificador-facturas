# app_facturas.py
# -------------------------------------------------
# Clasificador de facturas: Cobradas / En curso / No cobradas
# - Soporta CSV, XLSX y PDF (tablas)
# - Clasificación por "Total" y "Pagado" (preferente)
#   o por columna de estado cuando no hay importes.
# - Exportación a CSV y a Excel (3 hojas)
# -------------------------------------------------

import io
import re
from typing import List, Optional

import pandas as pd
import streamlit as st

# pdfplumber es opcional: si no está instalado, seguimos con CSV/XLSX
try:
    import pdfplumber  # type: ignore
    PDF_ENABLED = True
except Exception:
    PDF_ENABLED = False


# ================================
# Utilidades
# ================================
def _to_number(x) -> Optional[float]:
    """Convierte valores con símbolos €/$, puntos, comas, etc. a float.
    Devuelve None si no se puede convertir."""
    if pd.isna(x):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()

    # eliminar todo excepto dígitos, coma, punto y signo -
    s = re.sub(r"[^\d,.\-]", "", s)

    # si hay coma y punto, decidir cuál es decimal (asumimos coma decimal si está al final)
    if "," in s and "." in s:
        # caso típico "1.234,56"
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        # solo coma -> usar como decimal
        if "," in s:
            s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    """Normaliza un texto a minúsculas sin espacios extra."""
    return re.sub(r"\s+", " ", str(s).strip()).lower()


def read_csv_or_excel(file) -> pd.DataFrame:
    """Lee CSV o Excel en DataFrame con heurística segura."""
    name = file.name.lower()
    if name.endswith(".csv"):
        # Intenta algunos separadores típicos
        for sep in [",", ";", "\t", "|"]:
            try:
                df = pd.read_csv(file, encoding="utf-8", sep=sep, engine="python")
                if df.shape[1] > 1:
                    return df
            except Exception:
                file.seek(0)
        # último intento sin sep forzado
        file.seek(0)
        return pd.read_csv(file, encoding="utf-8", engine="python")
    else:
        return pd.read_excel(file)


def read_pdf_tables(file) -> pd.DataFrame:
    """Extrae tablas de un PDF (si pdfplumber está disponible).
    Devuelve un DataFrame concatenado o vacío."""
    if not PDF_ENABLED:
        return pd.DataFrame()

    try:
        dfs: List[pd.DataFrame] = []
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for tb in tables or []:
                    if not tb or len(tb) < 1:
                        continue
                    # Si la primera fila parece header (texto no numérico), úsala
                    header = tb[0]
                    if any(isinstance(h, str) for h in header):
                        df_page = pd.DataFrame(tb[1:], columns=[str(h) for h in header])
                    else:
                        df_page = pd.DataFrame(tb)

                    if not df_page.empty:
                        dfs.append(df_page)
        if dfs:
            return pd.concat(dfs, ignore_index=True)
    except Exception:
        pass
    return pd.DataFrame()


def load_files(files) -> pd.DataFrame:
    """Carga múltiples archivos y concatena en un único DataFrame."""
    frames: List[pd.DataFrame] = []
    for f in files:
        name = f.name.lower()
        if name.endswith((".csv", ".xlsx", ".xls")):
            try:
                df_part = read_csv_or_excel(f)
                if not df_part.empty:
                    frames.append(df_part)
            except Exception as e:
                st.error(f"Error leyendo {f.name}: {e}")
        elif name.endswith(".pdf"):
            df_part = read_pdf_tables(f)
            if df_part.empty:
                st.warning(f"No se han detectado tablas válidas en {f.name}")
            else:
                frames.append(df_part)
        else:
            st.warning(f"Formato no soportado: {f.name}")

    if frames:
        # Homogeneizar columnas por nombre (minúsculas, espacios -> _)
        normed = []
        for df in frames:
            df2 = df.copy()
            df2.columns = [
                re.sub(r"\s+", "_", str(c).strip().lower()) for c in df2.columns
            ]
            normed.append(df2)
        return pd.concat(normed, ignore_index=True)
    return pd.DataFrame()


# ================================
# Clasificación
# ================================
def classify_by_amounts(df: pd.DataFrame):
    """Clasifica usando columnas de importes (preferente si existen).
    Busca columnas para total, pagado y (opcional) pendiente."""
    # Candidatos por nombre
    total_candidates = ["total", "importe", "monto", "amount", "total_factura", "importe_total"]
    paid_candidates = ["pagado", "abonado", "pago", "paid", "importe_pagado", "monto_pagado"]
    pending_candidates = ["pendiente", "restante", "saldo", "due", "por_cobrar"]

    cols = list(df.columns)

    # Encontrar columnas mejor coincidentes
    def find_col(cands):
        for c in cols:
            c_norm = _normalize_text(c)
            for cand in cands:
                if cand in c_norm:
                    return c
        return None

    col_total = find_col(total_candidates)
    col_paid = find_col(paid_candidates)
    col_pending = find_col(pending_candidates)

    if not col_total:
        return None  # no podemos usar importes

    work = df.copy()

    # Convertir a números
    work["_total_"] = work[col_total].apply(_to_number)

    if col_paid:
        work["_pagado_"] = work[col_paid].apply(_to_number)
    else:
        work["_pagado_"] = None

    if col_pending:
        work["_pendiente_"] = work[col_pending].apply(_to_number)
    else:
        work["_pendiente_"] = None

    # Completar faltantes si hay dos de tres:
    # Si falta pagado y tenemos total/pendiente
    mask = work["_pagado_"].isna() & work["_total_"].notna() & work["_pendiente_"].notna()
    work.loc[mask, "_pagado_"] = work.loc[mask, "_total_"] - work.loc[mask, "_pendiente_"]

    # Si falta pendiente y tenemos total/pagado
    mask = work["_pendiente_"].isna() & work["_total_"].notna() & work["_pagado_"].notna()
    work.loc[mask, "_pendiente_"] = work.loc[mask, "_total_"] - work.loc[mask, "_pagado_"]

    # Reglas de clasificación
    eps = 0.01  # margen por redondeos
    cobradas = work[(work["_total_"].notna()) &
                    (work["_pagado_"].notna()) &
                    (work["_pagado_"] >= work["_total_"] - eps)]

    en_curso = work[(work["_total_"].notna()) &
                    (work["_pagado_"].notna()) &
                    (work["_pagado_"] > eps) &
                    (work["_pagado_"] < work["_total_"] - eps)]

    # No cobradas: total existe y (pagado es 0 o NaN)
    no_cobradas = work[(work["_total_"].notna()) &
                       ((work["_pagado_"].isna()) | (work["_pagado_"] <= eps))]

    # Añadimos columnas calculadas visibles si existen
    def visible(df_slice):
        cols_show = list(df.columns)
        extra = []
        if "_total_" in df_slice:
            df_slice["Total"] = df_slice["_total_"]
            extra.append("Total")
        if "_pagado_" in df_slice:
            df_slice["Pagado"] = df_slice["_pagado_"]
            extra.append("Pagado")
        if "_pendiente_" in df_slice:
            df_slice["Pendiente"] = df_slice["_pendiente_"]
            extra.append("Pendiente")
        # Dejar columnas originales primero + extra al final
        return df_slice[[c for c in cols_show if c in df_slice.columns] + extra]

    return visible(cobradas), visible(en_curso), visible(no_cobradas)


def classify_by_status(df: pd.DataFrame):
    """Clasifica usando una columna de estado si no hay importes."""
    cols = list(df.columns)
    candidates = [c for c in cols if any(x in c.lower() for x in ["estado", "status", "pag", "cob"])]

    if not candidates:
        return None  # no hay forma de clasificar

    # Si hay varias posibles, deja elegir
    estado_col = st.selectbox("Selecciona la columna que indica el estado de la factura:", candidates)

    work = df.copy()
    s = work[estado_col].astype(str).str.strip().str.lower()
    # Normalizar tildes simples:
    s = s.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("utf-8")

    valores_pagadas = {"pagada", "pagado", "cobrado", "cobrada", "si", "sí", "1", "true", "y", "yes"}
    valores_no_pagadas = {"no pagada", "no pagado", "impaga", "pendiente", "0", "false", "n", "no", ""}

    cobradas = work[s.isin(valores_pagadas)]
    no_cobradas = work[s.isin(valores_no_pagadas)]
    # Cuando no se puede decidir (otros estados), lo consideramos "en curso"
    en_curso = work[~s.isin(valores_pagadas | valores_no_pagadas)]

    return cobradas, en_curso, no_cobradas


# ================================
# App Streamlit
# ================================
st.set_page_config(page_title="Clasificador de Facturas", page_icon="💶", layout="wide")

st.title("💶 Clasificador de Facturas Cobradas, En Curso y No Cobradas")
st.write(
    """
    Sube un archivo de facturas (**CSV**, **Excel** o **PDF con tablas**).  
    La app clasifica automáticamente las facturas en:
    - ✅ **Cobradas**  
    - 🟡 **En curso** (pagos parciales)  
    - ⛔ **No cobradas**

    **Preferencia:** si hay columnas de **Total** y **Pagado**, se usan para el cálculo;  
    si no, se usa una columna de **Estado** (Pagada / No pagada / etc.).
    """
)

uploaded_files = st.file_uploader(
    "Sube uno o varios archivos",
    type=["csv", "xlsx", "xls", "pdf"],
    accept_multiple_files=True,
    help="Tamaño típico permitido por Streamlit Cloud: ~200MB por archivo",
)

if not uploaded_files:
    st.info("⬆️ Sube al menos un archivo para comenzar.")
    st.stop()

df = load_files(uploaded_files)
if df.empty:
    st.error("No se han podido leer datos de los archivos subidos.")
    st.stop()

st.subheader("👀 Vista previa")
st.dataframe(df.head(50), use_container_width=True)

# ---- Clasificación
result = classify_by_amounts(df)
by_amounts = True
if result is None:
    result = classify_by_status(df)
    by_amounts = False

if result is None:
    st.error("No se han encontrado columnas de importes ni de estado para clasificar.")
    st.stop()

cobradas, en_curso, no_cobradas = result

# ---- Resumen
st.subheader("📊 Resumen")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total de facturas", len(df))
col2.metric("✅ Cobradas", len(cobradas))
col3.metric("🟡 En curso", len(en_curso))
col4.metric("⛔ No cobradas", len(no_cobradas))

# ---- Tablas
st.markdown("### ✅ Facturas **cobradas**")
st.dataframe(cobradas, use_container_width=True)

st.markdown("### 🟡 Facturas **en curso**")
if by_amounts and not en_curso.empty and {"Total", "Pagado"}.issubset(en_curso.columns):
    st.caption("Pagos parciales detectados. Se muestra Total, Pagado y Pendiente (si es posible).")
st.dataframe(en_curso, use_container_width=True)

st.markdown("### ⛔ Facturas **NO cobradas**")
st.dataframe(no_cobradas, use_container_width=True)

# ---- Exportación CSV individuales
st.subheader("⬇️ Descarga por separado (CSV)")
cols_dl = st.columns(3)

with cols_dl[0]:
    st.download_button(
        "CSV - Cobradas",
        data=cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_cobradas.csv",
        mime="text/csv",
        disabled=cobradas.empty,
    )

with cols_dl[1]:
    st.download_button(
        "CSV - En curso",
        data=en_curso.to_csv(index=False).encode("utf-8"),
        file_name="facturas_en_curso.csv",
        mime="text/csv",
        disabled=en_curso.empty,
    )

with cols_dl[2]:
    st.download_button(
        "CSV - No cobradas",
        data=no_cobradas.to_csv(index=False).encode("utf-8"),
        file_name="facturas_no_cobradas.csv",
        mime="text/csv",
        disabled=no_cobradas.empty,
    )

# ---- Exportación Excel con 3 hojas
st.subheader("⬇️ Descarga consolidada (Excel con 3 hojas)")
if st.button("Generar Excel de resultados"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        cobradas.to_excel(writer, index=False, sheet_name="Cobradas")
        en_curso.to_excel(writer, index=False, sheet_name="En_curso")
        no_cobradas.to_excel(writer, index=False, sheet_name="No_cobradas")
    output.seek(0)

    st.download_button(
        "Descargar Excel",
        data=output.getvalue(),
        file_name="clasificacion_facturas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.success("✅ Clasificación finalizada. Puedes descargar los resultados arriba.")
