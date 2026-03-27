from mumbleman import MumbleMgr, PyAudioMgr
import threading
import time
import keyboard  # pip install keyboard

# --- Fake GPIO replacement ---
class FakeGPIO:
	BCM = "BCM"
	IN = "IN"
	PUD_UP = "PUD_UP"
	LOW = 0
	HIGH = 1

	def __init__(self):
		self.keymap = {}

	def setmode(self, mode):
		pass

	def setup(self, pin, mode, pull_up_down=None):
		pass

	def map_key(self, pin, key):
		self.keymap[pin] = key

	def input(self, pin):
		key = self.keymap.get(pin)
		if key and keyboard.is_pressed(key):
			return self.LOW   # pressed
		return self.HIGH      # not pressed

	def cleanup(self):
		pass


GPIO = FakeGPIO()

# --- Setup "GPIO" ---
PUSH_TO_TALK_PIN = 22
ALARM_PIN = 2

GPIO.setmode(GPIO.BCM)
GPIO.setup(PUSH_TO_TALK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(ALARM_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Map pins → keyboard keys
GPIO.map_key(PUSH_TO_TALK_PIN, "space")
GPIO.map_key(ALARM_PIN, "a")

# --- Setup audio/mumble ---
m = MumbleMgr("127.0.0.1", "WeAreKirkingIt2")
a = PyAudioMgr(input=True)
a.open_stream()

m.start_ffmpeg_process()

def push_to_talk():
	while True:
		if GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
			print("[main] Push-To-Talk Button pressed")
			while GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
				data = a.get_audio_chunk()
				m.play_raw_audio(data)
		else:
			a.flush_audio()
			time.sleep(0.01)

def push_to_alarm():
	while True:
		if GPIO.input(ALARM_PIN) == GPIO.LOW:
			print("[main] Push-To-Alarm Button pressed")
			m.play_file("alarm.mp3")
		time.sleep(0.01)

try:
	push_to_talk_thread = threading.Thread(target=push_to_talk, daemon=True)
	push_to_talk_thread.start()

	push_to_alarm_thread = threading.Thread(target=push_to_alarm, daemon=True)
	push_to_alarm_thread.start()

	print("[main] Loop started (SPACE = talk, A = alarm)")

	while True:
		time.sleep(1)

except KeyboardInterrupt:
	print("Exiting...")
	m.close()

finally:
	GPIO.cleanup()
