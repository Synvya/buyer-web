"""
This is the main file for the buyer agent API.
"""

import asyncio
import json
import logging
import uuid
import warnings
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path
from typing import Any, Generator, List, Optional

import nest_asyncio

# import nest_asyncio
from agentstr import AgentProfile, BuyerTools, Keys, generate_and_save_keys
from agno.agent import Agent, AgentKnowledge  # type: ignore
from agno.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIChat  # type: ignore
from agno.vectordb.pgvector import PgVector, SearchType
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pgvector.sqlalchemy import Vector  # Correct import for vector storage
from pydantic import BaseModel
from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql import text

from .utils.prompt import ClientMessage

# nest_asyncio.apply()  # type: ignore

# Set logging to WARN level to suppress INFO logs
logging.basicConfig(level=logging.WARN)

# Configure logging first
logging.getLogger("cassandra").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="cassandra")

# Set logging to WARN level to suppress INFO logs
logging.basicConfig(level=logging.WARN)

# Configure logging first
logging.getLogger("cassandra").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="cassandra")


# nest_asyncio.apply()
# Set logging to WARN level to suppress INFO logs
logging.basicConfig(level=logging.WARN)

# Get directory where the script is located
script_dir = Path(__file__).parent
# Load .env from the script's directory
load_dotenv(script_dir / ".env")

# Load or generate keys
NSEC = getenv("BUYER_AGENT_KEY")
if NSEC is None:
    keys = generate_and_save_keys(
        env_var="BUYER_AGENT_KEY", env_path=script_dir / ".env"
    )
else:
    keys = Keys.parse(NSEC)

# Load or use default relay
RELAY = getenv("RELAY")
if RELAY is None:
    RELAY = "wss://relay.damus.io"

OPENAI_API_KEY = getenv("OPENAI_API_KEY")
if OPENAI_API_KEY is None:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

DB_USERNAME = getenv("DB_USERNAME")
if DB_USERNAME is None:
    raise ValueError("DB_USERNAME environment variable is not set")

DB_PASSWORD = getenv("DB_PASSWORD")
if DB_PASSWORD is None:
    raise ValueError("DB_PASSWORD environment variable is not set")

DB_HOST = getenv("DB_HOST")
if DB_HOST is None:
    raise ValueError("DB_HOST environment variable is not set")

DB_PORT = getenv("DB_PORT")
if DB_PORT is None:
    raise ValueError("DB_PORT environment variable is not set")

DB_NAME = getenv("DB_NAME")
if DB_NAME is None:
    raise ValueError("DB_NAME environment variable is not set")

# Buyer profile constants
NAME = "Snoqualmie Valley Chamber of Commerce"
DESCRIPTION = "Supporting the Snoqualmie Valley business community."
PICTURE = "https://i.nostr.build/ocjZ5GlAKwrvgRhx.png"
DISPLAY_NAME = "Snoqualmie Valley Chamber of Commerce"

# Initialize a buyer profile
profile = AgentProfile(keys=keys)
profile.set_name(NAME)
profile.set_about(DESCRIPTION)
profile.set_display_name(DISPLAY_NAME)
profile.set_picture(PICTURE)

# Initialize database connection
db_url = (
    f"postgresql+psycopg://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(db_url)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Seller(Base):
    """
    SQLAlchemy model for table `sellers` in the ai schema.
    """

    __tablename__ = "sellers"
    __table_args__ = {"schema": "ai"}  # If the table is inside the 'ai' schema

    id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )  # UUID primary key
    name = Column(Text, nullable=True)
    meta_data = Column(JSONB, default={})
    filters = Column(JSONB, default={})
    content = Column(Text, nullable=True)
    embedding: Optional[Vector] = Column(Vector(1536), nullable=True)
    usage = Column(JSONB, default={})
    content_hash = Column(Text, nullable=True)

    def __repr__(self) -> str:
        """
        Return a string representation of the Seller object.
        """
        return f"<Seller(id={self.id}, name={self.name})>"


# Function to drop and recreate the table
def reset_database() -> None:
    """
    Drop and recreate all tables in the database.
    """
    with engine.connect() as conn:
        # Enable pgvector extension
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

    # Drop and recreate all tables
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


reset_database()

vector_db = PgVector(
    table_name="sellers",
    db_url=db_url,
    schema="ai",
    search_type=SearchType.vector,
    embedder=OpenAIEmbedder(),
)

knowledge_base = AgentKnowledge(vector_db=vector_db)


buyer = Agent(  # type: ignore[call-arg]
    name="Virtual Guide for the Snoqualmie Valley",
    model=OpenAIChat(id="gpt-4o", api_key=OPENAI_API_KEY),
    tools=[
        BuyerTools(knowledge_base=knowledge_base, buyer_profile=profile, relay=RELAY)
    ],
    add_history_to_messages=True,
    num_history_responses=10,
    read_chat_history=True,
    read_tool_call_history=True,
    knowledge=knowledge_base,
    show_tool_calls=False,
    debug_mode=False,
    # async_mode=True,
    instructions=[
        """
        You're an AI tourist guide for people visiting Snoqualmie Falls. You will help them find things
        to do, places to go, and things to buy at nearby Historic Downtown Snoqualmie using
        exclusively the information provided by BuyerTools and stored in your knowledge base.
        
        When I ask you to refresh your sellers, use the refresh_sellers tool.
        
        Search the knowledge base for the most relevant information to the query before using
        the tools.
        
        After using the tool find_sellers_by_location, always immediately call the tool 
        get_seller_products to retrieve the products from the merchants in that location
        and include the products in the itinerary.
        
        When including merchants from your knowledge base in your response, make sure to 
        include their products and services. Provide also the price of the products and services.
        Offer to purchase the products or make a reservation and then include
        this in your overall response.
        """.strip(),
    ],
)


#######
app = FastAPI()


class Request(BaseModel):
    """
    Simple request model for the buyer agent.
    """

    messages: List[ClientMessage]


def stream_mock_text(input_str: str) -> Generator[str, Any, None]:
    """
    Mimics the output format from stream_text.
    It simply yields lines prefixed with 0: for content and an e: line
    for usage once finished.
    """

    # Here, we simply yield the entire input as a single content chunk.
    # If you want finer granularity (like line-by-line), you can split
    # input_str however you wish.
    yield f"0:{json.dumps(input_str)}\n"

    # Emit a final line with usage (prompt/completion tokens),
    # mirroring how stream_text does it at the end.
    usage_info = {
        "finishReason": "stop",
        "usage": {
            "promptTokens": 0,
            "completionTokens": len(input_str),
        },
        "isContinued": False,
    }
    yield f"e:{json.dumps(usage_info)}\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Refresh the sellers on startup. This is a lenghtly operation
    that will take around a minute to complete, slowing down the
    startup of the API.
    """
    await buyer.arun("refresh your sellers")
    yield


app.router.lifespan_context = lifespan


# @app.middleware("http")
# async def timeout_middleware(request: Request, call_next):
#     """
#     Middleware to handle request timeouts.
#     """
#     try:
#         return await asyncio.wait_for(
#             call_next(request), timeout=300  # 5-minute timeout per request
#         )
#     except asyncio.TimeoutError as exc:
#         raise HTTPException(
#             status_code=504, detail="Server processing timeout"
#         ) from exc


@app.post("/api/chat")
def query_buyer(request: Request, protocol: str = Query("data")) -> StreamingResponse:
    """
    POST an object like {"query": "Hi, what can I do in Snoqualmie, WA?"}
    and get back the agent's response.
    """

    response = buyer.run(request.messages[-1].content)
    response = StreamingResponse(
        stream_mock_text(response.get_content_as_string()), media_type="text/plain"
    )
    response.headers["x-vercel-ai-data-stream"] = "v1"

    return response
