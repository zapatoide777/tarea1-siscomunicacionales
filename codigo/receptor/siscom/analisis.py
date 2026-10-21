"""Dibuja las mediciones y calcula frecuencias y errores de texto."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


def figura_senal(tiempo, intensidad, umbral):
    """Muestra el brillo medido en la ROI y el umbral ON/OFF."""
    figura, eje = plt.subplots(figsize=(10, 3.5), constrained_layout=True)
    # La línea horizontal separa los cuadros con luz de los cuadros sin luz.
    eje.plot(tiempo, intensidad, lw=1, label="ROI")
    eje.axhline(umbral, color="tab:red", ls="--", label="Umbral fijo")
    eje.set(xlabel="Tiempo (s)", ylabel="Intensidad digital", title="Señal recibida")
    eje.grid(alpha=.25)
    eje.legend()
    return figura


def figura_espectro(espectro):
    """Compara la FFT de la señal con su PSD y marca el ancho B95."""
    figura, ejes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
    # Arriba se ven las frecuencias presentes; abajo, cómo se reparte la potencia.
    ejes[0].plot(espectro["fft_f"], espectro["amplitude"])
    ejes[0].set(xlabel="Frecuencia (Hz)", ylabel="Amplitud digital", title="FFT sin promedio")
    ejes[1].plot(espectro["psd_f"], espectro["psd"])
    ejes[1].axvline(espectro["b95"], color="tab:red", ls="--",
                   label=f"B95 = {espectro['b95']:.3f} Hz")
    ejes[1].set(xlabel="Frecuencia (Hz)", ylabel="Intensidad digital²/Hz", title="PSD Welch")
    ejes[1].legend()
    for eje in ejes:
        eje.set_xlim(0, espectro["fs"]/2)
        eje.grid(alpha=.25)
    return figura


def figura_distancia(resultados):
    """Grafica el CER de los ensayos válidos en función de la distancia."""
    figura, eje = plt.subplots(figsize=(7,4), constrained_layout=True)
    # Si faltó un video válido, no se inventa un valor de error para graficarlo.
    resultados_validos = sorted(
        (resultado for resultado in resultados if resultado.get("cer") is not None),
        key=lambda resultado: resultado["distance_m"],
    )
    distancias = [resultado["distance_m"] for resultado in resultados_validos]
    valores_cer = [resultado["cer"] for resultado in resultados_validos]
    eje.plot(distancias, valores_cer, "o-")
    eje.set(xlabel="Distancia (m)", ylabel="CER", title="Errores por distancia")
    eje.grid(alpha=.25)
    return figura


def figura_comparacion(ensayo_cercano, ensayo_lejano, umbral, ventana=(0., 3.)):
    """Compara señales a 0,5 m y 3 m alineadas por su primer pulso."""
    figura, ejes = plt.subplots(2,1, figsize=(9,5), sharey=True, constrained_layout=True)
    comparaciones = zip(ejes, [ensayo_cercano, ensayo_lejano], ["0,5 m", "3,0 m"])
    for eje, ensayo, titulo in comparaciones:
        datos_senal = ensayo["signal"]
        resultado_decodificacion = ensayo["result"]
        if not resultado_decodificacion["decisions"]:
            raise ValueError("No se puede alinear por primer pulso una señal sin pulsos")
        # Pone ambos primeros pulsos en el mismo instante para compararlos.
        tiempo_transcurrido = (
            np.arange(len(datos_senal["intensity"])) / datos_senal["fs"]
            - resultado_decodificacion["decisions"][0]["start"]
        )
        dentro_ventana = (tiempo_transcurrido >= ventana[0]) & (tiempo_transcurrido <= ventana[1])
        if not dentro_ventana.any():
            raise ValueError("Tramo de comparacion sin muestras")
        eje.plot(tiempo_transcurrido[dentro_ventana], datos_senal["intensity"][dentro_ventana], label=titulo)
        eje.axhline(umbral, color="tab:red", ls="--", label="Umbral fijo")
        eje.set(xlabel="Tiempo desde primer pulso (s)", ylabel="Intensidad digital")
        eje.legend()
        eje.grid(alpha=.25)
    return figura

# Frecuencias de la señal y ancho B95.


def analizar_senal(intensidad, fps: float) -> dict:
    """Calcula qué frecuencias aparecen en el brillo medido cuadro a cuadro."""
    muestras = np.asarray(intensidad, dtype=float)
    if (
        muestras.ndim != 1
        or len(muestras) < 4
        or not np.all(np.isfinite(muestras))
        or not np.isfinite(fps)
        or fps <= 0
    ):
        raise ValueError("Se requieren al menos 4 muestras finitas y FPS positivos")

    # Resta el brillo promedio para estudiar los cambios de luz, no el fondo fijo.
    muestras_sin_media = muestras - muestras.mean()
    cantidad_muestras = len(muestras)

    # La FFT separa la señal en frecuencias. Se conserva la mitad útil del
    # espectro y se ajustan sus amplitudes para representar toda la señal.
    amplitud = np.abs(np.fft.rfft(muestras_sin_media)) / cantidad_muestras
    if cantidad_muestras % 2 == 0:
        amplitud[1:-1] *= 2
    else:
        amplitud[1:] *= 2
    frecuencias_fft = np.fft.rfftfreq(cantidad_muestras, 1 / fps)

    # La PSD muestra cuánta potencia corresponde a cada frecuencia. Welch la
    # calcula promediando partes superpuestas; Hann suaviza sus bordes.
    longitud_segmento = min(256, cantidad_muestras)
    frecuencias_psd, densidad_potencia = welch(
        muestras_sin_media,
        fs=fps,
        window="hann",
        nperseg=longitud_segmento,
        noverlap=longitud_segmento // 2,
        detrend=False,
        scaling="density",
    )

    # Suma el área bajo la PSD desde 0 Hz. B95 es la frecuencia donde ya se
    # acumuló el 95 % de esa área.
    areas_intervalos = (
        (densidad_potencia[:-1] + densidad_potencia[1:])
        * np.diff(frecuencias_psd)
        / 2
    )
    area_acumulada = np.r_[0.0, np.cumsum(areas_intervalos)]
    area_total = float(area_acumulada[-1])
    ancho_b95 = 0.0
    if area_total > 0:
        ancho_b95 = float(
            np.interp(0.95 * area_total, area_acumulada, frecuencias_psd)
        )

    return dict(
        fft_f=frecuencias_fft,
        amplitude=amplitud,
        psd_f=frecuencias_psd,
        psd=densidad_potencia,
        cumulative=area_acumulada,
        b95=ancho_b95,
        psd_area=area_total,
        mean=float(muestras.mean()),
        variance=float(np.mean(muestras_sin_media**2)),
        method="Welch",
        window="hann",
        nperseg=longitud_segmento,
        noverlap=longitud_segmento // 2,
        detrend=False,
        scaling="density",
        fs=fps,
    )

# Errores entre el texto esperado y el texto reconstruido.

def calcular_cer(referencia: str, recibido: str) -> dict:
    """Cuenta cambios mínimos y divide ese total por el largo del original."""
    referencia = referencia.upper()
    recibido = recibido.upper()

    if not referencia:
        raise ValueError("La referencia no puede estar vacia")

    cantidad_referencia = len(referencia)
    cantidad_recibida = len(recibido)

    # Cada casilla guarda cuántos cambios hacen falta para igualar partes de
    # los dos textos. La primera fila y columna parten desde texto vacío.
    tabla = [
        [0] * (cantidad_recibida + 1)
        for _ in range(cantidad_referencia + 1)
    ]

    for indice_referencia in range(cantidad_referencia + 1):
        tabla[indice_referencia][0] = indice_referencia

    for indice_recibido in range(cantidad_recibida + 1):
        tabla[0][indice_recibido] = indice_recibido

    # Para cada carácter elige el camino con menos reemplazos, borrados o añadidos.
    for indice_referencia in range(1, cantidad_referencia + 1):
        for indice_recibido in range(1, cantidad_recibida + 1):
            costo_sustitucion = int(
                referencia[indice_referencia - 1]
                != recibido[indice_recibido - 1]
            )

            tabla[indice_referencia][indice_recibido] = min(
                tabla[indice_referencia - 1][indice_recibido - 1]
                + costo_sustitucion,
                tabla[indice_referencia - 1][indice_recibido] + 1,
                tabla[indice_referencia][indice_recibido - 1] + 1,
            )

    # Recorre la tabla hacia atrás para separar el total en S, D e I.
    # Si hay varios caminos igual de cortos, mantiene siempre el mismo criterio.
    indice_referencia = cantidad_referencia
    indice_recibido = cantidad_recibida
    conteo = {"S": 0, "D": 0, "I": 0}

    while indice_referencia or indice_recibido:
        if indice_referencia and indice_recibido:
            costo_sustitucion = int(
                referencia[indice_referencia - 1]
                != recibido[indice_recibido - 1]
            )
            if (
                tabla[indice_referencia][indice_recibido]
                == tabla[indice_referencia - 1][indice_recibido - 1]
                + costo_sustitucion
            ):
                conteo["S"] += costo_sustitucion
                indice_referencia -= 1
                indice_recibido -= 1
                continue

        if (
            indice_referencia
            and tabla[indice_referencia][indice_recibido]
            == tabla[indice_referencia - 1][indice_recibido] + 1
        ):
            conteo["D"] += 1
            indice_referencia -= 1
        else:
            conteo["I"] += 1
            indice_recibido -= 1

    # CER (tasa de error de caracteres) = cambios / caracteres originales.
    # Los espacios también cuentan.
    errores = tabla[cantidad_referencia][cantidad_recibida]
    return {
        **conteo,
        "errors": errores,
        "cer": errores / cantidad_referencia,
        "exact": referencia == recibido,
        "reference": referencia,
        "received": recibido,
    }
