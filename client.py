from mumbleman import MumbleMgr, PyAudioMgr
from remote_client import RemoteConfig
import RPi.GPIO as GPIO
import threading
import time

PUSH_TO_TALK_PIN = 22
ALARM_PIN = 2
GPIO.setmode(GPIO.BCM)
GPIO.setup(PUSH_TO_TALK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(ALARM_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

remote = RemoteConfig()
while not remote.config_loaded:
	time.sleep(2)
	

a_input = PyAudioMgr(input=True)
a_input.open_stream()

a_output = PyAudioMgr(output=True)
a_output.open_stream()

def play_audio_callback(user, soundchunk):
	try:
		a_output.stream.write(soundchunk.pcm)
	except:
		pass

m.play_audio_callback = play_audio_callback


# remote.get_room() provides the username as per your setup
m = MumbleMgr(remote.get_ip(), remote.get_room(), password=remote.get_password())
m.start_ffmpeg_process()



def push_to_talk():
	while True:
		if GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
			while GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
				data = a_input.get_audio_chunk()
				m.play_raw_audio(data)
		else:
			a_input.flush_audio()
			time.sleep(0.01)

threading.Thread(target=push_to_talk, daemon=True).start()

while True:
	time.sleep(1)