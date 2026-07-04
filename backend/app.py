import os
# Allow HTTP for Google OAuth callback during local testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

import secrets
import datetime
import uuid
import requests
import jwt
from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

import db_helper

app = Flask(__name__, static_folder='../frontend/dist', static_url_path='/')
CORS(app, expose_headers=["Range", "Content-Range"])

# Secure flask sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# Load/generate persistent JWT secret from db.json
JWT_SECRET = db_helper.get_setting("jwt_secret")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    db_helper.set_setting("jwt_secret", JWT_SECRET)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

@app.route('/')
def index():
    return app.send_static_file('index.html')
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_google_credentials():
    creds = None
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'token.json')
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'w') as token_file:
                token_file.write(creds.to_json())
        except Exception as e:
            print(f"Failed to refresh Google credentials: {e}")
            creds = None
            
    return creds

def is_descendant_of(folder_id, root_id):
    if folder_id == root_id:
        return True
    creds = get_google_credentials()
    if not creds:
        return False
    try:
        service = build('drive', 'v3', credentials=creds)
        current_id = folder_id
        for _ in range(6):
            file_meta = service.files().get(
                fileId=current_id, 
                fields='parents', 
                supportsAllDrives=True
            ).execute()
            parents = file_meta.get('parents', [])
            if not parents:
                break
            if root_id in parents:
                return True
            current_id = parents[0]
    except Exception as e:
        print(f"Error in is_descendant_of traversal: {e}")
    return False


def init_passkey():
    stored_passkey = db_helper.get_setting("passkey")
    if not stored_passkey:
        generated = secrets.token_hex(8) # 16 characters
        db_helper.set_setting("passkey", generated)
        print("\n" + "="*50)
        print(f"  ADMIN PASSKEY INITIALIZED:")
        print(f"  {generated}")
        print("="*50 + "\n")

def check_passkey():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0] != "Passkey":
        return False
        
    stored_passkey = db_helper.get_setting("passkey")
    return parts[1] == stored_passkey

def generate_upload_token(link_id, target_folder_id, expiry_datetime):
    payload = {
        "link_id": link_id,
        "folder_id": target_folder_id,
        "exp": int(expiry_datetime.timestamp())
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_upload_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Initial passkey generation
init_passkey()

@app.route('/api/status', methods=['GET'])
def get_status():
    creds = get_google_credentials()
    has_credentials = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'credentials.json'))
    return jsonify({
        "authenticated": creds is not None,
        "has_credentials_json": has_credentials,
        "passkey_configured": db_helper.get_setting("passkey") is not None
    })

@app.route('/api/auth/google', methods=['GET'])
def auth_google():
    client_secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'credentials.json')
    if not os.path.exists(client_secrets_path):
        return jsonify({"error": "credentials.json is missing on backend inside the config folder. Please download Desktop credentials from Google Cloud Console."}), 400
    
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/api/auth/callback'
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    
    session['oauth_state'] = state
    return jsonify({"authorization_url": authorization_url})

@app.route('/api/auth/callback', methods=['GET'])
def auth_callback():
    client_secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'credentials.json')
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/api/auth/callback'
    )
    
    flow.fetch_token(authorization_response=request.url)
    
    creds = flow.credentials
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'token.json')
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
        
    return redirect(f"{FRONTEND_URL}/?admin=true&auth=success")

@app.route('/api/links/generate', methods=['POST'])
def generate_link():
    if not check_passkey():
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    if not data or not data.get("name") or not data.get("target_folder_id"):
        return jsonify({"error": "Missing name or target_folder_id"}), 400
        
    name = data["name"]
    target_folder_id = data["target_folder_id"]
    expiry_days = int(data.get("expiry_days", 7))
    max_file_size_mb = data.get("max_file_size_mb")
    allow_view = bool(data.get("allow_view", False))
    allow_delete = bool(data.get("allow_delete", False))
    
    expiry_datetime = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
    link_id = secrets.token_urlsafe(8)
    
    token = generate_upload_token(link_id, target_folder_id, expiry_datetime)
    
    link_data = db_helper.save_link(
        link_id=link_id,
        target_folder_id=target_folder_id,
        name=name,
        expiry=expiry_datetime.isoformat(),
        token=token,
        max_file_size_mb=max_file_size_mb,
        allow_view=allow_view,
        allow_delete=allow_delete
    )
    
    # Append the signed token to return
    link_data["token"] = token
    
    return jsonify(link_data)

@app.route('/api/links/list', methods=['GET'])
def list_links():
    if not check_passkey():
        return jsonify({"error": "Unauthorized"}), 401
    links = db_helper.list_links()
    
    # Ensure every link has a token (regenerate and save if missing)
    for link in links:
        if not link.get("token"):
            try:
                expiry_dt = datetime.datetime.fromisoformat(link["expiry"])
                token = generate_upload_token(link["id"], link["target_folder_id"], expiry_dt)
                link["token"] = token
                
                # Write back to db
                db = db_helper._load_db()
                if link["id"] in db.get("links", {}):
                    db["links"][link["id"]]["token"] = token
                    db_helper._save_db(db)
            except Exception as e:
                print(f"Error restoring token for link {link.get('id')}: {e}")
                
    return jsonify(links)

@app.route('/api/links/revoke/<link_id>', methods=['POST'])
def revoke_link(link_id):
    if not check_passkey():
        return jsonify({"error": "Unauthorized"}), 401
    if db_helper.delete_link(link_id):
        return jsonify({"message": "Link revoked successfully"})
    return jsonify({"error": "Link not found"}), 404

@app.route('/api/links/validate', methods=['GET'])
def validate_link():
    token = request.args.get("token")
    if not token:
        return jsonify({"valid": False, "error": "Token missing"}), 400
        
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"valid": False, "error": "Token invalid or expired"}), 400
        
    link_id = payload.get("link_id")
    folder_id = payload.get("folder_id")
    
    link_db = db_helper.get_link(link_id)
    if not link_db:
        return jsonify({"valid": False, "error": "Upload link has been revoked"}), 400
        
    # Check expiry in ISO format
    expiry_dt = datetime.datetime.fromisoformat(link_db["expiry"])
    if expiry_dt < datetime.datetime.now():
        return jsonify({"valid": False, "error": "Upload link has expired"}), 400
        
    # Check folder name and existence using Google Drive API
    folder_name = "Google Drive Folder"
    creds = get_google_credentials()
    if creds:
        try:
            service = build('drive', 'v3', credentials=creds)
            file_meta = service.files().get(
                fileId=folder_id, 
                fields='name, trashed', 
                supportsAllDrives=True
            ).execute()
            
            if file_meta.get("trashed", False):
                return jsonify({"valid": False, "error": "The target folder on Google Drive has been deleted or moved to trash."}), 410
                
            folder_name = file_meta.get("name", folder_name)
        except Exception as e:
            print(f"Error fetching folder metadata: {e}")
            return jsonify({"valid": False, "error": "The target folder on Google Drive does not exist, has been deleted, or is inaccessible."}), 404
            
    return jsonify({
        "valid": True,
        "name": link_db["name"],
        "expiry": link_db["expiry"],
        "max_file_size_mb": link_db.get("max_file_size_mb"),
        "allow_view": link_db.get("allow_view", False),
        "allow_delete": link_db.get("allow_delete", False),
        "folder_name": folder_name
    })

@app.route('/api/upload/initiate', methods=['POST'])
def upload_initiate():
    data = request.json
    if not data or not data.get("token") or not data.get("filename"):
        return jsonify({"error": "Missing token or filename"}), 400
        
    token = data["token"]
    filename = data["filename"]
    filesize = data.get("filesize", 0)
    mimetype = data.get("mimetype", "application/octet-stream")
    target_subfolder_id = data.get("folder_id")
    
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired link token"}), 401
        
    link_id = payload.get("link_id")
    root_folder_id = payload.get("folder_id")
    
    link_db = db_helper.get_link(link_id)
    if not link_db:
        return jsonify({"error": "Upload link has been revoked"}), 403
        
    # Validate file size if set
    if link_db.get("max_file_size_mb"):
        max_bytes = link_db["max_file_size_mb"] * 1024 * 1024
        if filesize > max_bytes:
            return jsonify({"error": f"File is too large. Max size allowed is {link_db['max_file_size_mb']} MB"}), 400
            
    # Resolve actual destination folder
    destination_folder_id = root_folder_id
    if target_subfolder_id and target_subfolder_id != root_folder_id:
        if not link_db.get("allow_view", False):
            return jsonify({"error": "Access denied"}), 403
        if not is_descendant_of(target_subfolder_id, root_folder_id):
            return jsonify({"error": "Access denied: outside target directory"}), 403
        destination_folder_id = target_subfolder_id
        
    # Check if a session already exists for this file in db.json
    existing = db_helper.find_existing_session(filename, filesize, destination_folder_id, link_id)
    if existing:
        creds = get_google_credentials()
        if creds:
            try:
                headers = {
                    "Authorization": f"Bearer {creds.token}",
                    "Content-Range": f"bytes */{filesize}"
                }
                g_status = requests.put(existing["gdrive_url"], headers=headers)
                
                if g_status.status_code == 308:
                    range_header = g_status.headers.get("Range")
                    bytes_uploaded = 0
                    if range_header:
                        try:
                            parts = range_header.split('=')[1].split('-')
                            bytes_uploaded = int(parts[1]) + 1
                        except Exception as e:
                            print(f"Failed to parse Range header '{range_header}': {e}")
                    return jsonify({
                        "session_id": existing["id"],
                        "chunk_size": 5 * 1024 * 1024,
                        "bytes_uploaded": bytes_uploaded,
                        "resumed": True
                    })
                elif g_status.status_code in [200, 201]:
                    db_helper.delete_upload_session(existing["id"])
                    db_helper.increment_upload_count(link_id)
                    return jsonify({
                        "completed": True,
                        "message": "File already completely uploaded."
                    })
                else:
                    db_helper.delete_upload_session(existing["id"])
            except Exception as e:
                print(f"Failed to verify existing session: {e}")
                
    # Check if a file with same name and size already exists in target folder on Google Drive
    creds = get_google_credentials()
    if creds:
        try:
            service = build('drive', 'v3', credentials=creds)
            escaped_filename = filename.replace("'", "\\'")
            query = f"name = '{escaped_filename}' and '{destination_folder_id}' in parents and trashed = false"
            results = service.files().list(
                q=query,
                fields="files(id, size)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            for f in results.get("files", []):
                f_size = int(f.get("size", 0)) if f.get("size") is not None else 0
                if f_size == filesize:
                    return jsonify({
                        "completed": True,
                        "message": "File already completely uploaded."
                    })
        except Exception as e:
            print(f"Failed to check existing file duplicates on Google Drive: {e}")
            
    if not creds:
        return jsonify({"error": "Google Drive not authorized on backend. Please contact owner."}), 503
        
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mimetype
    }
    
    metadata = {
        "name": filename,
        "parents": [destination_folder_id]
    }
    
    try:
        g_response = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true",
            headers=headers,
            json=metadata
        )
        
        if g_response.status_code != 200:
            return jsonify({
                "error": "Google Drive initialization failed",
                "details": g_response.text
            }), g_response.status_code
            
        location = g_response.headers.get("Location")
        if not location:
            return jsonify({"error": "No upload URL returned from Google Drive"}), 500
            
        session_id = str(uuid.uuid4())
        db_helper.save_upload_session(
            session_id=session_id,
            gdrive_url=location,
            filename=filename,
            filesize=filesize,
            folder_id=destination_folder_id,
            link_id=link_id
        )
        
        chunk_size = 5 * 1024 * 1024
        return jsonify({
            "session_id": session_id,
            "chunk_size": chunk_size
        })
        
    except Exception as e:
        return jsonify({"error": "Relay error initiating upload", "details": str(e)}), 500

@app.route('/api/upload/chunk/<session_id>', methods=['PUT'])
def upload_chunk(session_id):
    session_data = db_helper.get_upload_session(session_id)
    if not session_data:
        return jsonify({"error": "Session expired or invalid"}), 404
        
    gdrive_url = session_data["gdrive_url"]
    content_range = request.headers.get("Content-Range")
    chunk_data = request.data
    
    headers = {}
    if content_range:
        headers["Content-Range"] = content_range
        
    try:
        g_response = requests.put(
            gdrive_url,
            headers=headers,
            data=chunk_data
        )
        
        status_code = g_response.status_code
        response_headers = dict(g_response.headers)
        
        if status_code in [200, 201]:
            db_helper.increment_upload_count(session_data["link_id"])
            db_helper.delete_upload_session(session_id)
            return jsonify({"message": "Upload complete!", "status": status_code}), 200
            
        elif status_code == 308:
            return jsonify({
                "message": "Chunk uploaded", 
                "range": response_headers.get("Range", "")
            }), 308
            
        else:
            return jsonify({
                "error": "Google Drive error uploading chunk",
                "status": status_code,
                "details": g_response.text
            }), status_code
            
    except Exception as e:
        return jsonify({"error": "Relay chunk error", "details": str(e)}), 500

@app.route('/api/upload/session/<session_id>', methods=['DELETE'])
def upload_cancel(session_id):
    token = request.args.get("token") or (request.json.get("token") if request.json else None)
    if not token:
        return jsonify({"error": "Token missing"}), 400
        
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401
        
    session_data = db_helper.get_upload_session(session_id)
    if not session_data:
        return jsonify({"message": "Session already closed or cancelled"}), 200
        
    if session_data.get("link_id") != payload.get("link_id"):
        return jsonify({"error": "Access denied"}), 403
        
    db_helper.delete_upload_session(session_id)
    return jsonify({"message": "Upload session cancelled successfully"})

@app.route('/api/upload/incomplete', methods=['GET'])
def get_incomplete_uploads():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token missing"}), 400
        
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401
        
    link_id = payload.get("link_id")
    
    db = db_helper._load_db()
    sessions = db.get("upload_sessions", {})
    
    link_sessions = []
    for sid, s in sessions.items():
        if s.get("link_id") == link_id:
            link_sessions.append(s)
            
    incomplete = []
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Google Drive not authorized"}), 503
        
    for s in link_sessions:
        try:
            headers = {
                "Authorization": f"Bearer {creds.token}",
                "Content-Range": f"bytes */{s['filesize']}"
            }
            g_status = requests.put(s["gdrive_url"], headers=headers)
            
            if g_status.status_code == 308:
                range_header = g_status.headers.get("Range")
                bytes_uploaded = 0
                if range_header:
                    try:
                        parts = range_header.split('=')[1].split('-')
                        bytes_uploaded = int(parts[1]) + 1
                    except:
                        pass
                
                incomplete.append({
                    "session_id": s["id"],
                    "filename": s["filename"],
                    "filesize": s["filesize"],
                    "folder_id": s["folder_id"],
                    "bytes_uploaded": bytes_uploaded,
                    "created_at": s.get("created_at")
                })
            elif g_status.status_code in [200, 201]:
                db_helper.delete_upload_session(s["id"])
                db_helper.increment_upload_count(link_id)
            else:
                db_helper.delete_upload_session(s["id"])
        except Exception as e:
            print(f"Error querying incomplete session {s['id']}: {e}")
            
    return jsonify(incomplete)

@app.route('/api/upload/ensure-folders', methods=['POST'])
def upload_ensure_folders():
    data = request.json
    if not data or not data.get("token") or not data.get("parent_id") or not data.get("path"):
        return jsonify({"error": "Missing token, parent_id, or path"}), 400
        
    token = data["token"]
    parent_id = data["parent_id"]
    path_str = data["path"]
    
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401
        
    link_id = payload.get("link_id")
    root_folder_id = payload.get("folder_id")
    
    link_db = db_helper.get_link(link_id)
    if not link_db:
        return jsonify({"error": "Link revoked"}), 403
        
    if parent_id != root_folder_id:
        if not is_descendant_of(parent_id, root_folder_id):
            return jsonify({"error": "Access denied"}), 403
            
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Google Drive not authorized"}), 503
        
    try:
        service = build('drive', 'v3', credentials=creds)
        current_parent = parent_id
        
        folders = [f for f in path_str.split('/') if f]
        for folder_name in folders:
            query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed = false"
            results = service.files().list(
                q=query,
                fields="files(id)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            files = results.get("files", [])
            if files:
                current_parent = files[0]["id"]
            else:
                body = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [current_parent]
                }
                new_folder = service.files().create(body=body, fields='id', supportsAllDrives=True).execute()
                current_parent = new_folder.get("id")
                
        return jsonify({"folder_id": current_parent})
    except Exception as e:
        return jsonify({"error": "Failed to resolve folder path", "details": str(e)}), 500

@app.route('/api/upload/files', methods=['GET'])
def get_files():
    token = request.args.get("token")
    folder_id = request.args.get("folder_id")
    
    if not token:
        return jsonify({"error": "Token missing"}), 400
        
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401
        
    link_id = payload.get("link_id")
    root_folder_id = payload.get("folder_id")
    
    link_db = db_helper.get_link(link_id)
    if not link_db:
        return jsonify({"error": "Link revoked"}), 403
        
    if not link_db.get("allow_view", False):
        return jsonify({"error": "Viewing files not allowed for this link"}), 403
        
    target_folder = folder_id if folder_id else root_folder_id
    
    # Security check: Ensure target_folder is descendant of root_folder_id
    if target_folder != root_folder_id:
        if not is_descendant_of(target_folder, root_folder_id):
            return jsonify({"error": "Access denied"}), 403
            
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Not authenticated with Google Drive"}), 503
        
    try:
        service = build('drive', 'v3', credentials=creds)
        
        # Build breadcrumbs up to root_folder_id
        breadcrumbs = []
        current = target_folder
        while current and current != root_folder_id:
            meta = service.files().get(fileId=current, fields='id, name, parents', supportsAllDrives=True).execute()
            breadcrumbs.insert(0, {"id": meta["id"], "name": meta["name"]})
            parents = meta.get("parents", [])
            current = parents[0] if parents else None
            
        # Add root folder itself
        root_meta = service.files().get(fileId=root_folder_id, fields='name', supportsAllDrives=True).execute()
        breadcrumbs.insert(0, {"id": root_folder_id, "name": root_meta.get("name", "Root")})
        
        # List files & folders under target_folder
        query = f"'{target_folder}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, md5Checksum, size, createdTime)",
            orderBy="folder, name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        
        files = results.get("files", [])
        
        return jsonify({
            "breadcrumbs": breadcrumbs,
            "files": files
        })
    except Exception as e:
        return jsonify({"error": "Failed to retrieve folder contents", "details": str(e)}), 500

@app.route('/api/upload/file/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token missing"}), 400
        
    payload = decode_upload_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401
        
    link_id = payload.get("link_id")
    root_folder_id = payload.get("folder_id")
    
    link_db = db_helper.get_link(link_id)
    if not link_db:
        return jsonify({"error": "Link revoked"}), 403
        
    if not link_db.get("allow_delete", False):
        return jsonify({"error": "Deleting files not allowed for this link"}), 403
        
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Not authenticated with Google Drive"}), 503
        
    try:
        service = build('drive', 'v3', credentials=creds)
        
        # Verify parent is descendant
        file_meta = service.files().get(
            fileId=file_id, 
            fields='parents', 
            supportsAllDrives=True
        ).execute()
        
        parents = file_meta.get('parents', [])
        if not parents:
            return jsonify({"error": "File parent not found"}), 400
            
        parent_id = parents[0]
        if not is_descendant_of(parent_id, root_folder_id):
            return jsonify({"error": "Access denied"}), 403
            
        # Delete file from Drive
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        return jsonify({"message": "File deleted successfully"})
    except Exception as e:
        return jsonify({"error": "Failed to delete file", "details": str(e)}), 500

@app.route('/api/admin/drive/list', methods=['GET'])
def admin_drive_list():
    if not check_passkey():
        return jsonify({"error": "Unauthorized"}), 401
        
    parent_id = request.args.get("parent_id", "root")
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Google Drive not authorized"}), 503
        
    try:
        service = build('drive', 'v3', credentials=creds)
        
        if parent_id == 'root':
            root_meta = service.files().get(fileId='root', fields='id', supportsAllDrives=True).execute()
            resolved_parent_id = root_meta.get('id')
        else:
            resolved_parent_id = parent_id
            
        # Build breadcrumbs
        breadcrumbs = []
        current = resolved_parent_id
        while current:
            try:
                meta = service.files().get(fileId=current, fields='id, name, parents', supportsAllDrives=True).execute()
                breadcrumbs.insert(0, {"id": meta["id"], "name": meta["name"]})
                parents = meta.get("parents", [])
                current = parents[0] if parents else None
            except:
                break
                
        # List folders inside parent
        query = f"'{resolved_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(
            q=query,
            fields="files(id, name)",
            orderBy="name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        
        folders = results.get("files", [])
        
        return jsonify({
            "current_folder_id": resolved_parent_id,
            "breadcrumbs": breadcrumbs,
            "folders": folders
        })
    except Exception as e:
        return jsonify({"error": "Failed to list folders", "details": str(e)}), 500

@app.route('/api/admin/drive/create-folder', methods=['POST'])
def admin_drive_create_folder():
    if not check_passkey():
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    if not data or not data.get("name") or not data.get("parent_id"):
        return jsonify({"error": "Missing name or parent_id"}), 400
        
    name = data["name"]
    parent_id = data["parent_id"]
    
    creds = get_google_credentials()
    if not creds:
        return jsonify({"error": "Google Drive not authorized"}), 503
        
    try:
        service = build('drive', 'v3', credentials=creds)
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = service.files().create(body=body, fields='id', supportsAllDrives=True).execute()
        return jsonify({"id": folder.get("id"), "name": name})
    except Exception as e:
        return jsonify({"error": "Failed to create folder", "details": str(e)}), 500

if __name__ == '__main__':
    # Determine debug mode from environment variables (defaults to False in production)
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ["true", "1", "t", "y", "yes"]
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
