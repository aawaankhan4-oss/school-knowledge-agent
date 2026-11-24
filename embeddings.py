"""Turns text into embedding vectors for semantic search, and compares them.

Uses a small model that runs locally on your own CPU — no API key needed,
no cost, works offline once the model has been downloaded once.
"""
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model():
    return SentenceTransformer(MODEL_NAME)


def embed_text(text):
    """Return a normalized embedding vector for a piece of text."""
    vec = get_model().encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def serialize_embedding(vec):
    return np.asarray(vec, dtype=np.float32).tobytes()


def deserialize_embedding(blob):
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a, b):
    # embed_text already normalizes vectors, so a plain dot product is cosine similarity
    return float(np.dot(a, b))
