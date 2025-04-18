# Smart Car Park System

A comprehensive smart car park system built using STM32 microcontroller and Raspberry Pi, with license plate recognition and automated barrier control.

## Project Overview

The Smart Car Park System automates vehicle entry/exit management using an STM32 microcontroller and a Raspberry Pi, communicating via UART. It includes:

- LM393 sensor for vehicle detection
- SG90 servo for barrier control
- SSD1306 OLED display for user messages
- Webcam for license plate recognition
- SQLite database for registered plate storage
- Web interface for managing license plates

## Hardware Requirements

### Components
- **STM32F4 Microcontroller**
- **Raspberry Pi 4**
- **LM393 Comparator Sensor**
- **SG90 Servo Motor**
- **0.96-inch SSD1306 OLED Display**
- **USB Webcam**
- **Power supplies (5V, 3.3V)**
- **Jumper wires**

### Wiring Diagram

#### STM32 Connections
- **UART Communication**:
  - PA2 (TX) → Raspberry Pi RX (GPIO15)
  - PA3 (RX) → Raspberry Pi TX (GPIO14)
  - Common GND

- **LM393 Sensor**:
  - VCC → 3.3V or 5V
  - GND → GND
  - Digital Output → PA0 (with pull-down resistor)

- **SG90 Servo**:
  - VCC → 5V external supply
  - GND → GND
  - Signal → PB6 (TIM3 Channel 1)

- **SSD1306 OLED**:
  - VCC → 3.3V
  - GND → GND
  - SCL → PB8 (I2C1 SCL)
  - SDA → PB9 (I2C1 SDA)

#### Raspberry Pi Connections
- **UART**:
  - GPIO14 (TX) → STM32 PA3 (RX)
  - GPIO15 (RX) → STM32 PA2 (TX)
  - GND → Common GND

- **Webcam**:
  - Connected to USB port

## Software Components

### STM32 Firmware (`main.c`)
- Reads vehicle sensor data from LM393
- Controls servo for barrier movement
- Displays status messages on OLED
- Communicates with Raspberry Pi via binary protocol

### Raspberry Pi Software
- **`smart_car_park.py`**: Main script handling:
  - UART communication with STM32
  - License plate detection with OpenCV and EasyOCR
  - SQLite database queries
  - Capacity tracking

- **`app.py`**: Flask web application for:
  - Adding/removing license plates
  - Viewing activity logs
  - Web-based management

### Communication Protocol

Binary packet format:
```
| Start Byte (0xAA) | Length (1 byte) | Event ID (1 byte) | Data (n bytes) | CRC8 (1 byte) |
```

#### Event IDs
| Event ID | Direction | Event Name | Data Format |
|----------|-----------|------------|-------------|
| `0x01` | Pi → STM32 | Display | Null-terminated string (max 16 chars) |
| `0x02` | Pi → STM32 | Servo | 1-byte angle (0-180) |
| `0x03` | STM32 → Pi | Car Detect | 1-byte boolean (1 = detected, 0 = not detected) |
| `0x04` | Pi → STM32 | LP Status | 1-byte status (0 = unregistered, 1 = registered) |
| `0x05` | Pi → STM32 | Park Full Status | 1-byte boolean (1 = full, 0 = not full) |

## Setup Instructions

### STM32 Setup
1. **Hardware Setup**:
   - Configure STM32 with STM32CubeMX to set up:
     - USART2 (PA2/PA3) at 115200 baud
     - GPIO PA0 as input with pull-down
     - TIM3 for PWM on PB6 at 50Hz
     - I2C1 on PB8/PB9
   - Connect all components according to wiring diagram

2. **Firmware Loading**:
   - Compile `main.c` with necessary libraries (HAL, u8g2)
   - Flash to STM32 using ST-Link or other programmer

### Raspberry Pi Setup
1. **System Configuration**:
   ```bash
   # Enable UART
   sudo nano /boot/config.txt
   # Add these lines:
   enable_uart=1
   dtoverlay=disable-bt
   ```

2. **Install Dependencies**:
   ```bash
   sudo apt update
   sudo apt install -y python3-pip libopencv-dev python3-opencv
   pip3 install pyserial easyocr opencv-python flask
   ```

3. **Setup Scripts**:
   ```bash
   # Clone the repository (if applicable)
   git clone https://github.com/yourusername/smart-car-park.git
   cd smart-car-park
   
   # Run the main program
   python3 smart_car_park.py
   
   # Run the web interface (in a separate terminal)
   python3 app.py
   ```

4. **Access Web Interface**:
   - Open a browser and navigate to: `http://<raspberry_pi_ip>:5000`
   - Login with username: `admin`, password: `carpark2023`

## Usage Examples

### Scenario 1: Registered Car Entry
1. Car approaches and is detected by LM393 sensor
2. STM32 sends detection packet to Pi
3. Pi captures plate image and recognizes the plate number
4. Pi checks database and confirms plate is registered
5. Pi sends commands to STM32 to display "Welcome" and open barrier
6. Car passes through, sensor detects absence, barrier closes

### Scenario 2: Unregistered Car
1. Car is detected by sensor
2. STM32 sends detection packet to Pi
3. Pi captures and recognizes plate number
4. Pi checks database and finds plate is not registered
5. Pi sends command to STM32 to display "Invalid Plate"
6. Barrier remains closed

### Adding a New License Plate
1. Access the web interface at `http://<raspberry_pi_ip>:5000`
2. Login with admin credentials
3. Navigate to "License Plates" and click "Add New Plate"
4. Enter the license plate number (e.g., "ABC123")
5. Submit the form to add the plate to the database

## Cybersecurity Considerations

### Risks
- **Data Interception**: UART communication can be intercepted physically
- **Buffer Overflows**: Improper packet handling could lead to memory corruption
- **Unauthorized Access**: Website access could allow unauthorized changes to database
- **Network Exposure**: If Pi is exposed to untrusted networks

### Precautions
- **CRC8 Validation**: All packets include CRC8 for data integrity
- **Input Validation**: All user inputs and packet data validated
- **Authentication**: Web interface protected by login
- **Network Security**: Use VPN/proxy for Pi when connected to networks
- **Physical Security**: Secure hardware in controlled environment

## Testing

### Test Procedures
1. **Sensor Testing**:
   - Simulate car detection by manually toggling PA0 pin high/low
   - Verify UART packets are transmitted properly

2. **License Plate Recognition**:
   - Use sample plates to test webcam recognition
   - Test various lighting conditions and angles

3. **Web Interface Testing**:
   - Add and remove test plates via web interface
   - Check database integrity

4. **Integration Testing**:
   - End-to-end testing with sample plates

### Debug Tips
- Use logic analyzer to monitor UART communication
- Check webcam permissions (`ls -la /dev/video*`)
- Verify I2C address for OLED (typically 0x3C or 0x3D)
- Monitor logs with `tail -f car_park.log` and `tail -f web_app.log`

## Example Communication Log

### Registered Car
```
STM32 → Pi: [AA 02 03 01 DB] (Car Detected)
Pi → STM32: [AA 02 04 01 D8] (LP Status: Registered)
Pi → STM32: [AA 02 02 5A A0] (Servo: 90°)
Pi → STM32: [AA 08 01 57 65 6C 63 6F 6D 65 00 B7] (Display: "Welcome")
STM32 UART: "OK" (x3)
Pi Console: "Car Detected\nOK"
```

### Unregistered Car
```
STM32 → Pi: [AA 02 03 01 DB] (Car Detected)
Pi → STM32: [AA 02 04 00 D9] (LP Status: Unregistered)
Pi → STM32: [AA 0E 01 49 6E 76 61 6C 69 64 20 50 6C 61 74 65 00 C2] (Display: "Invalid Plate")
STM32 UART: "OK" (x2)
Pi Console: "Car Detected\nOK"
```

## License

This project is for educational purposes only. Use in real environments requires additional security measures and owner consent for all activities.

## Contributors

- Your Name - Project Developer

## Acknowledgements

- Reference materials and prior work from educational resources
- Open source libraries: OpenCV, EasyOCR, Flask, u8g2