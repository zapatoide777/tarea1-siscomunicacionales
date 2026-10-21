# Cómo funciona y cómo se usa la Tarea 1

Este instructivo explica el recorrido completo del mensaje, desde el Monitor
Serial hasta los archivos que Python genera. Los comandos se ejecutan en
PowerShell desde la carpeta raíz de este repositorio, donde está `ensayos.json`.
La instalación inicial está en [README.md](README.md#instalar-después-de-clonar).

## 1. Recorrido del mensaje

```text
Texto escrito en el Monitor Serial
        ↓
Arduino convierte las letras en puntos, rayas y pausas
        ↓
El LED se enciende y apaga siguiendo ese patrón
        ↓
La cámara graba la luz y se guarda el video
        ↓
Python obtiene un valor de brillo por cuadro
        ↓
Detecta pulsos, mide sus tiempos y reconstruye el texto
        ↓
Calcula errores, frecuencias y gráficos
```

El brillo se expresa en unidades digitales de la imagen, no en watts. La frase
original se usa al final para evaluar los errores; el receptor no la usa para
adivinar letras ni corregir el texto recibido.

## 2. Qué hace cada archivo

| Archivo | Para qué se usa |
| --- | --- |
| `codigo/transmisor_morse/transmisor_morse.ino` | Recibe las órdenes del Monitor Serial y controla el LED con tiempos Morse. |
| `codigo/receptor/ejecutar_tarea1.py` | Es el archivo que ejecutas en Python. Permite preparar el patrón, calibrar, decodificar y evaluar. |
| `codigo/receptor/siscom/receptor.py` | Lee el video, mide la ROI, calcula la calibración y convierte los pulsos en letras. |
| `codigo/receptor/siscom/procesar.py` | Une las etapas de procesamiento, guarda los archivos y recorre los cuatro ensayos. |
| `codigo/receptor/siscom/analisis.py` | Calcula la FFT, la PSD, B95 y CER, y dibuja los gráficos. |
| `ensayos.json` | Indica qué video corresponde a cada distancia. |
| `codigo/receptor/requirements.txt` | Enumera las bibliotecas de Python y las versiones usadas. |

Se ejecuta un solo archivo Python: `ejecutar_tarea1.py`. Este carga los otros
tres automáticamente; no es necesario abrirlos y ejecutarlos uno por uno.

## 3. Preparar el montaje

Conecta un LED convencional a D8 mediante una resistencia de 330 Ω y completa
el circuito hacia GND. El LED integrado de la placa también parpadea para ayudar
a observar la transmisión. Fija la fuente y la cámara en soportes.

Abre el `.ino` en Arduino IDE, selecciona Arduino UNO y el puerto de tu placa,
verifica y carga el programa. El Monitor Serial debe mostrar `READY`. Configura
115200 baudios y Nueva línea.

| Orden que escribes | Qué hace |
| --- | --- |
| `STATUS` | Muestra los ajustes actuales. |
| `T 300` | Establece la duración de un punto en 300 milisegundos. |
| `CAL` | Transmite `AN E` para calibrar. |
| `SEND SIS COM` | Transmite la frase de la tarea. |
| `SEND LUNA` | Ejemplo de envío de otra palabra. |

El programa acepta letras A-Z y espacios, convierte minúsculas a mayúsculas y
limita el texto normalizado a 80 caracteres. La orden `T` admite valores de
100 a 2000 milisegundos. Para este procedimiento se conserva `T 300` en todos
los ensayos.

Al empezar aparece `BEGIN CAL` o `BEGIN SEND`; al terminar, `DONE CAL` o
`DONE SEND`. Espera ese término antes de enviar otra orden. El Arduino realiza
una transmisión por orden e incluye márgenes apagados de 7T antes y después.

## 4. Tiempos Morse y patrón previsto

T es el tiempo de referencia del punto. La raya dura 3T; las pausas duran 1T
entre símbolos de una letra, 3T entre letras y 7T entre palabras. Las pausas
entre letras o palabras son completas: no se suma otra pausa de 1T.

Para documentar lo que se debería transmitir:

```powershell
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py patron --texto "SIS COM" --t-ms 300 --salida resultados/patron_previsto
```

Esto crea `patron_previsto.csv` y `mensaje.json`. La frase ocupa 61T, es decir,
18,3 segundos con T = 300 ms, sin contar los dos márgenes apagados. Con ellos,
la secuencia óptica prevista dura 22,5 segundos. Empieza a grabar antes de enviar
la orden y espera a `DONE` para detener la grabación.

## 5. Calibrar una vez a 0,5 m

Graba una transmisión completa de `CAL` a 0,5 m y guarda el archivo como
`datos/calibracion/calibracion.mp4`. La secuencia `AN E` contiene puntos, rayas
y pausas de los tres tamaños para comprobar sus duraciones.

```powershell
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py calibrar --video datos/calibracion/calibracion.mp4 --seleccionar-roi --salida resultados/calibracion.json
```

En la ventana de selección, dibuja un rectángulo alrededor de la fuente y
confirma con Enter. Esa región es la ROI. El programa promedia el brillo de
sus píxeles en cada cuadro y busca los niveles de luz apagada y encendida.

La calibración guarda tres valores centrales:

- **Umbral:** brillo que separa los estados apagado y encendido.
- **T:** duración del punto estimada desde los tiempos observados en el video.
- **Tolerancia:** diferencia de duración admitida para reconocer cada pulso o pausa.

Los resultados se guardan en `resultados/calibracion.json`, junto con la ROI y
los datos del video. Se reutilizan para los cuatro ensayos. No se vuelve a
calibrar ni se ajusta el umbral conociendo la frase recibida a otra distancia.

Si conoces las coordenadas, `--roi X Y ANCHO ALTO` reemplaza a
`--seleccionar-roi`. X e Y son la esquina superior izquierda del rectángulo,
medidas en píxeles. Por ejemplo, `--roi 100 100 32 32` selecciona un cuadrado
de 32 × 32 píxeles; es solo un ejemplo y debe corresponder a tu propia imagen.

## 6. Grabar los cuatro videos del mensaje

Envía `SEND SIS COM` una vez para cada grabación y guarda los archivos así:

| Distancia | Ruta desde la raíz del repositorio |
| --- | --- |
| 0,5 m | `datos/videos_originales/sis_com_0p5m.mp4` |
| 1,0 m | `datos/videos_originales/sis_com_1p0m.mp4` |
| 2,0 m | `datos/videos_originales/sis_com_2p0m.mp4` |
| 3,0 m | `datos/videos_originales/sis_com_3p0m.mp4` |

Cambia solo la distancia. Conserva la fuente, la cámara, la iluminación,
el ritmo de transmisión y el tamaño de la ROI. Mantén también exposición y
enfoque fijos si la cámara lo permite. Mide la distancia desde el LED a la cámara.

El programa usa los cuadros por segundo del archivo como frecuencia de muestreo.
Por ejemplo, un video de 30 FPS aporta 30 muestras de brillo por segundo; con
T = 300 ms, cada punto ocupa aproximadamente nueve cuadros.

Si el LED cambia de posición en la imagen, puedes recentrar la ROI en
`ensayos.json`: añade `"roi": [X, Y, ANCHO, ALTO]` al ensayo correspondiente.
El ancho y alto deben ser los mismos que en la calibración. Si no se indica
ROI, se utiliza exactamente la de `calibracion.json`.

Las rutas de video de `ensayos.json` se interpretan desde la carpeta de ese
archivo. Conserva los cuatro ensayos y sus distancias.

## 7. Procesar y evaluar

```powershell
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py evaluar --ensayos ensayos.json --config resultados/calibracion.json --salida resultados/comparacion
```

Para cada video, Python sigue estos pasos:

1. Lee los cuadros y obtiene el brillo medio de la ROI.
2. Compara ese brillo con el umbral guardado para decidir encendido o apagado.
3. Agrupa cuadros consecutivos del mismo estado y mide cuánto dura cada grupo.
4. Compara esas duraciones con T, 3T y 7T usando la tolerancia calibrada.
5. Reúne puntos y rayas y consulta la tabla Morse para recuperar cada letra.
6. Conserva patrones inválidos como `?`; no completa el mensaje por contexto.
7. Compara el texto recibido con `SIS COM` para calcular CER.
8. Calcula los resultados de frecuencia y guarda datos y figuras.

**CER** es la cantidad mínima de letras o espacios que habría que reemplazar,
borrar o agregar para pasar de un texto al otro, dividida por el largo del
original. El cálculo usa la distancia de Levenshtein. Para `SIS COM` el divisor
es 7, porque el espacio también cuenta. CER = 0 significa recuperación exacta.

La **FFT** muestra las frecuencias presentes en los cambios de brillo. La
**PSD**, estimada con Welch, muestra cómo se reparte su potencia entre
frecuencias. **B95** es la frecuencia hasta la que se acumula el 95 % del área
bajo la PSD. Para esos cálculos se resta primero el brillo promedio.

## 8. Qué resultados revisar

Dentro de `resultados/comparacion/` aparecen:

| Archivo o carpeta | Qué revisar |
| --- | --- |
| `tabla_resultados.csv` | Distancia, duración del mensaje, S, D, I, CER, texto y estado de cada ensayo. |
| `evaluacion.json` | Resumen de los cuatro ensayos y ajustes utilizados. |
| `cer_distancia.png` y `.pdf` | Relación entre distancia y errores. |
| `comparacion_0p5_3m.png` y `.pdf` | El mismo tramo a 0,5 y 3 m, alineado por el primer pulso y con igual escala vertical. |
| `comparacion.json` | Indica si esa alineación fue posible. |
| `distancia_0.5m/`, `distancia_1m/`, `distancia_2m/`, `distancia_3m/` | Archivos detallados de los ensayos procesados. |

Cada carpeta de distancia contiene el texto recibido, las decisiones sobre los
pulsos, la señal en CSV, FFT, PSD, resumen del espectro, calibración utilizada,
metadatos y figuras de señal y espectro. Si falla la alineación, se intenta
guardar `comparacion_sin_alineacion.png` y se registra la causa.

Conserva los videos y resultados incorrectos. Si una transmisión completa se
decodifica como texto vacío, su CER es 1. Una falla de grabación se declara en
el ensayo con `"valid": false` y una explicación en `"note"`; queda sin CER.
No declares inválida una grabación solo porque el texto recibido tiene errores.

## 9. Leer la palabra nueva

Cuando el docente indique las cuatro letras, envía `SEND` seguido de la palabra
desde el Monitor Serial y graba la transmisión completa. Guarda el video como
`datos/videos_originales/palabra_nueva.mp4` y ejecuta:

```powershell
.\.venv\Scripts\python.exe codigo/receptor/ejecutar_tarea1.py decodificar --video datos/videos_originales/palabra_nueva.mp4 --config resultados/calibracion.json --salida resultados/palabra_nueva
```

El receptor usa la ROI guardada. Si necesitas recentrarla, añade
`--roi X Y ANCHO ALTO` con el mismo tamaño de calibración. No se entrega la
palabra esperada a Python.

## 10. Resolver problemas comunes

- **No aparece READY:** comprueba la placa, el puerto USB y los 115200 baudios.
- **No responde al Monitor Serial:** selecciona Nueva línea y espera a que termine cualquier transmisión anterior.
- **Video inexistente:** revisa el nombre del archivo y la carpeta desde la que ejecutas los comandos.
- **No se distinguen niveles ON/OFF:** comprueba que la ROI incluya el LED y que no quede saturada ni demasiado oscura.
- **CAL incompleto:** conserva los cinco pulsos de AN E y evita cortar el inicio o el final de la transmisión.
- **ROI fuera del cuadro o de tamaño distinto:** revisa sus coordenadas y conserva el tamaño calibrado.
- **Temporización variable:** el programa detectó cuadros con tiempos incompatibles con los FPS declarados. Conserva el original; prepara una copia a FPS constantes y documenta esa conversión antes de procesarla.
- **Texto incorrecto o signos ?:** revisa `decisiones.csv` y la señal. El programa conserva esos errores y no los corrige manualmente.

`calibrar` y `decodificar` admiten `--inicio` y `--fin` en segundos para escoger
un tramo, conservando siempre la transmisión completa. En `ensayos.json`, los
campos equivalentes de cada video son `start_s` y `end_s`.

## Trabajar con GitHub

El repositorio contiene el código, la pauta y la documentación. `.gitignore`
excluye el entorno Python, cachés, videos y resultados generados. Las carpetas
vacías no viajan con Git: créalas al instalar como se indica en el README.

Compartan las grabaciones por una carpeta compartida y colóquenlas en las mismas
rutas relativas. La calibración y los resultados pueden regenerarse desde los
videos originales. Si el compañero recibe una calibración ya hecha con el mismo
montaje, puede colocarla en `resultados/calibracion.json`.

El repositorio público está en
[zapatoide777/tarea1-siscomunicacionales](https://github.com/zapatoide777/tarea1-siscomunicacionales).
Tu compañero puede clonarlo siguiendo el README. Para que también pueda subir
cambios directamente, el propietario debe invitarlo como colaborador desde
Settings → Collaborators en GitHub; conocer el enlace no da permiso de escritura.

Después de clonar, cada integrante configura su propio nombre y correo de Git
para identificar al autor de sus commits. Puede usar el correo `noreply` que aparece en los
ajustes de correo de su cuenta de GitHub. Cuando Git pida iniciar sesión,
utiliza tu cuenta mediante el mecanismo de autenticación que abra.

Para trabajar después de la primera subida, comienza con `git pull --ff-only`
cuando no tengas cambios pendientes. Al terminar, usa `git status`, añade los
archivos que modificaste con `git add`, crea un commit que describa el cambio
y ejecuta `git push`. Si tienen cambios pendientes antes de recibir los del
compañero, guárdenlos en un commit primero y revisen cualquier conflicto.

Cada integrante instala su propio entorno `.venv`; no se copia ni se sube a
Git. Los comandos habituales procesan archivos guardados y no necesitan que
el Arduino esté conectado al computador que analiza los videos.
