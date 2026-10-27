#include <Arduino.h>
#include <string.h>

// Ajustes del montaje: LEDs en D2 a D9 y T inicial de 300 ms por punto.
// Los mensajes se guardan en arreglos de tamaño fijo porque el UNO tiene poca memoria.
const uint8_t PINES_LED[] = {2, 3, 4, 5, 6, 7, 8, 9};
const uint8_t NUM_LEDS = 8;
const bool SINCRONIZAR_LED_INTEGRADO = true;  // false para desactivar el indicador integrado.
const uint8_t MAXIMO_LETRAS = 80;
const uint16_t CAPACIDAD_LINEA = 192;  // Incluye terminador NUL.
char bufferLinea[CAPACIDAD_LINEA];
char bufferMensaje[MAXIMO_LETRAS + 1];  // 80 caracteres normalizados + NUL.
uint16_t longitudLinea = 0;
bool lineaDesbordada = false;
bool retornoCarroPrevio = false;
uint16_t duracionUnidadMs = 300;

// Tabla para convertir cada letra en puntos y rayas (de A hasta Z).
const char CODIGO_MORSE[26][5] = {
  ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..",
  ".---", "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.",
  "...", "-", "..-", "...-", ".--", "-..-", "-.--", "--.."
};

// Reconoce los separadores admitidos en las ordenes seriales.
bool esEspacio(char caracter) {
  return caracter == ' ' || caracter == '\t' || caracter == '\v' || caracter == '\f';
}

void ponerLed(bool encendido) {
  // Enciende o apaga todos los LEDs del arreglo simultáneamente
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    digitalWrite(PINES_LED[i], encendido ? HIGH : LOW);
  }

  // El LED integrado repite la señal y permite verla directamente en la placa.
  if (SINCRONIZAR_LED_INTEGRADO) {
    digitalWrite(LED_BUILTIN, encendido ? HIGH : LOW);
  }
}

// Un tramo mantiene la luz encendida o apagada durante cierta cantidad de T.
// Si emitir es falso, solo suma su duración para anunciarla por Serial.
void transmitirTramo(bool encendido, uint8_t unidades, bool emitir,
                     uint16_t &totalUnidades, unsigned long &plazo) {
  totalUnidades += unidades;
  if (!emitir) {
    return;
  }
  ponerLed(encendido);
  // Usa el instante previsto para que las pequeñas demoras no se acumulen.
  plazo += static_cast<unsigned long>(unidades) * duracionUnidadMs * 1000UL;
  while (static_cast<long>(micros() - plazo) < 0) {
    // Espera sin escribir por Serial mientras se transmite el tramo.
  }
}

// Recorre letra por letra y coloca pausas de 1T, 3T o 7T según corresponda.
uint16_t recorrerMensaje(const char *texto, bool emitir, unsigned long &plazo) {
  uint16_t totalUnidades = 0;
  for (uint16_t indiceLetra = 0; texto[indiceLetra]; ++indiceLetra) {
    if (texto[indiceLetra] == ' ') {
      continue;
    }
    const char *codigo = CODIGO_MORSE[texto[indiceLetra] - 'A'];
    for (uint8_t indiceElemento = 0; codigo[indiceElemento]; ++indiceElemento) {
      transmitirTramo(true, codigo[indiceElemento] == '.' ? 1 : 3,
                      emitir, totalUnidades, plazo);
      if (codigo[indiceElemento + 1]) {
        transmitirTramo(false, 1, emitir, totalUnidades, plazo);
      }
    }
    if (texto[indiceLetra + 1]) {
      transmitirTramo(false, texto[indiceLetra + 1] == ' ' ? 7 : 3,
                      emitir, totalUnidades, plazo);
    }
  }
  return totalUnidades;
}

void transmitirMensaje(const char *texto, bool esCalibracion) {
  unsigned long plazo = 0;
  // Primero calcula la duración y avisa al Monitor Serial; después emite luz.
  const uint16_t totalUnidades = recorrerMensaje(texto, false, plazo);
  Serial.print(esCalibracion ? F("BEGIN CAL ") : F("BEGIN SEND "));
  Serial.print(totalUnidades);
  Serial.print(' ');
  Serial.println(duracionUnidadMs);
  Serial.flush();  // Vacía el mensaje serial antes de empezar a medir el tiempo.
  plazo = micros();
  uint16_t unidadesMargen = 0;
  // Deja un tiempo apagado al principio y al final para delimitar el mensaje.
  transmitirTramo(false, 7, true, unidadesMargen, plazo);
  recorrerMensaje(texto, true, plazo);
  transmitirTramo(false, 7, true, unidadesMargen, plazo);
  ponerLed(false);
  Serial.println(esCalibracion ? F("DONE CAL") : F("DONE SEND"));
}

// Convierte a mayúsculas, une espacios repetidos y rechaza caracteres ajenos a A-Z.
// Así evita enviar solo una parte del mensaje si la orden contiene un error.
bool normalizarMensaje(const char *entrada) {
  uint8_t cantidadLetras = 0;
  uint16_t indiceSalida = 0;
  bool espacioPendiente = false;
  for (; *entrada; ++entrada) {
    char caracter = *entrada;
    if (esEspacio(caracter)) {
      if (indiceSalida) espacioPendiente = true;
      continue;
    }
    if (caracter >= 'a' && caracter <= 'z') caracter -= ('a' - 'A');
    if (caracter < 'A' || caracter > 'Z') {
      Serial.println(F("ERROR INVALID_CHARACTER"));
      return false;
    }
    if (++cantidadLetras > MAXIMO_LETRAS) {
      Serial.println(F("ERROR TEXT_TOO_LONG"));
      return false;
    }
    if (indiceSalida + (espacioPendiente ? 1 : 0) + 1 > MAXIMO_LETRAS) {
      Serial.println(F("ERROR TEXT_TOO_LONG"));
      return false;
    }
    if (espacioPendiente) bufferMensaje[indiceSalida++] = ' ';
    bufferMensaje[indiceSalida++] = caracter;
    espacioPendiente = false;
  }
  bufferMensaje[indiceSalida] = '\0';
  if (!cantidadLetras) {
    Serial.println(F("ERROR EMPTY_TEXT"));
    return false;
  }
  return true;
}

// Interpreta una línea del Monitor Serial: SEND envía, T cambia el ritmo,
// CAL envía "AN E" y STATUS muestra los ajustes actuales.
void procesarLinea() {
  bufferLinea[longitudLinea] = '\0';
  char *comando = bufferLinea;
  while (esEspacio(*comando)) ++comando;
  char *finComando = comando + strlen(comando);
  while (finComando > comando && esEspacio(finComando[-1])) --finComando;
  *finComando = '\0';
  if (!*comando) {
    return;  // Lineas vacias ignoradas.
  }
  char *argumentos = comando;
  while (*argumentos && !esEspacio(*argumentos)) ++argumentos;
  if (*argumentos) *argumentos++ = '\0';
  while (esEspacio(*argumentos)) ++argumentos;

  if (strcmp(comando, "SEND") == 0) {
    if (normalizarMensaje(argumentos)) {
      transmitirMensaje(bufferMensaje, false);
    }
  } else if (strcmp(comando, "T") == 0) {
    uint16_t valor = 0;
    bool valorValido = *argumentos != '\0';
    for (const char *digito = argumentos; *digito; ++digito) {
      if (*digito < '0' || *digito > '9' || valor > 200) {
        valorValido = false;
        break;
      }
      valor = valor * 10 + (*digito - '0');
    }
    if (!valorValido || valor < 100 || valor > 2000) {
      Serial.println(F("ERROR T_RANGE"));
    } else {
      duracionUnidadMs = valor;
      Serial.print(F("OK T "));
      Serial.println(duracionUnidadMs);
    }
  } else if (strcmp(comando, "CAL") == 0 || strcmp(comando, "STATUS") == 0) {
    if (*argumentos) {
      Serial.println(F("ERROR ARGUMENTS"));
    } else if (strcmp(comando, "CAL") == 0) {
      transmitirMensaje("AN E", true);
    } else {
      Serial.print(F("STATUS T "));
      Serial.print(duracionUnidadMs);
      Serial.print(F(" PINES 2-9 BUILTIN "));
      Serial.print(SINCRONIZAR_LED_INTEGRADO ? 1 : 0);
      Serial.println(F(" MAX_LETTERS 80 IDLE"));
    }
  } else {
    Serial.println(F("ERROR COMMAND"));
  }
}

void setup() {
  // Prepara los pines del arreglo como salidas
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    pinMode(PINES_LED[i], OUTPUT);
  }

  if (SINCRONIZAR_LED_INTEGRADO) pinMode(LED_BUILTIN, OUTPUT);
  ponerLed(false);
  Serial.begin(115200);
  Serial.println(F("READY"));
}

void loop() {
  // Reúne caracteres hasta recibir fin de línea; entonces procesa una orden.
  while (Serial.available() > 0) {
    const char caracter = static_cast<char>(Serial.read());
    if (caracter == '\n' && retornoCarroPrevio) {
      retornoCarroPrevio = false;
      continue;
    }
    retornoCarroPrevio = caracter == '\r';
    if (caracter == '\r' || caracter == '\n') {
      if (lineaDesbordada) Serial.println(F("ERROR LINE_OVERFLOW"));
      else procesarLinea();
      longitudLinea = 0;
      lineaDesbordada = false;
    } else if (!lineaDesbordada) {
      if (caracter == '\0') {
        // Rechaza una orden que podría quedar cortada antes de tiempo.
        lineaDesbordada = true;
      } else if (longitudLinea < CAPACIDAD_LINEA - 1) {
        bufferLinea[longitudLinea++] = caracter;
      } else {
        lineaDesbordada = true;  // Descarta toda la línea hasta CR/LF.
      }
    }
  }
}