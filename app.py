# -*- coding: utf-8 -*-
import io
import csv
import json
import zipfile
from datetime import date

import requests
import streamlit as st

# ============================================================
# CONFIGURACIÓ DE L'API (Seguretat integrada amb Streamlit Cloud)
# ============================================================
URL_API = "https://nemon2ib.com"

# Intentem carregar el token des dels Secrets del núvol, si no, quedarà buit
TOKEN_SECRET = st.secrets.get("api", {}).get("token", "")
# ============================================================

CABECERAS = (
    ["ID", "CUPS", "Fecha"]
    + [f"Consumo kWh H{str(i).zfill(2)}" for i in range(1, 26)]
    + ["Código tipo", "Tipo", "Tipo Punto Medida",
       "Provincia", "Distribuidora", "Tipo Tarifa"]
)

def procesar_texto_cups(texto_raw):
    """Neteja el text d'entrada i en treu una llista de CUPS únics i vàlids."""
    if not texto_raw:
        return []
    
    # Substituïm salts de línia i espais per comes per normalitzar el text
    texto_normalizado = texto_raw.replace("\n", ",").replace(" ", ",")
    # Separem per comes
    tokens = texto_normalizado.split(",")
    
    registros = []
    contador = 1
    
    for token in tokens:
        cups = token.strip().upper()  # Forcem majúscules per als CUPS
        if cups and len(cups) >= 15:  # Validació bàsica de longitud d'un CUPS
            # Generem el número formatejat (001, 002...) de manera seqüencial
            num_formateado = f"{contador:03d}"
            registros.append((cups, num_formateado))
            contador += 1
            
    return registros

def llamar_api(cups, fecha_inicio, fecha_fin, tipo, token_actual):
    data_json = json.dumps({
        "cups": cups,
        "data_inicio": fecha_inicio,
        "data_final": fecha_fin,
        "tipo": tipo,
    })

    files = {
        "token":  (None, token_actual),
        "module": (None, "Metering"),
        "class":  (None, "MetMeteringHourly"),
        "action": (None, "getHourly"),
        "data":   (None, data_json),
    }

    try:
        r = requests.post(URL_API, files=files, timeout=60)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        error_msg = f"Error: {e}"
        if 'r' in locals() and hasattr(r, 'text'):
            error_msg += f" | Resposta API: {r.text[:150]}"
        return None, error_msg

def formatear_numero(valor):
    if valor is None or valor == "":
        return ""
    if isinstance(valor, str):
        s = valor.strip()
        if s == "":
            return ""
        try:
            f = float(s.replace(",", "."))
        except ValueError:
            return s
        valor = f

    try:
        f = float(valor)
    except (ValueError, TypeError):
        return str(valor)

    if f == 0:
        return "0"

    s = f"{f:.6f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")

def generar_csv_string(registros):
    output = io.StringIO()
    writer = csv.writer(
        output,
        delimiter=",",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writerow(CABECERAS)

    for reg in registros:
        fila = [
            reg.get("id", ""),
            reg.get("cups", ""),
            reg.get("date", ""),
        ]
        for i in range(1, 26):
            key = f"H{str(i).zfill(2)}"
            fila.append(formatear_numero(reg.get(key, "")))

        fila.append(reg.get("type", ""))
        fila.append(reg.get("typedesc", ""))

        pm = reg.get("point_measurment", "")
        if pm not in (None, ""):
            fila.append(f"Tipo {pm}")
        else:
            fila.append("")

        fila.append("")  
        fila.append(reg.get("distributor_name", ""))
        fila.append(reg.get("tariff", ""))

        writer.writerow(fila)

    csv_text = output.getvalue()
    csv_bytes = "\ufeff".encode("utf-16-le") + csv_text.encode("utf-16-le")
    return csv_bytes

# Interfície de Streamlit
st.set_page_config(page_title="Descàrrega Consums CUPS", page_icon="⚡", layout="centered")

st.title("⚡ Descàrrega de Consum Horari (CUPS)")
st.write("Introdueix els CUPS a mà, configura els paràmetres i descarrega els consums en format CSV.")

# Barra lateral d'autenticació
with st.sidebar:
    st.header("🔑 Autenticació")
    token_input = st.text_input(
        "API Token", 
        value=TOKEN_SECRET, 
        type="password",
        help="Si has configurat els Secrets a Streamlit Cloud, aquest camp es pot deixar buit."
    )
    st.info(f"API URL:\n`{URL_API}`")

# Secció Central de Paràmetres
st.header("📋 Paràmetres de la Consulta")

# Camp d'entrada nou: text area per enganxar CUPS
cups_raw = st.text_area(
    "1. Introdueix els CUPS (separats per comes, espais o salts de línia)",
    placeholder="ES0021000000000000XXXXXX, ES0021000000000000YYYYYY",
    height=150
)

col1, col2, col3 = st.columns(3)
with col1:
    fecha_inicio = st.date_input("2. Data d'inici", date.today())
with col2:
    fecha_fin = st.date_input("3. Data final", date.today())
with col3:
    tipo_consulta = st.text_input("4. Tipus de consulta (Telemedida)", value="1")

if fecha_inicio > fecha_fin:
    st.error("Error: La data d'inici no pot ser posterior a la data final.")

# Execució del procés
if st.button("🚀 Processar i descarregar dades", disabled=not cups_raw or not token_input):
    
    # Processar la llista des del text area
    registros_cups = procesar_texto_cups(cups_raw)
    
    if not registros_cups:
        st.warning("No s'ha detectat cap CUPS vàlid al camp de text (mínim 15 caràcters).")
    else:
        total_cups = len(registros_cups)
        st.info(f"S'han detectat **{total_cups}** CUPS preparats per a la consulta.")
        
        zip_buffer = io.BytesIO()
        exitos = 0
        fallos = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for idx, (cups, num) in enumerate(registros_cups, start=1):
                porcentaje = idx / total_cups
                progress_bar.progress(porcentaje)
                status_text.text(f"Processant [{idx}/{total_cups}]: {cups}...")
                
                f_ini_str = fecha_inicio.strftime("%Y-%m-%d")
                f_fin_str = fecha_fin.strftime("%Y-%m-%d")
                
                respuesta, error = llamar_api(cups, f_ini_str, f_fin_str, tipo_consulta, token_input)
                
                if error:
                    st.error(f"❌ Error en {cups}: {error}")
                    fallos += 1
                    continue
                
                lista = respuesta.get("listRequests") if respuesta else []

                if not lista:
                    st.warning(f"⚠️ Sense dades a la API per a {cups}")
                    fallos += 1
                    continue
                
                # Nom del fitxer utilitzant el seqüencial generat automàticament
                nombre_csv = f"03{num} {cups}.csv"
                csv_data_bytes = generar_csv_string(lista)
                zip_file.writestr(nombre_csv, csv_data_bytes)
                exitos += 1
        
        progress_bar.empty()
        status_text.empty()
        
        st.success(f"📊 Procés finalitzat: {exitos} correctes, {fallos} fallits de {total_cups}.")
        
        if exitos > 0:
            zip_buffer.seek(0)
            st.download_button(
                label="📥 Descarregar tots els CSVs (.ZIP)",
                data=zip_buffer,
                file_name=f"telemedida_{fecha_inicio}_al_{fecha_fin}.zip",
                mime="application/zip"
            )
        else:
            st.error("Totes les consultes a l'API han fallat o no tenien registres.")

elif not cups_raw:
    st.info("💡 Escriu o enganxa un o més CUPS al quadre de text superior per començar.")

