import os
import logging

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

from tqdm import tqdm

tqdm.disable = True

from transformers import logging as transformers_logging
from huggingface_hub.utils import logging as hf_logging

transformers_logging.set_verbosity_error()
hf_logging.set_verbosity_error()
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

from sentence_transformers import SentenceTransformer

_model = None


def load_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5", local_files_only=True)


def generate_embedding(text: str) -> list[float]:
    global _model
    if _model is None:
        load_embedding_model()
    return _model.encode(text).tolist()


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    global _model
    if _model is None:
        load_embedding_model()
    if not texts:
        return []
    return _model.encode(texts, show_progress_bar=False).tolist()
