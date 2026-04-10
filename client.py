from mumbleman import MumbleMgr, PyAudioMgr
from remote_client import RemoteConfig, RestartMgr
import RPi.GPIO as GPIO
import threading
import time

# --- Setup GPIO ---
PUSH_TO_TALK_PIN = 22
ALARM_PIN = 2

GPIO.setmode(GPIO.BCM)
GPIO.setup(PUSH_TO_TALK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(ALARM_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- Load remote config ---
remote = RemoteConfig()

while not remote.config_loaded:
    time.sleep(1)

# --- Setup Mumble ---
m = MumbleMgr(
    remote.get_ip(),
    remote.get_room(),
    whisper=remote.get_whisper(),
    password=remote.get_password()
)

m.start_ffmpeg_process()

restart_mgr = RestartMgr(m)

# --- Setup audio ---
a_input = PyAudioMgr(input=True)
a_input.open_stream()

a_output = PyAudioMgr(output=True)
a_output.open_stream()

# --- Audio playback callback ---
def play_audio_callback(user, soundchunk):
    try:
        a_output.stream.write(soundchunk.pcm)
    except Exception:
        pass

m.play_audio_callback = play_audio_callback

# --- Push-To-Talk ---
def push_to_talk():
    while True:
        if GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
            print("[main] Push-To-Talk Button pressed")
            while GPIO.input(PUSH_TO_TALK_PIN) == GPIO.LOW:
                data = a_input.get_audio_chunk()
                m.play_raw_audio(data)
        else:
            a_input.flush_audio()
            time.sleep(0.01)

# --- Alarm toggle ---
alarm_button_toggle = False

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
                m.play_file("alarm.wav")
            else:
                print("[main] Alarm OFF")
                m.playing_audio = False

        last_state = current_state
        time.sleep(0.05)  # debounce

# --- Start threads ---
threading.Thread(target=push_to_talk, daemon=True).start()
threading.Thread(target=push_to_alarm, daemon=True).start()

# --- Main loop ---
try:
    print("[main] Loop started")
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("Exiting...")
    m.close()

finally:
    GPIO.cleanup()