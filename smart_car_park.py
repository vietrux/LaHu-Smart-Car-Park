#!/usr/bin/python3
"""
Smart Car Park System - Raspberry Pi Controller

Manages:
- UART communication with STM32
- License plate recognition via USB webcam
- SQLite database for registered plates
- Parking lot capacity tracking
"""

import serial
import cv2
import sqlite3
import threading
import time
import logging
import os
import numpy as np
from datetime import datetime
from detector import LicensePlateDetector
from ocr_reader import OCRReader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("car_park.log"),
        logging.StreamHandler()
    ]
)

# Global constants
PACKET_START = 0xAA
EVENT_DISPLAY = 0x01
EVENT_SERVO = 0x02
EVENT_CAR_DETECT = 0x03
EVENT_LP_STATUS = 0x04
EVENT_PARK_FULL = 0x05

# Global variables
car_detected = False
lot_capacity = 0
MAX_CAPACITY = 100
lock = threading.Lock()
db_path = "car_park.db"

# Initialize license plate detector and OCR reader
detector = LicensePlateDetector(model_path="best.pt")
ocr = OCRReader()

class UARTHandler:
    """Handles UART communication with STM32"""
    
    def __init__(self, port="/dev/serial0", baud_rate=115200):
        """Initialize UART communication"""
        self.port = port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.buffer = bytearray()
    
    def connect(self):
        """Connect to UART port"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            self.running = True
            logging.info(f"Connected to {self.port} at {self.baud_rate} baud")
            return True
        except Exception as e:
            logging.error(f"Error connecting to {self.port}: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from UART port"""
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
            logging.info(f"Disconnected from {self.port}")
    
    def send_packet(self, event_id, data):
        """Send a packet to STM32
        
        Args:
            event_id (int): Event ID (0x01-0x05)
            data (bytes or bytearray): Data to send
        
        Returns:
            bool: True if packet was sent successfully
        """
        if not self.ser or not self.ser.is_open:
            logging.error("Cannot send packet: UART not connected")
            return False
        
        # Construct packet
        packet = bytearray([PACKET_START])
        packet.append(len(data) + 1)  # Length (event ID + data)
        packet.append(event_id)       # Event ID
        
        # Add data
        if isinstance(data, (bytes, bytearray)):
            packet.extend(data)
        else:
            packet.extend(data.encode('utf-8'))
        
        # Calculate CRC8
        crc = self.calculate_crc8(packet[2:])
        packet.append(crc)
        
        try:
            self.ser.write(packet)
            logging.debug(f"Sent packet: {packet.hex()}")
            
            # Wait for response
            response = self.ser.readline().decode('utf-8').strip()
            if response == "OK":
                logging.debug("Received OK response")
                return True
            elif response == "ERR":
                logging.warning("Received ERR response")
                return False
            else:
                logging.warning(f"Unknown response: {response}")
                return False
        except Exception as e:
            logging.error(f"Error sending packet: {str(e)}")
            return False
    
    def receiver_thread(self):
        """Thread that receives and processes incoming packets"""
        
        packet_state = 0  # 0: waiting for start, 1: got length, 2: collecting data
        packet_length = 0
        packet_data = bytearray()
        
        while self.running:
            if not self.ser or not self.ser.is_open:
                time.sleep(1)
                continue
            
            try:
                # Read available data
                if self.ser.in_waiting > 0:
                    data = self.ser.read(self.ser.in_waiting)
                    
                    for byte in data:
                        # State machine to parse incoming packets
                        if packet_state == 0:  # Waiting for start byte
                            if byte == PACKET_START:
                                packet_data = bytearray([PACKET_START])
                                packet_state = 1
                        
                        elif packet_state == 1:  # Got start, get length
                            packet_length = byte
                            packet_data.append(byte)
                            packet_state = 2
                        
                        elif packet_state == 2:  # Collecting data
                            packet_data.append(byte)
                            
                            # Check if we have a complete packet
                            if len(packet_data) >= packet_length + 3:  # Start + Length + Data + CRC
                                self.process_packet(packet_data)
                                packet_state = 0  # Reset state machine
                    
                time.sleep(0.01)  # Small delay to prevent CPU hogging
            
            except Exception as e:
                logging.error(f"Error in receiver thread: {str(e)}")
                time.sleep(1)
    
    def process_packet(self, packet):
        """Process a complete packet from STM32"""
        
        # Verify packet format
        if len(packet) < 4:  # Minimum: Start + Length + Event ID + CRC
            logging.error(f"Invalid packet length: {len(packet)}")
            self.send_response("ERR")
            return
        
        length = packet[1]
        event_id = packet[2]
        data = packet[3:-1]
        received_crc = packet[-1]
        
        # Calculate CRC
        calculated_crc = self.calculate_crc8(packet[2:-1])
        
        # Verify CRC
        if received_crc != calculated_crc:
            logging.error(f"CRC mismatch: received {received_crc}, calculated {calculated_crc}")
            self.send_response("ERR")
            return
        
        # Send OK response
        self.send_response("OK")
        
        # Process based on event ID
        if event_id == EVENT_CAR_DETECT:
            global car_detected
            is_detected = data[0] == 1
            
            # Only process state changes
            if is_detected != car_detected:
                car_detected = is_detected
                if car_detected:
                    logging.info("Car detected")
                    self.handle_car_arrival()
                else:
                    logging.info("No car")
        else:
            logging.warning(f"Unknown event ID: {event_id}")
    
    def send_response(self, response):
        """Send a simple text response (OK/ERR)"""
        if self.ser and self.ser.is_open:
            self.ser.write(f"{response}\n".encode())
    
    def handle_car_arrival(self):
        """Handle a car arriving at the barrier"""
        
        # Check if lot is full
        global lot_capacity, MAX_CAPACITY
        if lot_capacity >= MAX_CAPACITY:
            logging.info("Parking lot is full")
            self.send_packet(EVENT_PARK_FULL, bytearray([1]))
            self.send_packet(EVENT_DISPLAY, "Lot Full")
            return
        
        # Capture license plate
        plate_number = capture_license_plate()
        if plate_number:
            logging.info(f"Detected plate: {plate_number}")
            
            # Check if plate is registered
            if check_plate_registered(plate_number):
                logging.info(f"Plate {plate_number} is registered")
                
                # Increment lot capacity
                with lock:
                    lot_capacity += 1
                    if lot_capacity >= MAX_CAPACITY:
                        self.send_packet(EVENT_PARK_FULL, bytearray([1]))
                
                # Send commands to STM32
                self.send_packet(EVENT_LP_STATUS, bytearray([1]))  # Registered
                self.send_packet(EVENT_SERVO, bytearray([90]))     # Open barrier
                self.send_packet(EVENT_DISPLAY, f"Welcome")
                
                # Log entry
                log_vehicle_movement(plate_number, "entry")
            else:
                logging.info(f"Plate {plate_number} is not registered")
                self.send_packet(EVENT_LP_STATUS, bytearray([0]))  # Not registered
                self.send_packet(EVENT_DISPLAY, "Invalid Plate")
        else:
            logging.warning("Failed to detect license plate")
            self.send_packet(EVENT_DISPLAY, "No Plate Found")
    
    @staticmethod
    def calculate_crc8(data):
        """Calculate CRC8 with polynomial 0x07"""
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x07
                else:
                    crc = crc << 1
                crc &= 0xFF  # Keep only 8 bits
        return crc

def capture_license_plate():
    """Capture and recognize license plate using dedicated detector and OCR
    
    Returns:
        str or None: Recognized plate number or None if failed
    """
    try:
        # Open camera (adjust index if needed)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logging.error("Failed to open webcam")
            return None
        
        # Set camera parameters
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        # Allow camera to adjust exposure
        for _ in range(5):
            cap.read()
            time.sleep(0.1)
        
        # Capture frame
        ret, frame = cap.read()
        if not ret:
            logging.error("Failed to capture frame")
            cap.release()
            return None
        
        # Save original image for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_dir = "debug_images"
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(f"{debug_dir}/original_{timestamp}.jpg", frame)
        
        # Use license plate detector to find and crop the license plate
        cropped_plate = detector.detect_and_crop(frame)
        
        if cropped_plate is not None:
            # Save detected plate image
            cv2.imwrite(f"{debug_dir}/plate_{timestamp}.jpg", cropped_plate)
            
            # Use OCR to read the plate text
            plate_text = ocr.read_text(cropped_plate)
            
            # Release camera
            cap.release()
            
            if plate_text:
                # Clean up the detected text (remove spaces, convert to uppercase)
                plate_text = plate_text.upper().replace(' ', '')
                logging.info(f"Detected license plate text: {plate_text}")
                return plate_text
            else:
                logging.warning("OCR could not read text from the detected plate")
                return None
        else:
            logging.warning("No license plate detected in image")
            # Save processed image
            cv2.imwrite(f"{debug_dir}/processed_{timestamp}.jpg", frame)
            cap.release()
            return None
            
    except Exception as e:
        logging.error(f"Error capturing license plate: {str(e)}")
        return None

def init_database():
    """Initialize SQLite database if it doesn't exist"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create plates table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS plates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT UNIQUE NOT NULL,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create log table for entries/exits
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS movement_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT NOT NULL,
            action TEXT NOT NULL,  -- 'entry' or 'exit'
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()
        logging.info("Database initialized successfully")
        return True
    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")
        return False

def check_plate_registered(plate_number):
    """Check if a license plate is registered in the database
    
    Args:
        plate_number (str): License plate number to check
    
    Returns:
        bool: True if plate is registered, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT 1 FROM plates WHERE plate_number = ?", (plate_number,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    except Exception as e:
        logging.error(f"Error checking plate registration: {str(e)}")
        return False

def log_vehicle_movement(plate_number, action):
    """Log vehicle entry or exit
    
    Args:
        plate_number (str): License plate number
        action (str): 'entry' or 'exit'
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO movement_log (plate_number, action) VALUES (?, ?)",
            (plate_number, action)
        )
        
        conn.commit()
        conn.close()
        logging.info(f"Logged {action} for plate {plate_number}")
        return True
    except Exception as e:
        logging.error(f"Error logging vehicle movement: {str(e)}")
        return False

def main():
    """Main function"""
    
    # Initialize database
    if not init_database():
        logging.error("Failed to initialize database. Exiting.")
        return
    
    # Connect to UART
    uart = UARTHandler()
    if not uart.connect():
        logging.error("Failed to connect to UART. Exiting.")
        return
    
    # Start receiver thread
    receiver_thread = threading.Thread(target=uart.receiver_thread)
    receiver_thread.daemon = True
    receiver_thread.start()
    
    logging.info("Smart Car Park system running")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        uart.disconnect()

if __name__ == "__main__":
    main()