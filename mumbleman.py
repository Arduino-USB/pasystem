from pymumble_py3 import Mumble, constants
import threading
import subprocess as sp
import pyaudio
import time

class MumbleMgr:
	def __init__(self, host, nickname, whisper=None, password=""):
		print(f"Starting MumbleMgr as {nickname}")

		self.host = host
		self.password = password
		self.nickname = nickname
		self.whisper = whisper

		self.play_audio_callback = None

		self.mumble = None
		self.running = True
		self.playing_audio = False
	
		# Threaded connection manager
		threading.Thread(target=self.connect_loop, daemon=True).start()

		if whisper:
			threading.Thread(target=self.set_whisper_loop, daemon=True).start()

		# Kept (but now harmless)
		threading.Thread(target=self.connection_watchdog, daemon=True).start()

	def connect_loop(self):
		while self.running:
			if not self.mumble or not self.mumble.is_alive():
				try:
					print(f"[conn] Connecting to {self.host} as {self.nickname}...")

					self.mumble = Mumble(self.host, self.nickname, password=self.password)
					self.mumble.start()
					self.mumble.is_ready()

					# Setup audio reception
					self.mumble.callbacks.set_callback(
						constants.PYMUMBLE_CLBK_SOUNDRECEIVED,
						self._play_sound
					)
					self.mumble.set_receive_sound(True)
					self.mumble.users.myself.unmute()

					print(f"[conn] {self.nickname} Connected and Ready!")

				except Exception as e:
					print(f"[conn] Connection failed: {e}")

			time.sleep(5)

	def _play_sound(self, user, soundchunk):
		"""Callback to play audio from other users"""
		if callable(self.play_audio_callback):
			#print("[_play_sound] playing audio")
			self.play_audio_callback(user, soundchunk)
		#else:
			#print("[_play_sound] callback not found")

	def play_raw_audio(self, data):
		"""For microphone streaming"""

		if self.mumble:
			self.mumble.sound_output.add_sound(data)

	def start_ffmpeg_process(self):
		self.ffmpeg_process = None

	def play_file(self, file_path):
		self.playing_audio = True  # start playing

		def feed_audio():
			while self.playing_audio:
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
						break
					if self.mumble:
						self.mumble.sound_output.add_sound(chunk)

					time.sleep(4096 / (48000 * 2 * 1))

				if process.poll() is None:
					process.kill()
					process.wait()

		thread = threading.Thread(target=feed_audio, daemon=True)
		thread.start()

	def connection_watchdog(self):
		while self.running:
			time.sleep(10)
			if self.mumble and not self.mumble.is_alive():
				print("[watchdog] Connection lost, reconnecting...")
				self.mumble = None  # let connect_loop handle reconnect

	def safe_disconnect(self):
		try:
			if self.mumble:
				print("[conn] Stopping client")
				self.mumble.stop()
				time.sleep(1)
		except Exception as e:
			print(f"[conn] Disconnect error: {e}")
		finally:
			self.mumble = None

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

						if self.mumble.users.myself["self_muted"]:
							print("[whisper] Unmuting")
							self.mumble.users.myself.unmute()
							self.muted = False

						found = True

				if not found:
					if not self.mumble.users.myself["self_muted"]:
						print("[whisper] Muting")
						self.mumble.users.myself.mute()
						self.muted = True

			except:
				pass
				
	def restart(self, host=None, nickname=None, password=None, whisper=None):
		print("[conn] Restarting Mumble (clean)")

		if host is not None:
			self.host = host
		if nickname is not None:
			self.nickname = nickname
		if password is not None:
			self.password = password
		if whisper is not None:
			self.whisper = whisper

		self.safe_disconnect()
	


class PyAudioMgr:
	def __init__(self, chunk_size=960, input=False, output=False,
	             mic_search=None, speaker_search=None, target_rate=48000):

		if input == output:
			raise ValueError("Exactly one of input or output must be True")

		self.p = pyaudio.PyAudio()
		self.stream = None

		self.input = input
		self.output = output

		self.chunk_size = chunk_size
		self.target_rate = target_rate

		self.mic_search = mic_search
		self.speaker_search = speaker_search

		self.running = False
		self.ffmpeg_proc = None

	# ---------- DEVICE SEARCH ----------
	def _find_device(self, search, is_input):
		if not search:
			return None

		search = search.lower()

		for i in range(self.p.get_device_count()):
			info = self.p.get_device_info_by_index(i)
			name = info["name"].lower()

			if search in name:
				if is_input and info["maxInputChannels"] > 0:
					return i
				if not is_input and info["maxOutputChannels"] > 0:
					return i

		return None

	# ---------- OPEN STREAM ----------
	def open_stream(self):
		device_index = None

		if self.input:
			device_index = self._find_device(self.mic_search, True)
		else:
			device_index = self._find_device(self.speaker_search, False)

		if device_index is None:
			device_index = (
				self.p.get_default_input_device_info()["index"]
				if self.input
				else self.p.get_default_output_device_info()["index"]
			)

		info = self.p.get_device_info_by_index(device_index)

		self.stream = self.p.open(
			format=pyaudio.paInt16,
			channels=1,
			rate=self.target_rate,  # IMPORTANT: keep consistent
			input=self.input,
			output=self.output,
			input_device_index=device_index if self.input else None,
			output_device_index=device_index if self.output else None,
			frames_per_buffer=self.chunk_size
		)

		print(f"[PyAudioMgr] device={info['name']}")
		print(f"[PyAudioMgr] ffmpeg rate={self.target_rate}")

	# ---------- FFmpeg INPUT PIPE ----------
	def start_input_stream(self, callback):
		"""
		Mic -> ffmpeg -> callback(chunk)
		"""

		self.running = True

		def worker():
			command = [
				"ffmpeg",
				"-f", "s16le",
				"-ar", str(self.target_rate),
				"-ac", "1",
				"-i", "pipe:0",
				"-f", "s16le",
				"-acodec", "pcm_s16le",
				"-ac", "1",
				"-ar", str(self.target_rate),
				"pipe:1"
			]

			self.ffmpeg_proc = sp.Popen(
				command,
				stdin=sp.PIPE,
				stdout=sp.PIPE,
				stderr=sp.DEVNULL
			)

			while self.running:
				try:
					data = self.stream.read(self.chunk_size, exception_on_overflow=False)

					self.ffmpeg_proc.stdin.write(data)
					self.ffmpeg_proc.stdin.flush()

					out = self.ffmpeg_proc.stdout.read(self.chunk_size)

					if out and callback:
						callback(out)

				except Exception as e:
					print("FFmpeg input error:", e)
					break

			self.stop()

		threading.Thread(target=worker, daemon=True).start()

	# ---------- FFmpeg OUTPUT PLAYBACK ----------
	def start_output_stream(self, source_func):
		"""
		source_func() -> returns raw PCM chunks
		"""

		self.running = True

		def worker():
			command = [
				"ffmpeg",
				"-f", "s16le",
				"-ar", str(self.target_rate),
				"-ac", "1",
				"-i", "pipe:0",
				"-f", "s16le",
				"-acodec", "pcm_s16le",
				"-ar", str(self.target_rate),
				"-ac", "1",
				"pipe:1"
			]

			self.ffmpeg_proc = sp.Popen(
				command,
				stdin=sp.PIPE,
				stdout=sp.PIPE,
				stderr=sp.DEVNULL
			)

			while self.running:
				try:
					data = source_func()
					if not data:
						time.sleep(0.005)
						continue

					self.ffmpeg_proc.stdin.write(data)
					self.ffmpeg_proc.stdin.flush()

					out = self.ffmpeg_proc.stdout.read(self.chunk_size)

					if self.stream:
						self.stream.write(out)

				except Exception as e:
					print("FFmpeg output error:", e)
					break

			self.stop()

		threading.Thread(target=worker, daemon=True).start()

	# ---------- STOP ----------
	def stop(self):
		self.running = False

		try:
			if self.ffmpeg_proc:
				self.ffmpeg_proc.kill()
				self.ffmpeg_proc.wait()
		except:
			pass

		try:
			if self.stream:
				self.stream.stop_stream()
				self.stream.close()
		except:
			pass
