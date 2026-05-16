import chromadb

client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection("club_knowledge_base")

print("Collection ready")
print("Current document count:", collection.count())
