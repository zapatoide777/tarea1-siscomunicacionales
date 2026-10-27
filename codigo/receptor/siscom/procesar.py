"""Une la lectura, la decodificación y los resultados de cada video."""

import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform

from matplotlib import pyplot as plt
import numpy as np

from .analisis import (
    analizar_senal,
    calcular_cer,
    figura_comparacion,
    figura_distancia,
    figura_espectro,
    figura_senal,
)
from .receptor import decodificar, extraer_video


def convertir_para_json(valor):
    """Convierte valores de NumPy en tipos que el módulo json puede guardar."""
    # Los cálculos usan arreglos de NumPy; JSON necesita listas y números comunes.
    if isinstance(valor, np.ndarray):
        return valor.tolist()
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, dict):
        return {
            clave: convertir_para_json(contenido)
            for clave, contenido in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [convertir_para_json(contenido) for contenido in valor]
    return valor


def escribir_json(ruta, datos):
    """Crea el directorio necesario y escribe un objeto como JSON legible."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(convertir_para_json(datos), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def escribir_csv(ruta, filas, campos=None):
    """Escribe filas como CSV compatible con Excel y otros lectores comunes."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    filas = list(filas)
    if campos is None:
        campos = list(filas[0]) if filas else []
    with ruta.open("w", newline="", encoding="utf-8-sig") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(filas)


def procesar_video(ruta_video, configuracion, roi=None, inicio=0., fin=None, salida=None,
                   incluir_espectro=True):
    """Extrae y decodifica la señal; el espectro es opcional.

    La configuración aporta el umbral y los tiempos de calibración. La ROI se
    puede desplazar, pero su ancho y alto deben coincidir con los calibrados.
    Si se indica ``salida``, también se exportan los resultados. La interfaz
    usa ``incluir_espectro=False`` para entregar solo las tareas del receptor.
    """
    # Se puede mover la ROI para centrar el LED, pero debe conservar su tamaño.
    if roi is None:
        roi = configuracion["roi"]
    if list(roi)[2:] != list(configuracion["roi"])[2:]:
        raise ValueError("Mantener ancho y alto de ROI de la calibracion")

    # Del video sale una curva de brillo; de esa curva salen texto y espectro.
    datos_senal = extraer_video(ruta_video, roi=roi, inicio=inicio, fin=fin)
    resultado = decodificar(
        datos_senal["intensity"], datos_senal["fs"], configuracion,
        tiempos=datos_senal["time"], duraciones=datos_senal["frame_durations"],
    )
    resultado["warnings"] += datos_senal["metadata"]["warnings"]
    espectro = (analizar_senal(datos_senal["intensity"], datos_senal["fs"], datos_senal["time"])
                if incluir_espectro else None)
    datos_procesados = dict(
        signal=datos_senal, result=resultado, spectrum=espectro, config=configuracion
    )

    if salida is not None:
        if incluir_espectro:
            exportar_resultado(datos_procesados, salida)
        else:
            exportar_recepcion(datos_procesados, salida)
    return datos_procesados


def exportar_recepcion(datos, salida):
    """Entrega los datos exigidos para el receptor sin generar análisis espectral."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    senal, resultado, config = datos["signal"], datos["result"], datos["config"]
    (salida / "texto_recibido.txt").write_text(resultado["text"], encoding="utf-8")
    escribir_json(salida / "resultado.json", resultado)
    escribir_json(salida / "calibracion_utilizada.json", config)
    escribir_json(salida / "video.json", {
        "video": senal["metadata"]["source"], "roi": senal["roi"],
        "fs_efectiva_hz": senal["fs"], "fps_nominal": senal["metadata"]["nominal_fps"],
        "inicio_s": float(senal["time"][0]),
        "tiempos_decisiones": "Segundos relativos al primer cuadro del tramo seleccionado",
        "avisos_recepcion": resultado["warnings"],
    })
    escribir_csv(salida / "senal.csv", [dict(time=float(t), intensity=float(i))
                 for t, i in zip(senal["time"], senal["intensity"])])
    for nombre, figura in (
        ("senal", figura_senal(senal["time"], senal["intensity"], config["threshold"], senal["fs"])),
    ):
        figura.savefig(salida / f"{nombre}.png", dpi=160)
        plt.close(figura)


def exportar_resultado(datos, salida):
    """Guarda el texto, las decisiones, metadatos, datos numéricos y figuras.

    El texto esperado no se entrega al decodificador. Solo se usa más tarde
    para calcular el error de la evaluación.
    """
    directorio_salida = Path(salida)
    directorio_salida.mkdir(parents=True, exist_ok=True)
    datos_senal = datos["signal"]
    resultado = datos["result"]
    espectro = datos["spectrum"]

    # Conserva tanto el texto final como cada decisión sobre puntos y pausas.
    (directorio_salida / "texto_recibido.txt").write_text(
        resultado["text"], encoding="utf-8"
    )
    escribir_json(directorio_salida / "resultado.json", resultado)
    escribir_json(directorio_salida / "calibracion_utilizada.json", datos["config"])

    # Anota de qué video salieron los datos y con qué versiones se procesaron.
    metadatos = dict(datos_senal["metadata"])
    metadatos["roi"] = datos_senal["roi"]
    metadatos["python"] = platform.python_version()
    metadatos["versions"] = {
        paquete: importlib.metadata.version(paquete)
        for paquete in ["numpy", "scipy", "opencv-python", "matplotlib", "av"]
    }
    with Path(metadatos["source"]).open("rb") as archivo_video:
        metadatos["sha256_video"] = hashlib.file_digest(archivo_video, "sha256").hexdigest()
    metadatos["decision_times"] = "start/end relativos al primer cuadro del tramo extraido"
    metadatos["decision_video_offset_s"] = float(datos_senal["time"][0])
    metadatos["spectrum_estimation"] = {
        clave: valor for clave, valor in espectro.items() if not isinstance(valor, np.ndarray)
    }
    escribir_json(directorio_salida / "metadatos.json", metadatos)
    escribir_json(directorio_salida / "diagnostico.json", {
        **metadatos["diagnostics"],
        "threshold": datos["config"]["threshold"],
        "calibration_off_level": datos["config"].get("off_level"),
        "calibration_on_level": datos["config"].get("on_level"),
        "spectrum_sampling": espectro["sampling"],
        "spectrum_method": espectro["method"],
        "psd_integration": espectro["integration_method"],
        "parseval_ok": espectro["parseval_ok"],
        "parseval_absolute_error": espectro["parseval_absolute_error"],
        "warnings": resultado["warnings"],
    })

    # Estos CSV permiten revisar por separado la curva y los cálculos.
    filas_senal = []
    for tiempo_s, nivel in zip(datos_senal["time"], datos_senal["intensity"]):
        filas_senal.append(dict(time=tiempo_s, intensity=nivel))
    escribir_csv(directorio_salida / "senal.csv", filas_senal)
    escribir_csv(directorio_salida / "senal_espectro.csv", [
        dict(time=float(t), intensity=float(y))
        for t, y in zip(espectro["sample_time"], espectro["sample_intensity"])
    ])
    escribir_csv(
        directorio_salida / "decisiones.csv",
        resultado["decisions"],
        [
            "state", "start", "end", "duration", "frames",
            "units_measured", "kind", "valid", "pattern",
        ],
    )
    filas_fft = []
    for frecuencia, amplitud in zip(espectro["fft_f"], espectro["amplitude"]):
        filas_fft.append(dict(frequency=frecuencia, amplitude=amplitud))
    escribir_csv(directorio_salida / "fft.csv", filas_fft)

    filas_psd = []
    datos_psd = zip(espectro["psd_f"], espectro["psd"], espectro["cumulative"])
    for frecuencia, potencia, area in datos_psd:
        filas_psd.append(dict(frequency=frecuencia, psd=potencia, cumulative=area))
    escribir_csv(directorio_salida / "psd.csv", filas_psd)
    escribir_json(
        directorio_salida / "espectro.json",
        {clave: valor for clave, valor in espectro.items() if not isinstance(valor, np.ndarray)},
    )

    # Guarda una figura del brillo en el tiempo y otra de sus frecuencias.
    figuras = [
        ("senal", figura_senal(
            datos_senal["time"], datos_senal["intensity"], datos["config"]["threshold"]
        )),
        ("espectro", figura_espectro(espectro)),
    ]
    for nombre, figura in figuras:
        if datos["config"].get("synthetic"):
            figura.suptitle("DATOS SINTETICOS - prueba de software")
        figura.savefig(directorio_salida / f"{nombre}.png", dpi=160)
        figura.savefig(directorio_salida / f"{nombre}.pdf")
        plt.close(figura)
    return directorio_salida

# Comparación de los cuatro videos grabados a distintas distancias.


def evaluar_ensayos(manifiesto, configuracion, salida):
    """Procesa los ensayos descritos en un manifiesto y guarda sus resultados.

    Las rutas de video relativas se interpretan desde la carpeta del manifiesto.
    ``configuracion`` es la calibración común a todos los ensayos y ``salida`` es la
    carpeta donde se guardan las tablas, gráficas y exportaciones individuales.
    """
    # ensayos.json indica la distancia y la ruta de cada grabación.
    ruta_manifiesto = Path(manifiesto).resolve()
    especificacion = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
    ensayos = especificacion["trials"]
    distancias = [float(ensayo["distance_m"]) for ensayo in ensayos]

    if sorted(distancias) != [0.5, 1.0, 2.0, 3.0]:
        raise ValueError("Se requieren exactamente cuatro ensayos: 0,5;1;2;3 m")

    referencia = especificacion.get("reference", "SIS COM")
    if referencia != "SIS COM":
        raise ValueError("El ensayo oficial evalua SIS COM, incluyendo espacio")

    carpeta_salida = Path(salida)
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    filas_resultado = []
    procesados_por_distancia = {}

    for ensayo in ensayos:
        distancia = float(ensayo["distance_m"])
        fila_resultado = dict(
            distance_m=distancia,
            duration_s=None,
            S=None,
            D=None,
            I=None,
            errors=None,
            cer=None,
            text="",
            exact=False,
            status="",
            detail="",
            synthetic=bool(especificacion.get("synthetic", False)),
        )

        # Una grabación declarada inválida queda registrada sin inventar CER.
        if ensayo.get("valid", True) is False:
            fila_resultado.update(
                status="sin adquisicion valida",
                detail=ensayo.get("note", "Fallo declarado de grabacion"),
            )
        else:
            ruta_video = Path(ensayo["video"])
            if not ruta_video.is_absolute():
                ruta_video = ruta_manifiesto.parent / ruta_video

            try:
                salida_ensayo = carpeta_salida / f"distancia_{distancia:g}m"
                datos_video = procesar_video(
                    ruta_video,
                    configuracion,
                    roi=ensayo.get("roi"),
                    inicio=ensayo.get("start_s", 0.0),
                    fin=ensayo.get("end_s"),
                    salida=salida_ensayo,
                )

                # SIS COM se usa aquí, después de reconstruir el texto del video.
                metricas = calcular_cer(referencia, datos_video["result"]["text"])
                fila_resultado.update(
                    duration_s=datos_video["result"]["duration"],
                    text=datos_video["result"]["text"],
                    **{
                        clave: metricas[clave]
                        for clave in ["S", "D", "I", "errors", "cer", "exact"]
                    },
                    status="procesado",
                )
                procesados_por_distancia[distancia] = datos_video
            except (ValueError, OSError) as error:
                fila_resultado.update(
                    status="error de procesamiento",
                    detail=str(error),
                )

        filas_resultado.append(fila_resultado)

    # La tabla incluye también los intentos fallidos para no perderlos.
    escribir_csv(carpeta_salida / "tabla_resultados.csv", filas_resultado)
    escribir_json(
        carpeta_salida / "evaluacion.json",
        dict(
            synthetic=bool(especificacion.get("synthetic", False)),
            reference=referencia,
            trials=filas_resultado,
            manifest=especificacion,
            calibration=configuracion,
        ),
    )

    grafico_cer = figura_distancia(filas_resultado)
    if especificacion.get("synthetic"):
        grafico_cer.suptitle("DATOS SINTETICOS - no son mediciones fisicas")
    grafico_cer.savefig(carpeta_salida / "cer_distancia.png", dpi=160)
    grafico_cer.savefig(carpeta_salida / "cer_distancia.pdf")
    plt.close(grafico_cer)

    estado_comparacion = "No hay ambos ensayos procesados"
    if 0.5 in procesados_por_distancia and 3.0 in procesados_por_distancia:
        try:
            grafico_comparacion = figura_comparacion(
                procesados_por_distancia[0.5],
                procesados_por_distancia[3.0],
                configuracion["threshold"],
                ventana=especificacion.get("comparison_window_s", [0, 3]),
            )
            if especificacion.get("synthetic"):
                grafico_comparacion.suptitle("DATOS SINTETICOS - prueba de software")
            grafico_comparacion.savefig(
                carpeta_salida / "comparacion_0p5_3m.png", dpi=160
            )
            grafico_comparacion.savefig(carpeta_salida / "comparacion_0p5_3m.pdf")
            plt.close(grafico_comparacion)
            estado_comparacion = "alineado por primer pulso; tramo y escala iguales"
        except ValueError as error:
            # Si falta el primer pulso, dibuja ambos tramos sin alinearlos y
            # deja constancia de que la comparación es menos precisa.
            senal_cercana = procesados_por_distancia[0.5]["signal"]
            senal_lejana = procesados_por_distancia[3.0]["signal"]
            grafico_comparacion, ejes = plt.subplots(
                2, 1, sharey=True, figsize=(9, 5), layout="constrained"
            )

            for eje, senal, etiqueta in zip(
                ejes,
                [senal_cercana, senal_lejana],
                ["0,5m", "3,0m"],
            ):
                tiempo_transcurrido = senal["time"] - senal["time"][0]
                inicio_ventana, fin_ventana = especificacion.get(
                    "comparison_window_s", [0, 3]
                )
                dentro_ventana = (tiempo_transcurrido >= inicio_ventana) & (
                    tiempo_transcurrido <= fin_ventana
                )
                eje.plot(
                    tiempo_transcurrido[dentro_ventana],
                    senal["intensity"][dentro_ventana],
                    label=etiqueta,
                )
                eje.axhline(configuracion["threshold"], ls="--", color="tab:red")
                eje.set(
                    xlabel="Tiempo desde inicio seleccionado (s)",
                    ylabel="Intensidad digital",
                )
                eje.legend()

            grafico_comparacion.suptitle(
                "Sin alineacion por pulso; revisar tramo manual del ensayo"
            )
            if especificacion.get("synthetic"):
                grafico_comparacion.suptitle(
                    "DATOS SINTETICOS - sin alineacion por pulso"
                )
            grafico_comparacion.savefig(
                carpeta_salida / "comparacion_sin_alineacion.png", dpi=160
            )
            plt.close(grafico_comparacion)
            estado_comparacion = (
                str(error) + "; grafico sin alineacion por pulso"
            )

    escribir_json(
        carpeta_salida / "comparacion.json",
        dict(
            status=estado_comparacion,
            window_s=especificacion.get("comparison_window_s", [0, 3]),
        ),
    )

    if especificacion.get("synthetic"):
        (carpeta_salida / "SOLO_DATOS_SINTETICOS.txt").write_text(
            "No son resultados experimentales del grupo.\n",
            encoding="utf-8",
        )

    return filas_resultado
