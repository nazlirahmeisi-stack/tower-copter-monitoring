/*
  Tower Copter — Arduino Uno Telemetry & Control (Inisialisasi 0)
*/

#include <SoftwareSerial.h>
#include <ArduinoJson.h>

SoftwareSerial espSerial(10, 11); // Pin 10 = RX, Pin 11 = TX (ke Resistor)

// Set nilai awal ke 0 & sistem STANDBY
float altitude = 0.0;
float setpoint = 0.0;
float errorVal = 0.0;
int rpm = 0;
int pwm = 0;
float current = 0.0;
bool systemRunning = false; // Mati saat awal dinyalakan

unsigned long lastTelemetryTime = 0;
String inputBuffer = "";

void setup() {
  Serial.begin(115200);
  espSerial.begin(9600);
  Serial.println("==========================================");
  Serial.println("   Arduino Uno Ready (Default Standby 0)  ");
  Serial.println("==========================================");
}

void loop() {
  readIncomingCommands();

  unsigned long now = millis();
  if (now - lastTelemetryTime >= 500) {
    lastTelemetryTime = now;
    sendTelemetry();
  }
}

void sendTelemetry() {
  if (systemRunning) {
    // Dinamika saat sistem RUNNING
    if (setpoint > 0) {
      if (altitude < setpoint) altitude += 0.5;
      else if (altitude > setpoint) altitude -= 0.5;
    }
    rpm = 1800;
    pwm = 150;
    current = 0.52;
  } else {
    // Kondisi STOP / Standby
    if (altitude > 0) altitude -= 1.0;
    if (altitude < 0) altitude = 0;
    rpm = 0;
    pwm = 0;
    current = 0.0;
  }

  errorVal = setpoint - altitude;

  StaticJsonDocument<256> doc;
  doc["altitude"] = altitude;
  doc["setpoint"] = setpoint;
  doc["error"]    = errorVal;
  doc["rpm"]      = rpm;
  doc["pwm"]      = pwm;
  doc["current"]  = current;

  String jsonOutput;
  serializeJson(doc, jsonOutput);

  espSerial.println(jsonOutput);
  Serial.println("[TX -> ESP32] " + jsonOutput);
}

void readIncomingCommands() {
  while (espSerial.available()) {
    char c = espSerial.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        Serial.println("[RX <- ESP32] Perintah diterima: " + inputBuffer);

        StaticJsonDocument<256> cmdDoc;
        DeserializationError err = deserializeJson(cmdDoc, inputBuffer);

        if (!err) {
          String command = cmdDoc["command"] | "";
          if (command == "START") {
            systemRunning = true;
            Serial.println(">> Status: SISTEM RUNNING");
          } else if (command == "STOP") {
            systemRunning = false;
            setpoint = 0.0;
            Serial.println(">> Status: SISTEM STOPPED");
          } else if (command == "SETPOINT") {
            float sp = cmdDoc["setpoint"] | setpoint;
            setpoint = sp;
            systemRunning = true; // Otomatis jalan jika setpoint diatur
          }
        }
      }
      inputBuffer = "";
    } else if (c != '\r') {
      inputBuffer += c;
    }
  }
}