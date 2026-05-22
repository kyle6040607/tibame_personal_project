import requests


def get_embedding(text: str, model_name: str = "mxbai-embed-large") -> list[float]:
    text = (text or "").strip()
    if not text:
        return []

    response = requests.post(
        "http://localhost:11434/api/embeddings",
        json={
            "model": model_name,
            "prompt": text
        },
        timeout=120
    )
    response.raise_for_status()
    data = response.json()
    return data["embedding"]