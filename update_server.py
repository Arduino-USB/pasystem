import os
import threading
import time
import tempfile
import zipfile
import subprocess
import socket
import shutil
import ipaddress
import platform
import re
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from concurrent.futures import ThreadPoolExecutor, as_completed


class PortScanner:
	def __init__(self, target_port, timeout=0.5, max_threads=100):
		self.target_port = target_port
		self.timeout = timeout
		self.max_threads = max_threads
		self.network = self._get_local_network()

	def _get_local_ip(self):
		"""Get local IP address"""
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			s.connect(("8.8.8.8", 80))
			return s.getsockname()[0]
		finally:
			s.close()

	def _get_subnet_mask(self):
		"""Get subnet mask from OS (Windows/Linux)"""
		system = platform.system()

		try:
			if system == "Windows":
				output = subprocess.check_output("ipconfig", text=True)
				match = re.search(r"Subnet Mask[^\d]*(\d+\.\d+\.\d+\.\d+)", output)
				if match:
					return match.group(1)
			elif system in ("Linux", "Darwin"):
				ip = self._get_local_ip()
				output = subprocess.check_output(["ip", "addr"], text=True)

				match = re.search(rf"inet\s+{re.escape(ip)}/(\d+)", output)
				if match:
					prefix = int(match.group(1))
					return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)

		except Exception as e:
			print(f"[port_scanner] Failed to detect subnet mask: {e}")

		# fallback
		return "255.255.255.0"

	def _get_local_network(self):
		ip = self._get_local_ip()
		mask = self._get_subnet_mask()

		network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
	
		print(f"[port_scanner] Network detected: {network}")

		return network

	def _scan_ip(self, ip):
		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
				s.settimeout(self.timeout)
				if s.connect_ex((str(ip), self.target_port)) == 0:
					return str(ip)
		except Exception:
			pass
		return None

	def scan_network(self):
		"""Blocking scan, returns list of IPs with port open."""
		found_ips = []

		with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
			futures = [executor.submit(self._scan_ip, ip) for ip in self.network.hosts()]

			for future in as_completed(futures):
				result = future.result()
				if result:
					print(f"[port_scanner] Found open port on {result}")
					found_ips.append(result)

		return found_ips


class UpdateServer:
	def __init__(self):
		self.app = Flask(__name__, template_folder='templates', static_folder='static')
		self.update_path = None					# path to the mounted USB drive
		self.previous_versions_dir = "previous_versions"
		
		# Ensure storage exists
		os.makedirs(self.previous_versions_dir, exist_ok=True)
		
		self._register_routes()
		self._start_usb_poller()
		self.start()
		
	def _register_routes(self):
		self.app.add_url_rule('/', 'index', self.index, methods=['GET'])
		self.app.add_url_rule('/revert', 'revert', self.revert_page, methods=['GET'])
		self.app.add_url_rule('/get_update_status', 'get_update_status', self.get_update_status, methods=['GET'])
		self.app.add_url_rule('/get_all_versions', 'get_all_versions', self.get_all_versions, methods=['GET'])
		self.app.add_url_rule('/delete_version', 'delete_version', self.delete_version, methods=['GET'])
		self.app.add_url_rule('/update_network', 'update_network', self.update_network, methods=['GET'])

	def _start_usb_poller(self):
		"""Daemon thread that continuously looks for pa-system-update.zip"""
		threading.Thread(target=self._usb_poller_loop, daemon=True).start()

	def _usb_poller_loop(self):
		while True:
			self._check_for_usb_update()
			time.sleep(3)  # poll every 3 seconds

	def _check_for_usb_update(self):
		"""Scan common Linux mount points for the update zip"""
		self.update_path = None
		bases = ['/media', '/mnt', '/run/media']

		for base in bases:
			if not os.path.exists(base):
				continue

			for root, dirs, files in os.walk(base):
				if "pa-system-update.zip" in files:
					self.update_path = root
					return  # first match wins

	def index(self):
		"""Main dashboard with two big buttons"""
		return render_template('update.html')

	def revert_page(self):
		return render_template('revert.html')

	def get_update_status(self):
		"""Used by JS to show USB status"""
		return jsonify({
			"connected": self.update_path is not None,
			"path": self.update_path
		})

	def get_all_versions(self):
		"""Returns list of previous .zip files"""
		if not os.path.exists(self.previous_versions_dir):
			return jsonify([])
		versions = [
			f for f in os.listdir(self.previous_versions_dir)
			if f.endswith('.zip')
		]
		return jsonify(sorted(versions, reverse=True))

	def delete_version(self):
		version = request.args.get('version')
		if not version:
			return jsonify({"error": "no version"}), 400
		
		filepath = os.path.join(self.previous_versions_dir, version)
		if os.path.isfile(filepath):
			os.remove(filepath)
			return jsonify({"success": True})
		return jsonify({"error": "version not found"}), 404

	def update_network(self):
		"""Main update endpoint"""
		version = request.args.get('version', 'now')
		
		# Determine which zip to use
		if version == "now":
			if not self.update_path:
				return jsonify({"error": "No USB drive with pa-system-update.zip detected"}), 400
			zip_path = os.path.join(self.update_path, "pa-system-update.zip")
		else:
			zip_path = os.path.join(self.previous_versions_dir, version)
			if not os.path.isfile(zip_path):
				return jsonify({"error": "Selected version not found"}), 404

		# Perform the actual update in the background so UI stays responsive
		threading.Thread(
			target=self._perform_update,
			args=(version, zip_path),
			daemon=True
		).start()

		return jsonify({
			"status": "update_started",
			"message": "Network update has been launched in the background"
		})

	def _perform_update(self, version: str, zip_path: str):
		"""Heavy lifting: unzip → git → push to every device on the network"""
		try:
			with tempfile.TemporaryDirectory() as tmp_repo:
				# 1. Init fresh git repo
				subprocess.check_call(['git', 'init'], cwd=tmp_repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
				
				# 2. Unzip the update package into the repo
				with zipfile.ZipFile(zip_path) as z:
					z.extractall(tmp_repo)
				
				# 3. Commit everything
				subprocess.check_call(['git', 'add', '-A'], cwd=tmp_repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
				try:
					subprocess.check_call(
						['git', 'commit', '-m', f'PA System Update — {version}'],
						cwd=tmp_repo,
						stdout=subprocess.DEVNULL,
						stderr=subprocess.DEVNULL
					)
				except subprocess.CalledProcessError:
					pass  # no changes
				
				# Force main branch name (modern git default)
				subprocess.check_call(['git', 'branch', '-M', 'main'], cwd=tmp_repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

				# 4. Discover all network devices with SSH (port 22) open
				
				port_scanner = PortScanner(22)
				
				targets = port_scanner.scan_network()

				results = {}
				for ip in targets:
					try:
						self._push_to_target(tmp_repo, ip)
						results[ip] = "success"
					except Exception as e:
						results[ip] = f"failed: {e}"

				# 5. If this was a USB update, archive it to previous versions
				if version == "now":
					os.makedirs(self.previous_versions_dir, exist_ok=True)
					timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
					archive_name = f"{timestamp}_pa-system-update.zip"
					shutil.copy2(zip_path, os.path.join(self.previous_versions_dir, archive_name))

				print(f"[update_pusher] Update completed — pushed to {len(results)} device(s)")
				for ip, status in results.items():
					print(f"   {ip}: {status}")

		except Exception as e:
			print(f"[update_pusher] Update failed: {e}")

	def _check_port_worker(self, ip: str, targets: set):
		if self._check_port_open(ip, 22, timeout=0.25):
			targets.add(ip)

	def _check_port_open(self, ip: str, port: int, timeout: float = 0.25) -> bool:
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.settimeout(timeout)
		result = sock.connect_ex((ip, port)) == 0
		sock.close()
		return result

	def _push_to_target(self, repo_dir: str, ip: str):
		"""Push the new commit to a remote bare repo via SSH"""
		remote_url = f"ssh://mumble_client@{ip}:/home/mumble_client/mumble_client/update_recv"
		
		env = os.environ.copy()
		env["GIT_SSH_COMMAND"] = (
			"sshpass -p 'mumbleing_it' "
			"ssh -o StrictHostKeyChecking=no "
			"-o UserKnownHostsFile=/dev/null"
		)
		
		result = subprocess.run(
			[
				"git",
				"push",
				"--force",
				"-v",
				"--progress",
				remote_url,
				"main"
			],
			cwd=repo_dir,
			env=env,
			text=True,
			capture_output=True
		)
		
		print(result) 
	def start(self):
		"""Run the Flask server on a separate daemon thread (exactly as you asked)"""
		def run_server():
			self.app.run(
				host="0.0.0.0",
				port=6124,
				debug=False,
				use_reloader=False,
				threaded=True
			)
		
		server_thread = threading.Thread(target=run_server, daemon=True)
		server_thread.start()
		print("   PA System Update Server started on http://0.0.0.0:6124")
		print("   USB poller and network scanner are running in background")
		print("   Be warned: ts IS vibe coded, okay? i was tired of writing code!!! (it work tho)")
