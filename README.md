# Tarea 1 · Comunicación óptica Morse

## Empezar

Abre `abrir_interfaz.cmd` con doble clic. Pulsa **Ejemplo 0,5 m** y luego **Decodificar** para abrir uno de los videos incluidos. La calibración de esos videos se carga al iniciar.

La interfaz se concentra en el receptor: ROI y tramo manuales, intensidad media por cuadro, señal y frecuencia de muestreo, calibración común a 0,5 m, decisiones Morse, texto recibido y CER con espacios. Abre cada video que quieras analizar; cada ejecución guarda una carpeta nueva en `resultados`.

Las pestañas son **Resultado**, **Señal** y **FFT y PSD**. Al decodificar también se muestran y guardan la FFT y la densidad espectral de potencia de la señal de brillo. Los comandos anteriores de terminal se conservan para el trabajo posterior.

## FFT, periodograma y Parseval

Se centra el brillo medio de la ROI: `X[n] = I[n] − promedio(I)`. Sobre sus N muestras se calcula `F[k] = FFT(X)[k]`, sin normalización en la transformada. Se conservan los índices `k = 0,…,floor(N/2)`, con `f[k] = k fs/N` y `Δf = fs/N`. Con N impar, la última frecuencia queda antes de fs/2 y no existe una componente en Nyquist.

La **FFT de amplitud** se grafica por separado: `|F[k]|/N`. La **PSD** se estima con un **periodograma de una sola cara** del registro completo, con ventana rectangular: `PSD[k] = |F[k]|²/(fs N)`, en intensidad digital²/Hz. En ambas gráficas se duplican las componentes interiores, conservando DC y Nyquist sin duplicar; con N impar también se duplica la última componente. La PSD se calcula desde la FFT original, no desde la amplitud ya duplicada.

La relación de Parseval, presentada en `teoria/Respuesta espectral SLTI`, se aplica en su forma discreta: `sum(PSD[k] Δf) = mean(X[n]²)`. Se suman las contribuciones de los bins completos, sin trapecios. Cada análisis comprueba esta igualdad con tolerancia relativa `1e-10` y absoluta `1e-12`, y registra ambas potencias y el error numérico. Esta comprobación se ejecutará cuando proceses un video.

**B95** es la primera frecuencia donde `cumsum(PSD[k] Δf)` alcanza al menos el 95 % de la potencia total. Se elige un bin, sin interpolación; la resolución es Δf. Si la señal centrada no tiene potencia, se guarda B95 = 0 Hz. Se mide potencia del brillo digital, no watts ópticos.

`espectro.json` registra el método, la normalización, Δf, B95 y la comprobación de Parseval. Los CSV y las claves previas se conservan; `nperseg=N` y `noverlap=0` permanecen como campos de compatibilidad para representar un único registro completo. La interfaz mantiene `fft.csv`, `psd.csv`, `espectro.png` y `muestreo_espectro.json`; los comandos de terminal conservan también sus salidas anteriores.

Si los tiempos son irregulares, solo el análisis espectral usa una copia interpolada a una grilla uniforme. Parseval se comprueba sobre esa misma copia centrada. El receptor Morse conserva las muestras y tiempos originales. Los videos no se modifican.

La primera vez, el lanzador prepara Python y las bibliotecas; requiere conexión a internet. Para instrucciones paso a paso, consulta [INICIO_RAPIDO.md](INICIO_RAPIDO.md). Para grabar con Arduino y procesar desde la terminal, consulta [INSTRUCTIVO.md](INSTRUCTIVO.md).

## Archivos principales

- `abrir_interfaz.cmd`: abre la ventana de prueba.
- `preparar_entorno.ps1`: prepara el entorno Python si hace falta.
- `codigo/transmisor_morse/transmisor_morse.ino`: programa del Arduino.
- `codigo/receptor/interfaz.py`: ventana para cargar y procesar videos.
- `codigo/receptor/ejecutar_tarea1.py`: comandos de terminal.
- `codigo/receptor/siscom/video.py`: lectura de cuadros y tiempos del video.
- `codigo/receptor/siscom/receptor.py`: calibración y decodificación Morse.
- `codigo/receptor/siscom/procesar.py`: evaluación y exportación.
- `codigo/receptor/siscom/analisis.py`: señal, espectro y errores CER.
- `ensayos.json`: videos, distancias y regiones LED usados al evaluar.
- `datos/`: las grabaciones incluidas.
- `resultados/calibracion.json`: calibración de esas grabaciones.
- `Tarea1_SisCom_2026.docx` e `informe_software_tarea1.pdf`: material de la tarea.

`INSTRUCTIVO.md` contiene el montaje, las órdenes del Monitor Serial y los pasos para grabar y procesar nuevos videos.
