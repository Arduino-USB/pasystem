from flask import Flask, request, render_template, jsonify, make_response
import socket
import threading
import logging

class ConfigServer:
	def __init__(self):
		
		self.devices = []
		
		self.app = Flask(__name__, template_folder='templates', static_folder='static')
		#self.app.logger.disabled = True		
	
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
		threading.Thread(target=self.app.run, kwargs={"host": "0.0.0.0", "port": 6122}, daemon=True).start()

	def setup_routes(self):
		@self.app.route('/register')
		def register():
			self.devices.append({"ip" : request.remote_addr, "config" : None})
			print(f"[register] Device {request.remote_addr} added to list!")	
		
			return "O.K", 200
		
		@self.app.route('/get_devices')
		def return_devices():
			return jsonify(self.devices)
			
		@self.app.route('/alive')
		def alive():
			return "YES", 200
		
		@self.app.route('/')
		def main():
			return render_template('conf.html')
			
		@self.app.route('/get_local_ip')
		def get_local_ip():
			return self.get_local_ip()
	
	def get_local_ip(self):
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			# Doesn't have to be reachable
			s.connect(("8.8.8.8", 80))
			ip = s.getsockname()[0]
		finally:
			s.close()
		return ip