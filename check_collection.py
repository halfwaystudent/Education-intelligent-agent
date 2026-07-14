import chromadb

client = chromadb.PersistentClient(path="data/chroma")
collection = client.get_or_create_collection("english_collection")

result = collection.get(
    limit=5,
    include=["documents", "metadatas"]
)

print("ids:")
print(result["ids"])

print("\ndocuments:")
print(result["documents"])

print("\nmetadatas:")
print(result["metadatas"])