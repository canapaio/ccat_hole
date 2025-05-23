
"Devo creare un sistema integrato che collega **Cheshire AI Cat (CCAT)** con il plugin **RabbitHole** e una **WebUI client/server** per gestire file e interagire con un **MCP server**. Specifica un'architettura completa con codice di esempio per i seguenti componenti:

1. **Plugin RabbitHole Personalizzato**  
   - Deve funzionare come ponte tra il filesystem del MCP server e CCAT.  
   - Implementare un'API RESTful (es. `/import-file`) che riceve metadati da WebUI, recupera file dal MCP server e li invia a CCAT tramite RabbitHole.  
   - Codice Python esempio usando `fastapi` e librerie CCAT.

2. **WebUI Client/Server**  
   - Frontend (React/Vue.js): Interfaccia utente per caricare file, visualizzare lo stato dell'importazione e interagire con CCAT.  
   - Backend (Flask/FastAPI): Gestisce autenticazione, comunicazione con MCP server e il plugin RabbitHole.  
   - Esempio di endpoint `/upload` per inviare file al MCP server e attivare l'importazione.

3. **MCP Server con Filesystem**  
   - Configurazione di un MCP server (es. usando `model-control`) per archiviare file e fornire un'API `/files/{id}` per il recupero.  
   - Integrazione con il plugin RabbitHole per sincronizzare i dati con CCAT.  
   - Schema JSON per il trasferimento dei dati tra MCP e plugin.

4. **Integrazione CCAT + RabbitHole**  
   - Codice Python per utilizzare l'SDK di CCAT e il plugin RabbitHole, ad esempio:  
     ```python
     from cheshire_cat_api import CatClient
     client = CatClient(api_key="your_key")
     response = client.rabbit_hole.import_file(url="http://mcp-server/files/123")
     ```
   - Gestione degli errori (es. file non trovato, timeout).

5. **Workflow End-to-End**  
   - Sequenza passo-passo: Utente carica file → WebUI invia al MCP server → Plugin RabbitHole attiva l'import in CCAT → Notifica all'utente.  
   - Sicurezza: Token JWT per l'autenticazione tra WebUI, MCP server e plugin.

6. **Documentazione**  
   - Istruzioni per deploy (Dockerfile per ogni componente).  
   - Test: Comandi curl per testare l'API `/import-file` e verifica in CCAT."

---

**Dettagli tecnici richiesti:**  
- Specificare librerie/framework (es. FastAPI per backend, Axios per WebUI).  
- Gestione di file di grandi dimensioni (es. streaming con `multipart/form-data`).  
- Logging e monitoraggio (es. Prometheus per metriche MCP server).  
- Esempio di risposta JSON tra plugin e CCAT:  
  ```json
  {
    "file_id": "abc123",
    "status": "imported",
    "ccat_context_id": "ctx_456"
  }
  ```

**Output atteso:**  
Codice modulare, commentato e documentato, con chiaro separazione tra i componenti (es. microservizi) e best practices per scalabilità.
