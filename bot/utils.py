import subprocess
import os
import re
from config import SERVICE_NAME, DATA_PATH, SERVER_PROPS, WORLD_PREFIX, CONTAINER_NAME

def run_command(command):
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            encoding='utf-8'
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1

def get_server_status():
    stdout, stderr, code = run_command(f"systemctl --user is-active {SERVICE_NAME}")
    return stdout # 'active', 'inactive', 'failed', etc.

def manage_server(action):
    # action: start, stop, restart
    # Now that the bot runs on the host, systemctl --user works perfectly
    stdout, stderr, code = run_command(f"systemctl --user {action} {SERVICE_NAME}")
    return code == 0

def get_worlds():
    try:
        # List directories starting with 'world' and exclude nether/the_end
        # Match 'world' exactly or 'world_' followed by characters
        stdout, stderr, code = run_command(f"ls -1 {DATA_PATH} | grep -E '^world(_[a-zA-Z0-9_-]+)?$' | grep -v '_nether$' | grep -v '_the_end$'")
        if code != 0:
            return []
        return stdout.split('\n') if stdout.strip() else []
    except Exception:
        return []

def get_current_world():
    try:
        if not os.path.exists(SERVER_PROPS):
            return "Unknown"
        with open(SERVER_PROPS, 'r') as f:
            for line in f:
                if line.startswith("level-name="):
                    return line.split('=')[1].strip()
    except Exception:
        pass
    return "Unknown"

def set_current_world(world_name):
    try:
        # Try podman exec first (works if container is running)
        cmd = f"podman exec {CONTAINER_NAME} sed -i 's|^level-name=.*|level-name={world_name}|' /data/server.properties"
        stdout, stderr, code = run_command(cmd)
        
        if code == 0:
            return True
            
        # If podman exec failed (e.g. container is stopped), try editing on the host
        # Since it's rootless podman, the files are owned by the user mapping.
        # We can use sed on the host path.
        host_cmd = f"sed -i 's|^level-name=.*|level-name={world_name}|' {SERVER_PROPS}"
        stdout_h, stderr_h, code_h = run_command(host_cmd)
        
        if code_h == 0:
            return True
            
        logging.error(f"Failed to set world name. Podman error: {stderr}, Host error: {stderr_h}")
        return False
    except Exception as e:
        logging.error(f"Critical error setting current world: {e}")
        return False

def delete_world(world_name):
    try:
        # Use podman exec to delete folders from INSIDE the container
        # This bypasses the host permission issues (UID 999 vs 200999)
        cmd = f"podman exec {CONTAINER_NAME} rm -rf /data/{world_name} /data/{world_name}_nether /data/{world_name}_the_end"
        stdout, stderr, code = run_command(cmd)
        return code == 0
    except Exception as e:
        logging.error(f"Error deleting world {world_name}: {e}")
        return False

def create_world(suffix):
    world_name = f"{WORLD_PREFIX}{suffix}"
    # Create world by setting it as current and restarting
    if set_current_world(world_name):
        # Force restart to trigger world generation
        stdout, stderr, code = run_command(f"systemctl --user restart {SERVICE_NAME}")
        return True, world_name
    return False, None

def get_online_players():
    # Using podman exec to call rcon-cli
    stdout, stderr, code = run_command(f"podman exec {CONTAINER_NAME} rcon-cli list")
    if code != 0:
        return None
    
    # Typical output: "There are 0 of a max of 20 players online: "
    if "0 of a max" in stdout or "0 players online" in stdout:
        return "Игроков нет"
    
    match = re.search(r'online: (.+)', stdout)
    if match:
        names = match.group(1).strip()
        return names if names else "Игроков нет"
    
    return stdout if stdout else "Игроков нет"
