import os
import json

HOME_DIR = os.path.expanduser('~')
GGLTASKS_DIR = os.path.join(HOME_DIR, '.ggltasks')
STORAGE_FILE = os.path.join(GGLTASKS_DIR, 'local_tasks.json')


def _ensure_dir_exists():
    os.makedirs(GGLTASKS_DIR, exist_ok=True)


def load_data():
    _ensure_dir_exists()
    if not os.path.exists(STORAGE_FILE):
        return {'task_lists': [], 'tasks': {}}
    try:
        with open(STORAGE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'task_lists': [], 'tasks': {}}


def save_data(data):
    _ensure_dir_exists()
    tmp_path = STORAGE_FILE + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, STORAGE_FILE)
        return True
    except IOError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
