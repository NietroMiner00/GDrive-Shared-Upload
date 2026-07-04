# ==========================================
# Stage 1: Build the Vue Frontend
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend

# Copy package files and install dependencies
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source and build production bundle
COPY frontend/ ./
RUN npm run build

# ==========================================
# Stage 2: Set up Python Flask Backend
# ==========================================
FROM python:3.11-slim AS backend-server
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend files
COPY backend/ ./backend/

# Copy the built frontend bundle from Stage 1
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Expose Flask default port
EXPOSE 5000

# Set working directory to backend so relative paths resolve correctly
WORKDIR /app/backend

# Run the Flask app using Gunicorn production WSGI server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
