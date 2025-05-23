
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