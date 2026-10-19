#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <HardwareSerial.h>

// ================= KONFIGURASI =================
const char* WIFI_SSID     = "Princess";
const char* WIFI_PASSWORD = "TanyaBapakKos";

const char* MQTT_BROKER   = "192.168.1.32";
const int   MQTT_PORT     = 1883;

// Pin UART & Baud Rate ke Microcontroller
const int MEGA_RX_PIN = 16;
const int MEGA_TX_PIN = 17;
const long MEGA_BAUD  = 9600; // Ubah ke 9600 jika diuji dengan SoftwareSerial Arduino Uno

// Topic MQTT
const char* TOPIC_COMMAND   = "towercopter/control/command";
const char* TOPIC_SETPOINT  = "towercopter/control/setpoint";
const char* TOPIC_ACK       = "towercopter/control/ack";
const char* TOPIC_TELEMETRY = "towercopter/telemetry";

// ================= OBJEK & VARIABEL =================
HardwareSerial MegaSerial(2);
WiFiClient espClient;
PubSubClient mqtt(espClient);

String megaBuffer = "";
String usbBuffer = "";

unsigned long lastMqttReconnectAttempt = 0;
unsigned long lastWifiCheck = 0;

void setup() {
  Serial.begin(115200);
  MegaSerial.begin(MEGA_BAUD, SERIAL_8N1, MEGA_RX_PIN, MEGA_TX_PIN);

  // Alokasi ukuran buffer paket MQTT
  mqtt.setBufferSize(512);

  connectWifiBlocking();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
}

void loop() {
  // Manajemen koneksi non-blocking agar ESP32 tidak freeze
  maintainConnections();

  if (mqtt.connected()) {
    mqtt.loop();
  }

  forwardTelemetryFromMega();
  forwardTelemetryFromUsbSerial();
}

void connectWifiBlocking() {
  Serial.print("Menghubungkan ke WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(400);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi terhubung! IP ESP32: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nGagal terhubung WiFi, mencoba ulang di latar belakang...");
  }
}

void maintainConnections() {
  unsigned long now = millis();

  // Cek ulang koneksi WiFi tiap 5 detik jika terputus
  if (WiFi.status() != WL_CONNECTED && (now - lastWifiCheck > 5000)) {
    lastWifiCheck = now;
    WiFi.disconnect();
    WiFi.reconnect();
  }

  // Cek ulang koneksi MQTT tiap 3 detik tanpa menghentikan loop program
  if (WiFi.status() == WL_CONNECTED && !mqtt.connected()) {
    if (now - lastMqttReconnectAttempt > 3000) {
      lastMqttReconnectAttempt = now;
      reconnectMqttNonBlocking();
    }
  }
}

void reconnectMqttNonBlocking() {
  Serial.print("Menghubungkan ke MQTT broker... ");
  if (mqtt.connect("tower-copter-esp32-gateway")) {
    Serial.println("terhubung!");
    mqtt.subscribe(TOPIC_COMMAND);
    mqtt.subscribe(TOPIC_SETPOINT);
  } else {
    Serial.print("gagal, state=");
    Serial.println(mqtt.state());
  }
}

void forwardTelemetryFromMega() {
  while (MegaSerial.available()) {
    char c = MegaSerial.read();
    
    // Cetak langsung tiap karakter mentah dari Uno ke Serial Monitor
    Serial.print(c); 

    if (c == '\n') {
      megaBuffer.trim();
      if (megaBuffer.length() > 0) {
        StaticJsonDocument<256> doc;
        DeserializationError err = deserializeJson(doc, megaBuffer);

        if (!err) {
          if (mqtt.connected()) {
            mqtt.publish(TOPIC_TELEMETRY, megaBuffer.c_str());
            Serial.println("\n[UART -> MQTT] Telemetri diteruskan: " + megaBuffer);
          }
        } else {
          Serial.println("\n[WARN] Data UART bukan JSON valid: " + megaBuffer);
        }
      }
      megaBuffer = "";
    } else if (c != '\r') {
      megaBuffer += c;
      if (megaBuffer.length() > 512) megaBuffer = "";
    }
  }
}

void forwardTelemetryFromUsbSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      usbBuffer.trim();
      if (usbBuffer.length() > 0) {
        StaticJsonDocument<256> doc;
        DeserializationError err = deserializeJson(doc, usbBuffer);

        if (!err) {
          if (mqtt.connected()) {
            mqtt.publish(TOPIC_TELEMETRY, usbBuffer.c_str());
            Serial.println("[USB -> MQTT] Telemetri manual diteruskan: " + usbBuffer);
          }
        } else {
          Serial.println("[WARN] Data USB bukan JSON valid: " + usbBuffer);
        }
      }
      usbBuffer = "";
    } else if (c != '\r') {
      usbBuffer += c;
      if (usbBuffer.length() > 512) usbBuffer = ""; // Mencegah buffer overflow
    }
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  StaticJsonDocument<256> in;
  DeserializationError err = deserializeJson(in, msg);
  if (err) {
    Serial.println("[ERROR] JSON tidak valid dari MQTT");
    return;
  }

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
  Serial.println("[MQTT -> UART] Perintah diteruskan ke Mega: " + toMegaLine);

  String ackLine;
  serializeJson(ackDoc, ackLine);
  mqtt.publish(TOPIC_ACK, ackLine.c_str());
}
