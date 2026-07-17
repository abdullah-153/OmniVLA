import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"
os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
os.environ["ANON_TELEMETRY"] = "False"

import logging
import chromadb
from chromadb.config import Settings
import uuid
import time

logger = logging.getLogger(__name__)

class ChatsRAG:
    """Manages indexing and semantic search of past chat conversations for contextual retrieval."""
    
    def __init__(self):
        self._available = True
        try:
            from chromadb.config import Settings
            # Persistent storage in ./omnivla_memory_v2/
            self.client = chromadb.PersistentClient(
                path="./omnivla_memory_v2",
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self.client.get_or_create_collection(name="chat_history_rag")
            logger.info("Chats RAG Memory initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Chats RAG: {e}")
            self._available = False

    def index_message(self, chat_id: str, role: str, content: str):
        """Index a chat message for semantic retrieval. Only index text messages with content."""
        if not self._available or not content or not chat_id:
            return
            
        # Avoid indexing system messages or empty messages
        if role == "system" or not content.strip():
            return
            
        doc_id = f"msg_{uuid.uuid4().hex}"
        document = f"Role: {role} | Message: {content}"
        metadata = {
            "chat_id": chat_id,
            "role": role,
            "timestamp": time.time()
        }
        
        try:
            self._collection.add(
                documents=[document],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.info(f"Indexed chat message {doc_id} from chat {chat_id}.")
        except Exception as e:
            logger.error(f"Failed to index chat message: {e}")

    def search_context(self, query: str, current_chat_id: str, n_results: int = 3) -> str:
        """Query ChromaDB for relevant context from past chats (excluding the current chat)."""
        if not self._available or self._collection.count() == 0 or not query:
            return ""
            
        try:
            # Query and retrieve matching items
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results * 2, self._collection.count()), # Get extra to filter in Python
            )
            
            if not results["documents"] or len(results["documents"]) == 0 or len(results["documents"][0]) == 0:
                return ""
                
            contexts = []
            seen = set()
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                # Filter out current chat messages to prevent duplicate context
                if meta.get("chat_id") == current_chat_id:
                    continue
                # Simple de-duplication
                if doc in seen:
                    continue
                seen.add(doc)
                contexts.append(f"[{meta.get('role', 'user')}]: {doc.split(' | Message: ')[-1]}")
                if len(contexts) >= n_results:
                    break
                    
            if contexts:
                return "\n".join(contexts)
        except Exception as e:
            logger.error(f"Failed to query Chats RAG context: {e}")
            
        return ""
