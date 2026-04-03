import os
import threading
import time
import tempfile
import zipfile
import subprocess
import socket
import shutil
from datetime import datetime
from flask import Flask, jsonify, request, render_template

class UpdateServer:
    def __init__(self):
        self.app = Flask(__name__, template_folder='templates', static_folder='static')
        self.update_path = None                    # path to the mounted USB drive
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
            for item in os.listdir(base):
                mountpoint = os.path.join(base, item)
                if not os.path.isdir(mountpoint):
                    continue
                zip_file = os.path.join(mountpoint, "pa-system-update.zip")
                if os.path.isfile(zip_file):
                    self.update_path = mountpoint
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
                targets = self._discover_ssh_targets()

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

                print(f"✅ Update completed — pushed to {len(results)} device(s)")
                for ip, status in results.items():
                    print(f"   {ip}: {status}")

        except Exception as e:
            print(f"❌ Update failed: {e}")

    def _discover_ssh_targets(self):
        """Scan all local subnets for devices with port 22 open"""
        targets = set()
        try:
            # Get all IPv4 addresses + CIDR via `ip` command
            output = subprocess.check_output(
                ['ip', '-o', '-4', 'addr', 'show'], text=True
            )
            for line in output.splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                ip_cidr = parts[3]
                if '/' not in ip_cidr:
                    continue
                ip = ip_cidr.split('/')[0]
                
                # Take the /24 of whatever network we're on (most common for LAN)
                subnet = '.'.join(ip.split('.')[:3]) + '.'
                
                # Scan that /24 in parallel (fast)
                threads = []
                for i in range(1, 255):
                    test_ip = subnet + str(i)
                    if test_ip == ip:  # skip ourselves
                        continue
                    t = threading.Thread(target=self._check_port_worker, args=(test_ip, targets))
                    threads.append(t)
                    t.start()
                
                for t in threads:
                    t.join(timeout=0.5)

        except Exception:
            pass
        return list(targets)

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
        
        subprocess.check_call(
            [
                "git",
                "push",
                "--force",
                remote_url,
                "main"
            ],
            cwd=repo_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

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