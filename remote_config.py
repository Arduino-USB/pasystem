import socket, psutil, ipaddress, requests, threading, json, logging, random, string, os, time, hashlib, sys
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request



class RestartMgr:
	def __init__(self, m):
		self.m = m
		self.checksum = self.get_checksum('config.json')
		self.watchdog = threading.Thread(target=self.config_watchdog, daemon=True)
		
		self.watchdog.start()
	def get_checksum(self, file_path, algo="sha256"):
		h = hashlib.new(algo)

		if 'config.json' not in os.listdir():
			return "|-.-.-.-.-.-.-.-|"		
		
		with open(file_path, "rb") as f:
			while chunk := f.read(8192):
				h.update(chunk)

		return h.hexdigest()

	def config_watchdog(self):
		print("[config_watchdog] Service started")
		while True:
			time.sleep(1)
			new_checksum = self.get_checksum('config.json')
			if self.checksum != new_checksum:
				print("[config_watchdog] Config changed on disk")
				
				if 'config.json' in os.listdir():
					self.checksum = new_checksum
					config = json.load(open('config.json', 'r'))
						
					host = config.get("host")
					password = 	config.get("host")
					room = config.get("room")
					whisper = config.get("whisper")
					self.m.restart(host=host, room=room, whisper=whisper, password=password)
				else:
					print("[config_watchdog] Config wiped, killing client")
					m.close()
					sys.exit(0)

class KeyMgr:
	def __init__(self):
		print("[key_setup] Setting up key")
		
		self.config_loaded = False
		
		if 'key' in os.listdir():
			with open('key' , 'r') as f:
				self.key = f.read()
		else:
			with open('key' , 'w') as f:
				self.key = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
				f.write(self.key)
	
	def get_key(self):
		return self.key		

		
class PortIdentify:
	def __init__(self, target_port):
		self.TARGET_PORT = target_port
		self.found_ip = None
		self.keymgr = KeyMgr()

	def get_network(self):
		for iface, addrs in psutil.net_if_addrs().items():
			for addr in addrs:
				if addr.family == socket.AF_INET:
					ip = addr.address
					netmask = addr.netmask

					if ip.startswith("127."):
						continue

					network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
					return network

		raise Exception("No valid network found")

	def check_ip(self, ip):
		if self.found_ip:
			return  # stop early if already found

		ip = str(ip)

		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
				s.settimeout(0.5)
				if s.connect_ex((ip, self.TARGET_PORT)) == 0:
					try:
						response = requests.get(
							f"http://{ip}:{self.TARGET_PORT}/register?key={self.keymgr.get_key()}", 
							timeout=1
						)

						if response and response.status_code == 200:
							print(f"[ip_check] Found:  {ip}")
							self.found_ip = ip
					except:
						pass
		except:
			pass

	def scan_network(self):
		network = self.get_network()
		print(f"Scanning network: {network}")

		with ThreadPoolExecutor(max_workers=50) as executor:
			executor.map(self.check_ip, network.hosts())
		return self.found_ip

class ConfigClientServer:
	def __init__(self):
		self.app = Flask(__name__)
		self.app.logger.disabled = True
		
		self.config_resv = False

		self.keymgr = KeyMgr()			
	
		log = logging.getLogger('werkzeug')
		log.disabled = True
		
		self.setup_routes()
		threading.Thread(target=self.app.run, kwargs={"host": "0.0.0.0", "port": 6122}, daemon=True).start()

	def setup_routes(self):
		@self.app.route('/set_config')
		def set_config():
			config = request.get_json()
			key = request.args.get('key')
			
			print("[flask_app] Got config request")	
		
			if key != self.keymgr.get_key():
				print("[flask_app] Wrong key")
				return "Key Error", 400
			
			print("[flask_app] Writing to file")	
			
			self.config_resv = True			
			
			with open('config.json', 'w') as f:
				f.write(json.dumps(config))
			
			return "O.K", 200		
			
		@self.app.route('/wipe_config')
		def wipe_config():
			key = request.args.get('key')

			if key != self.keymgr.get_key():
				print("[flask_app] Wrong key")
				return "Key Error", 400
			
			if 'config.json' in os.listdir():
				os.remove('config.json')
				return "O.K", 200		
			else:
				return "File doen't exist", 400
		
		@self.app.route('/alive')
		def alive():
			return "YES", 200		
		
class RemoteConfig():
	def __init__(self, port=6741):
		
		self.config_resv_server = ConfigClientServer()
		self.port_idenifier = PortIdentify(port)
		self.ip_addr = self.port_idenifier.scan_network()
		self.config_loaded = False
		

		if 'config.json' in os.listdir():
			config_data = json.load(open('config.json'))
			self.config_loaded = True
			self.room = config_data.get('room')
			self.ip = config_data.get('ip')
			self.whisper = config_data.get('whisper')
		else:
			def poll_server():
				print(f"[remote_config] Starting Flask server to poll {self.ip_addr}:{port}")

				while not self.config_loaded:
					time.sleep(5)
					if self.config_resv_server.config_resv:
						print("[remote_config] Config recieved from server, applying")
						self.config_loaded = True
						config_data = json.load(open('config.json'))
						self.config_loaded = True
						self.room = config_data.get('room')
						self.ip = config_data.get('ip')
						self.whisper = config_data.get('whisper')

			poll_thread = threading.Thread(target=poll_server, daemon=True)
			poll_thread.start()
			
	def get_room(self):
		return self.room

	def get_ip(self):
		return self.ip

	def get_whisper(self):
		return self.whisper
	
		
