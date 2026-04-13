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
			print("[_play_sound] playing audio")
			self.play_audio_callback(user, soundchunk)
		else:
			print("[_play_sound] callback not found")

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
	def __init__(self, chunk_size=960, sample_rate=48000, input=False, output=False, debug=True):
		if input == output:
			raise ValueError("Exactly one of input or output must be True")

		self.debug = debug
		self.p = pyaudio.PyAudio()
		self.stream = None

		self.input = input
		self.output = output
		self.chunk_size = chunk_size
		self.sample_rate = sample_rate

		if self.debug:
			print(f"[PyAudioMgr] Initialized | input={self.input} output={self.output}")
			print(f"[PyAudioMgr] chunk_size={self.chunk_size} sample_rate={self.sample_rate}")

	def log(self, msg):
		if self.debug:
			print(f"[PyAudioMgr] {msg}")

	def open_stream(self):
		self.log("Opening stream...")

		try:
			self.stream = self.p.open(
				format=pyaudio.paInt16,
				channels=1,
				rate=self.sample_rate,
				input=self.input,
				output=self.output,
				frames_per_buffer=self.chunk_size
			)

			self.log("Stream opened successfully")

			self.log(f"Stream active: {self.stream.is_active()}")

		except Exception as e:
			self.log(f"FAILED to open stream: {e}")
			raise

	def get_audio_chunk(self):
		if not self.stream:
			self.log("get_audio_chunk called but stream is None")
			return b''

		try:
			data = self.stream.read(self.chunk_size, exception_on_overflow=False)
			self.log(f"Captured audio chunk: {len(data)} bytes")
			return data

		except Exception as e:
			self.log(f"Error reading audio: {e}")
			return b''

	def write_audio_chunk(self, pcm):
		if not self.stream:
			self.log("write_audio_chunk called but stream is None")
			return

		try:
			self.stream.write(pcm)
			self.log(f"Wrote audio chunk: {len(pcm)} bytes")

		except Exception as e:
			self.log(f"Error writing audio: {e}")

	def flush_audio(self):
		if self.stream and self.input:
			try:
				avail = self.stream.get_read_available()
				self.log(f"Flushing {avail} frames")

				self.stream.read(avail, exception_on_overflow=False)

			except Exception as e:
				self.log(f"Flush error: {e}")

	def close(self):
		self.log("Closing stream...")

		try:
			if self.stream:
				self.stream.stop_stream()
				self.stream.close()
				self.stream = None

			self.p.terminate()
			self.log("Closed successfully")

		except Exception as e:
			self.log(f"Error during close: {e}")
