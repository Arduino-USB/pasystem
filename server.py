from flask import Flask, render_template, request
from remote_server import ConfigServer
from mumbleman import MumbleMgr, PyAudioMgr
import threading
import time
import ast
import os

# Remote server for device management
config_server = ConfigServer()

# Server-side Mumble client (Username: Office)
m = MumbleMgr("127.0.0.1", "Office", password="password")

a_output = PyAudioMgr(output=True)
a_output.open_stream()

def play_audio_callback(user, soundchunk):
	try:
		a_output.stream.write(soundchunk.pcm)
	except:
		pass
		
m.play_audio_callback = play_audio_callback


# Server-side Mic input
a = PyAudioMgr(input=True)
a.open_stream()

class ContinousPlayback(threading.Thread):
	def __init__(self):
		super().__init__()
		self.playing = False
		self.daemon = True
		
	def run(self):
		while True:
			if self.playing:
				data = a.get_audio_chunk()
				m.play_raw_audio(data)
			else:
				# Essential sleep to allow Flask to process requests
				time.sleep(0.05)

playback_thread = ContinousPlayback()
playback_thread.start()
def usernames_to_session(usernames):
	user_list_full = list(dict(m.mumble.users.items()).values())

	if "BROADCAST" in usernames:
		return None
	
	return_list = []
	
	for i in range(len(user_list_full)):
		for j in range(len(usernames)):
			if usernames[j] == user_list_full[i]["name"]:
				return_list.append(user_list_full[i]["session"])

	return return_list
	
app = Flask(__name__)


@app.route('/get_users')
def get_users():
	user_name = m.mumble.users.myself["name"]
	user_list_full = list(dict(m.mumble.users.items()).values())
	user_list = ["BROADCAST"]
	for i in range(len(user_list_full)):
		if user_name != user_list_full[i]["name"]:
			user_list.append(user_list_full[i]["name"])
			
	return {"users" : user_list}
	
@app.route('/')
def index():
	return render_template('main.html')

@app.route('/toggle_stream')
def toggle_stream():
	mode = request.args.get("mode")
	users = ast.literal_eval(request.args.get("users"))
	whisper_list = usernames_to_session(users)

	if not whisper_list:
		print("[play_file] Removing Whisper")
		m.mumble.sound_output.remove_whisper()
	else:
		print(f"[play_file] Setiing whisper list to {whisper_list}")
		m.mumble.sound_output.set_whisper(whisper_list)	

	
	if mode == "on":
		playback_thread.playing = True
	else:
		playback_thread.playing = False
	return "OK", 200
	
	
@app.route('/play_file')
def play_file():
	users = ast.literal_eval(request.args.get("users"))
	file = request.args.get('file')
	
	
	whisper_list = usernames_to_session(users)
	
	print(users)
	
	if not whisper_list:
		print("[play_file] Removing Whisper")
		m.mumble.sound_output.remove_whisper()
	else:
		print(f"[play_file] Setiing whisper list to {whisper_list}")
		m.mumble.sound_output.set_whisper(whisper_list)	
	
	if file in os.listdir():
		print("[play_wrap] Playing file")
		m.play_file(file)
				

		return "O.K", 200
	else:
		return "FILE_NOT_FOUND", 400
		


@app.route('/stop_playing_file')
def stop_playing_file():
	
	playing_file_local = False
	m.playing_audio = False
	return "O.K", 200



#CONFIGURATOR
@app.route('/register')
def register():
	devices.append({"ip" : request.remote_addr, "config" : None})
	print(f"[register] Device {request.remote_addr} added to list!")
	

if __name__ == '__main__':
	# threaded=True is crucial for Flask stability
	app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
	
	
