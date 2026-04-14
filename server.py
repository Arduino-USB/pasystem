from flask import Flask, render_template, request, Response
from remote_server import ConfigServer
from update_server import UpdateServer
from mumbleman import MumbleMgr, PyAudioMgr
from flask_sock import Sock
import threading
import queue
import base64
import time
import ast
import json
import os

mic_queue = queue.Queue(maxsize=200)
# Remote server for device management
config_server = ConfigServer()
update_server = UpdateServer()
# Server-side Mumble client (Username: Office)
m = MumbleMgr("127.0.0.1", "Office", password="password")

sound_queue = queue.Queue()

mic_queue = queue.Queue(maxsize=50)	# small buffer

def audio_worker():
	print("[mic_worker] Running mic worker")

	while True:
		chunk = mic_queue.get()

		if chunk is None:
			break

		try:
			m.play_raw_audio(chunk)
		except Exception as e:
			print("Audio worker error:", e)

# start worker thread once at startup
threading.Thread(target=audio_worker, daemon=True).start()


def play_audio_callback(user, soundchunk):
	# assuming soundchunk.pcm is bytes
	encoded = base64.b64encode(soundchunk.pcm).decode("ascii")
	sound_queue.put({"user": user["name"], "soundchunk": encoded})

m.play_audio_callback = play_audio_callback


# Server-side Mic input
a = PyAudioMgr(input=True, mic_search="CA-2890PRO")
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
sock = Sock(app)

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
	



@sock.route('/talk_ws')
def talk_ws(ws):
	print("[ws] Client connected")

	# --- get whisper users from query ---
	users_param = request.args.get("users", "[]")

	try:
		users = json.loads(users_param)
	except:
		users = ast.literal_eval(users_param)

	whisper_list = usernames_to_session(users)

	if not whisper_list:
		print("[ws] Removing Whisper")
		m.mumble.sound_output.remove_whisper()
	else:
		print(f"[ws] Setting whisper list to {whisper_list}")
		m.mumble.sound_output.set_whisper(whisper_list)

	# --- receive audio stream ---
	while True:
		data = ws.receive()
		if data is None:
			break

		try:
			mic_queue.put_nowait(data)
		except queue.Full:
			print("Audio buffer full, dropping chunk")

	print("[ws] Client disconnected")
	
	
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
	
	
