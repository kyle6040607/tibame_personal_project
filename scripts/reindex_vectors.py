"""
One-shot script: 重建 Chroma 向量索引。

什麼時候要跑：
  把 collection 的距離度量從 L2 改成 cosine 之後（見 repositories/vector_repository.py）。
  舊的 collection 是用 L2 建立的，cosine 設定會被忽略，必須先刪掉舊 collection
  再用 SQL 裡既有的 chunks 重新 embedding。

注意：
  - SQL 的 documents / document_chunks 不受影響，只重建向量庫。
  - 會重新呼叫 Ollama 對所有 chunk 做 embedding，文件多時需要一些時間。
  - 請用專案的 venv 執行：  .venv\\Scripts\\python scripts\\reindex_vectors.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 先刪掉舊 collection，再 import services（vector_repository 會在 import 時
# 用 cosine 重新建立 collection）。順序很重要：若先 import，舊的 L2 collection
# 仍存在，cosine 設定會被忽略。
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
try:
    client.delete_collection("document_chunks")
    print("已刪除舊的 collection: document_chunks")
except Exception as e:
    print(f"沒有既有 collection 可刪（或刪除失敗，可忽略）：{e}")

from repositories.document_repository import get_documents
from services.embedding_service import index_document_chunks


def main():
    docs = get_documents()
    print(f"共 {len(docs)} 份文件，開始重建向量索引...\n")

    for i, d in enumerate(docs, start=1):
        print(f"[{i}/{len(docs)}] document_id={d['id']} title={d['title']!r}")
        index_document_chunks(d["id"])

    print(f"\n完成，已重建 {len(docs)} 份文件的向量索引（cosine）。")


if __name__ == "__main__":
    main()
