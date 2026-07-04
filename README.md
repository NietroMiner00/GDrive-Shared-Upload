# 📤 Google Drive Upload Relay

A high-performance, secure, and resumable Google Drive upload relay. It allows sharing secure, scoped upload links with guests, letting them upload files and folders of up to hundreds of gigabytes directly to your Google Drive while keeping your main account credentials and Drive contents fully isolated.

---

## ✨ Features

- **⏯️ Robust Resumable Upload Queue**:
  - Upload multiple files and directories recursively.
  - Pause, resume, retry, or cancel uploads at any time.
  - Recovers incomplete uploads smoothly after tab refreshes, browser crashes, or server restarts.
- **⚡ Dynamic Chunk-Size Adaptation**:
  - Automatically scales chunk sizes on-the-fly (from `256 KB` up to `1 GB`) based on your upload speeds, keeping target HTTP transfer times close to 4 seconds to saturate high-bandwidth connections.
- **🚀 Client-Side Performance Caching**:
  - Caches folder listings to check for duplicate file matches locally, skipping redundant `/api/upload/initiate` operations.
  - Caches resolved remote subfolder directories to execute `/api/upload/ensure-folders` exactly once per path context.
- **🔍 Checksum verification & Manifest Tools**:
  - Upload `.md5` or `.txt` manifests to check directory integrity.
  - Identifies matches, mismatches, or missing items relative to navigated subfolder path contexts.
  - Generates and downloads compiled `.md5` verification manifests for any folder.
- **🔒 Security & Persistence**:
  - Restricts guests to folders assigned by their share links.
  - Encrypts links with persistent JWT secret signatures saved in the local database (`config/db.json`).
  - Active verification of folder status on Google Drive to throw immediate errors if target folders are trashed or deleted.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11, Flask, Google API Client, JWT signatures.
- **Frontend**: Vite 5, Vue 3, TypeScript, TailwindCSS.

---

## 🐳 Docker Deployment (Recommended)

### 1. Prerequisites
You need to set up OAuth 2.0 Web Application credentials in your **Google Cloud Console**:
1. Enable the **Google Drive API**.
2. Create an **OAuth Client ID** of type **Web Application**.
3. Add the following Redirect URI under Authorized Redirect URIs:
   - `http://localhost:5000/api/auth/callback`
4. Download the credentials file and rename it to **`credentials.json`**.
5. Place it inside a folder named **`config`** inside the `backend` directory (i.e. `backend/config/credentials.json`).

### 2. Startup
Run the multi-stage build and spin up the relay:
```bash
docker-compose up -d --build
```
The server will start and be available at **`http://localhost:5000/`**.

*Note: Persistent credentials (`token.json`) and database settings (`db.json`) will be preserved inside the `./backend/config` host folder via docker volume mounts.*

---

## 💻 Local Development Setup

### Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create a folder named `config` inside `backend` and place your `credentials.json` file inside it:
   ```bash
   mkdir config
   # Place credentials.json inside backend/config/
   ```
3. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows (PowerShell)
   source .venv/bin/activate    # Linux/macOS
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Run the server:
   ```bash
   python app.py
   ```

### Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev
   ```
4. Build static production assets (will compile files directly to `frontend/dist` served by Flask):
   ```bash
   npm run build
   ```

---

## 📄 License
This project is open-source and free to distribute.
