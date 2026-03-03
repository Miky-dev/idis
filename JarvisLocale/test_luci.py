import serial
import time

print("Connessione ad Arduino in corso...")
# Apriamo la porta direttamente, senza fare gli snob!
arduino = serial.Serial('COM3', 9600)
time.sleep(2) # Aspettiamo che Arduino si svegli

print("Invio il comando THINK_ON...")
arduino.write(b"THINK_ON\n") # La "b" serve a trasformarlo in segnale elettrico (byte)

print("Fatto! Guarda i LED! (Attendo 10 secondi prima di chiudere la connessione...)")
time.sleep(10)
arduino.close()