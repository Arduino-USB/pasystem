from mumbleman import MumbleMgr, PyAudioMgr
from remote_client import RemoteConfig, RestartMgr
import threading
import time

# --- Simulated button states ---
push_to_talk_active = False
alarm_button_toggle = False
running = True

# --- Setup audio/mumble ---
remote = RemoteConfig()


while not remote.config_loaded:
	time.sleep(5)


m = MumbleMgr(remote.get_ip(), remote.get_room(), whisper=remote.get_whisper(), password=remote.get_password())

restart_mgr = RestartMgr(m)
a_input = PyAudioMgr(input=True)
a_input.open_stream()

a_output = PyAudioMgr(output=True)
a_output.open_stream()

def play_audio_callaback(user, soundchunk):
	try:
		self.audiomgr.stream.write(soundchunk.pcm)
	except:
		pass

m.play_audio_callaback = play_audio_callaback

m.start_ffmpeg_process()


def push_to_talk():
    global push_to_talk_active

    while running:
        if push_to_talk_active:
            print("[main] Push-To-Talk ACTIVE")
            while push_to_talk_active and running:
                data = a_input.get_audio_chunk()
                m.play_raw_audio(data)
        else:
            a_input.flush_audio()
            time.sleep(0.01)


def push_to_alarm():
    global alarm_button_toggle

    last_state = False

    while running:
        current_state = alarm_button_toggle

        # Detect toggle
        if current_state != last_state:
            if current_state:
                print("[main] Alarm ON")
                m.play_file("alarm.mp3")
            else:
                print("[main] Alarm OFF")
                m.playing_audio = False

        last_state = current_state
        time.sleep(0.05)


def input_listener():
    global push_to_talk_active, alarm_button_toggle, running

    print("\nControls:")
    print("  t = start push-to-talk")
    print("  s = stop push-to-talk")
    print("  a = toggle alarm")
    print("  q = quit\n")

    while running:
        cmd = input("> ").strip().lower()

        if cmd == "t":
            push_to_talk_active = True

        elif cmd == "s":
            push_to_talk_active = False

        elif cmd == "a":
            alarm_button_toggle = not alarm_button_toggle

        elif cmd == "q":
            running = False
            break


try:
    threading.Thread(target=push_to_talk, daemon=True).start()
    threading.Thread(target=push_to_alarm, daemon=True).start()
    threading.Thread(target=input_listener, daemon=True).start()

    print("[main] Loop started")

    while running:
        time.sleep(1)

except KeyboardInterrupt:
    print("Exiting...")

finally:
    m.close()
