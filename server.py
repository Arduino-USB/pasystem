from flask import Flask, render_template, send_file, request
from remote_client import RemoteConfig, RestartMgr
from remote_server import ConfigServer
from mumbleman import MumbleMgr, PyAudioMgr
from markupsafe import Markup
import threading
import logging
import sys
import os
import random
import re
import time
import ast

sys.path.append(os.getcwd())
# Blueprints


#Remote config server

config_server = ConfigServer()

#Because this is assmued to be the server, assuming the server runs on this machine

m = MumbleMgr("127.0.0.1", "Office", whisper=None, password="password")

a = PyAudioMgr(input=True)
a.open_stream()

m.start_ffmpeg_process()


devices = []

class ContinousPlayback(threading.Thread):
	def __init__(self):
		super().__init__()
		print("[cont_play] Starting continous playback")
		self.playing = False
		
	def run(self):
		while True:
			if self.playing:
				data = a.get_audio_chunk()
				m.play_raw_audio(data)
			time.sleep(0.01)
			
	def play(self):
		print("[cont_play] Playing")
		self.playing = True
	
	def pause(self):
		print("[cont_play] Pausing")
		self.playing = False

#init flask
app = Flask(__name__, template_folder='templates', static_folder='static')
playback_thread = ContinousPlayback()

playback_thread.daemon = True 
playback_thread.start()
playing_file_local = False
#spooky scary secert key

app.config['SECRET_KEY'] = 'JHIKBFjhGFHjgFhkJHfVJJUfgJKkHhKkjhjKler578hy7t78ii0ui'


			
def generate_template(filepath, vars_dict):
	with open(filepath, "r") as f:
		content = f.read()

	# generate a random number for this call
	call_id = random.randint(100000, 999999)

	def replace_var(match):
		var = match.group(1)
		default = match.group(2)

		if var == "ID":
			return str(call_id)
		elif var in vars_dict:
			return str(vars_dict[var])
		elif default is not None:
			return default
		else:
			return ""

	# pattern: $VAR or $VAR='default value'
	content = re.sub(r"\$([A-Z0-9_]+)(?:='([^']*)')?", replace_var, content)

	return Markup(content)

# make it available in Jinja templates
app.jinja_env.globals.update(generate_template=generate_template)



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

@app.route('/')
def main_page():
	return render_template('main.html')

@app.route('/get_users')
def get_users():
	user_name = m.mumble.users.myself["name"]
	user_list_full = list(dict(m.mumble.users.items()).values())
	user_list = ["BROADCAST"]
	for i in range(len(user_list_full)):
		if user_name != user_list_full[i]["name"]:
			user_list.append(user_list_full[i]["name"])

	return {"users" : user_list}

@app.route('/toggle_stream')
def push_to_talk():
	mode = request.args.get("mode")
	users = ast.literal_eval(request.args.get("users"))
	
	print(f"[p2t] Mode: {mode}")
	
	whisper_list = usernames_to_session(users)
	
	print(users)
	
	if not whisper_list:
		print("[p2t] Removing Whisper")
		m.mumble.sound_output.remove_whisper()
	else:
		print(f"[p2t] Setiing whisper list to {whisper_list}")
		m.mumble.sound_output.set_whisper(whisper_list)
	
	if mode == "on":
		playback_thread.play()
		
		return "O.K", 200
	elif mode == "off":
		playback_thread.pause()
		return "O.K", 200
	else:
		return "Error, 'mode' wrong param", 400

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
	
if __name__ == "__main__":
	app.run(debug=False, host="0.0.0.0", port=5000)
