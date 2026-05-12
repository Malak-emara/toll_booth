cat > README.md << 'EOF'
# 🚗 TollGate Pro - IoT Toll Collection System

## Overview
Automated toll collection using ESP32, RFID, MQTT, and Python GUI.

## Features
- RFID vehicle identification
- Automatic balance deduction  
- Real-time gate control
- Desktop + Mobile GUI
- Live transaction feed
- WAN-scale operation

## Hardware
- ESP32
- MFRC522 RFID Module
- SG90 Servo Motor

## Installation

### Desktop GUI
```bash
pip install customtkinter paho-mqtt
python gui/tollbooth_pro.py
