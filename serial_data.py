# import serial
# import time

# ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
# time.sleep(2)

# while True:
#     if ser.in_waiting > 0:
#         line = ser.readline().decode('utf-8').strip()
#         print("Arduino:", line)
#     else:
#         print("Waiting for data...")
#     time.sleep(1)

import serial
import time

ser_acm0 = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
ser_acm1 = serial.Serial('/dev/ttyACM1', 9600, timeout=1)
time.sleep(2)

print("Bridge started: ACM0 -> ACM1")

while True:
    # Read from ACM0
    if ser_acm0.in_waiting > 0:
        line = ser_acm0.readline().decode('utf-8', errors='ignore').strip()
        print(f"ACM0 sent: {line}")
        
        # Forward to ACM1
        ser_acm1.write((line + '\n').encode('utf-8'))
        print(f"Forwarded to ACM1: {line}")
    
    # Optional: Read response from ACM1
    if ser_acm1.in_waiting > 0:
        response = ser_acm1.readline().decode('utf-8', errors='ignore').strip()
        print(f"ACM1 replied: {response}")
    
    time.sleep(0.1)
