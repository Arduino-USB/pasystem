from flask import Flask, render_template, request, Response
from remote_server import ConfigServer
from mumbleman import MumbleMgr, PyAudioMgr
import threading
import queue
import base64
import time
import ast
import json
import os

# Remote server for device management
config_server = ConfigServer()

# Server-side Mumble client (Username: Office)
m = MumbleMgr("127.0.0.1", "Office", password="password")

sound_queue = queue.Queue()


def play_audio_callback(user, soundchunk):
	# assuming soundchunk.pcm is bytes
	encoded = base64.b64encode(soundchunk.pcm).decode("ascii")
	sound_queue.put({"user": user["name"], "soundchunk": encoded})

m.play_audio_callback = play_audio_callback


# Server-side Mic input
a = PyAudioMgr(input=True)
a.open_stream()

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

@app.route('/')
def index():
	return render_template('main.html')



@app.route("/audio_stream")
def audio_stream():
    def generator():
        while True:
            item = sound_queue.get()  # blocks until data arrives
            # Send JSON string per SSE
            yield f"data: {json.dumps(item)}\n\n"

    return Response(generator(), mimetype="text/event-stream")
	
	
@app.route('/get_users')
def get_users():
	user_name = m.mumble.users.myself["name"]
	user_list_full = list(dict(m.mumble.users.items()).values())
	user_list = ["BROADCAST"]
	for i in range(len(user_list_full)):
		if user_name != user_list_full[i]["name"]:
			user_list.append(user_list_full[i]["name"])
			
	return {"users" : user_list}
	
@app.route('/talk', methods=['POST'])
def talk():
	users = ast.literal_eval(request.args.get("users", "[]"))
	whisper_list = usernames_to_session(users)
	pcm_data = request.data  # raw PCM 16-bit

	if not whisper_list:
		print("[talk] Removing Whisper")
		m.mumble.sound_output.remove_whisper()
	else:
		print(f"[talk] Setiing whisper list to {whisper_list}")
		m.mumble.sound_output.set_whisper(whisper_list)

	m.play_raw_audio(pcm_data)
	return '', 200
	
	
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
	
	
