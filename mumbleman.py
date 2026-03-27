from pymumble_py3 import Mumble, constants
import random
import threading
import subprocess as sp
import socket
import pyaudio
import time

class MumbleMgr:
	def __init__(self, host, room, whisper=None, password=""):
		print("Starting MumbleMgr")

		self.host = host
		self.password = password
		self.room = room
		self.whisper = whisper

		self.mumble = None
		self.muted = False
		self.running = True
		

		self.audiomgr = PyAudioMgr(output=True)
		self.audiomgr.open_stream()

		self.connect_loop()

		self.mumble.callbacks.set_callback(
			constants.PYMUMBLE_CLBK_SOUNDRECEIVED,
			self.__play_sound
		)

		if whisper:
			print("[whisper] Starting whisper thread")
			threading.Thread(target=self.set_whisper_loop, daemon=True).start()

		threading.Thread(target=self.connection_watchdog, daemon=True).start()

	def safe_disconnect(self):
		try:
			if self.mumble:
				print("[conn] Stopping old client")
				self.mumble.stop()
				time.sleep(1)
		except Exception as e:
			print(f"[conn] Disconnect error: {e}")

	def close(self):
		print("[conn] Closing MumbleMgr")
		self.running = False

		try:
			if hasattr(self, 'ffmpeg_process'):
				self.ffmpeg_process.terminate()
				self.ffmpeg_process.wait()
		except:
			pass

		self.safe_disconnect()
		self.audiomgr.close_stream()

	def connect_loop(self, retry_delay=5):
		while self.running:
			print("[conn] Attempting connection...")

			try:
				self.safe_disconnect()

				self.mumble = Mumble(self.host, self.room, password=self.password)
				self.mumble.start()
				self.mumble.is_ready()

				print("[conn] Connected!")

				self.mumble.set_receive_sound(True)

				self.mumble.callbacks.set_callback(
					constants.PYMUMBLE_CLBK_SOUNDRECEIVED,
					self.__play_sound
				)

				self.mumble.users.myself.unmute()
				self.muted = False

				return

			except Exception as e:
				print(f"[conn] Failed: {e}")

			print(f"[conn] Retrying in {retry_delay}s...")
			time.sleep(retry_delay)

	def connection_watchdog(self):
		print("[conn] Starting watchdog")

		while self.running:
			time.sleep(2)

			try:
				if not self.mumble or self.mumble.connected != constants.PYMUMBLE_CONN_STATE_CONNECTED:
					print("[conn] Lost connection, reconnecting")
					self.connect_loop()
			except Exception as e:
				print(f"[conn] Watchdog error: {e}")

	def set_whisper_loop(self):
		while self.running:
			time.sleep(1)

			if not self.mumble:
				continue

			found = False

			try:
				for session_id, user in self.mumble.users.items():
					if user["name"] == self.whisper:
						self.mumble.sound_output.set_whisper(user["session"])

						if self.muted:
							print("[whisper] Unmuting")
							self.mumble.users.myself.unmute()
							self.muted = False

						found = True

				if not found:
					if not self.muted:
						print("[whisper] Muting")
						self.mumble.users.myself.mute()
						self.muted = True

			except:
				pass

	def __play_sound(self, user, soundchunk):
		if not self.running:
			return

		if soundchunk.pcm is None:
			return

		try:
			self.audiomgr.stream.write(soundchunk.pcm)
		except:
			pass

	def play_file(self, file_path):
			self.playing_audio = True  # start playing

			def feed_audio():
				while self.playing_audio:
					# Start ffmpeg process for this iteration
					command = [
						"ffmpeg",
						"-i", file_path,
						"-acodec", "pcm_s16le",
						"-f", "s16le",
						"-ab", "192k",
						"-ac", "1",
						"-ar", "48000",
						"-"
					]

					process = sp.Popen(command, stdout=sp.PIPE, stderr=sp.DEVNULL)

					while self.playing_audio:
						chunk = process.stdout.read(4096)
						if not chunk:
							break  # end of file reached, restart loop
						if self.mumble:
							self.mumble.sound_output.add_sound(chunk)
						
						# sleep to avoid overwhelming CPU
						time.sleep(4096 / (48000 * 2 * 1))

					# stop ffmpeg when done
					if process.poll() is None:
						process.kill()
						process.wait()

			# run audio feeding in a separate thread
			thread = threading.Thread(target=feed_audio, daemon=True)
			thread.start()

	def play_raw_audio(self, raw_audio_bytes):
		if self.mumble:
			self.mumble.sound_output.add_sound(raw_audio_bytes)

	def start_ffmpeg_process(self):
		self.ffmpeg_process = sp.Popen(
			[
				"ffmpeg",
				"-f", "s16le",
				"-ac", "1",
				"-ar", "48000",
				"-i", "-",
				"-acodec", "pcm_s16le",
				"-f", "s16le",
				"-ar", "48000",
				"-"
			],
			stdin=sp.PIPE,
			stdout=sp.PIPE,
			stderr=sp.DEVNULL
		)

	def feed_audio_to_ffmpeg(self, raw_audio_bytes):
		if hasattr(self, "ffmpeg_process"):
			self.ffmpeg_process.stdin.write(raw_audio_bytes)
			self.ffmpeg_process.stdin.flush()

	def read_ffmpeg_and_send(self):
		while self.running and hasattr(self, "ffmpeg_process"):
			data = self.ffmpeg_process.stdout.read(1920)
			if not data:
				break

			if self.mumble:
				self.mumble.sound_output.add_sound(data)

	def restart(self, host=None, room=None, password=None, whisper=None):
		print("[conn] Restarting Mumble only")

		# update params if provided
		if host is not None:
			self.host = host
		if room is not None:
			self.room = room
		if password is not None:
			self.password = password
		if whisper is not None:
			self.whisper = whisper

		# disconnect current client
		self.safe_disconnect()
		time.sleep(1)

		# reconnect
		try:
			self.mumble = Mumble(self.host, self.room, password=self.password)
			self.mumble.start()
			self.mumble.is_ready()

			print("[conn] Reconnected!")

			self.mumble.set_receive_sound(True)

			self.mumble.callbacks.set_callback(
				constants.PYMUMBLE_CLBK_SOUNDRECEIVED,
				self.__play_sound
			)

			self.mumble.users.myself.unmute()
			self.muted = False

		except Exception as e:
			print(f"[conn] Restart failed: {e}")
			
		

class PyAudioMgr:
	
	def __init__(self, chunck_size=960, sample_rate=48000, input=False, output=False):
		
		if input == output:
			# This means both are True or both are False
			raise ValueError("Exactly one of input or output must be True")
		self.input = input
		self.output = output
		self.p = pyaudio.PyAudio()

		self.stream = None
		self.chunk_size = chunck_size
		self.sample_rate = sample_rate
	
	def open_stream(self):
		self.stream = self.p.open(
			format=pyaudio.paInt16,  # 16-bit PCM
			channels=1,              # mono
			rate=self.sample_rate,
			input=self.input,
			output=self.output,
			frames_per_buffer=self.chunk_size
		)
		
	def close_stream(self):
		if self.stream == None:
			print("Error: stream not open")
		else:
			self.stream.stop_stream()
			self.stream.close()
			
	def get_audio_chunk(self):
		return self.stream.read(self.chunk_size, exception_on_overflow=False)

	def flush_audio(self):
		if self.stream is not None:
			while self.stream.get_read_available() > 0:
				self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)

	def play_sound(self, sound):
		self.stream.write(sound)
	
