
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