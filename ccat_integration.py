
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