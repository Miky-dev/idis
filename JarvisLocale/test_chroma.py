import chromadb
import sys

client = chromadb.PersistentClient(path='./chroma_db')
col = client.get_or_create_collection('memoria_jarvis')

data = col.get(include=['embeddings', 'documents', 'metadatas'])
docs = data['documents']
embs = data['embeddings']

print(f"Total docs: {len(docs)}")
for d, e in zip(docs, embs):
    print(f"Doc: {d}")
    if e is not None:
        print(f"Emb len: {len(e)}, first 3: {e[:3]}")
    else:
        print("Emb: None")
