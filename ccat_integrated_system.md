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
async def update_ccat_context(file_i