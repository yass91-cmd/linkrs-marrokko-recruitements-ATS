import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Multilingual (FR/NL/AR/EN), 384 dimensions — matches the vector(384) column.
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_model = None


def get_model() -> SentenceTransformer:
    """Load the model once and reuse it (loading is slow)."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    """Turn one text into a 384-dimension vector."""
    vector = get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    v = embed("Téléconseiller néerlandais à Casablanca")
    print("Vector length:", len(v))
    print("First 5 values:", v[:5])

    # Sanity check: similar texts should score higher than unrelated ones.
    import numpy as np
    a = np.array(embed("téléconseiller néerlandais centre d'appel"))
    b = np.array(embed("conseiller client néerlandophone"))
    c = np.array(embed("comptable fiscalité et paie"))
    print("\nsimilar   (NL agent vs NL advisor):", round(float(a @ b), 3))
    print("unrelated (NL agent vs accountant) :", round(float(a @ c), 3))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)