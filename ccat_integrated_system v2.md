# Sistema Integrato CCAT + RabbitHole + WebUI + MCP Server

## Architettura del Sistema

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   WebUI Client  │────│  WebUI Backend   │────│   MCP Server    │
│   (React/Vue)   │    │  (FastAPI)       │    │  (Filesystem)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                │                        │ 
                                ▼                        ▼
                    ┌──────────────────┐    ┌─────────────────┐
                    │  RabbitHole      │────│   CCAT Core     │
                    │  Plugin          │    │   (AI Engine)   │
                    └──────────────────┘    └─────────────────┘
```

## 1. Plugin RabbitHole Personalizzato

### plugin_rabbithole.py
```python
"""
Plugin RabbitHole personalizzato per CCAT
Bridge tra MCP Server e CCAT Core
"""
import asyncio
import httpx
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from cheshire_cat_api import CatClient
import jwt
from datetime import datetime, timedelta
import os

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Modelli Pydantic
class FileImportRequest(BaseModel):
    file_id: str
    mcp_server_url: str
    user_id: str
    context_metadata: Optional[Dict[str, Any]] = None

class FileImportResponse(BaseModel):
    file_id: str
    status: str
    ccat_context_id: Optional[str] = None
    message: str
    timestamp: str

# Configurazione
class Config:
    JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
    CCAT_API_KEY = os.getenv("CCAT_API_KEY", "your-ccat-key")
    CCAT_BASE_URL = os.getenv("CCAT_BASE_URL", "http://localhost:1865")
    MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))

# FastAPI App
app = FastAPI(title="RabbitHole Plugin API", version="1.0.0")
security = HTTPBearer()

# CCAT Client
ccat_client = CatClient(
    base_url=Config.CCAT_BASE_URL,
    api_key=Config.CCAT_API_KEY
)

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verifica JWT token"""
    try:
        payload = jwt.decode(
            credentials.credentials, 
            Config.JWT_SECRET, 
            algorithms=["HS256"]
        )
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

class RabbitHoleService:
    """Servizio per gestire l'importazione di file in CCAT"""
    
    @staticmethod
    async def fetch_file_from_mcp(file_id: str, mcp_url: str) -> bytes:
        """Recupera file dal MCP server"""
        async with httpx.AsyncClient(timeout=Config.MCP_TIMEOUT) as client:
            try:
                response = await client.get(f"{mcp_url}/files/{file_id}")
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as e:
                logger.error(f"MCP server error: {e}")
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
            except httpx.TimeoutException:
                logger.error(f"MCP server timeout for file: {file_id}")
                raise HTTPException(status_code=408, detail="MCP server timeout")
    
    @staticmethod
    async def import_to_ccat(
        file_content: bytes, 
        file_id: str, 
        user_id: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """Importa file in CCAT tramite RabbitHole"""
        try:
            # Simulazione chiamata CCAT API
            # In realtà useresti: ccat_client.rabbit_hole.import_file()
            context_id = f"ctx_{file_id}_{int(datetime.now().timestamp())}"
            
            # Esempio di importazione file
            import_result = await asyncio.to_thread(
                ccat_client.rabbit_hole.import_memory,
                content=file_content.decode('utf-8') if isinstance(file_content, bytes) else file_content,
                source=f"file_{file_id}",
                metadata={
                    "user_id": user_id,
                    "file_id": file_id,
                    "import_timestamp": datetime.now().isoformat(),
                    **(metadata or {})
                }
            )
            
            logger.info(f"File {file_id} imported successfully to CCAT")
            return context_id
            
        except Exception as e:
            logger.error(f"CCAT import error: {e}")
            raise HTTPException(status_code=500, detail=f"CCAT import failed: {str(e)}")

@app.post("/import-file", response_model=FileImportResponse)
async def import_file(
    request: FileImportRequest,
    background_tasks: BackgroundTasks,
    token: dict = Depends(verify_token)
):
    """
    Importa file dal MCP server in CCAT
    """
    try:
        # Recupera file dal MCP server
        file_content = await RabbitHoleService.fetch_file_from_mcp(
            request.file_id, 
            request.mcp_server_url
        )
        
        # Importa in CCAT
        context_id = await RabbitHoleService.import_to_ccat(
            file_content,
            request.file_id,
            request.user_id,
            request.context_metadata
        )
        
        return FileImportResponse(
            file_id=request.file_id,
            status="imported",
            ccat_context_id=context_id,
            message="File imported successfully",
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return FileImportResponse(
            file_id=request.file_id,
            status="error",
            message=f"Import failed: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

## 2. WebUI Client/Server

### Backend (webui_backend.py)
```python
"""
WebUI Backend - FastAPI server
Gestisce autenticazione e comunicazione con MCP server
"""
import os
import uuid
import aiofiles
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import jwt
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WebUI Backend API", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurazione
class Config:
    JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8002")
    RABBITHOLE_URL = os.getenv("RABBITHOLE_URL", "http://localhost:8001")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

# Crea directory upload se non esiste
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

# Modelli
class LoginRequest(BaseModel):
    username: str
    password: str

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    status: str
    mcp_url: str

class ImportRequest(BaseModel):
    file_id: str
    context_metadata: Optional[dict] = None

security = HTTPBearer()

def create_jwt_token(user_id: str) -> str:
    """Crea JWT token"""
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm="HS256")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verifica JWT token"""
    try:
        payload = jwt.decode(credentials.credentials, Config.JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/auth/login")
async def login(request: LoginRequest):
    """Autenticazione utente (mock)"""
    # In produzione, verificare credenziali da database
    if request.username == "admin" and request.password == "password":
        token = create_jwt_token(request.username)
        return {"access_token": token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_data: dict = Depends(verify_token)
):
    """
    Carica file e lo invia al MCP server
    """
    try:
        # Genera ID univoco per il file
        file_id = str(uuid.uuid4())
        file_path = os.path.join(Config.UPLOAD_DIR, f"{file_id}_{file.filename}")
        
        # Salva file temporaneamente
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        # Invia al MCP server
        async with httpx.AsyncClient() as client:
            with open(file_path, 'rb') as f:
                files = {"file": (file.filename, f, file.content_type)}
                data = {"file_id": file_id, "user_id": user_data["user_id"]}
                response = await client.post(
                    f"{Config.MCP_SERVER_URL}/files",
                    files=files,
                    data=data
                )
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="MCP server upload failed")
        
        # Cleanup file temporaneo
        os.remove(file_path)
        
        return UploadResponse(
            file_id=file_id,
            filename=file.filename,
            status="uploaded",
            mcp_url=f"{Config.MCP_SERVER_URL}/files/{file_id}"
        )
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.post("/import")
async def import_to_ccat(
    request: ImportRequest,
    user_data: dict = Depends(verify_token)
):
    """
    Attiva importazione file in CCAT tramite RabbitHole
    """
    try:
        async with httpx.AsyncClient() as client:
            import_data = {
                "file_id": request.file_id,
                "mcp_server_url": Config.MCP_SERVER_URL,
                "user_id": user_data["user_id"],
                "context_metadata": request.context_metadata
            }
            
            headers = {"Authorization": f"Bearer {create_jwt_token(user_data['user_id'])}"}
            
            response = await client.post(
                f"{Config.RABBITHOLE_URL}/import-file",
                json=import_data,
                headers=headers
            )
            
            return response.json()
            
    except Exception as e:
        logger.error(f"Import error: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@app.get("/files")
async def list_files(user_data: dict = Depends(verify_token)):
    """Lista file dell'utente dal MCP server"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{Config.MCP_SERVER_URL}/files",
                params={"user_id": user_data["user_id"]}
            )
            return response.json()
    except Exception as e:
        logger.error(f"List files error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Frontend React (webui-client/)

#### package.json
```json
{
  "name": "ccat-webui-client",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "axios": "^1.6.0",
    "react-router-dom": "^6.8.0",
    "react-dropzone": "^14.2.3",
    "@mui/material": "^5.14.0",
    "@emotion/react": "^11.11.0",
    "@emotion/styled": "^11.11.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test",
    "eject": "react-scripts eject"
  },
  "eslintConfig": {
    "extends": [
      "react-app",
      "react-app/jest"
    ]
  },
  "browserslist": {
    "production": [
      ">0.2%",
      "not dead",
      "not op_mini all"
    ],
    "development": [
      "last 1 chrome version",
      "last 1 firefox version",
      "last 1 safari version"
    ]
  }
}
```

#### src/App.js
```javascript
import React, { useState, useEffect } from 'react';
import {
  Container,
  Paper,
  Typography,
  Button,
  Box,
  Alert,
  LinearProgress,
  Card,
  CardContent,
  Grid
} from '@mui/material';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

// Configurazione API
const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Configurazione Axios
const api = axios.create({
  baseURL: API_BASE_URL,
});

// Interceptor per aggiungere token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [files, setFiles] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      setIsAuthenticated(true);
      loadFiles();
    }
  }, []);

  const login = async () => {
    try {
      const response = await api.post('/auth/login', {
        username: 'admin',
        password: 'password'
      });
      localStorage.setItem('token', response.data.access_token);
      setIsAuthenticated(true);
      loadFiles();
    } catch (error) {
      setMessage('Login failed: ' + error.response?.data?.detail);
    }
  };

  const loadFiles = async () => {
    try {
      const response = await api.get('/files');
      setFiles(response.data.files || []);
    } catch (error) {
      console.error('Failed to load files:', error);
    }
  };

  const onDrop = async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;

    const file = acceptedFiles[0];
    const formData = new FormData();
    formData.append('file', file);

    setLoading(true);
    setUploadProgress(0);

    try {
      // Upload file
      const uploadResponse = await api.post('/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(percentCompleted);
        },
      });

      setMessage(`File uploaded successfully: ${uploadResponse.data.filename}`);

      // Auto-import to CCAT
      const importResponse = await api.post('/import', {
        file_id: uploadResponse.data.file_id,
        context_metadata: {
          filename: file.name,
          size: file.size,
          type: file.type
        }
      });

      setMessage(
        `File imported to CCAT: ${importResponse.data.message} (Context ID: ${importResponse.data.ccat_context_id})`
      );

      loadFiles();
    } catch (error) {
      setMessage('Error: ' + (error.response?.data?.detail || error.message));
    } finally {
      setLoading(false);
      setUploadProgress(0);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      'text/*': ['.txt', '.md', '.csv'],
      'application/pdf': ['.pdf'],
      'application/json': ['.json']
    }
  });

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ mt: 4 }}>
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h4" gutterBottom>
            CCAT File Manager
          </Typography>
          <Button variant="contained" onClick={login} size="large">
            Login
          </Button>
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <Typography variant="h3" gutterBottom>
        CCAT Integrated File Manager
      </Typography>

      {/* Upload Area */}
      <Paper sx={{ p: 4, mb: 4 }}>
        <div
          {...getRootProps()}
          style={{
            border: '2px dashed #ccc',
            borderRadius: '4px',
            padding: '40px',
            textAlign: 'center',
            cursor: 'pointer',
            backgroundColor: isDragActive ? '#f5f5f5' : 'transparent'
          }}
        >
          <input {...getInputProps()} />
          {isDragActive ? (
            <Typography>Drop the file here...</Typography>
          ) : (
            <Typography>
              Drag & drop a file here, or click to select
              <br />
              Supported: TXT, MD, CSV, PDF, JSON
            </Typography>
          )}
        </div>

        {loading && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress variant="determinate" value={uploadProgress} />
            <Typography variant="body2" sx={{ mt: 1 }}>
              {uploadProgress}% uploaded
            </Typography>
          </Box>
        )}
      </Paper>

      {/* Messages */}
      {message && (
        <Alert 
          severity={message.includes('Error') ? 'error' : 'success'} 
          sx={{ mb: 4 }}
          onClose={() => setMessage('')}
        >
          {message}
        </Alert>
      )}

      {/* Files List */}
      <Typography variant="h5" gutterBottom>
        Your Files
      </Typography>
      <Grid container spacing={2}>
        {files.map((file) => (
          <Grid item xs={12} md={6} lg={4} key={file.id}>
            <Card>
              <CardContent>
                <Typography variant="h6" noWrap>
                  {file.filename}
                </Typography>
                <Typography color="text.secondary">
                  Status: {file.status}
                </Typography>
                <Typography color="text.secondary">
                  Uploaded: {new Date(file.created_at).toLocaleString()}
                </Typography>
                {file.ccat_context_id && (
                  <Typography color="success.main">
                    CCAT Context: {file.ccat_context_id}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Container>
  );
}

export default App;
```

## 3. MCP Server con Filesystem

### mcp_server.py
```python
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
```

## 4. Integrazione CCAT + RabbitHole

### ccat_integration.py
```python
"""
Integrazione CCAT + RabbitHole
SDK wrapper per gestire interazioni con CCAT
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import httpx
from cheshire_cat_api import CatClient
from cheshire_cat_api.exceptions import CatAPIError

logger = logging.getLogger(__name__)

@dataclass
class CCATImportResult:
    """Risultato dell'importazione in CCAT"""
    success: bool
    context_id: Optional[str]
    message: str
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@dataclass
class CCATQueryResult:
    """Risultato di una query a CCAT"""
    response: str
    context_used: List[str]
    processing_time: float
    confidence: Optional[float] = None

class CCATManager:
    """Manager per gestire interazioni con CCAT"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:1865",
        api_key: str = "your-ccat-key",
        timeout: int = 30
    ):
        self.client = CatClient(base_url=base_url, api_key=api_key)
        self.timeout = timeout
        self.session_contexts = {}  # Cache dei contesti per sessione
    
    async def import_file_content(
        self,
        content: str,
        file_id: str,
        user_id: str,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> CCATImportResult:
        """
        Importa contenuto file in CCAT tramite RabbitHole
        """
        try:
            # Prepara metadata per CCAT
            import_metadata = {
                "source": "mcp_server",
                "file_id": file_id,
                "user_id": user_id,
                "filename": filename,
                "import_timestamp": datetime.now().isoformat(),
                "type": "document",
                **(metadata or {})
            }
            
            # Importa in CCAT usando RabbitHole
            result = await asyncio.to_thread(
                self.client.rabbit_hole.import_memory,
                content=content,
                source=f"file_{file_id}",
                metadata=import_metadata
            )
            
            # Genera context ID
            context_id = f"ctx_{file_id}_{int(datetime.now().timestamp())}"
            
            # Crea embedding per ricerca futura
            await self._create_searchable_embedding(
                content=content,
                context_id=context_id,
                metadata=import_metadata
            )
            
            logger.info(f"Successfully imported file {file_id} to CCAT")
            
            return CCATImportResult(
                success=True,
                context_id=context_id,
                message="File imported successfully",
                metadata=import_metadata
            )
            
        except CatAPIError as e:
            logger.error(f"CCAT API error: {e}")
            return CCATImportResult(
                success=False,
                context_id=None,
                message="CCAT import failed",
                error=str(e)
            )
        except Exception as e:
            logger.error(f"Unexpected error during import: {e}")
            return CCATImportResult(
                success=False,
                context_id=None,
                message="Import failed due to unexpected error",
                error=str(e)
            )
    
    async def _create_searchable_embedding(
        self,
        content: str,
        context_id: str,
        metadata: Dict[str, Any]
    ):
        """
        Crea embedding per rendere il contenuto ricercabile
        """
        try:
            # Chunk del contenuto se troppo grande
            chunks = self._chunk_content(content, max_size=1000)
            
            for i, chunk in enumerate(chunks):
                chunk_metadata = {
                    **metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "context_id": context_id
                }
                
                await asyncio.to_thread(
                    self.client.memory.create_memory,
                    content=chunk,
                    metadata=chunk_metadata
                )
                
        except Exception as e:
            logger.warning(f"Failed to create embeddings: {e}")
    
    def _chunk_content(self, content: str, max_size: int = 1000) -> List[str]:
        """
        Divide il contenuto in chunks per l'elaborazione
        """
        words = content.split()
        chunks = []
        current_chunk = []
        current_size = 0
        
        for word in words:
            if current_size + len(word) > max_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_size = len(word)
            else:
                current_chunk.append(word)
                current_size += len(word) + 1
        
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks
    
    async def query_with_context(
        self,
        query: str,
        user_id: str,
        context_ids: Optional[List[str]] = None,
        max_tokens: int = 500
    ) -> CCATQueryResult:
        """
        Esegue query a CCAT con contesto specifico
        """
        start_time = datetime.now()
        
        try:
            # Prepara il messaggio con contesto
            message_data = {
                "text": query,
                "user_id": user_id,
                "context_ids": context_ids or [],
                "max_tokens": max_tokens
            }
            
            # Esegue query
            response = await asyncio.to_thread(
                self.client.message.send,
                **message_data
            )
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Estrae informazioni dal contesto utilizzato
            context_used = self._extract_context_used(response)
            
            return CCATQueryResult(
                response=response.get("content", ""),
                context_used=context_used,
                processing_time=processing_time,
                confidence=response.get("confidence")
            )
            
        except Exception as e:
            logger.error(f"Query error: {e}")
            processing_time = (datetime.now() - start_time).total_seconds()
            return CCATQueryResult(
                response=f"Error processing query: {str(e)}",
                context_used=[],
                processing_time=processing_time
            )
    
    def _extract_context_used(self, response: Dict[str, Any]) -> List[str]:
        """
        Estrae i context ID utilizzati dalla risposta
        """
        try:
            # Logica per estrarre context utilizzati dalla risposta CCAT
            # Questo dipende dalla struttura della risposta CCAT
            contexts = []
            if "memory" in response:
                for memory_item in response["memory"]:
                    if "metadata" in memory_item:
                        context_id = memory_item["metadata"].get("context_id")
                        if context_id and context_id not in contexts:
                            contexts.append(context_id)
            return contexts
        except Exception as e:
            logger.warning(f"Failed to extract context: {e}")
            return []
    
    async def get_file_contexts(self, file_id: str) -> List[str]:
        """
        Recupera tutti i context ID associati a un file
        """
        try:
            # Query per trovare contesti associati al file
            memories = await asyncio.to_thread(
                self.client.memory.get_memories,
                filter_metadata={"file_id": file_id}
            )
            
            contexts = []
            for memory in memories:
                context_id = memory.get("metadata", {}).get("context_id")
                if context_id and context_id not in contexts:
                    contexts.append(context_id)
                    
            return contexts
            
        except Exception as e:
            logger.error(f"Error getting file contexts: {e}")
            return []
    
    async def delete_file_context(self, file_id: str) -> bool:
        """
        Elimina tutti i contesti associati a un file
        """
        try:
            # Recupera contesti del file
            contexts = await self.get_file_contexts(file_id)
            
            # Elimina ogni contesto
            for context_id in contexts:
                await asyncio.to_thread(
                    self.client.memory.delete_memories,
                    filter_metadata={"context_id": context_id}
                )
            
            logger.info(f"Deleted {len(contexts)} contexts for file {file_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file contexts: {e}")
            return False

# Esempio di utilizzo dell'integrazione
async def example_usage():
    """
    Esempio di come utilizzare CCATManager
    """
    # Inizializza manager
    ccat = CCATManager(
        base_url="http://localhost:1865",
        api_key="your-ccat-key"
    )
    
    # Importa contenuto file
    result = await ccat.import_file_content(
        content="Questo è il contenuto di un documento importante...",
        file_id="file_123",
        user_id="user_456",
        filename="documento.txt",
        metadata={"category": "documentation", "priority": "high"}
    )
    
    if result.success:
        print(f"Import successful: {result.context_id}")
        
        # Esegui query sul contenuto importato
        query_result = await ccat.query_with_context(
            query="Dimmi qualcosa sul documento importante",
            user_id="user_456",
            context_ids=[result.context_id]
        )
        
        print(f"Query response: {query_result.response}")
        print(f"Processing time: {query_result.processing_time}s")
    else:
        print(f"Import failed: {result.error}")

if __name__ == "__main__":
    asyncio.run(example_usage())
```

## 5. Workflow End-to-End

### workflow_orchestrator.py
```python
"""
Orchestratore del workflow end-to-end
Gestisce l'intero processo di upload e importazione
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import httpx
import jwt
from enum import Enum

logger = logging.getLogger(__name__)

class WorkflowStatus(Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class WorkflowStep:
    """Rappresenta un passo del workflow"""
    name: str
    status: WorkflowStatus
    timestamp: datetime
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@dataclass
class WorkflowExecution:
    """Esecuzione completa del workflow"""
    workflow_id: str
    user_id: str
    file_id: str
    filename: str
    status: WorkflowStatus
    steps: list[WorkflowStep]
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None

class SecurityManager:
    """Gestisce la sicurezza e autenticazione"""
    
    def __init__(self, jwt_secret: str):
        self.jwt_secret = jwt_secret
    
    def create_service_token(self, service_name: str, user_id: str) -> str:
        """Crea token JWT per comunicazione tra servizi"""
        payload = {
            "service": service_name,
            "user_id": user_id,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow().timestamp() + 3600  # 1 ora
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    def verify_service_token(self, token: str) -> Dict[str, Any]:
        """Verifica token JWT"""
        try:
            return jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e}")

class WorkflowOrchestrator:
    """Orchestratore principale del workflow"""
    
    def __init__(
        self,
        webui_url: str = "http://localhost:8000",
        mcp_url: str = "http://localhost:8002",
        rabbithole_url: str = "http://localhost:8001",
        jwt_secret: str = "your-secret-key"
    ):
        self.webui_url = webui_url
        self.mcp_url = mcp_url
        self.rabbithole_url = rabbithole_url
        self.security = SecurityManager(jwt_secret)
        self.active_workflows: Dict[str, WorkflowExecution] = {}
    
    async def execute_complete_workflow(
        self,
        file_path: str,
        filename: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecution:
        """
        Esegue il workflow completo end-to-end
        """
        import uuid
        workflow_id = str(uuid.uuid4())
        
        # Inizializza workflow
        workflow = WorkflowExecution(
            workflow_id=workflow_id,
            user_id=user_id,
            file_id="",  # Sarà popolato durante l'upload
            filename=filename,
            status=WorkflowStatus.PENDING,
            steps=[],
            started_at=datetime.now()
        )
        
        self.active_workflows[workflow_id] = workflow
        
        try:
            # Step 1: Upload file al MCP server
            await self._execute_step(
                workflow,
                "upload_to_mcp",
                self._upload_to_mcp_server,
                file_path=file_path,
                filename=filename,
                user_id=user_id
            )
            
            # Step 2: Import in CCAT via RabbitHole
            await self._execute_step(
                workflow,
                "import_to_ccat",
                self._import_to_ccat,
                workflow=workflow,
                metadata=metadata
            )
            
            # Step 3: Aggiorna stato nel MCP server
            await self._execute_step(
                workflow,
                "update_mcp_status",
                self._update_mcp_status,
                workflow=workflow
            )
            
            # Completa workflow
            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.now()
            
            logger.info(f"Workflow {workflow_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed: {e}")
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.now()
            
            # Aggiungi step di errore
            error_step = WorkflowStep(
                name="workflow_error",
                status=WorkflowStatus.FAILED,
                timestamp=datetime.now(),
                message="Workflow failed",
                error=str(e)
            )
            workflow.steps.append(error_step)
        
        return workflow
    
    async def _execute_step(
        self,
        workflow: WorkflowExecution,
        step_name: str,
        step_function,
        **kwargs
    ):
        """Esegue un singolo step del workflow"""
        step = WorkflowStep(
            name=step_name,
            status=WorkflowStatus.PENDING,
            timestamp=datetime.now(),
            message=f"Starting {step_name}"
        )
        workflow.steps.append(step)
        
        try:
            # Esegui step
            result = await step_function(**kwargs)
            
            # Aggiorna step con successo
            step.status = WorkflowStatus.COMPLETED
            step.message = f"{step_name} completed successfully"
            step.data = result
            
            logger.info(f"Step {step_name} completed for workflow {workflow.workflow_id}")
            
        except Exception as e:
            # Aggiorna step con errore
            step.status = WorkflowStatus.FAILED
            step.message = f"{step_name} failed"
            step.error = str(e)
            
            logger.error(f"Step {step_name} failed for workflow {workflow.workflow_id}: {e}")
            raise
    
    async def _upload_to_mcp_server(
        self,
        file_path: str,
        filename: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Upload file al MCP server"""
        import uuid
        file_id = str(uuid.uuid4())
        
        async with httpx.AsyncClient() as client:
            # Leggi file
            with open(file_path, 'rb') as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"file_id": file_id, "user_id": user_id}
                
                response = await client.post(
                    f"{self.mcp_url}/files",
                    files=files,
                    data=data,
                    timeout=60.0
                )
            
            if response.status_code != 200:
                raise Exception(f"MCP upload failed: {response.text}")
            
            return {"file_id": file_id, "mcp_response": response.json()}
    
    async def _import_to_ccat(
        self,
        workflow: WorkflowExecution,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Import file in CCAT via RabbitHole"""
        # Estrai file_id dal risultato dell'upload
        upload_result = None
        for step in workflow.steps:
            if step.name == "upload_to_mcp" and step.data:
                upload_result = step.data
                workflow.file_id = upload_result["file_id"]
                break
        
        if not upload_result:
            raise Exception("Upload result not found")
        
        # Crea token per autenticazione
        token = self.security.create_service_token("workflow_orchestrator", workflow.user_id)
        
        # Richiesta import
        import_data = {
            "file_id": workflow.file_id,
            "mcp_server_url": self.mcp_url,
            "user_id": workflow.user_id,
            "context_metadata": {
                "filename": workflow.filename,
                "workflow_id": workflow.workflow_id,
                **(metadata or {})
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.rabbithole_url}/import-file",
                json=import_data,
                headers={"Authorization": f"Bearer {token}"},
                timeout=120.0
            )
            
            if response.status_code != 200:
                raise Exception(f"RabbitHole import failed: {response.text}")
            
            return response.json()
    
    async def _update_mcp_status(self, workflow: WorkflowExecution) -> Dict[str, Any]:
        """Aggiorna stato nel MCP server"""
        # Estrai context_id dal risultato dell'import
        import_result = None
        for step in workflow.steps:
            if step.name == "import_to_ccat" and step.data:
                import_result = step.data
                break
        
        if not import_result or not import_result.get("ccat_context_id"):
            raise Exception("Import result or context_id not found")
        
        context_id = import_result["ccat_context_id"]
        
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.mcp_url}/files/{workflow.file_id}/ccat-context",
                params={"context_id": context_id},
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise Exception(f"MCP status update failed: {response.text}")
            
            return response.json()
    
    def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowExecution]:
        """Recupera stato del workflow"""
        return self.active_workflows.get(workflow_id)
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancella workflow in esecuzione"""
        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            return False
        
        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = datetime.now()
        
        # Aggiungi step di cancellazione
        cancel_step = WorkflowStep(
            name="workflow_cancelled",
            status=WorkflowStatus.FAILED,
            timestamp=datetime.now(),
            message="Workflow cancelled by user"
        )
        workflow.steps.append(cancel_step)
        
        logger.info(f"Workflow {workflow_id} cancelled")
        return True

# Esempio di utilizzo
async def example_workflow():
    """Esempio di esecuzione workflow completo"""
    orchestrator = WorkflowOrchestrator()
    
    # Esegui workflow completo
    workflow = await orchestrator.execute_complete_workflow(
        file_path="./test_document.txt",
        filename="test_document.txt",
        user_id="user_123",
        metadata={"category": "test", "priority": "low"}
    )
    
    print(f"Workflow {workflow.workflow_id} status: {workflow.status}")
    print(f"Steps executed: {len(workflow.steps)}")
    
    for step in workflow.steps:
        print(f"  - {step.name}: {step.status} ({step.message})")
        if step.error:
            print(f"    Error: {step.error}")

if __name__ == "__main__":
    asyncio.run(example_workflow())
```

## 6. Documentazione e Deploy

### docker-compose.yml
```yaml
version: '3.8'

services:
  # MCP Server
  mcp-server:
    build:
      context: ./mcp-server
      dockerfile: Dockerfile
    ports:
      - "8002:8002"
    volumes:
      - ./data/mcp_storage:/app/mcp_storage
      - ./data/mcp_server.db:/app/mcp_server.db
    environment:
      - STORAGE_DIR=/app/mcp_storage
      - DB_PATH=/app/mcp_server.db
      - MAX_FILE_SIZE=104857600  # 100MB
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # RabbitHole Plugin
  rabbithole-plugin:
    build:
      context: ./rabbithole-plugin
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    environment:
      - JWT_SECRET=your-super-secret-jwt-key
      - CCAT_API_KEY=your-ccat-api-key
      - CCAT_BASE_URL=http://ccat-core:1865
      - MCP_TIMEOUT=30
    depends_on:
      - mcp-server
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # WebUI Backend
  webui-backend:
    build:
      context: ./webui-backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data/uploads:/app/uploads
    environment:
      - JWT_SECRET=your-super-secret-jwt-key
      - MCP_SERVER_URL=http://mcp-server:8002
      - RABBITHOLE_URL=http://rabbithole-plugin:8001
      - UPLOAD_DIR=/app/uploads
    depends_on:
      - mcp-server
      - rabbithole-plugin
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # WebUI Frontend
  webui-frontend:
    build:
      context: ./webui-client
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - REACT_APP_API_URL=http://localhost:8000
    depends_on:
      - webui-backend

  # CCAT Core (esempio)
  ccat-core:
    image: ghcr.io/cheshire-cat-ai/core:latest
    ports:
      - "1865:80"
    volumes:
      - ./data/ccat:/app/cat/data
    environment:
      - CCAT_LOG_LEVEL=INFO

  # Prometheus per monitoring
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'

  # Grafana per dashboard
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    volumes:
      - ./monitoring/grafana:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

volumes:
  mcp_data:
  ccat_data:
  grafana_data:
```

### Dockerfile per MCP Server
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["python", "mcp_server.py"]
```

### requirements.txt (MCP Server)
```txt
fastapi==0.104.1
uvicorn==0.24.0
aiofiles==23.2.1
httpx==0.25.2
prometheus-client==0.19.0
pydantic==2.5.0
sqlite3
```

### Dockerfile per RabbitHole Plugin
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["python", "plugin_rabbithole.py"]
```

### requirements.txt (RabbitHole Plugin)
```txt
fastapi==0.104.1
uvicorn==0.24.0
httpx==0.25.2
pyjwt==2.8.0
cheshire-cat-api==1.5.0
pydantic==2.5.0
```

### Script di test (test_integration.sh)
```bash
#!/bin/bash

# Test dell'integrazione completa CCAT
echo "🚀 Testing CCAT Integration System"

# Variabili
API_BASE="http://localhost:8000"
MCP_BASE="http://localhost:8002" 
RABBITHOLE_BASE="http://localhost:8001"

# Colori per output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funzione per log colorato
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Test 1: Health checks
log "Testing health endpoints..."

curl -s "$MCP_BASE/health" | jq . || error "MCP Server health check failed"
curl -s "$RABBITHOLE_BASE/health" | jq . || error "RabbitHole health check failed"
curl -s "$API_BASE/health" | jq . || error "WebUI Backend health check failed"

# Test 2: Authentication
log "Testing authentication..."

TOKEN=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"password"}' | \
    jq -r '.access_token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    error "Authentication failed"
    exit 1
fi

log "Authentication successful, token: ${TOKEN:0:20}..."

# Test 3: File upload
log "Testing file upload..."

# Crea file di test
echo "Questo è un documento di test per CCAT integration" > test_file.txt

UPLOAD_RESPONSE=$(curl -s -X POST "$API_BASE/upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@test_file.txt")

FILE_ID=$(echo $UPLOAD_RESPONSE | jq -r '.file