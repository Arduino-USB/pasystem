import socket, psutil, ipaddress, requests, threading, json, logging, random, string, os, time, hashlib, sys, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, make_response



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
		print(f"[port_identify] Initialized with target port {self.TARGET_PORT}")

	def get_network(self):
		print("[port_identify] Discovering network...")

		for iface, addrs in psutil.net_if_addrs().items():
			print(f"[port_identify] Checking interface: {iface}")

			for addr in addrs:
				if addr.family == socket.AF_INET:
					ip = addr.address
					netmask = addr.netmask

					print(f"[port_identify] Found address {ip} with netmask {netmask}")

					if ip.startswith("127."):
						print("[port_identify] Skipping loopback address")
						continue

					network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
					print(f"[port_identify] Using network: {network}")
					return network

		raise Exception("[port_identify] No valid network found")

	def check_ip(self, ip):
		if self.found_ip:
			return None

		ip = str(ip)
		#print(f"[port_identify] Checking IP: {ip}")

		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
				s.settimeout(0.5)
				result = s.connect_ex((ip, self.TARGET_PORT))

				if result == 0:
					print(f"[port_identify] Port open on {ip}, attempting HTTP check")

					try:
						url = f"http://{ip}:{self.TARGET_PORT}/register?key={self.keymgr.get_key()}"
						print(f"[port_identify] Sending request to {url}")

						response = requests.get(url, timeout=1)

						if response:
							print(f"[port_identify] Response from {ip}: {response.status_code}")

						if response and response.status_code == 200:
							print(f"[port_identify] SUCCESS - Found valid server at {ip}")
							self.found_ip = ip
							return ip

					except Exception as e:
						print(f"[port_identify] HTTP check failed for {ip}: {e}")
				else:
					#print(f"[port_identify] Port closed on {ip}")
					pass

		except Exception as e:
			print(f"[port_identify] Socket error on {ip}: {e}")

		return None

	def scan_network(self):
		print("[port_identify] Starting network scan loop")
		network = self.get_network()

		while True:
			print("[port_identify] Beginning new scan cycle")

			with ThreadPoolExecutor(max_workers=50) as executor:
				futures = {
					executor.submit(self.check_ip, ip): ip
					for ip in network.hosts()
				}

				for future in as_completed(futures):
					if self.found_ip:
						print(f"[port_identify] Found IP early: {self.found_ip}, stopping scan")
						return self.found_ip

					try:
						result = future.result()
						if result:
							print(f"[port_identify] Found IP via future: {result}")
							return result
					except Exception as e:
						print(f"[port_identify] Future error: {e}")

			print("[port_identify] Scan cycle complete, retrying in 1 second")
			time.sleep(1)
			
class ConfigClient:
	def __init__(self):
		self.app = Flask(__name__)
		#self.app.logger.disabled = True
		
		self.config_resv = False

		self.keymgr = KeyMgr()			
	
		#log = logging.getLogger('werkzeug')
		#log.disabled = True
		@self.app.before_request
		def handle_options():
			if request.method == 'OPTIONS':
				response = make_response()
				response.headers['Access-Control-Allow-Origin'] = '*'
				response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
				response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
				return response  # only short-circuit OPTIONS

		# Add CORS headers to all responses
		@self.app.after_request
		def add_cors_headers(response):
			response.headers['Access-Control-Allow-Origin'] = '*'
			response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
			response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
			return response
			
		self.setup_routes()
		threading.Thread(target=self.app.run, kwargs={"host": "0.0.0.0", "port": 6123}, daemon=True).start()

	def setup_routes(self):
		@self.app.route('/set_config', methods=['GET', 'POST', 'OPTIONS', "PUT", "DELETEt"])
		def set_config():
			config = request.get_json()
			
		
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
	def __init__(self, port=6122):
		
		self.config_resv_server = ConfigClient()
		self.port_idenifier = PortIdentify(port)
		self.ip_addr = self.port_idenifier.scan_network()
		self.config_loaded = False
		

		if 'config.json' in os.listdir():
			config_data = json.load(open('config.json'))
			self.config_loaded = True
			self.room = config_data.get('room')
			self.ip = config_data.get('host')
			self.whisper = config_data.get('whisper')
			self.password = config_data.get('password')
		else:
			def poll_server():
				print(f"[remote_config] Starting Flask server to poll {self.ip_addr}:{port}")

				while not self.config_loaded:
					time.sleep(5)
					if self.config_resv_server.config_resv:
						print("[remote_config] Config recieved from server, applying")
						config_data = json.load(open('config.json'))
						
						self.room = config_data.get('room')
						self.ip = config_data.get('host')
						self.whisper = config_data.get('whisper')
						self.password = config_data.get('password')
						self.config_loaded = True
						
			poll_thread = threading.Thread(target=poll_server, daemon=True)
			poll_thread.start()
			
	def get_room(self):
		return self.room

	def get_ip(self):
		return self.ip

	def get_whisper(self):
		return self.whisper
	
	def get_password(self):
		return self.password
	
		
