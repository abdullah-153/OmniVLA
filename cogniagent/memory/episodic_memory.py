import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"
os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
os.environ["ANON_TELEMETRY"] = "False"

import json
import logging
import time
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)

@dataclass
class Episode:
    # Context
    task: str               # "Send email to john@example.com"
    app_context: str        # "Gmail"
    goal: str               # "Click Compose button"
    
    # Action taken
    action_type: str        # "click"
    action_args: list[str]  # ["1"]
    action_method: str      # "shortcut" | "uia" | "coordinate"
    
    # Result
    success: bool           # True
    state_summary: str      # "Gmail inbox, Compose button visible"
    outcome: str            # "Compose window opened"
    
    # Metadata
    timestamp: float
    execution_time_ms: int
    retry_count: int

@dataclass
class Trajectory:
    task: str
    episodes: list[Episode]
    total_time_ms: int
    success: bool
    app_sequence: list[str]

class EpisodicMemory:
    """Stores and retrieves episodic memory using ChromaDB."""
    
    def __init__(self, config):
        self.config = config
        self._available = bool(getattr(config.memory, "enabled", True))
        if not self._available:
            logger.info("Episodic Memory is disabled by local privacy settings.")
            return
        try:
            import chromadb
            from chromadb.config import Settings
            # Persistent storage in ./omnivla_memory_v2/
            self.client = chromadb.PersistentClient(
                path=getattr(config.memory, "db_path", "./omnivla_memory_v2"),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self.client.get_or_create_collection(name="episodes")
            self._trajectory_collection = self.client.get_or_create_collection(name="trajectories")
            logger.info("Episodic Memory initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self._available = False

    def store(self, episode: Episode):
        """Store an episode."""
        if not self._available:
            return
            
        document = (
            f"App: {episode.app_context} | "
            f"Goal: {episode.goal} | "
            f"Action: {episode.action_type}({', '.join(episode.action_args)}) | "
            f"State: {episode.state_summary}"
        )
        
        metadata = {
            "task": episode.task,
            "app": episode.app_context,
            "goal": episode.goal,
            "action_type": episode.action_type,
            "action_args": json.dumps(episode.action_args),
            "action_method": episode.action_method,
            "success": episode.success,
            "timestamp": episode.timestamp,
        }
        
        import uuid
        doc_id = f"ep_{uuid.uuid4().hex}"
        
        try:
            self._collection.add(
                documents=[document],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.debug(f"Stored episode {doc_id} to memory.")
        except Exception as e:
            logger.error(f"Failed to store episode: {e}")

    def recall(self, goal: str, app_context: str = "", n_results: int = 3) -> str:
        """Retrieve relevant past experiences."""
        if not self._available or self._collection.count() == 0:
            return ""
        
        query = f"App: {app_context} | Goal: {goal}"
        
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, self._collection.count()),
                where={"success": True}
            )
            
            if not results["documents"] or len(results["documents"]) == 0 or len(results["documents"][0]) == 0:
                return ""
            
            memories = []
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                action_args = json.loads(meta.get("action_args", "[]"))
                memories.append(
                    f"Previously: for goal '{meta['goal']}' in {meta.get('app', 'unknown')}, "
                    f"action {meta['action_type']}({', '.join(action_args)}) "
                    f"succeeded."
                )
            
            return " | ".join(memories[:3])
        except Exception as e:
            logger.error(f"Failed to recall memories: {e}")
            return ""

    def exact_recall(self, goal: str, app_context: str) -> Optional[dict]:
        """Check for an exact high-confidence match to bypass LLM reasoning."""
        if not self._available or self._collection.count() == 0:
            return None
            
        try:
            # Use metadata exact match instead of embedding similarity
            results = self._collection.get(
                where={"$and": [{"success": True}, {"app": app_context}, {"goal": goal}]}
            )
            
            if results["metadatas"] and len(results["metadatas"]) > 0:
                meta = results["metadatas"][0]
                action_args = json.loads(meta.get("action_args", "[]"))
                return {
                    "action_type": meta["action_type"],
                    "action_args": action_args,
                    "confidence": 1.0  # Exact metadata match is 100% confidence
                }
        except Exception as e:
            logger.error(f"Exact recall failed: {e}")
            
        return None

    def store_trajectory(self, trajectory: Trajectory):
        """Store an entire successful task trajectory."""
        if not self._available or not trajectory.success:
            return
            
        doc_id = f"traj_{int(time.time() * 1000)}"
        
        document = f"Task: {trajectory.task}"
        
        # We only serialize basic metadata since nested episodes are hard to store cleanly in chroma metadata
        metadata = {
            "task": trajectory.task,
            "success": trajectory.success,
            "total_time_ms": trajectory.total_time_ms,
            "app_sequence": json.dumps(trajectory.app_sequence),
            "episodes_count": len(trajectory.episodes)
        }
        
        try:
            self._trajectory_collection.add(
                documents=[document],
                metadatas=[metadata],
                ids=[doc_id]
            )
        except Exception as e:
            logger.error(f"Failed to store trajectory: {e}")

    def recall_trajectory(self, task: str) -> Optional[dict]:
        """Find a past trajectory similar to the current task."""
        if not self._available or self._trajectory_collection.count() == 0:
            return None
            
        query = f"Task: {task}"
        try:
            results = self._trajectory_collection.query(
                query_texts=[query],
                n_results=1,
                where={"success": True}
            )
            
            if results["documents"] and len(results["documents"][0]) > 0:
                meta = results["metadatas"][0][0]
                return {
                    "task": meta["task"],
                    "app_sequence": json.loads(meta.get("app_sequence", "[]"))
                }
        except Exception as e:
            logger.error(f"Failed to recall trajectory: {e}")
            
        return None


def clear_local_memory(storage_dir: str = "./omnivla_memory_v2") -> int:
    """Clear OmniVLA recall collections and its flat chat index."""
    removed = 0
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=storage_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        existing = {collection.name for collection in client.list_collections()}
        for name in ("episodes", "trajectories"):
            if name in existing:
                client.delete_collection(name)
                removed += 1
    except Exception as error:
        logger.warning("Unable to clear one or more Chroma collections: %s", error)

    for filename in (
        "chat_rag_store.json", "chat_rag_store.json.migrated", "chat_recall.sqlite3",
        "chat_recall.sqlite3-wal", "chat_recall.sqlite3-shm",
    ):
        chat_index = os.path.join(storage_dir, filename)
        if os.path.isfile(chat_index):
            os.remove(chat_index)
            removed += 1
    return removed
