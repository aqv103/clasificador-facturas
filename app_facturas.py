# app_facturas.py
import streamlit as st
import pandas as pd

# Configuración de la página
st.set_page_config(page_title="Clasificador de Facturas", page_icon="💰", layout="wide")

st.title("💰 Clasificador de Facturas Cobradas y No Cobradas")

st.write("""
Esta aplicación te permite cargar un archivo de facturas (CSV o Excel) y clasificarlas automáticamente en **cobradas** y **no cobradas**.
Solo necesitas que el archivo tenga alguna columna que indique el estado del pago (por ejemplo, *Estado*, *Pagada*, *Cobrado*, etc.).
""")

# Subir archivo
archivo = st.file_uploader("📤 Sube tu archivo de facturas", type=["csv", "xlsx"])

if archivo:
    # Leer archivo
    try:
        if archivo.name.lower().endswith(".csv"):
            df = pd.read_csv(archivo, encoding="utf-8", sep=None, engine="python")
        else:
            df = pd.read_excel(archivo)
    except Exception as e:
        st.error(f"❌ Error al leer el archivo: {e}")
        st.stop()

    st.subheader("📋 Vista previa de los datos")
    st.dataframe(df.head())

    # Detectar posibles columnas relacionadas con estado/pago
    columnas_estado = [c for c in df.columns if any(x in c.lower() for x in ["estado", "pag", "cob"])]
    if not columnas_estado:
        st.error("⚠️ No se detectó ninguna columna relacionada con el pago. Asegúrate de tener una columna llamada por ejemplo 'Estado' o 'Pagada'.")
    else:
        columna_estado = st.selectbox("Selecciona la columna que indica si la factura está pagada:", columnas_estado)

        # Normalizar valores
        valores_pagada = {"pagada", "cobrada", "pagado", "cobrado", "sí", "si", "1", "true", "y", "yes"}
        df[columna_estado] = df[columna_estado].astype(str).str.lower().str.strip()

        # Clasificar
        cobradas = df[df[columna_estado].isin(valores_pagada)]
        no_cobradas = df[~df.index.isin(cobradas.index)]

        # Mostrar resultados
        st.subheader("💸 Facturas cobradas")
        st.dataframe(cobradas)

        st.subheader("🧾 Facturas no cobradas")
        st.dataframe(no_cobradas)

        # Resumen numérico
        st.subheader("📊 Resumen general")
        total = len(df)
        total_cobradas = len(cobradas)
        total_no_cobradas = len(no_cobradas)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total de facturas", total)
        col2.metric("Cobradas", total_cobradas)
        col3.metric("No cobradas", total_no_cobradas)

        st.bar_chart(pd.DataFrame({
            "Cobradas": [total_cobradas],
            "No cobradas": [total_no_cobradas]
        }))

        # Descarga de resultados
        st.subheader("📥 Exportar resultados")
        if not cobradas.empty:
            st.download_button(
                "⬇️ Descargar cobradas (CSV)",
                cobradas.to_csv(index=False).encode("utf-8"),
                file_name="facturas_cobradas.csv",
                mime="text/csv"
            )
        if not no_cobradas.empty:
            st.download_button(
                "⬇️ Descargar no cobradas (CSV)",
                no_cobradas.to_csv(index=False).encode("utf-8"),
                file_name="facturas_no_cobradas.csv",
                mime="text/csv"
            )
else:
    st.info("⬆️ Sube un archivo CSV o Excel para comenzar.")
