
"""
MCP Server con Filesystem
Archivia file e fornisce API per il recupero
"""
import os
import uuid
import json
import sqlite3
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest
import aiofiles
import logging

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Metriche Prometheus
file_uploads = Counter('mcp_file_uploads_total', 'Total file uploads')
file_downloads = Counter('mcp_file_downloads_total', 'Total file downloads')
request_duration = Histogram('mcp_request_duration_seconds', 'Request duration')

app = FastAPI(title="MCP Server", version="1.0.0")

# Configurazione
class Config:
    STORAGE_DIR = os.getenv("STORAGE_DIR", "./mcp_storage")
    DB_PATH = os.getenv("DB_PATH", "./mcp_server.db")
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "100")) * 1024 * 1024  # 100MB

# Crea directory storage
os.makedirs(Config.STORAGE_DIR, exist_ok=True)

# Modelli
class FileMetadata(BaseModel):
    id: str
    filename: str
    user_id: str
    file_path: str
    content_type: str
    size: int
    status: str
    created_at: str
    ccat_context_id: Optional[str] = None

class FileListResponse(BaseModel):
    files: List[FileMetadata]
    total: int

# Database setup
def init_db():
    """Inizializza database SQLite"""
    conn = sqlite3.connect(Config.DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            user_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_type TEXT,
            size INTEGER,
            status TEXT DEFAULT 'stored',
            created_at TEXT,
            ccat_context_id TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class FileService:
    """Servizio per gestione file"""
    
    @staticmethod
    def save_metadata(file_meta: FileMetadata):
        """Salva metadata nel database"""
        conn = sqlite3.connect(Config.DB_PATH)
        conn.execute('''
            INSERT INTO files (id, filename, user_id, file_path, content_type, 
                             size, status, created_at, ccat_context_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_meta.id, file_meta.filename, file_meta.user_id,
            file_meta.file_path, file_meta.content_type, file_meta.size,
            file_meta.status, file_meta.created_at, file_meta.ccat_context_id
        ))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_file_metadata(file_id: str) -> Optional[FileMetadata]:
        """Recupera metadata file"""
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.execute(
            'SELECT * FROM files WHERE id = ?', (file_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return FileMetadata(
                id=row[0], filename=row[1], user_id=row[2],
                file_path=row[3], content_type=row[4], size=row[5],
                status=row[6], created_at=row[7], ccat_context_id=row[8]
            )
        return None
    
    @staticmethod
    def list_user_files(user_id: str) -> List[FileMetadata]:
        """Lista file per utente"""
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.execute(
            'SELECT * FROM files WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            FileMetadata(
                id=row[0], filename=row[1], user_id=row[2],
                file_path=row[3], content_type=row[4], size=row[5],
                status=row[6], created_at=row[7], ccat_context_id=row[8]
            )
            for row in rows
        ]

@app.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    file_id: str = Form(...),
    user_id: str = Form(...),
):
    """
    Carica file nel filesystem MCP
    """
    file_uploads.inc()
    
    try:
        # Validazione dimensione file
        if file.size > Config.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413, 
                detail=f"File too large. Max size: {Config.MAX_FILE_SIZE} bytes"
            )
        
        # Path per salvare il file
        file_path = os.path.join(Config.STORAGE_DIR, f"{file_id}_{file.filename}")
        
        # Salva file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        # Crea metadata
        file_meta = FileMetadata(
            id=file_id,
            filename=file.filename,
            user_id=user_id,
            file_path=file_path,
            content_type=file.content_type or "application/octet-stream",
            size=file.size,
            status="stored",
            created_at=datetime.now().isoformat()
        )
        
        # Salva metadata nel DB
        FileService.save_metadata(file_meta)
        
        logger.info(f"File uploaded successfully: {file_id}")
        return {"status": "success", "file_id": file_id, "message": "File uploaded"}
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/files/{file_id}")
async def download_file(file_id: str):
    """
    Scarica file dal filesystem MCP
    """
    file_downloads.inc()
    
    try:
        # Recupera metadata
        file_meta = FileService.get_file_metadata(file_id)
        if not file_meta:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Verifica esistenza file
        if not os.path.exists(file_meta.file_path):
            raise HTTPException(status_code=404, detail="File not found on disk")
        
        return FileResponse(
            path=file_meta.file_path,
            filename=file_meta.filename,
            media_type=file_meta.content_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@app.get("/files", response_model=FileListResponse)
async def list_files(user_id: str = Query(...)):
    """
    Lista file per utente
    """
    try:
        files = FileService.list_user_files(user_id)
        return FileListResponse(files=files, total=len(files))
    except Exception as e:
        logger.error(f"List files error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@app.get("/files/{file_id}/metadata")
async def get_file_metadata(file_id: str):
    """
    Recupera metadata file
    """
    file_meta = FileService.get_file_metadata(file_id)
    if not file_meta:
        raise HTTPException(status_code=404, detail="File not found")
    return file_meta

@app.put("/files/{file_id}/ccat-context")
async def update_ccat_context(file_id: str, context_id: str):
    """
    Aggiorna CCAT context ID per un file
    """
    try:
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.execute(
            'UPDATE files SET ccat_context_id = ? WHERE id = ?',
            (context_id, file_id)
        )
        
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="File not found")
        
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": "CCAT context updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update context error: {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@app.get("/metrics")
async def get_metrics():
    """
    Endpoint per metriche Prometheus
    """
    return generate_latest()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_path": Config.STORAGE_DIR,
        "db_path": Config.DB_PATH
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)