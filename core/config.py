import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:latest")

DB_CONNECTION_STRING = os.getenv(
    "DB_CONNECTION_STRING",
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=localhost\\SQLEXPRESS;"
    "DATABASE=local_llm_notebook;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;",
)

SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-to-a-random-secret-string")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
