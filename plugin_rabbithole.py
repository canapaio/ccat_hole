
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