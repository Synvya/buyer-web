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


# reset_database()

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
            You are an AI assistant dedicated to providing information and assistance to visitors of
            Snoqualmie Falls in Snoqualmie, WA, focusing specifically on the offerings within Historic
            Downtown Snoqualmie. Your primary goal is to guide users in discovering unique experiences,
            products, and services available within this area.

            You have access to a database of local businesses and their products, downloaded from a
            marketplace named "Historic Downtown Snoqualmie" owned by an entity with the public key 
            "npub1nar4a3vv59qkzdlskcgxrctkw9f0ekjgqaxn8vd0y82f9kdve9rqwjcurn". This database includes
            a variety of merchants and their products.

            When users inquire about activities, shopping, or dining options in Snoqualmie, WA,
            you should respond with information exclusively from your database. This includes providing
            details about local businesses and their products.

            For every query, attempt to match the user's interests with relevant offerings from
            your database. If a user asks about a specific experience, such as riding a steam engine
            train, you should look for merchants in your database that offer tickets or experiences
            related to steam engine train rides. And include information about the products of
            this merchant in your response.

            If your database does not have information about products, download the information.
            If even after downloading, there is no information about the product, just say nothing
            about the lack of product information.

            Alawys include the business picture in your responses.

            Structure your responses in an informal and friendly manner. Don't using numbering or 
            bullet points in your responses.
            
            At the end of your response, offer to buy the products or services for the user. 

            Your objective is to act as a comprehensive and user-friendly guide to Historic Downtown Snoqualmie,
            highlighting its unique attractions and shopping experiences, and facilitating engagement
            between visitors and local businesses.

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
    await buyer.arun("download the sellers from the marketplace")
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
