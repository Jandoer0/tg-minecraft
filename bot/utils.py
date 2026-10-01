import subprocess
import os
import re
import logging
from config import SERVICE_NAME, DATA_PATH, SERVER_PROPS, WORLD_PREFIX, CONTAINER_NAME

def run_command(command):
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=False, # Changed to False to get bytes
            encoding=None
        )
        # Decode using 'replace' to ignore broken characters/ANSI
        stdout = result.stdout.decode('utf-8', errors='replace').strip()
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        return stdout, stderr, result.returncode
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
        # 1. Try using podman exec if container is running
        cmd = f"podman exec {CONTAINER_NAME} rm -rf /data/{world_name} /data/{world_name}_nether /data/{world_name}_the_end"
        stdout, stderr, code = run_command(cmd)
        if code == 0:
            return True
            
        # 2. Fallback: Use 'podman unshare' to delete files on the host.
        # This allows us to act as the container user (UID 0 inside, 200999 outside)
        # and bypass 'Permission denied' errors on the host.
        host_world_path = os.path.join(DATA_PATH, world_name)
        host_nether_path = os.path.join(DATA_PATH, f"{world_name}_nether")
        host_end_path = os.path.join(DATA_PATH, f"{world_name}_the_end")
        
        # We build a command to delete all existing world folders for this name
        paths_to_delete = [host_world_path, host_nether_path, host_end_path]
        
        # Execute deletion via podman unshare
        # Use quotes for paths to handle spaces
        delete_cmd = f"podman unshare rm -rf {' '.join([f'\"{p}\"' for p in paths_to_delete])}"
        stdout, stderr, code = run_command(delete_cmd)
        
        if code == 0:
            return True
            
        logging.error(f"Failed to delete world {world_name} even with unshare: {stderr}")
        return False
    except Exception as e:
        logging.error(f"Critical error deleting world {world_name}: {e}")
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
        logging.error(f"RCON command failed with code {code}: {stderr}")
        return None
    
    # RCON output often contains ANSI escape codes and trailing garbage
    # We remove all ANSI sequences using a regex for reliability
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -~])')
    clean_stdout = ansi_escape.sub('', stdout).strip()
    
    if not clean_stdout:
        return "Игроков нет"

    # Expected format: "There are 1 of a max of 20 players online: UltraMaximus"
    # We look for the colon that separates the count from the player list
    if "online:" in clean_stdout:
        parts = clean_stdout.split("online:", 1)
        if len(parts) > 1:
            players = parts[1].strip()
            if players:
                logging.info(f"Success! Found players: {players}")
                return players
    
    # Fallback: check if it's a "0 players" message
    if "0 players online" in clean_stdout or "There are 0 of a max" in clean_stdout:
        return "Игроков нет"
    
    # Last resort: if we have a line that doesn't look like a count, it might be a list
    lines = [line.strip() for line in clean_stdout.splitlines() if line.strip()]
    if lines:
        first_line = lines[0]
        if "There are" not in first_line and "players online" not in first_line:
            return first_line

    return "Игроков нет"

def update_server_property(key, value):
    """Обновляет или добавляет настройку в server.properties"""
    try:
        # Use sed to replace existing or append if not found
        # First check if key exists
        check_cmd = f"grep '^{key}=' {SERVER_PROPS}"
        _, _, code = run_command(check_cmd)
        
        if code == 0:
            cmd = f"sed -i 's|^{key}=.*|{key}={value}|' {SERVER_PROPS}"
        else:
            cmd = f"echo '{key}={value}' >> {SERVER_PROPS}"
            
        stdout, stderr, code = run_command(cmd)
        return code == 0
    except Exception as e:
        logging.error(f"Error updating property {key}: {e}")
        return False

def get_user_cache():
    """Загружает сопоставление UUID -> Nickname из usercache.json"""
    cache_path = os.path.join(DATA_PATH, "usercache.json")
    if not os.path.exists(cache_path):
        return {}
    try:
        import json
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Формат Mojang: список объектов [{'name': '...', 'uuid': '...'}, ...]
            return {user['uuid']: user['name'] for user in data}
    except Exception as e:
        logging.error(f"Error reading usercache.json: {e}")
        return {}

def get_world_stats():
    """Парсит статистику игроков из JSON файлов мира (1.20.1)"""
    current_world = get_current_world()
    stats_path = os.path.join(DATA_PATH, current_world, "stats")
    
    if not os.path.exists(stats_path):
        return None

    user_cache = get_user_cache()
    player_stats = []
    try:
        import json
        for filename in os.listdir(stats_path):
            if filename.endswith(".json"):
                uuid = filename.replace(".json", "")
                
                with open(os.path.join(stats_path, filename), 'r') as f:
                    data = json.load(f)
                    # В 1.20.1 Forge статистика лежит в stats -> minecraft:custom
                    custom_stats = data.get("stats", {}).get("minecraft:custom", {})
                    
                    # 1.20.1 stats keys
                    play_time_ticks = custom_stats.get("minecraft:play_time", 0)
                    play_time_seconds = play_time_ticks // 20
                    
                    deaths = custom_stats.get("minecraft:deaths", 0)
                    
                    player_stats.append({
                        "uuid": uuid,
                        "name": user_cache.get(uuid, uuid), # Ник или UUID если не найден
                        "time": play_time_seconds,
                        "deaths": deaths,
                        "advancements": 0
                    })
        
        # Подсчет достижений через файлы в /advancements
        adv_path = os.path.join(DATA_PATH, current_world, "advancements")
        if os.path.exists(adv_path):
            for p in player_stats:
                p_adv_path = os.path.join(adv_path, f"{p['uuid']}.json")
                if os.path.exists(p_adv_path):
                    with open(p_adv_path, 'r') as f:
                        adv_data = json.load(f)
                        # Считаем только полученные достижения (где есть timestamp)
                        p['advancements'] = len([v for v in adv_data.values() if isinstance(v, dict) and 'timestamp' in v])
                        
    except Exception as e:
        logging.error(f"Error reading stats: {e}")
        return None
        
    return player_stats


def tail_server_log():
    """Читает последние строки лога для мониторинга событий"""
    log_file = os.path.join(DATA_PATH, "logs/latest.log")
    if not os.path.exists(log_file):
        return ""
    stdout, stderr, code = run_command(f"tail -n 50 {log_file}")
    return stdout

