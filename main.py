from mumbleman import MumbleMgr, PyAudioMgr
import RPi.GPIO as GPIO
import threading
import time
#TODO fix issue with voice being choppy 
# --- Setup GPIO ---
PUSH_TO_TALK_PIN = 22
ALARM_PIN = 2
GPIO.setmode(GPIO.BCM)  # Use BCM numbering
GPIO.setup(PUSH_TO_TALK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(ALARM_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- Setup audio/mumble ---
m = MumbleMgr("192.168.0.20", "eho", password="password",whisper="Office")
a = PyAudioMgr(input=True)
a.open_stream()

m.start_ffmpeg_process()


alarm_button_toggle = False


def push_to_talk():

    while True:
        if GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:  # button pressed
            print("[main] Push-To-Talk Button pressed")
            while GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
                #a.flush_audio() 
                data = a.get_audio_chunk()
                m.play_raw_audio(data)
        else:
            a.flush_audio()
            time.sleep(0.01)



def push_to_alarm():
	global alarm_button_toggle

	last_state = GPIO.HIGH

	while True:
		current_state = GPIO.input(ALARM_PIN)

		# Detect button press (falling edge)
		if last_state == GPIO.HIGH and current_state == GPIO.LOW:
			alarm_button_toggle = not alarm_button_toggle

			if alarm_button_toggle:
				print("[main] Alarm ON")
				m.play_file("alarm.mp3")
			else:
				print("[main] Alarm OFF")
				m.playing_audio = False

		last_state = current_state
		time.sleep(0.05)  # debounce
        
try:
    push_to_talk_thread = threading.Thread(target=push_to_talk, daemon=True)
    push_to_talk_thread.start()
    
    push_to_alarm_thread = threading.Thread(target=push_to_alarm, daemon=True)
    push_to_alarm_thread.start()
    
    print("[main] Loop started")
    while True:
        # Main Loop
        time.sleep(1)
except KeyboardInterrupt:
    print("Exiting...")
    m.close()
    pass

finally:

    GPIO.cleanup()
