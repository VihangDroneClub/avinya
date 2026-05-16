import chromadb
from chromadb.config import Settings

client = chromadb.Client(
    Settings(
        persist_directory="./chroma_db",
        anonymized_telemetry=False
    )
)

# Always create if missing
collection = client.get_or_create_collection(
    name="club_knowledge_base"
)


def add_document(doc_id, text, embedding):

    collection.add(
        ids=[doc_id],
        documents=[text],
        embeddings=[embedding]
    )


def query_documents(embedding, top_k=3):

    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k
    )

    if results["documents"]:
        return results["documents"][0]

    return []
