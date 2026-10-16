/*
  Tower Copter — ESP32 IoT Gateway
  Tugas file ini:
    Arduino Mega --(UART)--> ESP32 --(MQTT publish)--> broker (telemetry)
    broker --(MQTT subscribe)--> ESP32 --(UART)--> Arduino Mega (perintah)
*/

#define MQTT_MAX_PACKET_SIZE 512
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <HardwareSerial.h>

// ================= KONFIGURASI =================
const char* WIFI_SSID     = "Anjay_grup";
const char* WIFI_PASSWORD = "Gaktau123";

const char* MQTT_BROKER   = "192.168.18.40";
const int   MQTT_PORT     = 1883;

// Pin UART ke Arduino Mega
const int MEGA_RX_PIN = 16;
const int MEGA_TX_PIN = 17;
const long MEGA_BAUD  = 115200;

// Topic MQTT
const char* TOPIC_COMMAND   = "towercopter/control/command";
const char* TOPIC_SETPOINT  = "towercopter/control/setpoint";
const char* TOPIC_ACK       = "towercopter/control/ack";
const char* TOPIC_TELEMETRY = "towercopter/telemetry";
// =================================================

HardwareSerial MegaSerial(2);
WiFiClient espClient;
PubSubClient mqtt(espClient);
String megaBuffer = "";
String usbBuffer = "";

void setup() {
  Serial.begin(115200);
  MegaSerial.begin(MEGA_BAUD, SERIAL_8N1, MEGA_RX_PIN, MEGA_TX_PIN);

  connectWifi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) reconnectMqtt();
  mqtt.loop();
  forwardTelemetryFromMega();
  forwardTelemetryFromUsbSerial();  // Jalur pengujian manual via USB
}

void connectWifi() {
  Serial.print("Menghubungkan ke WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println("\nWiFi terhubung, IP ESP32: " + WiFi.localIP().toString());
}

void forwardTelemetryFromMega() {
  while (MegaSerial.available()) {
    char c = MegaSerial.read();
    if (c == '\n') {
      if (megaBuffer.length() > 0) {
        mqtt.publish(TOPIC_TELEMETRY, megaBuffer.c_str());
        Serial.println("Telemetry diteruskan: " + megaBuffer);
      }
      megaBuffer = "";
    } else if (c != '\r') {
      megaBuffer += c;
    }
  }
}

void forwardTelemetryFromUsbSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (usbBuffer.length() > 0) {
        mqtt.publish(TOPIC_TELEMETRY, usbBuffer.c_str());
        Serial.println("[TEST] Telemetry manual diteruskan: " + usbBuffer);
      }
      usbBuffer = "";
    } else if (c != '\r') {
      usbBuffer += c;
    }
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  StaticJsonDocument<256> in;
  DeserializationError err = deserializeJson(in, msg);
  if (err) { Serial.println("JSON tidak valid dari MQTT"); return; }

  int commandId = in["command_id"] | 0;
  String topicStr = String(topic);

  StaticJsonDocument<128> toMega;
  StaticJsonDocument<256> ackDoc;
  ackDoc["command_id"] = commandId;
  ackDoc["status"] = "ACKNOWLEDGED";

  if (topicStr == TOPIC_COMMAND) {
    String command = in["command"] | "";
    toMega["command"] = command;
    ackDoc["command"] = command;
  } else if (topicStr == TOPIC_SETPOINT) {
    float sp = in["setpoint"] | 0.0;
    toMega["command"] = "SETPOINT";
    toMega["setpoint"] = sp;
    ackDoc["command"] = "SETPOINT";
    ackDoc["setpoint"] = sp;
  } else {
    return;
  }

  String toMegaLine;
  serializeJson(toMega, toMegaLine);
  MegaSerial.println(toMegaLine);
  Serial.println("Perintah diteruskan ke Mega: " + toMegaLine);

  String ackLine;
  serializeJson(ackDoc, ackLine);
  mqtt.publish(TOPIC_ACK, ackLine.c_str());
}

void reconnectMqtt() {
  while (!mqtt.connected()) {
    Serial.print("Menghubungkan ke MQTT broker...");
    if (mqtt.connect("tower-copter-esp32-device")) {
      Serial.println("terhubung");
      mqtt.subscribe(TOPIC_COMMAND);
      mqtt.subscribe(TOPIC_SETPOINT);
    } else {
      Serial.print("gagal, rc=");
      Serial.print(mqtt.state());
      Serial.println(" — coba lagi 2 detik");
      delay(2000);
    }
  }
}