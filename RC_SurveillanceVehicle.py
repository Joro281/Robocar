import logging
import os
import sys

# Set up the environment for custom packages
site_packages_path = os.path.join('/home/embedded/myenv/lib/python3.11/site-packages')
if site_packages_path not in sys.path:
    sys.path.append(site_packages_path)
    
import threading
import time
import RPi.GPIO as GPIO
from flask import Flask, Response, jsonify, render_template
from bluedot import BlueDot
from signal import pause
import cv2
import adafruit_dht

# GPIO setup function (only set mode once)
def setup_gpio():
    if GPIO.getmode() is None:  # Check if the GPIO mode is already set
        GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)  # Suppress warnings

    # Pin configurations
    global MQ2_PIN, MQ3_PIN, MQ6_PIN, Motor_In1, Motor_In2, Motor_In3, Motor_In4
    MQ2_PIN = 17  
    MQ3_PIN = 27 
    MQ6_PIN = 22
    Motor_In1 = 29
    Motor_In2 = 31
    Motor_In3 = 33
    Motor_In4 = 35

    GPIO.setup([Motor_In1, Motor_In2, Motor_In3, Motor_In4], GPIO.OUT)
    GPIO.setup([MQ2_PIN, MQ3_PIN, MQ6_PIN], GPIO.IN)

# Flask app setup
app = Flask(__name__, template_folder='templates')

# Video capture setup
video_capture = cv2.VideoCapture(0)
if not video_capture.isOpened():
    logging.error("Unable to access the camera. Ensure the camera is connected and enabled in raspi-config.")

# BlueDot setup
bd = BlueDot()
bluedot_active = False

# Sensor data
sensor_data = {
    "mq2": 0,
    "mq3": 0,
    "mq6": 0
}

def generate_frames():
    while True:
        success, frame = video_capture.read()
        if not success:
            logging.error("Failed to read frame from camera. Ensure the camera is accessible.")
            break
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def control_motor(action):
    motor_states = {
        'Forward': [True, False, True, False],
        'Backward': [False, True, False, True],
        'left': [True, False, False, True],
        'right': [False, True, True, False],
        'stop': [False, False, False, False]
    }
    GPIO.output([Motor_In1, Motor_In2, Motor_In3, Motor_In4], motor_states[action])

@app.route('/<action>', methods=['POST', 'GET'])
def motor_control(action):
    global bluedot_active
    if not bluedot_active:
        try:
            logging.info(f"Web command: {action}")
            control_motor(action)
            time.sleep(0.1)
        except Exception as e:
            logging.error(f"Error in {action}: {e}")
    return '', 204

@app.route('/')
def login():
    return render_template("temp.html")

def map_position_to_command(pos):
    x, y = pos.x, pos.y

    if y > 0.5:
        command = 'Forward'
    elif y < -0.5:
        command = 'Backward'
    elif x > 0.5:
        command = 'right'
    elif x < -0.5:
        command = 'left'
    else:
        command = 'stop'

    return command

def on_move(pos):
    global bluedot_active
    bluedot_active = True
    command = map_position_to_command(pos)
    logging.info(f"BlueDot command: {command} at position {pos}")
    
    try:
        control_motor(command)
    except Exception as e:
        logging.error(f"Error in on_move: {e}")

    bluedot_active = False

bd.when_moved = on_move

@app.route('/sensors')
def sensors():
    return jsonify(sensor_data)

# Example for debugging sensors in a thread
def run_sensors():
    try:
        setup_gpio()  # Ensure GPIO is set up before using it

        while True:
            # Poll sensors only if necessary or at longer intervals
            if GPIO.input(MQ2_PIN) != sensor_data["mq2"]:
                sensor_data["mq2"] = GPIO.input(MQ2_PIN)
                logging.info(f"MQ2: {sensor_data['mq2']}")
            if GPIO.input(MQ3_PIN) != sensor_data["mq3"]:
                sensor_data["mq3"] = GPIO.input(MQ3_PIN)
                logging.info(f"MQ3: {sensor_data['mq3']}")
            if GPIO.input(MQ6_PIN) != sensor_data["mq6"]:
                sensor_data["mq6"] = GPIO.input(MQ6_PIN)
                logging.info(f"MQ6: {sensor_data['mq6']}")
            
            # Reduce polling rate to every 2 seconds
            time.sleep(2)
    except Exception as e:
        logging.error(f"Error in run_sensors: {e}")

# BlueDot thread
def run_bluedot():
    try:
        bd.wait_for_press()
        pause()  # Make sure this doesn't block indefinitely
    except Exception as e:
        logging.error(f"Error in run_bluedot: {e}")

# Flask thread
def run_flask():
    try:
        setup_gpio()  # Ensure GPIO is set up before using it
        app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
    except Exception as e:
        logging.error(f"Error in run_flask: {e}")

# Main execution with multithreading for separate components
if __name__ == '__main__':
    try:
        logging.basicConfig(level=logging.DEBUG)

        logging.info("Initializing BlueDot...")
        bluedot_thread = threading.Thread(target=run_bluedot)
        bluedot_thread.daemon = True  # Daemonize to exit when main program exits
        bluedot_thread.start()

        logging.info("Initializing Flask...")
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True  # Daemonize to exit when main program exits
        flask_thread.start()

        logging.info("Starting sensors...")
        sensors_thread = threading.Thread(target=run_sensors)
        sensors_thread.daemon = True  # Daemonize to exit when main program exits
        sensors_thread.start()
        
        logging.info("System running...")

        # Use join on the threads if you want them to wait for completion (not necessary for daemon threads)
        while True:
            time.sleep(1)  # Main thread stays alive

    except Exception as e:
        logging.error(f"Error in main execution: {e}")
