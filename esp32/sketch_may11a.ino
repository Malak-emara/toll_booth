#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "Luka";
const char* password = "12345678";
const char* mqtt_server = "broker.emqx.io";

#define SS_PIN    5
#define RST_PIN   4
MFRC522 rfid(SS_PIN, RST_PIN);

#define SERVO_PIN 13
Servo gateServo;

WiFiClient espClient;
PubSubClient client(espClient);
bool gateOpen = false;

void setup() {
  Serial.begin(115200);
  SPI.begin();
  rfid.PCD_Init();

  gateServo.setPeriodHertz(50);
  gateServo.attach(SERVO_PIN, 500, 2400);
  gateServo.write(0);
  delay(600);
  gateServo.detach();

  WiFi.begin(ssid, password);
  Serial.print("Connecting WiFi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi Connected!");
    Serial.println("IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi FAILED!");
    delay(5000);
    ESP.restart();
  }

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
  Serial.println("--- ESP32 Online ---");
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();

  Serial.println("Card: " + uid);

  String msg = "{\"uid\":\"" + uid + "\"}";
  client.publish("tollbooth/scan", msg.c_str());
  Serial.println("Sent: " + msg);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

void callback(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (int i = 0; i < length; i++) msg += (char)payload[i];
  Serial.println("MQTT: " + String(topic) + " -> " + msg);

  if (String(topic) == "tollbooth/command") {
    if (msg.indexOf("OPEN") >= 0) openGate();
    else if (msg.indexOf("CLOSE") >= 0) closeGate();
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT connecting...");
    if (client.connect("ESP32_TollBooth")) {
      Serial.println(" CONNECTED!");
      client.subscribe("tollbooth/command");
    } else {
      Serial.print(" FAILED rc=");
      Serial.print(client.state());
      Serial.println(" retrying...");
      delay(5000);
    }
  }
}

void openGate() {
  if (gateOpen) return;
  gateOpen = true;
  gateServo.attach(SERVO_PIN);
  for (int pos = 0; pos <= 90; pos++) {
    gateServo.write(pos);
    delay(15);
  }
  Serial.println("GATE OPENED");
}

void closeGate() {
  if (!gateOpen) return;
  gateOpen = false;
  for (int pos = 90; pos >= 0; pos--) {
    gateServo.write(pos);
    delay(15);
  }
  delay(200);
  gateServo.detach();
  Serial.println("GATE CLOSED");
}