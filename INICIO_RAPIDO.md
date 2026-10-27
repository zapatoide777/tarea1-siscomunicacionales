# Probar videos con la interfaz

Abre **abrir_interfaz.cmd** con doble clic. No necesitas activar Python, escribir comandos ni conectar el Arduino. La primera apertura prepara las bibliotecas si faltan; en ese caso necesita internet y puede demorar. Las siguientes aperturas usan el entorno local.

## Primera prueba con los videos incluidos

1. Pulsa **Ejemplo 0,5 m** para cargar `sis_com_0p5m.mp4`. Tambien puedes abrir un video de `datos/videos_originales`.
2. Carga `resultados/calibracion.json` si la ventana no la tiene cargada. La copia incluye la calibracion de las grabaciones originales.
3. Revisa el LED con el deslizador o avanzando cuadro a cuadro. Para estos archivos se reutilizan las posiciones indicadas en `ensayos.json`. Para mover el recuadro, selecciona **Recentrar con clic (conserva tamaño calibrado)** y haz clic en el centro del LED.
4. Pulsa **Decodificar**. Verás el texto recibido y su Morse. **Señal** muestra intensidad digital versus tiempo, umbral y frecuencia de muestreo efectiva. **FFT y PSD** muestra el análisis de frecuencias. Los tramos fuera de tolerancia se conservan como errores. La frase transmitida en estos videos es `SIS COM`.
5. Escribe la frase original en **Referencia opcional** antes de decodificar. El CER se calcula después de reconstruir el texto, contando los espacios. Verás la fórmula y si la frase y sus espacios coinciden exactamente. Para analizar otro video, ábrelo y reutiliza la misma calibración.

Para otro video, abre el archivo, selecciona el rectangulo del LED y, si corresponde, ajusta inicio y fin en segundos. No recortes una parte del mensaje. La referencia de texto es opcional: sirve para calcular el error, sin intervenir en la decodificacion.

## Calibrar con otra grabacion

La ventana tiene tres columnas: **video**, **selección y procesamiento**, y **resultados**. El visor mantiene siempre la proporción vertical **9:16**. Los videos verticales conservan su orientación; los horizontales se giran a vertical. Si el archivo tiene otra proporción, se ajusta con márgenes sin deformarlo. Los separadores permiten repartir el espacio entre las columnas.

Para ubicar el LED con precisión:

1. En la vista completa, haz clic cerca del LED con **Recentrar con clic**.
2. Acerca el puntero al LED y usa la rueda sobre el video para ampliar o reducir. Al ampliar se distinguen los píxeles originales.
3. Si necesitas desplazar la imagen, arrastra con el botón derecho. Usa el botón izquierdo para colocar o dibujar la ROI, según el modo seleccionado.
4. Para una nueva calibración, selecciona **Dibujar nueva ROI** y encierra el LED en la vista ampliada.

El giro y el zoom solo afectan al visor, que sigue siendo 9:16 al ampliar. Las coordenadas y el tamaño de ROI siguen expresados en píxeles originales; el receptor mide el archivo original sin girarlo ni ampliarlo.

Abre un video de calibración grabado a **0,5 m** que contenga **AN E** completo, selecciona **Dibujar nueva ROI (para una nueva calibración)**, dibuja el rectángulo del LED y pulsa **Calibrar con este video**. En **Resultado → Resultados** verás el brillo promedio OFF y ON, su diferencia, la fórmula del umbral, T y la tolerancia temporal. Reutiliza esa calibración para los videos del mismo montaje, conservando el tamaño de ROI. Si solo cambia la posición del LED, usa **Recentrar con clic**.

Cada ejecución guarda una carpeta nueva dentro de `resultados`. En la decodificación se guardan texto recibido, resultado Morse, calibración utilizada, datos del video, señal en CSV, gráfico de señal y, si hay referencia, comparación CER. Usa **Abrir resultados** para consultarlos.

Al decodificar se genera además la pestaña **FFT y PSD**: arriba muestra la amplitud de la FFT y abajo la densidad espectral de potencia, estimada con un **periodograma de una sola cara** del registro completo. Ambas usan la señal de brillo sin su promedio. La PSD se calcula como `|FFT(X)[k]|²/(fs N)` y se duplican las componentes interiores, sin duplicar DC ni Nyquist. Con N impar, el último punto no es Nyquist y sí se duplica. Las frecuencias son `f[k] = k fs/N`.

El panel explica Parseval: la suma `PSD[k] × (fs/N)` coincide con el promedio de `X[n]²`, salvo error numérico. B95 es la primera frecuencia cuya potencia acumulada alcanza al menos el 95 % del total, sin interpolación. Se guardan `espectro.png`, `fft.csv`, `psd.csv`, la descripción del muestreo y `espectro.json` con el método y la comprobación numérica. Para tiempos irregulares, el espectro usa una copia remuestreada y Parseval se comprueba sobre esa copia; la decodificación mantiene la señal original. Si los tiempos impiden calcular un espectro fiable, se conserva el texto recibido y se informa la causa.

La ventana cubre las tareas del receptor de los puntos 1.3–1.5, decodifica mensajes A–Z con espacios del punto 1.6 e incluye FFT y PSD. El transmisor, el montaje y los diagramas quedan fuera de este recorrido. La copia de Descargas y las grabaciones originales no se modifican.

## Sobre videos de telefono

- **Exposicion:** un cuadro puede integrar parte de un encendido y apagado, dando brillo intermedio. El programa conserva esa medicion.
- **Rolling shutter:** las filas se captan en instantes distintos; pueden aparecer bandas durante las transiciones.
- **Tiempos variables:** el receptor usa los tiempos originales de los cuadros. Los saltos o tiempos inconsistentes aparecen en el diagnostico.
- **Movimiento y ajustes automaticos:** fija el telefono, bloquea enfoque y exposicion si puedes y evita saturar el LED.
- Transfiere el archivo original. Aumentar artificialmente los FPS o suavizar cuadros no recupera mediciones perdidas y puede alterar pulsos o espectros. La primera version no aplica esos filtros al video.

## Si no abre

El lanzador deja visibles los errores de preparacion. Si el error ocurre al iniciar la aplicacion, muestra un aviso y guarda el detalle en `resultados/interfaz_error.log`. Si no se encuentra Python compatible, instala Python 3.11 o posterior con Tcl/Tk desde [python.org](https://www.python.org/downloads/windows/) y vuelve a abrir el lanzador.

Esta primera version esta preparada para que pruebes la ventana manualmente.
