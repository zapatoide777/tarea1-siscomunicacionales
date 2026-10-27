"""Convierte letras en Morse y luz grabada en letras recibidas."""

import json
from math import isfinite
from pathlib import Path

import numpy as np


# Morse previsto: se usa para documentar lo que debería emitir el Arduino.

# Cada patrón corresponde a la letra que ocupa la misma posición del alfabeto.
# El espacio no está en esta tabla: separa palabras y se trata por separado.
alfabeto = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
tabla_morse = dict(zip(
    alfabeto,
    [
        ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---",
        "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.", "...", "-",
        "..-", "...-", ".--", "-..-", "-.--", "--..",
    ],
))

# Tabla inversa: permite traducir un patrón Morse a su letra correspondiente.
tabla_morse_inversa = {patron: letra for letra, patron in tabla_morse.items()}

# Mensaje conocido que el transmisor puede enviar para la calibración.
texto_calibracion = "AN E"


def normalizar_texto(texto: str) -> str:
    """Valida y normaliza texto para transmitirlo en Morse.

    Solo admite letras ASCII A-Z y espacios. Convierte las letras a mayúsculas,
    reduce espacios repetidos y en los extremos, y limita el mensaje a 80
    caracteres normalizados. Esta función es para la entrada del transmisor;
    no se aplica al texto que el receptor reconstruye.
    """
    caracteres_permitidos = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "
    if any(caracter not in caracteres_permitidos for caracter in texto):
        raise ValueError("Solo se admiten letras A-Z y espacios; sin tildes ni numeros")

    texto_mayusculas = texto.upper()
    if any(
        caracter not in tabla_morse and caracter != " "
        for caracter in texto_mayusculas
    ):
        raise ValueError("Solo se admiten letras A-Z y espacios; sin tildes ni numeros")

    texto_normalizado = " ".join(
        palabra for palabra in texto_mayusculas.split(" ") if palabra
    )
    if not texto_normalizado:
        raise ValueError("El mensaje no puede estar vacio")
    if len(texto_normalizado) > 80:
        raise ValueError("Maximo 80 caracteres normalizados")
    return texto_normalizado


def codificar(texto: str) -> str:
    """Traduce texto válido a Morse con separadores legibles.

    Usa `/` entre letras y `//` entre palabras. La validación y normalización
    se realizan primero mediante :func:`normalizar_texto`.
    """
    texto_normalizado = normalizar_texto(texto)
    palabras = texto_normalizado.split(" ")

    palabras_en_morse = []
    for palabra in palabras:
        letras_en_morse = [tabla_morse[letra] for letra in palabra]
        palabras_en_morse.append(" / ".join(letras_en_morse))

    return " // ".join(palabras_en_morse)


def segmentos(texto: str, duracion_t: float = 0.3) -> list[dict]:
    """Devuelve los tramos ON/OFF ideales de un mensaje.

    El tiempo se expresa en segundos y cada duración conserva también su
    equivalente en unidades T. No incluye los márgenes apagados del video.
    """
    # Aquí no se lee un video: se arma el patrón ideal a partir del texto y T.
    if not isfinite(duracion_t) or duracion_t <= 0:
        raise ValueError("T debe ser positivo y finito")

    texto = normalizar_texto(texto)
    tramos = []
    tiempo_actual = 0.0

    def agregar(estado: int, unidades: int, tipo: str):
        nonlocal tiempo_actual
        tiempo_final = tiempo_actual + unidades * duracion_t
        tramos.append(dict(
            state=estado,
            units=unidades,
            start=tiempo_actual,
            end=tiempo_final,
            duration=tiempo_final - tiempo_actual,
            kind=tipo,
        ))
        tiempo_actual = tiempo_final

    for indice_letra, letra in enumerate(texto):
        if letra == " ":
            continue

        codigo = tabla_morse[letra]
        for indice_simbolo, simbolo in enumerate(codigo):
            es_punto = simbolo == "."
            agregar(1, 1 if es_punto else 3, "punto" if es_punto else "raya")
            if indice_simbolo < len(codigo) - 1:
                agregar(0, 1, "simbolo")

        if indice_letra < len(texto) - 1:
            separa_palabras = texto[indice_letra + 1] == " "
            agregar(0, 7 if separa_palabras else 3,
                    "palabra" if separa_palabras else "letra")

    return tramos

# Del brillo medido al texto recibido.


def separar_tramos(intensidad, fps: float, umbral: float, tiempos=None, duraciones=None) -> list[dict]:
    """Agrupa cuadros consecutivos según el LED esté apagado o encendido.

    Cada resultado conserva los índices temporales como segundos, para que
    las duraciones se puedan comparar con la unidad Morse T.
    """
    intensidades = np.asarray(intensidad, dtype=float)
    if intensidades.ndim != 1 or not np.all(np.isfinite(intensidades)):
        raise ValueError("La intensidad debe ser un vector finito")
    if not np.isfinite(fps) or fps <= 0 or not np.isfinite(umbral):
        raise ValueError("FPS/umbral invalidos")
    if not len(intensidades):
        return []
    # Conserva la API anterior para señales ideales; los videos aportan PTS.
    if tiempos is None:
        limites_tiempo = np.arange(len(intensidades) + 1, dtype=float) / fps
    else:
        tiempos = np.asarray(tiempos, dtype=float)
        if (tiempos.shape != intensidades.shape or not np.all(np.isfinite(tiempos))
                or (len(tiempos) > 1 and np.any(np.diff(tiempos) <= 0))):
            raise ValueError("Los tiempos deben ser finitos, crecientes y coincidir con las muestras")
        if duraciones is not None:
            duraciones = np.asarray(duraciones, dtype=float)
            if (duraciones.shape != tiempos.shape or not np.all(np.isfinite(duraciones))
                    or np.any(duraciones <= 0)):
                raise ValueError("Duraciones de cuadro invalidas")
            duracion_final = float(duraciones[-1])
        elif len(tiempos) > 1:
            duracion_final = float(np.median(np.diff(tiempos)))
        else:
            raise ValueError("Una muestra aislada necesita duracion de cuadro")
        limites_tiempo = np.r_[tiempos - tiempos[0], tiempos[-1] - tiempos[0] + duracion_final]
    # Si el brillo supera el umbral, se considera luz encendida. Se agrupan
    # los cuadros seguidos que tengan el mismo estado.
    led_encendido = intensidades > umbral
    limites_tramos = np.r_[
        0,
        np.flatnonzero(led_encendido[1:] != led_encendido[:-1]) + 1,
        len(led_encendido),
    ]
    tramos = []
    for cuadro_inicial, cuadro_final in zip(limites_tramos[:-1], limites_tramos[1:]):
        tramos.append(dict(
            state=int(led_encendido[cuadro_inicial]),
            start=float(limites_tiempo[cuadro_inicial]),
            end=float(limites_tiempo[cuadro_final]),
            duration=float(limites_tiempo[cuadro_final] - limites_tiempo[cuadro_inicial]),
            frames=int(cuadro_final - cuadro_inicial),
        ))
    return tramos


def decodificar(intensidad, fps: float, configuracion: dict, tiempos=None, duraciones=None) -> dict:
    """Decodifica las rachas de luz usando la calibración indicada.

    Los márgenes sin luz se descartan; luego se clasifican las duraciones
    como puntos, rayas o separaciones y se traducen los patrones a letras.
    """
    unidad_t = float(configuracion["t_seconds"])
    tolerancia = float(configuracion["tolerance_units"])
    if not np.isfinite(unidad_t) or unidad_t <= 0 or not 0 < tolerancia < 1:
        raise ValueError("T/tolerancia invalidos: tolerancia en unidades T debe ser <1")
    todos_los_tramos = separar_tramos(
        intensidad, fps, float(configuracion["threshold"]), tiempos, duraciones
    )
    indices_activos = [
        indice for indice, tramo in enumerate(todos_los_tramos) if tramo["state"]
    ]
    if not indices_activos:
        return dict(text="", morse="", decisions=[], duration=0., warnings=["Sin pulsos detectados"])
    # El tiempo apagado antes y después no pertenece al mensaje Morse.
    tramos_seleccionados = todos_los_tramos[indices_activos[0] : indices_activos[-1] + 1]
    caracteres_decodificados, patrones_decodificados, decisiones = [], [], []
    patron_actual = ""
    advertencias = []

    def terminar_letra():
        """Busca la letra del patrón recibido; usa ? si no existe."""
        nonlocal patron_actual
        if patron_actual:
            caracteres_decodificados.append(tabla_morse_inversa.get(patron_actual, "?"))
            patrones_decodificados.append(patron_actual)
            patron_actual = ""

    for tramo in tramos_seleccionados:
        # Compara la duración observada con los tiempos esperados: 1T o 3T
        # con luz, y 1T, 3T o 7T sin luz. La tolerancia viene de calibrar.
        unidades_medidas = tramo["duration"] / unidad_t
        if tramo["state"]:
            unidades_permitidas = [1, 3]
        else:
            unidades_permitidas = [1, 3, 7]
        unidad_mas_cercana = min(
            unidades_permitidas,
            key=lambda unidad: abs(unidades_medidas - unidad),
        )
        valido = abs(unidades_medidas - unidad_mas_cercana) <= tolerancia + 1e-9
        if tramo["state"]:
            if not valido:
                tipo = "pulso_invalido"
                patron_actual += "!"
            elif unidad_mas_cercana == 1:
                tipo = "punto"
                patron_actual += "."
            else:
                tipo = "raya"
                patron_actual += "-"
        elif not valido:
            # Una pausa fuera de tiempo no se corrige adivinando la frase.
            tipo = "pausa_invalida"
            terminar_letra()
            caracteres_decodificados.append("?")
            patrones_decodificados.append("[pausa?]")
        elif unidad_mas_cercana == 3:
            tipo = "letra"
            terminar_letra()
        elif unidad_mas_cercana == 7:
            tipo = "palabra"
            terminar_letra()
            caracteres_decodificados.append(" ")
            patrones_decodificados.append("/")
        else:
            tipo = "simbolo"
        if not valido:
            advertencias.append(
                f"{tipo} a {tramo['start']:.3f} s ({unidades_medidas:.2f}T)"
            )
        decisiones.append(
            {
                **tramo,
                "units_measured": unidades_medidas,
                "kind": tipo,
                "valid": valido,
                "pattern": patron_actual,
            }
        )

    terminar_letra()
    morse = " / ".join(patrones_decodificados).replace(" / / / ", " // ")
    return dict(
        text="".join(caracteres_decodificados),
        morse=morse,
        decisions=decisiones,
        duration=tramos_seleccionados[-1]["end"] - tramos_seleccionados[0]["start"],
        warnings=advertencias,
    )

# Calibración: usa una grabación conocida de AN E a 0,5 m.


def calibrar(intensidades, fps: float, roi, fuente="", distancia=0.5, tiempos=None, duraciones=None) -> dict:
    """Estima el umbral de brillo, T y tolerancia usando la secuencia CAL.

    La calibracion oficial se hace a 0,5 m. La secuencia conocida permite
    comprobar que los niveles de brillo y la estructura temporal sean validos.
    """
    if distancia != 0.5:
        raise ValueError("La calibracion oficial debe realizarse a 0,5 m")

    intensidades = np.asarray(intensidades, dtype=float)
    if len(intensidades) < 10 or not np.all(np.isfinite(intensidades)):
        raise ValueError("Calibracion insuficiente o invalida")

    # Los valores bajos y altos del video dan una primera idea de cómo se ve
    # el LED apagado y encendido en esta cámara.
    nivel_apagado, nivel_encendido = np.quantile(intensidades, [0.1, 0.9])

    # Repite la separación hasta que los dos niveles de brillo se estabilicen.
    for _ in range(30):
        umbral_estimado = (nivel_apagado + nivel_encendido) / 2
        esta_encendido = intensidades > umbral_estimado
        if not esta_encendido.any() or esta_encendido.all():
            raise ValueError("No se distinguen niveles ON/OFF")

        nuevo_nivel_apagado = intensidades[~esta_encendido].mean()
        nuevo_nivel_encendido = intensidades[esta_encendido].mean()
        if (
            abs(nuevo_nivel_apagado - nivel_apagado)
            + abs(nuevo_nivel_encendido - nivel_encendido)
            < 1e-6
        ):
            break
        nivel_apagado, nivel_encendido = nuevo_nivel_apagado, nuevo_nivel_encendido

    if nivel_encendido - nivel_apagado < 10:
        raise ValueError("Contraste inferior a 10 unidades digitales; revisar ROI y montaje")

    umbral = float((nivel_apagado + nivel_encendido) / 2)

    # Busca los pulsos de AN E y quita los segundos apagados de los extremos.
    tramos_observados = separar_tramos(intensidades, fps, umbral, tiempos, duraciones)
    indices_encendidos = [
        indice for indice, tramo in enumerate(tramos_observados) if tramo["state"]
    ]
    if not indices_encendidos:
        raise ValueError("Calibracion sin pulsos")
    tramos_observados = tramos_observados[
        indices_encendidos[0] : indices_encendidos[-1] + 1
    ]

    # AN E permite comprobar que se distinguen puntos, rayas y pausas.
    tramos_esperados = segmentos(texto_calibracion, 1.)
    if len(tramos_observados) != len(tramos_esperados) or any(
        tramo_observado["state"] != tramo_esperado["state"]
        for tramo_observado, tramo_esperado in zip(tramos_observados, tramos_esperados)
    ):
        raise ValueError("CAL debe contener AN E completo (5 pulsos); revise tramo/ROI")

    # Estima T con todos los tramos; la mediana evita que uno anómalo domine.
    duracion_unidad = float(
        np.median(
            [
                tramo_observado["duration"] / tramo_esperado["units"]
                for tramo_observado, tramo_esperado in zip(
                    tramos_observados, tramos_esperados
                )
            ]
        )
    )
    desviacion_maxima = max(
        abs(tramo_observado["duration"] / duracion_unidad - tramo_esperado["units"])
        for tramo_observado, tramo_esperado in zip(
            tramos_observados, tramos_esperados
        )
    )
    # La tolerancia admite pequeñas diferencias de tiempo entre cuadros.
    intervalo_muestreo = (float(np.max(np.diff(tiempos)))
                         if tiempos is not None and len(tiempos) > 1 else 1 / fps)
    tolerancia = max(0.35, desviacion_maxima + intervalo_muestreo / duracion_unidad)
    if tolerancia >= 1:
        raise ValueError("Calibracion temporal inconsistente; aumentar T o revisar video")

    return dict(
        schema_version=1,
        distance_m=distancia,
        source=str(fuente),
        calibration_text=texto_calibracion,
        threshold=umbral,
        off_level=float(nivel_apagado),
        on_level=float(nivel_encendido),
        t_seconds=duracion_unidad,
        tolerance_units=tolerancia,
        roi=list(map(int, roi)),
        fs_calibration=fps,
        method="Dos grupos de intensidad; mediana duracion/unidades CAL; tolerancia absoluta en T",
        roi_rule="Rectangulo fijo centrado en fuente; mismo ancho y alto en todas las distancias",
        calibration_runs=tramos_observados,
    )


def guardar_configuracion(configuracion: dict, ruta):
    """Guarda los valores de calibración para reutilizarlos después."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(configuracion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def cargar_configuracion(ruta) -> dict:
    """Carga la calibración y comprueba que sus valores sean utilizables."""
    configuracion = json.loads(Path(ruta).read_text(encoding="utf-8"))

    if not isinstance(configuracion, dict):
        raise ValueError("La calibracion debe ser un objeto JSON")
    requeridos = {"schema_version", "distance_m", "threshold", "t_seconds", "tolerance_units", "roi"}
    faltantes = requeridos - configuracion.keys()
    if faltantes:
        raise ValueError("Faltan campos de calibracion: " + ", ".join(sorted(faltantes)))

    if configuracion.get("schema_version") != 1:
        raise ValueError("Version de calibracion no compatible")
    if configuracion.get("distance_m") != 0.5:
        raise ValueError("La configuracion debe provenir de calibracion a 0,5 m")

    for nombre_campo in ["threshold", "t_seconds", "tolerance_units"]:
        try:
            configuracion[nombre_campo] = float(configuracion[nombre_campo])
        except (ValueError, TypeError) as error:
            raise ValueError(f"Parametro no numerico: {nombre_campo}") from error
        if not np.isfinite(configuracion[nombre_campo]):
            raise ValueError(f"Parametro no finito: {nombre_campo}")

    if (
        not 0 <= configuracion["threshold"] <= 255
        or configuracion["t_seconds"] <= 0
        or not 0 < configuracion["tolerance_units"] < 1
    ):
        raise ValueError("Umbral, T o tolerancia fuera de rango")

    roi = configuracion["roi"]
    if not isinstance(roi, list) or len(roi) != 4:
        raise ValueError("ROI de calibracion requiere una lista de cuatro numeros")
    if any(not isinstance(valor, (int, float)) or not np.isfinite(valor) for valor in roi):
        raise ValueError("ROI de calibracion debe contener numeros finitos")
    if (
        len(roi) != 4
        or any(int(valor) != valor for valor in roi)
        or any(valor < 0 for valor in roi[:2])
        or any(valor <= 0 for valor in roi[2:])
    ):
        raise ValueError("ROI de calibracion invalida")

    configuracion["roi"] = list(map(int, roi))

    return configuracion

# Lectura del video: una muestra de brillo por cada cuadro.


def extraer_video(ruta, roi=None, inicio=0., fin=None, seleccion_interactiva=False) -> dict:
    """Mide brillo original con los tiempos reales de presentacion del video."""
    from .video import leer_video
    return leer_video(ruta, roi, inicio, fin, seleccion_interactiva)
