import socket, psutil, ipaddress, requests, threading, json, logging, random, string, os, time, hashlib, sys, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, make_response



class RestartMgr:
	def __init__(self, m):
		print("")
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
				print("[config_watchdog] Config changed on disk!!!")
				
				if 'config.json' in os.listdir():
					self.checksum = new_checksum
					config = json.load(open('config.json', 'r'))
						
					host = config.get("host")
					password = 	config.get("password")
					room = config.get("room")
					whisper = config.get("whisper")
			
					self.m.host = host
					self.m.password = password
					self.m.whisper = whisper
					self.m.nickname = room
					self.m.restart()
				else:
					print("[config_watchdog] Config wiped, killing client")
					self.m.safe_disconnect()
					




class PortIdentify:
	def __init__(self, target_port):
		self.TARGET_PORT = target_port
		self.found_ip = None
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

		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
				s.settimeout(0.5)
				result = s.connect_ex((ip, self.TARGET_PORT))

				if result == 0:
					print(f"[port_identify] Port open on {ip}, attempting HTTP check")

					try:
						url = f"http://{ip}:{self.TARGET_PORT}/register"
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
		#self.config_resv = False			
		#log = logging.getLogger('werkzeug') 
		#log.disabled = True
		@self.app.before_request
		def handle_options():
			if request.method == 'OPTIONS':
				response = make_response()
				response.headers['Access-Control-Allow-Origin'] = '*'
				response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
				response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
				return response

		@self.app.after_request
		def add_cors_headers(response):
			response.headers['Access-Control-Allow-Origin'] = '*'
			response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
			response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
			return response
			
		self.setup_routes()
		threading.Thread(target=self.app.run, kwargs={"host": "0.0.0.0", "port": 6123}, daemon=True).start()

	def setup_routes(self):
		@self.app.route('/set_config', methods=['GET', 'POST', 'OPTIONS', "PUT", "DELETE"])
		def set_config():
			config = request.get_json()
			
			print("[config_client] Writing to file")	
			
			self.config_resv = True			
			
			with open('config.json', 'w') as f:
				f.write(json.dumps(config))
			
			return "O.K", 200		
			
		@self.app.route('/wipe_config', methods=['GET', 'POST', 'OPTIONS', "PUT", "DELETE"])
		def wipe_config():
			
			if 'config.json' in os.listdir():
				print("[config_client] Emptying file")
				with open('config.json', 'w') as f:
					f.write('{"room": "", "host": "", "whisper": "", "password": ""}')
					f.close()
				return "O.K", 200		
			else:
				return "File doen't exist", 400

		@self.app.route('/get_config')
		def get_config():
			if 'config.json' in os.listdir():
				return json.load(open('config.json', 'r'))
			else:
				return "", 400
		
		@self.app.route('/alive')
		def alive():
			return "YES", 200		





class RemoteConfig():
	def __init__(self, port=6122):
		
		self.config_resv_server = ConfigClient()
		self.port_idenifier = PortIdentify(port)
		self.ip_addr = self.port_idenifier.scan_network()
		self.config_loaded = False
		

		threading.Thread(target=self.watchdog_alive, daemon=True).start()

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
					if 'config.json' in os.listdir():
						print("[remote_config] Config recieved from server, applying")
						config_data = json.load(open('config.json'))
					
						self.room = config_data.get('room')
						self.ip = config_data.get('host')
						self.whisper = config_data.get('whisper')
						self.password = config_data.get('password')
						self.config_loaded = True
						
			poll_thread = threading.Thread(target=poll_server, daemon=True)
			poll_thread.start()

	
	def watchdog_alive(self):
		print("[remote_config] Alive watchdog started")
		while True:
			time.sleep(3)

			if not self.ip_addr:
				continue

			try:
				url = f"http://{self.ip_addr}:6122/alive"
				r = requests.get(url, timeout=1)

				if r.status_code == 200:
					continue
				else:
					print("[remote_config] Alive check failed (bad status), rescanning...")

			except Exception:
				print("[remote_config] Alive check failed (exception), rescanning...")

			self.port_idenifier.found_ip = None
			self.ip_addr = self.port_idenifier.scan_network()
			
	def get_room(self):
		return self.room

	def get_ip(self):
		return self.ip

	def get_whisper(self):
		return self.whisper
	
	def get_password(self):
		return self.password
