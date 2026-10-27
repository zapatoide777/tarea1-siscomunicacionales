"""Dibuja las mediciones y calcula frecuencias y errores de texto."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def figura_senal(tiempo, intensidad, umbral, fs=None):
    """Muestra el brillo medido en la ROI y el umbral ON/OFF."""
    figura, eje = plt.subplots(figsize=(10, 3.5), constrained_layout=True)
    # La línea horizontal separa los cuadros con luz de los cuadros sin luz.
    eje.plot(tiempo, intensidad, lw=1, label="ROI")
    eje.axhline(umbral, color="tab:red", ls="--", label="Umbral fijo")
    eje.set(xlabel="Tiempo (s)", ylabel="Intensidad digital", title="Señal recibida")
    if fs is not None:
        eje.set_title(f"Señal recibida · fs = {fs:.3f} muestras/s (efectiva)")
    eje.grid(alpha=.25)
    eje.legend()
    return figura


def figura_decisiones(tiempo, intensidad, configuracion, decisiones):
    """Documenta los primeros ocho tramos sin alterar la decodificación."""
    figura, ejes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True,
                               gridspec_kw={"height_ratios": [2, 3]})
    eje, tabla = ejes
    tiempo = np.asarray(tiempo)
    intensidad = np.asarray(intensidad)
    muestra = decisiones[:8]
    nombres = {"punto": "Punto", "raya": "Raya", "simbolo": "Pausa de símbolo",
               "letra": "Pausa de letra", "palabra": "Pausa de palabra",
               "pulso_invalido": "Pulso fuera de tolerancia",
               "pausa_invalida": "Pausa fuera de tolerancia"}
    eje.plot(tiempo, intensidad, lw=1)
    eje.axhline(configuracion["threshold"], ls="--", color="tab:red", label="Umbral")
    filas = []
    origen = float(tiempo[0])
    for numero, decision in enumerate(muestra, 1):
        inicio, fin = origen + decision["start"], origen + decision["end"]
        color = "tab:green" if decision["valid"] else "tab:red"
        eje.axvspan(inicio, fin, alpha=.12, color=color)
        eje.text((inicio + fin) / 2, .95, str(numero), ha="center", va="top",
                 transform=eje.get_xaxis_transform(), fontsize=9)
        filas.append([str(numero), "ON" if decision["state"] else "OFF",
                      f"{inicio:.3f}–{fin:.3f}", f"{decision['duration'] * 1000:.1f}",
                      f"{decision['units_measured']:.2f}", nombres[decision["kind"]]])
    if muestra:
        eje.set_xlim(origen + muestra[0]["start"], origen + muestra[-1]["end"])
    else:
        tabla.text(.5, .5, "No se detectaron tramos de mensaje.", ha="center")
    eje.set(xlabel="Tiempo en el video (s)", ylabel="Intensidad digital",
            title="Tramo recibido y decisiones temporales")
    eje.grid(alpha=.25)
    eje.legend()
    tabla.axis("off")
    if filas:
        celdas = tabla.table(cellText=filas,
                            colLabels=["N°", "LED", "Inicio–fin (s)", "Duración (ms)", "Duración/T", "Decisión"],
                            colWidths=[.05, .07, .21, .16, .14, .37], loc="center")
        celdas.auto_set_font_size(False)
        celdas.set_fontsize(8)
        celdas.scale(1, 1.65)
    figura.suptitle(f"T = {configuracion['t_seconds'] * 1000:.1f} ms · "
                     f"tolerancia = ±{configuracion['tolerance_units']:.3f} T")
    return figura


def figura_espectro(espectro):
    """Compara la FFT de la señal con su PSD y marca el ancho B95."""
    figura, ejes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
    # Arriba se ven las frecuencias presentes; abajo, cómo se reparte la potencia.
    ejes[0].plot(espectro["fft_f"], espectro["amplitude"])
    ejes[0].set(xlabel="Frecuencia (Hz)", ylabel="Amplitud digital",
                title=r"FFT de $X[n] = I[n] - I_{\mathrm{prom}}$")
    ejes[1].plot(espectro["psd_f"], espectro["psd"])
    ejes[1].axvline(espectro["b95"], color="tab:red", ls="--",
                   label=f"B95 = {espectro['b95']:.3f} Hz")
    ejes[1].set(xlabel="Frecuencia (Hz)", ylabel="Intensidad digital²/Hz",
                title=r"PSD de $X[n]$ · Periodograma de una sola cara")
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
            datos_senal["time"] - datos_senal["time"][0]
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


def analizar_senal(intensidad, fps: float, tiempos=None) -> dict:
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

    tiempo_uniforme = np.arange(len(muestras), dtype=float) / fps
    remuestreo = False
    if tiempos is not None:
        tiempos = np.asarray(tiempos, dtype=float)
        if (tiempos.shape != muestras.shape or not np.all(np.isfinite(tiempos))
                or np.any(np.diff(tiempos) <= 0)):
            raise ValueError("Tiempos invalidos para calcular espectro")
        intervalos = np.diff(tiempos)
        intervalo = float(np.median(intervalos))
        remuestreo = not np.allclose(intervalos, intervalo, rtol=.005, atol=.000002)
        if remuestreo:
            cantidad = int(np.floor((tiempos[-1] - tiempos[0]) / intervalo + 1e-8)) + 1
            if cantidad > max(1000000, len(muestras) * 100):
                raise ValueError("Saltos temporales demasiado grandes para calcular un espectro fiable")
            tiempo_uniforme = tiempos[0] + np.arange(cantidad) * intervalo
            muestras = np.interp(tiempo_uniforme, tiempos, muestras)
            fps = 1 / intervalo
        else:
            tiempo_uniforme = tiempos.copy()

    # Resta el brillo promedio para estudiar los cambios de luz, no el fondo fijo.
    muestras_sin_media = muestras - muestras.mean()
    cantidad_muestras = len(muestras)

    # La FFT separa la señal en frecuencias. Se conserva la mitad útil del
    # espectro y se ajustan sus amplitudes para representar toda la señal.
    transformada = np.fft.rfft(muestras_sin_media)
    amplitud = np.abs(transformada) / cantidad_muestras
    # |DFT|²/(fs N) tiene unidades de intensidad²/Hz. Se aplica el mismo
    # plegado unilateral a potencia y amplitud, por separado.
    densidad_potencia = np.abs(transformada)**2 / (fps * cantidad_muestras)
    if cantidad_muestras % 2 == 0:
        amplitud[1:-1] *= 2
        densidad_potencia[1:-1] *= 2
    else:
        amplitud[1:] *= 2
        # Con N impar la última componente no es Nyquist: también se duplica.
        densidad_potencia[1:] *= 2
    delta_f = float(fps / cantidad_muestras)
    frecuencias_fft = np.arange(len(transformada), dtype=float) * delta_f
    frecuencias_psd = frecuencias_fft.copy()

    # Cada bin aporta PSD[k] Δf; los trapecios perderían parte de la potencia
    # de los extremos. Esta suma discreta conserva exactamente Parseval.
    potencias_bins = densidad_potencia * delta_f
    area_acumulada = np.cumsum(potencias_bins)
    area_total = float(area_acumulada[-1])
    potencia_temporal = float(np.mean(muestras_sin_media**2))
    error_parseval = abs(area_total - potencia_temporal)
    parseval_correcto = bool(np.isclose(area_total, potencia_temporal, rtol=1e-10, atol=1e-12))
    if not parseval_correcto:
        raise ValueError("El periodograma no conserva la potencia de la señal centrada (Parseval)")
    ancho_b95 = 0.0
    if area_total > 0:
        indice_b95 = min(len(frecuencias_psd) - 1,
                         int(np.searchsorted(area_acumulada, 0.95 * area_total)))
        ancho_b95 = float(frecuencias_psd[indice_b95])

    return dict(
        fft_f=frecuencias_fft,
        amplitude=amplitud,
        psd_f=frecuencias_psd,
        psd=densidad_potencia,
        cumulative=area_acumulada,
        b95=ancho_b95,
        psd_area=area_total,
        mean=float(muestras.mean()),
        variance=potencia_temporal,
        method="Periodograma de una sola cara",
        window="boxcar",
        # Campos conservados por compatibilidad: un único registro completo.
        nperseg=cantidad_muestras,
        noverlap=0,
        detrend=False,
        scaling="density",
        centering="X[n] = I[n] - mean(I)",
        sample_count=cantidad_muestras,
        frequency_rule="f[k] = k fs/N, k = 0,...,floor(N/2)",
        delta_f_hz=delta_f,
        psd_normalization="abs(rFFT(X))**2/(fs*N); duplicar interiores, excepto DC y Nyquist si N par",
        fft_amplitude_normalization="abs(rFFT(X))/N; duplicar interiores, excepto DC y Nyquist si N par",
        psd_units="intensidad digital^2/Hz",
        integration_method="sum(PSD[k] * delta_f); cumulative[k] incluye el bin k",
        b95_method="Primera frecuencia con cumulative[k] >= 0.95 * psd_area; sin interpolacion",
        time_power=potencia_temporal,
        parseval_absolute_error=error_parseval,
        parseval_relative_error=(error_parseval / potencia_temporal if potencia_temporal > 0 else 0.0),
        parseval_ok=parseval_correcto,
        parseval_rtol=1e-10,
        parseval_atol=1e-12,
        fs=fps,
        resampled=bool(remuestreo),
        sampling=("Interpolacion lineal a intervalo mediano SOLO para FFT/PSD; Morse usa PTS originales"
                  if remuestreo else "Muestreo uniforme original; sin remuestreo"),
        sample_time=tiempo_uniforme,
        sample_intensity=muestras,
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
