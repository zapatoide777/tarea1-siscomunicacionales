"""Ventana local para revisar videos y probar el receptor óptico Morse.

Ejecutar desde el lanzador abrir_interfaz.cmd en la raíz del proyecto.
Las operaciones largas trabajan en un hilo; Tk se utiliza solo desde el principal.
"""

from datetime import datetime
import json
import math
import os
from pathlib import Path
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import av
import cv2
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import numpy as np

from siscom.analisis import analizar_senal, calcular_cer, figura_senal, figura_espectro
from siscom.procesar import escribir_csv, escribir_json, procesar_video
from siscom.receptor import (
    calibrar, cargar_configuracion, decodificar, extraer_video, guardar_configuracion,
)


CARPETA_TAREA = Path(__file__).resolve().parents[2]
VIDEOS = CARPETA_TAREA / "datos" / "videos_originales"
RESULTADOS = CARPETA_TAREA / "resultados"


def nueva_salida(etiqueta):
    ruta = RESULTADOS / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + etiqueta)
    ruta.mkdir(parents=True, exist_ok=False)
    return ruta


def indexar_video(ruta):
    """Conserva los PTS y un cuadro; no carga el video completo en memoria."""
    tiempos = []
    primero = None
    duracion_ultimo = None
    try:
        with av.open(str(ruta)) as contenedor:
            if not contenedor.streams.video:
                raise ValueError("El archivo no contiene una pista de video.")
            pista = contenedor.streams.video[0]
            declarados = pista.frames
            for cuadro in contenedor.decode(pista):
                if cuadro.pts is None or cuadro.time_base is None:
                    raise ValueError("Faltan tiempos de presentación fiables en el video.")
                tiempo = float(cuadro.pts * cuadro.time_base)
                if not math.isfinite(tiempo) or (tiempos and tiempo <= tiempos[-1]):
                    raise ValueError("Los tiempos del video son inconsistentes o no avanzan.")
                if cuadro.is_corrupt:
                    raise ValueError("Se encontró un cuadro dañado. Conserva el archivo original.")
                tiempos.append(tiempo)
                if primero is None:
                    primero = cuadro.to_ndarray(format="rgb24")
                duracion = getattr(cuadro, "duration", None)
                if duracion and duracion > 0:
                    duracion_ultimo = float(duracion * cuadro.time_base)
    except av.error.FFmpegError as error:
        raise ValueError(f"No se pudo leer el video: {error}") from error
    if not tiempos:
        raise ValueError("No se encontraron cuadros en el archivo.")
    if declarados and len(tiempos) < declarados:
        raise ValueError("La lectura terminó antes de los cuadros declarados: video incompleto.")
    tiempos = np.asarray(tiempos, dtype=float)
    tiempos -= tiempos[0]
    intervalos = np.diff(tiempos)
    mediana = float(np.median(intervalos)) if len(intervalos) else duracion_ultimo
    if mediana is None or mediana <= 0:
        raise ValueError("No hay suficientes tiempos para medir la duración del video.")
    return {
        "times": tiempos,
        "first_frame": primero,
        "duration": float(tiempos[-1] + (duracion_ultimo or mediana)),
        "fps": 1 / mediana,
        "variable": bool(len(intervalos) and not np.allclose(intervalos, mediana, rtol=.001, atol=1e-6)),
        "min_interval": float(intervalos.min()) if len(intervalos) else mediana,
        "max_interval": float(intervalos.max()) if len(intervalos) else mediana,
    }


def foto_tk(rgb, ancho, alto):
    """Convierte RGB a una imagen de Tk sin depender de Pillow."""
    original_alto, original_ancho = rgb.shape[:2]
    escala = min(ancho / original_ancho, alto / original_alto)
    nuevo_ancho = max(1, round(original_ancho * escala))
    nuevo_alto = max(1, round(original_alto * escala))
    interpolacion = cv2.INTER_NEAREST if escala > 1 else cv2.INTER_AREA
    reducido = cv2.resize(rgb, (nuevo_ancho, nuevo_alto), interpolation=interpolacion)
    cabecera = f"P6\n{nuevo_ancho} {nuevo_alto}\n255\n".encode("ascii")
    return tk.PhotoImage(data=cabecera + reducido.tobytes(), format="PPM"), escala


class Aplicacion:
    def __init__(self, ventana):
        self.ventana = ventana
        self.ventana.title("Videos Morse · Sistemas de Comunicaciones")
        self.ventana.geometry("1280x820")
        self.ventana.minsize(1100, 720)
        self.cola = queue.Queue()
        self.ocupado = False
        self.configuracion = None
        self.ruta_config = None
        self.video = None
        self.info = None
        self.captura = None
        self.cuadro_rgb = None
        self.indice = 0
        self.salida = None
        self.imagenes_graficos = {}
        self.fotos_graficos = {}
        self.rectangulo = None
        self.arrastre = None
        self.actualizar_pendiente = None
        self.actualizando_deslizador = False
        self.escala = 1
        self.origen = (0, 0)
        self.giro = 0
        self.zoom = 1.0
        self.centro_vista = None
        self.recorte_vista = (0, 0)
        self.arrastre_vista = None
        self.vista_texto = tk.StringVar(value="Vista completa")
        self.acciones = []
        self.inicio = tk.StringVar(value="0")
        self.fin = tk.StringVar(value="")
        self.referencia = tk.StringVar(value="")
        self.roi = [tk.StringVar(value=str(valor)) for valor in (0, 0, 6, 5)]
        self.modo_roi = tk.StringVar(value="recentrar")
        self.estado = tk.StringVar(value="Abre un video o pulsa Ejemplo 0,5 m para comenzar.")
        self.video_texto = tk.StringVar(value="Ningún video abierto")
        self.cal_texto = tk.StringVar(value="Sin calibración")
        self.cuadro_texto = tk.StringVar(value="Cuadro — · tiempo —")
        self.resultado_texto = tk.StringVar(value="—")
        self.morse_texto = tk.StringVar(value="")
        self.cer_texto = tk.StringVar(value="CER: sin referencia")
        self._construir()
        calibracion = RESULTADOS / "calibracion.json"
        if calibracion.is_file():
            try:
                self._aplicar_config(cargar_configuracion(calibracion), calibracion)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self._log(f"No se pudo cargar la calibración inicial: {error}")
        self.ventana.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.ventana.after(100, self._revisar_cola)

    def _boton(self, padre, texto, orden, **grid):
        boton = ttk.Button(padre, text=texto, command=orden)
        boton.grid(**grid)
        self.acciones.append(boton)
        return boton

    def _construir(self):
        estilo = ttk.Style()
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        estilo.configure("Result.TLabel", font=("Segoe UI", 19, "bold"))
        base = ttk.Frame(self.ventana, padding=12)
        base.pack(fill="both", expand=True)
        ttk.Label(base, text="Prueba de videos · Comunicación óptica Morse", style="Title.TLabel").pack(anchor="w")
        ttk.Label(base, text="1. Abre el video   →   2. Selecciona el LED   →   3. Decodifica con la calibración cargada").pack(anchor="w", pady=(3, 10))
        barra = ttk.Frame(base)
        barra.pack(fill="x", pady=(0, 8))
        self._boton(barra, "Abrir video…", self._elegir_video, row=0, column=0, padx=(0, 5))
        self._boton(barra, "Ejemplo 0,5 m", self._ejemplo, row=0, column=1, padx=5)
        self._boton(barra, "Cargar calibración…", self._elegir_config, row=0, column=2, padx=5)
        self._boton(barra, "Abrir resultados", self._abrir_salida, row=0, column=3, padx=5)
        ttk.Label(base, textvariable=self.cal_texto, wraplength=1080).pack(anchor="w", pady=(0, 8))
        panel = ttk.Panedwindow(base, orient="horizontal")
        panel.pack(fill="both", expand=True)
        izquierda = ttk.Frame(panel, padding=(0, 0, 10, 0))
        controles = ttk.Frame(panel, padding=(8, 0, 12, 0))
        derecha = ttk.Frame(panel)
        panel.add(izquierda, weight=1)
        panel.add(controles, weight=0)
        panel.add(derecha, weight=2)
        controles.columnconfigure(0, weight=1)
        izquierda.columnconfigure(0, weight=1)
        izquierda.rowconfigure(1, weight=1)
        ttk.Label(izquierda, textvariable=self.video_texto, wraplength=290).grid(row=0, column=0, sticky="w", pady=(0, 5))
        visor = ttk.Frame(izquierda, width=300, height=534)
        visor.grid(row=1, column=0, sticky="nsew")
        ttk.Label(controles, text="Selección y procesamiento", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.lienzo = tk.Canvas(visor, background="#17212b", highlightthickness=0, width=300, height=534)
        self.lienzo.place(relx=.5, rely=.5, anchor="center", width=300, height=534)
        visor.bind("<Configure>", self._ajustar_visor)
        self.lienzo.bind("<Configure>", lambda evento: self._dibujar())
        self.lienzo.bind("<ButtonPress-1>", self._empezar_roi)
        self.lienzo.bind("<B1-Motion>", self._mover_roi)
        self.lienzo.bind("<ButtonRelease-1>", self._terminar_roi)
        self.lienzo.bind("<MouseWheel>", self._rueda_zoom)
        self.lienzo.bind("<ButtonPress-3>", self._empezar_mover_vista)
        self.lienzo.bind("<B3-Motion>", self._mover_vista)
        self.lienzo.bind("<ButtonRelease-3>", lambda evento: setattr(self, "arrastre_vista", None))
        self.deslizador = ttk.Scale(izquierda, from_=0, to=1, command=self._deslizar)
        self.deslizador.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        transporte = ttk.Frame(izquierda)
        transporte.grid(row=3, column=0, sticky="ew", pady=4)
        self._boton(transporte, "◀ Cuadro", lambda: self._ir_cuadro(self.indice - 1), row=0, column=0)
        self._boton(transporte, "Cuadro ▶", lambda: self._ir_cuadro(self.indice + 1), row=0, column=1, padx=5)
        ttk.Label(transporte, textvariable=self.cuadro_texto).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        tramo = ttk.LabelFrame(controles, text="Tramo a procesar", padding=6)
        tramo.grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Label(tramo, text="Inicio (s)").grid(row=0, column=0)
        entrada = ttk.Entry(tramo, textvariable=self.inicio, width=9)
        entrada.grid(row=0, column=1, padx=4)
        self.acciones.append(entrada)
        self._boton(tramo, "Usar cuadro", lambda: self._marcar_tramo(self.inicio), row=0, column=2, padx=4)
        ttk.Label(tramo, text="Fin (s)").grid(row=1, column=0, pady=4)
        entrada = ttk.Entry(tramo, textvariable=self.fin, width=9)
        entrada.grid(row=1, column=1, padx=4)
        self.acciones.append(entrada)
        self._boton(tramo, "Usar cuadro", lambda: self._marcar_tramo(self.fin), row=1, column=2, padx=4)
        ttk.Label(tramo, text="Fin exclusivo; vacío: final.").grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        region = ttk.LabelFrame(controles, text="Región del LED (píxeles originales)", padding=6)
        region.grid(row=3, column=0, sticky="ew", pady=4)
        for indice, (etiqueta, variable) in enumerate(zip(("X", "Y", "Ancho", "Alto"), self.roi)):
            fila, columna = divmod(indice, 2)
            ttk.Label(region, text=etiqueta).grid(row=fila, column=columna * 2, sticky="w")
            entrada = ttk.Entry(region, textvariable=variable, width=5)
            entrada.grid(row=fila, column=columna * 2 + 1, padx=(3, 9), pady=3)
            entrada.bind("<FocusOut>", lambda evento: self._dibujar())
            entrada.bind("<Return>", lambda evento: self._dibujar())
            self.acciones.append(entrada)
        for fila, (texto, valor) in enumerate((
            ("Recentrar (conserva tamaño calibrado)", "recentrar"),
            ("Dibujar ROI (nueva calibración)", "dibujar"),
        ), start=2):
            control = ttk.Radiobutton(region, text=texto, variable=self.modo_roi, value=valor)
            control.grid(row=fila, column=0, columnspan=8, sticky="w", pady=2)
            self.acciones.append(control)
        botones = ttk.Frame(controles)
        botones.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._boton(botones, "Calibrar con este video", self._calibrar, row=0, column=0, padx=(0, 6))
        self._boton(botones, "Decodificar", self._decodificar, row=0, column=1)
        self.pestanas = ttk.Notebook(derecha)
        self.pestanas.pack(fill="both", expand=True)
        resultado = ttk.Frame(self.pestanas, padding=10)
        self.pestanas.add(resultado, text="Resultado")
        ttk.Label(resultado, text="Texto recibido").pack(anchor="w")
        ttk.Label(resultado, textvariable=self.resultado_texto, style="Result.TLabel", wraplength=480).pack(anchor="w", pady=(5, 8))
        ttk.Label(resultado, textvariable=self.morse_texto, wraplength=480).pack(anchor="w", pady=(0, 8))
        ttk.Label(resultado, text="Referencia opcional (se compara después de decodificar):").pack(anchor="w")
        referencia = ttk.Entry(resultado, textvariable=self.referencia)
        referencia.pack(fill="x", pady=4)
        self.acciones.append(referencia)
        ttk.Label(resultado, textvariable=self.cer_texto, wraplength=460).pack(anchor="w", pady=(0, 8))
        ttk.Label(resultado, text="Resultados").pack(anchor="w")
        contenedor_log = ttk.Frame(resultado)
        contenedor_log.pack(fill="both", expand=True, pady=(5, 0))
        self.log = tk.Text(contenedor_log, wrap="word", font=("Consolas", 10), width=40, height=14, state="disabled")
        scroll = ttk.Scrollbar(contenedor_log, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.graficos = {}
        for nombre in ("Señal", "FFT y PSD"):
            marco = ttk.Frame(self.pestanas)
            self.pestanas.add(marco, text=nombre)
            padre_grafico = marco
            if nombre == "FFT y PSD":
                division = ttk.Panedwindow(marco, orient="vertical")
                division.pack(fill="both", expand=True)
                padre_grafico = ttk.Frame(division, height=300)
                explicacion = ttk.LabelFrame(division, text="Método y cálculo de B95", padding=6)
                division.add(padre_grafico, weight=3)
                division.add(explicacion, weight=2)
                self.metodo_espectro = tk.Text(explicacion, wrap="word", font=("Segoe UI", 10),
                                               width=40, height=11, state="disabled")
                scroll_metodo = ttk.Scrollbar(explicacion, command=self.metodo_espectro.yview)
                self.metodo_espectro.configure(yscrollcommand=scroll_metodo.set)
                self.metodo_espectro.pack(side="left", fill="both", expand=True)
                scroll_metodo.pack(side="right", fill="y")
                self._mostrar_metodo_espectro()
            lienzo = tk.Canvas(padre_grafico, background="white", highlightthickness=0)
            lienzo.pack(fill="both", expand=True)
            lienzo.bind("<Configure>", lambda evento, n=nombre: self._dibujar_grafico(n))
            self.graficos[nombre] = lienzo
        pie = ttk.Frame(base)
        pie.pack(fill="x", pady=(8, 0))
        self.progreso = ttk.Progressbar(pie, mode="indeterminate", length=110)
        self.progreso.pack(side="right", padx=(10, 0))
        ttk.Label(pie, textvariable=self.estado, wraplength=900).pack(side="left", fill="x", expand=True)
        self._log("Receptor: selecciona el LED y el tramo completo del mensaje.\nCalibra una vez a 0,5 m con AN E; reutiliza esa calibración en los mensajes.\nDecodificar muestra texto, señal, FFT y PSD.\nLa referencia solo se usa después para calcular CER, contando los espacios.")

    def _log(self, texto):
        self.log.configure(state="normal")
        self.log.insert("end", str(texto) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _error(self, error):
        self.estado.set("No se pudo completar la operación. Revisa el mensaje de error.")
        self._log(f"ERROR: {error}")
        messagebox.showerror("Revisar entrada", str(error), parent=self.ventana)

    def _iniciar_trabajo(self, mensaje, trabajo, al_terminar):
        if self.ocupado:
            return
        self.ocupado = True
        self.estado.set(mensaje)
        self.progreso.start(12)
        for control in self.acciones:
            control.state(["disabled"])
        self.deslizador.state(["disabled"])
        def ejecutar():
            try:
                self.cola.put(("ok", al_terminar, trabajo()))
            except Exception as error:
                self.cola.put(("error", str(error), traceback.format_exc()))
        threading.Thread(target=ejecutar, daemon=True).start()

    def _revisar_cola(self):
        try:
            while True:
                mensaje = self.cola.get_nowait()
                self.ocupado = False
                self.progreso.stop()
                for control in self.acciones:
                    control.state(["!disabled"])
                self.deslizador.state(["!disabled"])
                if mensaje[0] == "ok":
                    try:
                        mensaje[1](mensaje[2])
                    except Exception as error:
                        self._error(error)
                else:
                    self._log(f"No se completó la operación: {mensaje[1]}")
                    self._error(mensaje[1])
        except queue.Empty:
            pass
        self.ventana.after(100, self._revisar_cola)

    def _elegir_video(self):
        ruta = filedialog.askopenfilename(parent=self.ventana, title="Abrir una grabación original", initialdir=VIDEOS, filetypes=[("Videos", "*.mp4 *.mov *.mkv *.avi *.m4v"), ("Todos los archivos", "*.*")])
        if ruta:
            self._abrir_video(Path(ruta))

    def _ejemplo(self):
        ruta = VIDEOS / "sis_com_0p5m.mp4"
        if not ruta.is_file():
            self._error("No se encuentra el video de ejemplo en datos/videos_originales.")
            return
        self.referencia.set("SIS COM")
        self._abrir_video(ruta)

    def _abrir_video(self, ruta):
        self._iniciar_trabajo("Leyendo los tiempos originales del video…", lambda: (ruta, indexar_video(ruta)), self._video_abierto)

    def _video_abierto(self, datos):
        ruta, info = datos
        if self.captura:
            self.captura.release()
        self.video, self.info = ruta, info
        self.captura = cv2.VideoCapture(str(ruta))
        # La lectura conserva la matriz original. El visor transforma las coordenadas.
        self.captura.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
        self.cuadro_rgb = info["first_frame"]
        alto, ancho = self.cuadro_rgb.shape[:2]
        self.giro = 1 if ancho > alto else 0
        self.zoom = 1.0
        self.centro_vista = None
        self.arrastre = None
        self.arrastre_vista = None
        self.indice = 0
        self.inicio.set("0")
        self.fin.set("")
        self.video_texto.set(f"{ruta.name} · {len(info['times'])} cuadros · {info['duration']:.3f} s · fs efectiva: {info['fps']:.3f} Hz")
        self.deslizador.configure(to=max(0, len(info["times"]) - 1))
        self.deslizador.set(0)
        self._roi_conocida()
        self._actualizar_etiqueta_cuadro()
        self._dibujar()
        tipo = "variable" if info["variable"] else "uniforme"
        self._log(f"Video cargado: {ruta.name}\n{len(info['times'])} cuadros · {info['duration']:.3f} s · muestreo {tipo}.")
        self.estado.set("Video listo. Revisa que el rectángulo verde encierre el LED y pulsa Decodificar.")

    def _roi_conocida(self):
        roi = self.configuracion.get("roi") if self.configuracion else None
        try:
            manifiesto = CARPETA_TAREA / "ensayos.json"
            ensayos = json.loads(manifiesto.read_text(encoding="utf-8"))
            for ensayo in ensayos["trials"]:
                if (manifiesto.parent / ensayo["video"]).resolve() == self.video.resolve():
                    candidata = ensayo.get("roi")
                    if candidata and (roi is None or list(candidata)[2:] == list(roi)[2:]):
                        roi = candidata
                    break
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if roi:
            for variable, valor in zip(self.roi, roi):
                variable.set(str(valor))

    def _elegir_config(self):
        ruta = filedialog.askopenfilename(parent=self.ventana, title="Cargar calibración", initialdir=RESULTADOS, filetypes=[("Calibración JSON", "*.json")])
        if ruta:
            try:
                self._aplicar_config(cargar_configuracion(ruta), Path(ruta))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self._error(error)

    def _aplicar_config(self, config, ruta):
        self.configuracion, self.ruta_config = config, Path(ruta)
        self.cal_texto.set(f"Calibración a 0,5 m: {Path(ruta).name} · T = {config['t_seconds'] * 1000:.1f} ms · umbral = {config['threshold']:.2f} · tolerancia = ±{config['tolerance_units']:.3f} T · ROI {config['roi'][2]} × {config['roi'][3]} px")
        for variable, valor in zip(self.roi, config["roi"]):
            variable.set(str(valor))
        self.modo_roi.set("recentrar")
        if self.video:
            self._roi_conocida()
        self._dibujar()

    def _deslizar(self, valor):
        if self.ocupado or not self.info or self.actualizando_deslizador:
            return
        if self.actualizar_pendiente is not None:
            self.ventana.after_cancel(self.actualizar_pendiente)
        indice = round(float(valor))
        self.actualizar_pendiente = self.ventana.after(90, lambda: self._ir_cuadro(indice))

    def _ir_cuadro(self, indice):
        self.actualizar_pendiente = None
        if self.ocupado or not self.info:
            return
        indice = max(0, min(int(indice), len(self.info["times"]) - 1))
        if indice != self.indice or self.cuadro_rgb is None:
            self.captura.set(cv2.CAP_PROP_POS_FRAMES, indice)
            correcto, cuadro = self.captura.read()
            if not correcto:
                self.estado.set("No se pudo mostrar ese cuadro.")
                return
            self.cuadro_rgb = cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB)
        self.indice = indice
        self.actualizando_deslizador = True
        try:
            self.deslizador.set(indice)
        finally:
            self.actualizando_deslizador = False
        self._actualizar_etiqueta_cuadro()
        self._dibujar()

    def _actualizar_etiqueta_cuadro(self):
        self.cuadro_texto.set(f"Cuadro {self.indice + 1}/{len(self.info['times'])} · {self.info['times'][self.indice]:.3f} s")

    def _marcar_tramo(self, variable):
        if self.info:
            variable.set(f"{self.info['times'][self.indice]:.6f}")

    def _ajustar_visor(self, evento):
        """El visor conserva 9:16 aunque se redimensione la ventana o los paneles."""
        ancho = max(1, min(evento.width, evento.height * 9 / 16))
        alto = ancho * 16 / 9
        self.lienzo.place_configure(width=round(ancho), height=round(alto))

    def _punto_vista(self, x, y, inverso=False):
        """Transforma bordes de píxel; la ROI siempre queda en la matriz original."""
        alto, ancho = self.cuadro_rgb.shape[:2]
        if inverso:
            return ((x, y), (y, alto - x), (ancho - x, alto - y), (ancho - y, x))[self.giro]
        return ((x, y), (alto - y, x), (ancho - x, alto - y), (y, ancho - x))[self.giro]

    def _girar_vista(self):
        if self.cuadro_rgb is not None:
            self.giro = (self.giro + 2) % 4
            self._dibujar()

    def _restablecer_vista(self):
        self.zoom = 1.0
        self.centro_vista = None
        self._dibujar()

    def _acercar_led(self):
        if self.cuadro_rgb is None:
            return
        try:
            x, y, ancho, alto = [int(variable.get()) for variable in self.roi]
        except ValueError:
            return
        self.centro_vista = (x + ancho / 2, y + alto / 2)
        self.zoom = max(self.zoom, 4.0)
        self._dibujar()

    def _cambiar_zoom(self, factor, centro=None):
        if self.ocupado or self.cuadro_rgb is None:
            return
        # El zoom se centra en el puntero o en el centro de la vista actual.
        if centro is not None:
            self.centro_vista = centro
        elif self.centro_vista is None:
            alto, ancho = self.cuadro_rgb.shape[:2]
            self.centro_vista = (ancho / 2, alto / 2)
        self.zoom = min(32.0, max(1.0, self.zoom * factor))
        if self.zoom == 1:
            self.centro_vista = None
        self._dibujar()

    def _rueda_zoom(self, evento):
        if evento.delta:
            self._cambiar_zoom(1.5 if evento.delta > 0 else 1 / 1.5, self._coordenada(evento))
        return "break"

    def _empezar_mover_vista(self, evento):
        if not self.ocupado and self.cuadro_rgb is not None:
            self.arrastre_vista = (evento.x, evento.y)

    def _mover_vista(self, evento):
        if self.ocupado or self.arrastre_vista is None:
            return
        x, y = self.centro_vista
        cx, cy = self._punto_vista(x, y)
        dx = (evento.x - self.arrastre_vista[0]) / self.escala
        dy = (evento.y - self.arrastre_vista[1]) / self.escala
        self.centro_vista = self._punto_vista(cx - dx, cy - dy, inverso=True)
        self.arrastre_vista = (evento.x, evento.y)
        self._dibujar()

    def _dibujar(self):
        if self.cuadro_rgb is None:
            return
        ancho = max(1, self.lienzo.winfo_width())
        alto = max(1, self.lienzo.winfo_height())
        imagen = np.rot90(self.cuadro_rgb, k=-self.giro)
        h, w = imagen.shape[:2]
        # Recortar antes de escalar evita crear una imagen gigante al ampliar.
        escala_ajuste = min(ancho / w, alto / h)
        escala_objetivo = escala_ajuste * self.zoom
        visible_w = min(w, max(1, round(ancho / escala_objetivo)))
        visible_h = min(h, max(1, round(alto / escala_objetivo)))
        if self.centro_vista is None:
            cx, cy = w / 2, h / 2
        else:
            cx, cy = self._punto_vista(*self.centro_vista)
        x0 = max(0, min(w - visible_w, round(cx - visible_w / 2)))
        y0 = max(0, min(h - visible_h, round(cy - visible_h / 2)))
        self.recorte_vista = (x0, y0)
        self.centro_vista = self._punto_vista(x0 + visible_w / 2, y0 + visible_h / 2, inverso=True)
        recorte = imagen[y0:y0 + visible_h, x0:x0 + visible_w]
        self.foto, self.escala = foto_tk(recorte, ancho, alto)
        self.vista_texto.set(f"{self.zoom:.1f}× · {self.giro * 90}°")
        self.origen = ((ancho - self.foto.width()) / 2, (alto - self.foto.height()) / 2)
        self.lienzo.delete("all")
        self.lienzo.create_image(*self.origen, anchor="nw", image=self.foto)
        try:
            roi = [int(variable.get()) for variable in self.roi]
            self._pintar_roi(roi)
        except ValueError:
            pass

    def _pintar_roi(self, roi):
        x, y, ancho, alto = roi
        ox, oy = self.origen
        rx, ry = self.recorte_vista
        esquinas = [self._punto_vista(px, py) for px, py in (
            (x, y), (x + ancho, y), (x, y + alto), (x + ancho, y + alto),
        )]
        xs, ys = zip(*esquinas)
        if self.rectangulo:
            self.lienzo.delete(self.rectangulo)
        self.rectangulo = self.lienzo.create_rectangle(
            ox + (min(xs) - rx) * self.escala, oy + (min(ys) - ry) * self.escala,
            ox + (max(xs) - rx) * self.escala, oy + (max(ys) - ry) * self.escala,
            outline="#4ade80", width=2,
        )

    def _coordenada(self, evento):
        if self.cuadro_rgb is None:
            return None
        if not (self.origen[0] <= evento.x < self.origen[0] + self.foto.width()
                and self.origen[1] <= evento.y < self.origen[1] + self.foto.height()):
            return None
        x = (evento.x - self.origen[0]) / self.escala + self.recorte_vista[0]
        y = (evento.y - self.origen[1]) / self.escala + self.recorte_vista[1]
        x, y = self._punto_vista(x, y, inverso=True)
        alto, ancho = self.cuadro_rgb.shape[:2]
        return (max(0, min(ancho - 1, math.floor(x))), max(0, min(alto - 1, math.floor(y))))

    def _empezar_roi(self, evento):
        if self.ocupado or self.cuadro_rgb is None:
            return
        self.arrastre = self._coordenada(evento)
        if self.arrastre is None:
            return
        if self.modo_roi.get() == "recentrar":
            if self.configuracion:
                ancho, alto = self.configuracion["roi"][2:]
            else:
                try:
                    ancho, alto = [int(variable.get()) for variable in self.roi[2:]]
                except ValueError:
                    return
            alto_imagen, ancho_imagen = self.cuadro_rgb.shape[:2]
            ancho = max(1, min(ancho, ancho_imagen))
            alto = max(1, min(alto, alto_imagen))
            x = max(0, min(ancho_imagen - ancho, self.arrastre[0] - ancho // 2))
            y = max(0, min(alto_imagen - alto, self.arrastre[1] - alto // 2))
            self._fijar_roi([x, y, ancho, alto])

    def _mover_roi(self, evento):
        if self.ocupado or self.arrastre is None or self.modo_roi.get() != "dibujar":
            return
        punto = self._coordenada(evento)
        if punto is None:
            return
        x, y = punto
        x0, y0 = self.arrastre
        self._pintar_roi([min(x0, x), min(y0, y), abs(x - x0) + 1, abs(y - y0) + 1])

    def _terminar_roi(self, evento):
        if self.ocupado or self.arrastre is None:
            return
        if self.modo_roi.get() == "dibujar":
            punto = self._coordenada(evento)
            if punto is None:
                self.arrastre = None
                self._dibujar()
                return
            x, y = punto
            x0, y0 = self.arrastre
            self._fijar_roi([min(x0, x), min(y0, y), abs(x - x0) + 1, abs(y - y0) + 1])
        self.arrastre = None

    def _fijar_roi(self, roi):
        for variable, valor in zip(self.roi, roi):
            variable.set(str(valor))
        self._pintar_roi(roi)

    def _entrada_video(self, requiere_config=False):
        if self.video is None:
            raise ValueError("Primero abre un video.")
        if requiere_config and self.configuracion is None:
            raise ValueError("Carga una calibración o genera una con el video CAL AN E.")
        roi = [int(variable.get()) for variable in self.roi]
        if any(valor < 0 for valor in roi[:2]) or any(valor <= 0 for valor in roi[2:]):
            raise ValueError("La ROI requiere X e Y no negativos y ancho/alto positivos.")
        alto, ancho = self.cuadro_rgb.shape[:2]
        if roi[0] + roi[2] > ancho or roi[1] + roi[3] > alto:
            raise ValueError("La ROI queda fuera del cuadro.")
        inicio = float(self.inicio.get().replace(",", "."))
        fin = float(self.fin.get().replace(",", ".")) if self.fin.get().strip() else None
        if not math.isfinite(inicio) or inicio < 0 or (fin is not None and (not math.isfinite(fin) or fin <= inicio)):
            raise ValueError("El inicio debe ser ≥ 0 y el fin debe ser posterior al inicio.")
        if inicio >= self.info["duration"] or (fin is not None and fin > self.info["duration"] + .001):
            raise ValueError("El tramo queda fuera de la duración del video.")
        if requiere_config and roi[2:] != self.configuracion["roi"][2:]:
            raise ValueError("Al decodificar, conserva el ancho y alto de la calibración. Usa Recentrar con clic para mover el recuadro.")
        return self.video, roi, inicio, fin

    def _calibrar(self):
        try:
            video, roi, inicio, fin = self._entrada_video()
        except (ValueError, TypeError) as error:
            self._error(error)
            return
        def trabajo():
            salida = nueva_salida("calibracion")
            datos = extraer_video(video, roi=roi, inicio=inicio, fin=fin)
            config = calibrar(datos["intensity"], datos["fs"], datos["roi"], fuente=video, tiempos=datos["time"], duraciones=datos["frame_durations"])
            config["video_metadata"] = datos["metadata"]
            guardar_configuracion(config, salida / "calibracion.json")
            escribir_csv(salida / "senal.csv", [dict(time=float(t), intensity=float(i)) for t, i in zip(datos["time"], datos["intensity"])])
            figura = figura_senal(datos["time"], datos["intensity"], config["threshold"], datos["fs"])
            figura.savefig(salida / "senal.png", dpi=140)
            plt.close(figura)
            recibido = decodificar(datos["intensity"], datos["fs"], config,
                                   tiempos=datos["time"], duraciones=datos["frame_durations"])
            escribir_json(salida / "resultado.json", recibido)
            return salida, config, datos["metadata"]
        self._iniciar_trabajo("Calibrando: se espera la secuencia AN E completa a 0,5 m…", trabajo, self._calibracion_lista)

    def _calibracion_lista(self, datos):
        self.salida, config, _ = datos
        self._aplicar_config(config, self.salida / "calibracion.json")
        self._limpiar_resultado()
        self.resultado_texto.set("Calibración guardada")
        apagado = config["off_level"]
        encendido = config["on_level"]
        diferencia = encendido - apagado
        umbral = (apagado + encendido) / 2
        self._log(
            "CALIBRACIÓN DEL BRILLO (escala digital 0–255)\n\n"
            f"Brillo promedio con LED apagado (OFF): {apagado:.2f}\n"
            f"Brillo promedio con LED encendido (ON): {encendido:.2f}\n"
            f"Diferencia ON − OFF: {encendido:.2f} − {apagado:.2f} = {diferencia:.2f}\n\n"
            f"Umbral = (OFF + ON) / 2 = ({apagado:.2f} + {encendido:.2f}) / 2 "
            f"= {umbral:.2f}\n"
            f"Umbral guardado: {config['threshold']:.2f}\n\n"
            "En cada cuadro se promedia el brillo dentro de la región marcada. "
            "Si supera el umbral, se interpreta como encendido; si no, como apagado.\n"
            "Son valores digitales de la imagen, no porcentajes ni potencia de luz.\n\n"
            f"T estimado: {config['t_seconds'] * 1000:.1f} ms por punto.\n"
            f"Tolerancia temporal: ±{config['tolerance_units']:.3f} T "
            f"(±{config['tolerance_units'] * config['t_seconds'] * 1000:.1f} ms).\n"
            "Punto: 1T; raya: 3T; pausas de símbolo/letra/palabra: 1T/3T/7T.\n"
            "La tolerancia es el mayor valor entre 0,35T y la desviación máxima "
            "de AN E más un intervalo entre cuadros.\n"
            f"Calibración guardada en: {self.ruta_config}"
        )
        self._cargar_graficos(self.salida)
        self.estado.set("Calibración lista y cargada. Abre el video del mensaje y recentra el LED si hace falta.")

    def _decodificar(self):
        try:
            video, roi, inicio, fin = self._entrada_video(requiere_config=True)
        except (ValueError, TypeError) as error:
            self._error(error)
            return
        config = dict(self.configuracion)
        # Conserva los espacios originales: también cuentan para el CER.
        referencia = self.referencia.get()
        def trabajo():
            salida = nueva_salida("decodificacion")
            datos = procesar_video(video, config, roi=roi, inicio=inicio, fin=fin, salida=salida,
                                   incluir_espectro=False)
            senal = datos["signal"]
            try:
                espectro = analizar_senal(senal["intensity"], senal["fs"], senal["time"])
            except ValueError as error:
                # Una limitación del espectro no descarta el texto ya recibido.
                datos["result"]["warnings"].append(f"FFT y PSD no disponibles: {error}")
                escribir_json(salida / "resultado.json", datos["result"])
            else:
                datos["spectrum"] = espectro
                figura = figura_espectro(espectro)
                try:
                    figura.savefig(salida / "espectro.png", dpi=160)
                finally:
                    plt.close(figura)
                escribir_csv(salida / "fft.csv", [dict(frequency=float(f), amplitude=float(a))
                             for f, a in zip(espectro["fft_f"], espectro["amplitude"])])
                escribir_csv(salida / "psd.csv", [dict(frequency=float(f), psd=float(p))
                             for f, p in zip(espectro["psd_f"], espectro["psd"])])
                escribir_json(salida / "muestreo_espectro.json", espectro["sampling"])
                escribir_json(salida / "espectro.json", {
                    clave: valor for clave, valor in espectro.items() if not isinstance(valor, np.ndarray)
                })
            metricas = calcular_cer(referencia, datos["result"]["text"]) if referencia else None
            if metricas is not None:
                escribir_json(salida / "comparacion_referencia.json", metricas)
            return salida, datos, metricas
        self._iniciar_trabajo("Decodificando el video y guardando resultados…", trabajo, self._decodificacion_lista)

    def _limpiar_resultado(self):
        self.resultado_texto.set("—")
        self.morse_texto.set("")
        self.cer_texto.set("CER: sin referencia")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.imagenes_graficos.clear()
        self._mostrar_metodo_espectro()
        for lienzo in self.graficos.values():
            lienzo.delete("all")
        self.pestanas.select(0)

    def _decodificacion_lista(self, datos):
        self.salida, procesado, metricas = datos
        self._limpiar_resultado()
        resultado = procesado["result"]
        self.resultado_texto.set(resultado["text"] or "(sin texto recibido)")
        self.morse_texto.set("Morse: " + resultado["morse"])
        if metricas is not None:
            exacta = "Sí" if metricas["exact"] else "No"
            self.cer_texto.set(
                f"CER = (S + D + I) / N = ({metricas['S']} + {metricas['D']} + {metricas['I']}) "
                f"/ {len(metricas['reference'])} = {metricas['cer']:.4f}\n"
                f"Frase y espacios recuperados exactamente: {exacta}."
            )
        self._log(
            f"Video procesado: {procesado['signal']['metadata']['source']}\n\n"
            f"Señal recibida: {len(procesado['signal']['intensity'])} cuadros.\n"
            f"Frecuencia de muestreo efectiva: {procesado['signal']['fs']:.3f} Hz.\n"
            "I[n] es el promedio de los píxeles de la ROI, en intensidad digital (0–255).\n"
            "Señal: brillo versus tiempo y umbral.\n"
            "FFT y PSD: amplitud y densidad espectral de la señal de brillo.\n"
            "S: sustituciones; D: eliminaciones; I: inserciones; N: caracteres originales, incluidos espacios.\n\n"
            f"Archivos guardados en: {self.salida}"
        )
        if metricas is not None:
            self._log(f"Referencia: {metricas['reference']!r}\nRecibido: {metricas['received']!r}\n"
                      "Las comillas permiten ver espacios al inicio o al final.")
        if resultado["warnings"]:
            self._log("Observaciones de recepción:\n" + "\n".join(resultado["warnings"]))
        if procesado["spectrum"] is not None:
            self._mostrar_metodo_espectro(procesado["spectrum"])
            self._log("La FFT y la PSD usan una copia uniforme de la señal si los tiempos son "
                      "irregulares. La decodificación conserva las muestras originales.")
        else:
            self.graficos["FFT y PSD"].create_text(
                15, 20, anchor="nw", text="FFT y PSD no disponibles.\nConsulta las observaciones en Resultado.")
        self._cargar_graficos(self.salida)
        self.estado.set(f"Decodificación terminada. Resultados en {self.salida.name}")

    def _mostrar_metodo_espectro(self, espectro=None):
        if espectro is None:
            texto = "Decodifica un video para ver los parámetros utilizados y el cálculo de B95."
        else:
            total = espectro["psd_area"]
            objetivo = .95 * total
            texto = (
                "DEL VIDEO A LA SEÑAL\n"
                "1. Seleccionas la región del LED (ROI). Se promedia el brillo de sus píxeles "
                "en cada cuadro: ese valor es I[n], donde n indica el cuadro. "
                "Al reunir todos los cuadros se obtiene la señal de brillo.\n"
                f"2. El promedio de esa señal es I_prom = {espectro['mean']:.3f} unidades digitales. "
                "Se resta a cada muestra: X[n] = I[n] − I_prom. Así se estudian las subidas "
                "y bajadas de brillo respecto del nivel medio.\n\n"
                "FFT: QUÉ FRECUENCIAS APARECEN\n"
                "3. Se calcula la FFT de X[n]. La FFT descompone esa señal en oscilaciones "
                "de distintas frecuencias y muestra la amplitud de cada una. "
                "Por ejemplo, 2 Hz significa dos ciclos por segundo. Un pico más alto indica "
                "una oscilación con mayor amplitud. Los encendidos y pausas del Morse "
                "pueden producir varios picos.\n"
                f"{len(espectro['sample_intensity'])} muestras; fs = {espectro['fs']:.3f} Hz.\n"
                f"{espectro['sampling']}.\n"
                "La amplitud se divide por el número de muestras. Se muestran solo las frecuencias "
                "de 0 a fs/2 y se ajustan sus amplitudes para conservar su valor "
                "(se duplican las interiores, sin duplicar 0 Hz ni Nyquist).\n\n"
                "PSD: CÓMO SE REPARTEN LAS VARIACIONES DEL BRILLO\n"
                "La PSD indica cuánto aporta cada zona de frecuencias a las variaciones de X[n]. "
                "Se usa un periodograma de una sola cara del registro completo: se toma "
                "la misma FFT de X[n], se eleva su módulo al cuadrado y se divide por fs × N. "
                "No se eleva al cuadrado la gráfica de amplitud ya duplicada.\n"
                "PSD[k] = |FFT(X)[k]|² / (fs × N). Se duplican las componentes interiores "
                "para incluir la potencia de las frecuencias negativas; 0 Hz no se duplica. "
                "Nyquist tampoco se duplica cuando N es par. Si N es impar, el último punto "
                "está antes de Nyquist y sí se duplica.\n"
                "Se usa el registro completo, sin atenuar sus extremos (ventana rectangular). "
                "La PSD se expresa en intensidad digital²/Hz.\n"
                f"f[k] = k × fs/N; separación Δf = {espectro['delta_f_hz']:.6g} Hz.\n\n"
                "PARSEVAL: LA MISMA POTENCIA EN TIEMPO Y FRECUENCIA\n"
                "La potencia promedio de X[n] es el promedio de sus valores al cuadrado. "
                "En frecuencia, cada componente aporta PSD[k] × Δf. Al sumar todos esos "
                "aportes debe obtenerse la misma potencia, salvo redondeo numérico.\n"
                f"Promedio de X[n]² = {espectro['time_power']:.12g}.\n"
                f"Suma de PSD[k] × Δf = {total:.12g}.\n"
                f"Diferencia absoluta = {espectro['parseval_absolute_error']:.3g}. "
                f"Comprobación: {'correcta' if espectro['parseval_ok'] else 'fuera de tolerancia'}.\n\n"
                "B95: HASTA QUÉ FRECUENCIA SE REÚNE EL 95 %\n"
                "Se acumulan los aportes PSD[k] × Δf desde 0 Hz hacia la derecha. "
                "B95 es la primera frecuencia cuya suma alcanza al menos el 95 % del total.\n"
                f"Área total = {total:.6g} unidades digitales².\n"
                f"Objetivo del 95 % = 0,95 × {total:.6g} = {objetivo:.6g}.\n"
            )
            if total > 0:
                acumulada = espectro["cumulative"]
                frecuencias = espectro["psd_f"]
                k = min(len(acumulada) - 1, int(np.searchsorted(acumulada, objetivo)))
                texto += (
                    f"En {frecuencias[k]:.4f} Hz la potencia acumulada es {acumulada[k]:.6g} "
                    f"({100 * acumulada[k] / total:.2f} % del total).\n"
                    "Se elige ese punto de frecuencia, sin interpolación. "
                    "La precisión de B95 está limitada por la separación Δf.\n"
                    f"B95 = {espectro['b95']:.4f} Hz.\n"
                    f"Es decir, entre 0 y {espectro['b95']:.4f} Hz se reúne al menos el 95 % "
                    "del área de la PSD de X[n]. La línea roja marca ese límite. "
                    "Se analiza brillo digital del video, no potencia óptica en watts."
                )
            else:
                texto += "No hay área espectral positiva: B95 se guarda como 0 Hz; no hay un ancho significativo que estimar."
        self.metodo_espectro.configure(state="normal")
        self.metodo_espectro.delete("1.0", "end")
        self.metodo_espectro.insert("1.0", texto)
        self.metodo_espectro.yview_moveto(0)
        self.metodo_espectro.configure(state="disabled")

    def _cargar_graficos(self, salida):
        nombres = {"Señal": "senal.png", "FFT y PSD": "espectro.png"}
        for pestana, archivo in nombres.items():
            ruta = salida / archivo
            if ruta.is_file():
                # imdecode permite rutas con tildes en Windows.
                imagen = cv2.imdecode(np.fromfile(ruta, dtype=np.uint8), cv2.IMREAD_COLOR)
                if imagen is not None:
                    self.imagenes_graficos[pestana] = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
                    self._dibujar_grafico(pestana)

    def _dibujar_grafico(self, nombre):
        if nombre not in self.imagenes_graficos:
            return
        lienzo = self.graficos[nombre]
        ancho, alto = max(1, lienzo.winfo_width()), max(1, lienzo.winfo_height())
        imagen, _ = foto_tk(self.imagenes_graficos[nombre], ancho, alto)
        self.fotos_graficos[nombre] = imagen
        lienzo.delete("all")
        lienzo.create_image(ancho / 2, alto / 2, image=imagen)

    def _abrir_salida(self):
        ruta = self.salida or RESULTADOS
        ruta.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(ruta))
        except OSError as error:
            self._error(error)

    def _cerrar(self):
        if self.ocupado:
            self.estado.set("Espera a que termine la operación antes de cerrar; se están guardando los resultados.")
            return
        if self.captura:
            self.captura.release()
        self.ventana.destroy()


def main():
    ventana = tk.Tk()
    def informar_error(tipo, error, traza):
        detalle = "".join(traceback.format_exception(tipo, error, traza))
        try:
            RESULTADOS.mkdir(parents=True, exist_ok=True)
            with (RESULTADOS / "interfaz_error.log").open("a", encoding="utf-8") as archivo:
                archivo.write(datetime.now().isoformat() + "\n" + detalle + "\n")
        except OSError:
            pass
        messagebox.showerror("Error de interfaz", f"{error}\n\nEl detalle se guarda en resultados/interfaz_error.log.", parent=ventana)
    ventana.report_callback_exception = informar_error
    Aplicacion(ventana)
    ventana.mainloop()


if __name__ == "__main__":
    main()
