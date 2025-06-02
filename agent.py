from __future__ import annotations
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    RunContext,
    function_tool,
    Agent,
    AgentSession
)
from dataclasses import dataclass
from livekit.plugins import openai, silero
from dotenv import load_dotenv
from typing import Literal, Any
from collections.abc import Iterable
from prompts import WELCOME_MESSAGE, INSTRUCTIONS
from pathlib import Path

import logging
import annoy
import pickle

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("rag-agent")

load_dotenv()

# RAG Index Types and Classes
Metric = Literal["angular", "euclidean", "manhattan", "hamming", "dot"]
ANNOY_FILE = "index.annoy"
METADATA_FILE = "metadata.pkl"

@dataclass
class _FileData:
    f: int
    metric: Metric
    userdata: dict[int, Any]


@dataclass
class Item:
    i: int
    userdata: Any
    vector: list[float]


@dataclass
class QueryResult:
    userdata: Any
    distance: float

class AnnoyIndex:
    def __init__(self, index: annoy.AnnoyIndex, filedata: _FileData) -> None:
        self._index = index
        self._filedata = filedata

    @classmethod
    def load(cls, path: str) -> "AnnoyIndex":
        p = Path(path)
        index_path = p / ANNOY_FILE
        metadata_path = p / METADATA_FILE

        with open(metadata_path, "rb") as f:
            metadata: _FileData = pickle.load(f)

        index = annoy.AnnoyIndex(metadata.f, metadata.metric)
        index.load(str(index_path))
        return cls(index, metadata)

    @property
    def size(self) -> int:
        return self._index.get_n_items()

    def items(self) -> Iterable[Item]:
        for i in range(self._index.get_n_items()):
            item = Item(
                i=i,
                userdata=self._filedata.userdata[i],
                vector=self._index.get_item_vector(i),
            )
            yield item

    def query(
        self, vector: list[float], n: int, search_k: int = -1
    ) -> list[QueryResult]:
        ids = self._index.get_nns_by_vector(
            vector, n, search_k=search_k, include_distances=True
        )
        return [
            QueryResult(userdata=self._filedata.userdata[i], distance=distance)
            for i, distance in zip(*ids)
        ]

class RAGEnrichedAgent(Agent):
    """
    An agent that can answer questions using RAG (Retrieval Augmented Generation).
    """
    def __init__(self) -> None:
        """Initialize the RAG-enabled agent."""
        super().__init__(instructions=INSTRUCTIONS)

        # Initialize RAG components
        vdb_dir = Path(__file__).parent / "data"
        data_path = vdb_dir / "paragraphs.pkl"
        
        if not vdb_dir.exists() or not data_path.exists():
            logger.warning(
                "RAG database not found. Please run build_rag_data.py first:\n"
                "$ python build_rag_data.py"
            )
            return
        
        # Load RAG index and data
        self._index_path = vdb_dir
        self._data_path = data_path
        self._embeddings_dimension = 1536
        self._embeddings_model = "text-embedding-3-small"
        self._seen_results = set() 

        try:
            self._annoy_index = AnnoyIndex.load(str(self._index_path))
            with open(self._data_path, "rb") as f:
                self._paragraphs_by_uuid = pickle.load(f)
            logger.info("RAG database loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load RAG database: {e}")

    @function_tool
    async def tumble_dry_search(self, context: RunContext, query: str):
        """Lookup information in the TumbleDry database. Will not return results already returned in previous lookups."""
        try:
            # Generate embeddings for the query
            query_embedding = await openai.create_embeddings(
                input=[query],
                model=self._embeddings_model,
                dimensions=self._embeddings_dimension,
            )

            # Query the index for more results than we need to ensure we have enough new content
            all_results = self._annoy_index.query(
                query_embedding[0].embedding, n=5
            )  # Get more results initially

            # Filter out previously seen results
            new_results = [
                r for r in all_results if r.userdata not in self._seen_results
            ]

            # If we don't have enough new results, clear the seen results and start fresh
            if len(new_results) == 0:
                return "No new results found."
            else:
                new_results = new_results[:2]  # Take top 2 new results

            # Build context from multiple relevant paragraphs
            context_parts = []
            for result in new_results:
                # Add result to seen set
                self._seen_results.add(result.userdata)

                paragraph = self._paragraphs_by_uuid.get(result.userdata, "")
                if paragraph:
                    # Extract source URL if available in the paragraph
                    source = "Unknown source"
                    if "from [" in paragraph:
                        source = paragraph.split("from [")[1].split("]")[0]
                        paragraph = paragraph.split("]")[1].strip()

                    context_parts.append(f"Source: {source}\nContent: {paragraph}\n")

            if not context_parts:
                return

            # Combine all context parts with clear separation
            full_context = "\n\n".join(context_parts)
            escaped_context = full_context.replace('\n', '\\n')
            logger.info(f"Results for query: {query}, full context: {escaped_context}")

            return full_context
        except Exception as e:
            return "Could not find any relevant information for that query."

    async def on_enter(self):
        """Called when the agent enters the session."""
        self.session.generate_reply(
            instructions=WELCOME_MESSAGE
        )


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the agent."""
    await ctx.connect()
    logger.info("Connected to room, waiting for participant")

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=openai.STT(model="whisper-1"),
        llm=openai.LLM(model="gpt-4-turbo"),
        tts=openai.TTS(model="tts-1", voice="alloy"),
    )

    await session.start(
        agent=RAGEnrichedAgent(),
        room=ctx.room,       
    )
    logger.info("Session started successfully")
        

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))