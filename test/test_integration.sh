
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

FILE_ID=$(echo $UPLOAD_RESPONSE | jq -r '.file_id')
if [ "$FILE_ID" == "null" ] || [ -z "$FILE_ID" ]; then
    error "File upload failed"
    exit 1
fi
log "File uploaded successfully, file_id: ${FILE_ID:0:8}..."