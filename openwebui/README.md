# Morpheus Open WebUI integration

`morpheus_rag_pipe.py` is a native Open WebUI Pipe. It intentionally calls the
local Morpheus gateway rather than reimplementing security, document ingestion,
retrieval, Temporal orchestration, or Tavily.

## Install the Pipe

1. Start Open WebUI at `http://127.0.0.1:3000`.
2. Create the first local administrator account.
3. Open **Admin Panel → Functions → Create**.
4. Set the ID to `morpheus_rag_pipe`, paste the contents of
   `morpheus_rag_pipe.py`, save, and enable it.
5. Select **Morpheus RAG Agent** in the model picker.

For Docker Desktop on macOS, the Pipe default gateway URL is correct:
`http://host.docker.internal:8000/v1`.

## Manual test flow

1. Attach one or more PDFs to a new chat.
2. Select **Morpheus RAG Agent** and ask a question about them.
3. Observe in-chat upload, ingestion, retrieval, and workflow status events.
4. When the workflow asks, approve or decline Tavily web search in the browser
   confirmation dialog.
5. The final assistant message is returned from the durable workflow status.

## Local launch

```bash
docker run -d --name morpheus-openwebui -p 3000:8080 \
  -v morpheus-openwebui:/app/backend/data \
  -e WEBSOCKET_EVENT_CALLER_TIMEOUT=900 \
  ghcr.io/open-webui/open-webui:main
```

The Pipe requires a running Morpheus gateway at `127.0.0.1:8000` on the host.
Do not expose either service publicly until authentication and ownership checks
are added to the Morpheus workflow routes.
