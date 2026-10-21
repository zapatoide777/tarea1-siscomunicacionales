# Tarea 1 · Comunicación óptica Morse

Repositorio público: [zapatoide777/tarea1-siscomunicacionales](https://github.com/zapatoide777/tarea1-siscomunicacionales).

Proyecto de Sistemas de Comunicaciones, UdeC, 2026. Un Arduino UNO transmite
letras mediante un LED. Una cámara graba la luz y Python reconstruye el texto
desde el video. Después calcula los errores y analiza la señal recibida.

El Arduino se maneja desde el **Monitor Serial de Arduino IDE**. Python se
ejecuta después de grabar; no necesita conectarse al Arduino por USB.

Lee [INSTRUCTIVO.md](INSTRUCTIVO.md) para conocer el montaje, cada programa,
la calibración, los resultados y la forma de trabajar entre compañeros.

## Qué contiene

```text
tarea1/
├── README.md                          Instalación y ejecución rápida
├── INSTRUCTIVO.md                     Explicación general y pasos completos
├── .gitignore                        Archivos locales que Git no sube
├── .gitattributes                    Conserva intactos los documentos binarios
├── ensayos.json                       Rutas de los cuatro videos
├── codigo/
│   ├── transmisor_morse/
│   │   └── transmisor_morse.ino        Programa del Arduino UNO
│   └── receptor/
│       ├── ejecutar_tarea1.py          Programa Python que se ejecuta
│       ├── requirements.txt           Versiones de las bibliotecas
│       └── siscom/
│           ├── receptor.py            Video, calibración y lectura de Morse
│           ├── procesar.py            Procesamiento y exportación de resultados
│           └── analisis.py            FFT, PSD, B95, CER y gráficos
├── Tarea1_SisCom_2026.docx             Pauta de la tarea
└── informe_software_tarea1.pdf        Documento explicativo complementario
```

`datos/`, `resultados/` y `.venv/` son carpetas locales: no se suben a Git.
El clon no incluye grabaciones ni resultados experimentales. Los videos deben
compartirse aparte y colocarse en las rutas del instructivo.

## Requisitos

- Arduino UNO, cable USB, LED convencional, resistencia de 330 Ω y cables.
- Cámara o celular que permita grabar video, y soportes para fijar el montaje.
- Arduino IDE con soporte para Arduino UNO.
- Python 3.12 de 64 bits y Git en el computador que procesará los videos.

El entorno local disponible usa Python 3.12.14. Las versiones de las bibliotecas
están fijadas en `codigo/receptor/requirements.txt`.

## Instalar después de clonar

Los ejemplos usan PowerShell en Windows. El comando de clonado guarda el
proyecto en una carpeta local llamada `tarea1`.

```powershell
git clone https://github.com/zapatoide777/tarea1-siscomunicacionales.git tarea1
cd tarea1
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r codigo/receptor/requirements.txt
New-Item -ItemType Directory -Force -Path datos/calibracion, datos/videos_originales
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py --help
```

No hace falta activar el entorno: los comandos usan directamente su Python.
Todos los pasos siguientes se ejecutan desde esta misma carpeta.

## Transmitir y grabar

1. Conecta `D8 → resistencia de 330 Ω → ánodo del LED`; conecta el cátodo a GND.
2. Abre `codigo/transmisor_morse/transmisor_morse.ino` en Arduino IDE, selecciona
   Arduino UNO y el puerto de la placa, y carga el programa.
3. Abre el Monitor Serial a **115200 baudios**, con **Nueva línea**.
4. Envía `T 300`. A 0,5 m, empieza a grabar y envía `CAL`; guarda el video como
   `datos/calibracion/calibracion.mp4`. `CAL` transmite `AN E`.
5. Graba `SEND SIS COM` una vez a cada distancia: 0,5; 1; 2 y 3 m. Usa los
   nombres de video indicados en `ensayos.json`.

Empieza cada grabación antes de enviar la orden y termínala después de `DONE`.
Espera a que termine una transmisión antes de enviar la siguiente.

## Procesar los videos

Primero guarda el patrón previsto; después calibra una vez y evalúa los cuatro
videos con esa misma calibración. El segundo comando permite dibujar con el
mouse el rectángulo que rodea al LED y confirmarlo con Enter.

```powershell
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py patron --texto "SIS COM" --t-ms 300 --salida resultados/patron_previsto
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py calibrar --video datos/calibracion/calibracion.mp4 --seleccionar-roi --salida resultados/calibracion.json
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py evaluar --ensayos ensayos.json --config resultados/calibracion.json --salida resultados/comparacion
```

Los resultados quedan en `resultados/`: texto recibido, decisiones sobre los
pulsos, señal de brillo, FFT, PSD, B95, tabla de errores y gráficos por distancia.
Para la palabra nueva y para recentrar la ROI, sigue [INSTRUCTIVO.md](INSTRUCTIVO.md).

## Estado y colaboración

El código Python ha pasado comprobaciones de sintaxis y apertura de los comandos
en el entorno local. La compilación del Arduino y la recepción con el montaje
real siguen pendientes de confirmación. Este repositorio no aporta mediciones
reales ni garantiza recepción correcta antes de esas pruebas.

El desarrollo del software y la documentación contó con apoyo de IA. Los
integrantes deben revisar el código y generar sus propias mediciones del montaje.

Para publicar y actualizar el proyecto, consulta la sección de GitHub del
[instructivo](INSTRUCTIVO.md#trabajar-con-github).
