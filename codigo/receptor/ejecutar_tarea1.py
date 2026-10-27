"""Punto de entrada para preparar, calibrar y leer los videos de la tarea.

Ejecuta ``python ejecutar_tarea1.py --help`` para ver los comandos y
``python ejecutar_tarea1.py COMANDO --help`` para consultar sus opciones.

Ejemplos (desde la carpeta ``codigo/receptor``)::

    python ejecutar_tarea1.py patron --texto "SIS COM"
    python ejecutar_tarea1.py calibrar --video ../../datos/calibracion/calibracion.mp4
    python ejecutar_tarea1.py decodificar --video ../../datos/videos_originales/mensaje.mp4
    python ejecutar_tarea1.py evaluar --ensayos ../../ensayos.json
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys

from siscom.receptor import (
    calibrar,
    cargar_configuracion,
    codificar,
    extraer_video,
    guardar_configuracion,
    normalizar_texto,
    segmentos,
)
from siscom.procesar import evaluar_ensayos, procesar_video, escribir_csv, escribir_json


# Las salidas predeterminadas se guardan dentro de la carpeta de la tarea.
CARPETA_TAREA = Path(__file__).resolve().parents[2]


def agregar_argumentos_video(analizador_comando):
    """Añade las opciones compartidas por calibrar y decodificar."""
    analizador_comando.add_argument("--video", required=True, type=Path)
    analizador_comando.add_argument(
        "--roi", nargs=4, type=int, metavar=("X", "Y", "ANCHO", "ALTO")
    )
    analizador_comando.add_argument("--inicio", type=float, default=0.0)
    analizador_comando.add_argument("--fin", type=float)


def crear_analizador():
    """Define los cuatro comandos disponibles desde la terminal."""
    analizador = argparse.ArgumentParser(
        description="Enlace optico Morse Arduino + Python"
    )
    comandos = analizador.add_subparsers(dest="comando", required=True)

    # "patron" deja por escrito los pulsos que deberían verse en el video.
    patron = comandos.add_parser("patron", help="Exportar patron Morse previsto")
    patron.add_argument("--texto", default="SIS COM")
    patron.add_argument("--t-ms", type=int, default=300)
    patron.add_argument("--salida", type=Path)

    # "calibrar" usa el video corto de AN E para fijar umbral, T y tolerancia.
    calibracion = comandos.add_parser(
        "calibrar", help="Calibrar una vez a 0,5m con video CAL AN E"
    )
    agregar_argumentos_video(calibracion)
    calibracion.add_argument("--seleccionar-roi", action="store_true")
    calibracion.add_argument(
        "--salida", type=Path,
        default=CARPETA_TAREA / "resultados/calibracion.json",
    )

    # "decodificar" sirve también para la palabra nueva de la demostración.
    decodificacion = comandos.add_parser(
        "decodificar", help="Reconstruir texto solo a partir del video"
    )
    agregar_argumentos_video(decodificacion)
    decodificacion.add_argument(
        "--config", type=Path,
        default=CARPETA_TAREA / "resultados/calibracion.json",
    )
    decodificacion.add_argument("--salida", type=Path)

    # "evaluar" lee los cuatro videos indicados en ensayos.json.
    evaluacion = comandos.add_parser(
        "evaluar", help="Procesar cuatro distancias y calcular CER despues"
    )
    evaluacion.add_argument("--ensayos", type=Path, required=True)
    evaluacion.add_argument(
        "--config", type=Path,
        default=CARPETA_TAREA / "resultados/calibracion.json",
    )
    evaluacion.add_argument("--salida", type=Path)
    return analizador


def ejecutar_patron(argumentos, carpeta_salida):
    """Guarda el patrón temporal ideal para el texto solicitado."""
    texto = normalizar_texto(argumentos.texto)
    tramos = segmentos(texto, argumentos.t_ms / 1000)
    total_unidades = sum(tramo["units"] for tramo in tramos)
    duracion_segundos = tramos[-1]["end"]

    # El CSV describe cuándo se enciende y apaga la luz; el JSON resume el mensaje.
    escribir_csv(carpeta_salida / "patron_previsto.csv", tramos)
    escribir_json(
        carpeta_salida / "mensaje.json",
        dict(
            text=texto,
            morse=codificar(texto),
            t_ms=argumentos.t_ms,
            units=total_unidades,
            duration=duracion_segundos,
        ),
    )
    print(codificar(texto))
    print(f"{total_unidades}T; {duracion_segundos:.3f} s")


def ejecutar_calibracion(argumentos, ruta_salida):
    """Extrae la señal CAL del video y guarda su configuración."""
    # Primero mide el brillo cuadro a cuadro; luego obtiene los valores fijos
    # que se usarán para todos los videos del mensaje.
    datos_video = extraer_video(
        argumentos.video,
        roi=argumentos.roi,
        inicio=argumentos.inicio,
        fin=argumentos.fin,
        seleccion_interactiva=argumentos.seleccionar_roi,
    )
    configuracion = calibrar(
        datos_video["intensity"],
        datos_video["fs"],
        datos_video["roi"],
        fuente=argumentos.video,
        tiempos=datos_video["time"],
        duraciones=datos_video["frame_durations"],
    )
    configuracion["video_metadata"] = datos_video["metadata"]
    guardar_configuracion(configuracion, ruta_salida)
    print(
        f"Umbral {configuracion['threshold']:.2f}; T {configuracion['t_seconds']:.4f} s; "
        f"tolerancia {configuracion['tolerance_units']:.3f}T"
    )


def ejecutar_decodificacion(argumentos, carpeta_salida):
    """Decodifica el video usando los parámetros de calibración guardados."""
    # El texto recibido se calcula desde el video, sin entregarle una respuesta.
    datos_procesados = procesar_video(
        argumentos.video,
        cargar_configuracion(argumentos.config),
        roi=argumentos.roi,
        inicio=argumentos.inicio,
        fin=argumentos.fin,
        salida=carpeta_salida,
    )
    resultado = datos_procesados["result"]
    print(f"Texto recibido: {resultado['text']!r}")
    print(f"Morse: {resultado['morse']}")
    for advertencia in resultado["warnings"]:
        print("Aviso:", advertencia)


def ejecutar_evaluacion(argumentos, carpeta_salida):
    """Evalúa los ensayos y devuelve 2 si hubo errores de procesamiento."""
    # La comparación con SIS COM ocurre después de reconstruir cada texto.
    filas = evaluar_ensayos(
        argumentos.ensayos, cargar_configuracion(argumentos.config), carpeta_salida
    )
    for fila in filas:
        print(
            f"{fila['distance_m']:g} m: {fila['text']!r}, "
            f"CER={fila['cer']}, {fila['status']}"
        )

    if any(fila["status"] == "error de procesamiento" for fila in filas):
        print(f"Resultados parciales en {carpeta_salida}", file=sys.stderr)
        return 2
    return None


def principal(argumentos_linea=None):
    """Interpreta los argumentos, ejecuta el subcomando y devuelve su estado."""
    argumentos = crear_analizador().parse_args(argumentos_linea)
    # Si no se indicó --salida, crea un nombre distinto para cada ejecución.
    salida_predeterminada = CARPETA_TAREA / "resultados" / (
        argumentos.comando + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    ruta_salida = getattr(argumentos, "salida", None) or salida_predeterminada

    try:
        if argumentos.comando == "patron":
            ejecutar_patron(argumentos, ruta_salida)
        elif argumentos.comando == "calibrar":
            ejecutar_calibracion(argumentos, ruta_salida)
        elif argumentos.comando == "decodificar":
            ejecutar_decodificacion(argumentos, ruta_salida)
        elif argumentos.comando == "evaluar":
            estado = ejecutar_evaluacion(argumentos, ruta_salida)
            if estado is not None:
                return estado
        print(f"Salida: {ruta_salida.resolve()}")
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(principal())
