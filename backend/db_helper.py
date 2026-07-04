import os
import json
import threading

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'db.json')
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
db_lock = threading.Lock()

def _load_db():
    with db_lock:
        if not os.path.exists(DB_FILE):
            default_data = {
                "settings": {},
                "links": {}
            }
            with open(DB_FILE, 'w') as f:
                json.dump(default_data, f, indent=2)
            return default_data
        
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # In case file is corrupt, return basic structure
            return {"settings": {}, "links": {}}

def _save_db(data):
    with db_lock:
        try:
            with open(DB_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except IOError:
            return False

def get_setting(key, default=None):
    db = _load_db()
    return db.get("settings", {}).get(key, default)

def set_setting(key, value):
    db = _load_db()
    if "settings" not in db:
        db["settings"] = {}
    db["settings"][key] = value
    _save_db(db)

def get_link(link_id):
    db = _load_db()
    return db.get("links", {}).get(link_id)

def list_links():
    db = _load_db()
    # Return as list sorted by creation date descending
    links = list(db.get("links", {}).values())
    links.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return links

def save_link(link_id, target_folder_id, name, expiry, token, max_file_size_mb=None, allow_view=False, allow_delete=False):
    db = _load_db()
    if "links" not in db:
        db["links"] = {}
    
    import datetime
    link_data = {
        "id": link_id,
        "target_folder_id": target_folder_id,
        "name": name,
        "expiry": expiry, # ISO String
        "token": token,
        "created_at": datetime.datetime.now().isoformat(),
        "uploaded_count": 0,
        "max_file_size_mb": max_file_size_mb,
        "allow_view": allow_view,
        "allow_delete": allow_delete
    }
    db["links"][link_id] = link_data
    _save_db(db)
    return link_data

def delete_link(link_id):
    db = _load_db()
    if "links" in db and link_id in db["links"]:
        del db["links"][link_id]
        _save_db(db)
        return True
    return False

def increment_upload_count(link_id):
    db = _load_db()
    if "links" in db and link_id in db["links"]:
        db["links"][link_id]["uploaded_count"] = db["links"][link_id].get("uploaded_count", 0) + 1
        _save_db(db)
        return True
    return False

def save_upload_session(session_id, gdrive_url, filename, filesize, folder_id, link_id):
    db = _load_db()
    if "upload_sessions" not in db:
        db["upload_sessions"] = {}
    
    import datetime
    db["upload_sessions"][session_id] = {
        "id": session_id,
        "gdrive_url": gdrive_url,
        "filename": filename,
        "filesize": filesize,
        "folder_id": folder_id,
        "link_id": link_id,
        "created_at": datetime.datetime.now().isoformat()
    }
    _save_db(db)

def get_upload_session(session_id):
    db = _load_db()
    return db.get("upload_sessions", {}).get(session_id)

def find_existing_session(filename, filesize, folder_id, link_id):
    db = _load_db()
    sessions = db.get("upload_sessions", {})
    for sid, s in sessions.items():
        if s.get("filename") == filename and s.get("filesize") == filesize and s.get("folder_id") == folder_id and s.get("link_id") == link_id:
            return s
    return None

def delete_upload_session(session_id):
    db = _load_db()
    if "upload_sessions" in db and session_id in db["upload_sessions"]:
        del db["upload_sessions"][session_id]
        _save_db(db)
        return True
    return False

