"""Lectura sin filtros: brillo original y tiempos de presentacion del archivo."""

from pathlib import Path

import av
import cv2
import numpy as np


def leer_video(ruta, roi=None, inicio=0., fin=None, seleccion_interactiva=False):
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ValueError(f"Video inexistente: {ruta}")
    if (not np.isfinite(inicio) or inicio < 0
            or (fin is not None and (not np.isfinite(fin) or fin <= inicio))):
        raise ValueError("El fin debe ser mayor que el inicio y ambos deben ser segundos validos")

    intensidades, tiempos, duraciones, indices = [], [], [], []
    primer_rgb = None
    origen = anterior = ultimo = None
    cantidad = 0
    detenido_por_fin = False
    saturados = pixeles = 0
    try:
        with av.open(str(ruta)) as contenedor:
            if not contenedor.streams.video:
                raise ValueError("El archivo no contiene una pista de video")
            pista = contenedor.streams.video[0]
            esperados = int(pista.frames or 0)
            fps_nominal = float(pista.average_rate) if pista.average_rate else None
            duracion_declarada = (float(pista.duration * pista.time_base)
                                  if pista.duration is not None and pista.time_base else None)
            if (duracion_declarada is None and len(contenedor.streams) == 1
                    and contenedor.duration is not None):
                duracion_declarada = contenedor.duration / av.time_base
            for indice, cuadro in enumerate(contenedor.decode(pista)):
                if cuadro.is_corrupt:
                    raise ValueError(f"Cuadro danado ({indice}); conservar el original y revisar el archivo")
                if cuadro.pts is None or cuadro.time_base is None:
                    raise ValueError("Faltan tiempos de presentacion fiables (PTS); no se inventaran FPS")
                marca = float(cuadro.pts * cuadro.time_base)
                if not np.isfinite(marca) or (anterior is not None and marca <= anterior):
                    raise ValueError("Tiempos de presentacion repetidos o desordenados; no se puede medir Morse")
                if origen is None:
                    origen = marca
                anterior = marca
                tiempo = marca - origen
                cantidad += 1
                duracion = float(cuadro.duration * cuadro.time_base) if cuadro.duration else None
                ultimo = (tiempo, duracion)
                if tiempo < inicio:
                    continue
                if fin is not None and tiempo >= fin:
                    detenido_por_fin = True
                    break
                bgr = cuadro.to_ndarray(format="bgr24")
                alto, ancho = bgr.shape[:2]
                if primer_rgb is None:
                    if seleccion_interactiva:
                        nombre = "ROI LED (ENTER confirma)"
                        try:
                            roi = list(cv2.selectROI(nombre, bgr, False, False))
                        finally:
                            cv2.destroyWindow(nombre)
                    if roi is None:
                        raise ValueError("Selecciona el LED o indica ROI X Y ANCHO ALTO")
                    if (len(roi) != 4 or any(not np.isfinite(v) or int(v) != v for v in roi)):
                        raise ValueError("ROI requiere cuatro coordenadas enteras")
                    roi = list(map(int, roi))
                    primer_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                x, y, w, h = roi
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > ancho or y + h > alto:
                    raise ValueError(f"ROI fuera de la imagen ({ancho} x {alto}) o vacia")
                gris = cv2.cvtColor(bgr[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
                intensidades.append(float(gris.mean()))
                saturados += int(np.count_nonzero(gris >= 250))
                pixeles += gris.size
                tiempos.append(tiempo)
                duraciones.append(duracion)
                indices.append(indice)
    except av.error.FFmpegError as error:
        raise ValueError(f"No se pudo decodificar el video completo: {error}") from error

    if not intensidades:
        raise ValueError("No hay cuadros en el tramo seleccionado")
    if not detenido_por_fin and esperados and cantidad < esperados:
        raise ValueError(f"Video incompleto: se leyeron {cantidad} de {esperados} cuadros declarados")
    tiempos = np.asarray(tiempos, dtype=float)
    intervalos = np.diff(tiempos)
    if not len(intervalos):
        raise ValueError("Selecciona al menos dos cuadros para comprobar los tiempos")
    mediana = float(np.median(intervalos))
    ultimo_intervalo = duraciones[-1]
    fin_estimado = ultimo_intervalo is None or not np.isfinite(ultimo_intervalo) or ultimo_intervalo <= 0
    if fin_estimado:
        ultimo_intervalo = mediana
    # Los PTS indican el principio de presentacion de cada cuadro. El ultimo
    # intervalo viene del contenedor o, si falta, de la mediana, y se documenta.
    duraciones = np.r_[intervalos, ultimo_intervalo]
    if fin is not None:
        duraciones[-1] = min(duraciones[-1], fin - tiempos[-1])
    if (not detenido_por_fin and duracion_declarada is not None and ultimo is not None
            and duracion_declarada - (ultimo[0] + ultimo_intervalo) > max(.2, 3 * mediana)):
        raise ValueError("El video termina antes de su duracion declarada; posible archivo incompleto")

    variable = not np.allclose(intervalos, mediana, rtol=.005, atol=.000002)
    saltos = np.flatnonzero(intervalos > 2.5 * mediana)
    advertencias = []
    if variable:
        advertencias.append("FPS variables: duraciones medidas con PTS originales, sin convertir el video")
    if len(saltos):
        advertencias.append(f"{len(saltos)} intervalos mayores a 2,5 veces la mediana: revisar posibles cuadros ausentes")
    if fin_estimado:
        advertencias.append("El ultimo cuadro no declara duracion; se usa la mediana solo para su final")
    valores = np.asarray(intensidades)
    nivel_bajo, nivel_alto = np.quantile(valores, [.1, .9])
    contraste = float(nivel_alto - nivel_bajo)
    if contraste < 10:
        advertencias.append("Contraste P90-P10 inferior a 10 niveles digitales: revisar ROI, luz y saturacion")
    fraccion_saturada = float(saturados / pixeles)
    if fraccion_saturada > .05:
        advertencias.append("Hay pixeles de la ROI cercanos a saturacion; comprobar exposicion en los cuadros ON")
    fs = 1 / mediana
    if fps_nominal and abs(fs - fps_nominal) / fs < .005 and not variable:
        fs = fps_nominal
    diagnostico = dict(
        variable_frame_rate=bool(variable), interval_min_s=float(intervalos.min()),
        interval_median_s=mediana, interval_max_s=float(intervalos.max()),
        large_interval_count=len(saltos), large_interval_times_s=tiempos[saltos].tolist(),
        nominal_fps=fps_nominal, effective_fps=fs, contrast_p90_p10=contraste,
        saturation_fraction=fraccion_saturada, last_duration_estimated=fin_estimado,
        processing="Brillo medio original de ROI; sin suavizado ni cuadros artificiales",
        edge_rule="Transicion asignada al PTS del primer cuadro con el nuevo estado; precision limitada por exposicion e intervalo entre muestras",
        warnings=advertencias,
    )
    return dict(
        intensity=valores, time=tiempos, frame_durations=duraciones, fs=fs,
        roi=roi, first_frame=primer_rgb,
        metadata=dict(
            source=str(ruta.resolve()), fps=fs, nominal_fps=fps_nominal,
            frames=len(valores), frame_size=[ancho, alto], start=inicio, end=fin,
            timing="PTS originales por cuadro (PyAV)",
            timestamp_origin_s=origen, first_frame_index=indices[0],
            last_frame_index=indices[-1], warnings=advertencias, diagnostics=diagnostico,
        ),
    )
