import os
import faiss
import numpy as np
import pickle
from sentence_transformers import SentenceTransformer
from django.conf import settings
from .crawler import crawl_college_sources
from .colleges_data import COLLEGES


# -------------------------------------------------
# CONFIG
# -------------------------------------------------

VECTOR_DIR = settings.MEDIA_ROOT
os.makedirs(VECTOR_DIR, exist_ok=True)

_embed_model = None


# -------------------------------------------------
# Load Embedding Model (Singleton)
# -------------------------------------------------

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        print("Loading embedding model...")
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Embedding model ready.")
    return _embed_model


# -------------------------------------------------
# Clean Text (Less Aggressive)
# -------------------------------------------------

def clean_text(text):
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        line = line.strip()
        if len(line) > 20:   # Reduced threshold
            cleaned.append(line)

    return "\n".join(cleaned)


# -------------------------------------------------
# Smart Chunking (Better Version)
# -------------------------------------------------

def smart_chunk(text, chunk_size=600, overlap=100):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if len(chunk) > 200:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


# -------------------------------------------------
# Build Knowledge Base (Cosine Similarity Based)
# -------------------------------------------------

def build_index_background(college_id):
    info = COLLEGES[college_id]
    print(f"Building knowledge base for {info['name']}...")

    master_text = crawl_college_sources(info)

    if not master_text:
        print("No data found.")
        return

    # Clean text
    master_text = clean_text(master_text)

    # Chunk text
    chunks = smart_chunk(master_text)

    print("Total chunks:", len(chunks))

    model = get_embed_model()

    # Normalize embeddings for cosine similarity
    embeddings = model.encode(
        chunks,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    dimension = embeddings.shape[1]

    # Use Inner Product (cosine similarity)
    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(embeddings))

    # Save index
    faiss.write_index(index, os.path.join(VECTOR_DIR, f"{college_id}.index"))

    # Save chunks
    with open(os.path.join(VECTOR_DIR, f"{college_id}.pkl"), "wb") as f:
        pickle.dump(chunks, f)

    print("Knowledge base built successfully.")


# -------------------------------------------------
# Ensure Index Exists
# -------------------------------------------------

def ensure_index(college_id):
    index_path = os.path.join(VECTOR_DIR, f"{college_id}.index")

    if not os.path.exists(index_path):
        build_index_background(college_id)
        return False

    return True

# -------------------------------------------------
# Retrieve Context (Hybrid Search with Multi-Index)
# -------------------------------------------------
from rank_bm25 import BM25Okapi
import numpy as np
import faiss
import pickle
import os

def retrieve_context(college_id, question, k=3, max_chars=3000):
    # -------------------------------------------------
    # 1️⃣ Decide which IDs to load
    # -------------------------------------------------
    college_ids = [college_id]

    # If college_id = 1 → also include 11
    if str(college_id) == "1":
        college_ids.append("11")

    all_chunks = []
    all_embeddings = []

    # -------------------------------------------------
    # 2️⃣ Load all indexes and chunks
    # -------------------------------------------------
    index_list = []
    chunk_offsets = []

    current_offset = 0

    for cid in college_ids:
        index_path = os.path.join(VECTOR_DIR, f"{cid}.index")
        pkl_path = os.path.join(VECTOR_DIR, f"{cid}.pkl")

        if not os.path.exists(index_path):
            continue

        # Load FAISS index
        index = faiss.read_index(index_path)
        index_list.append(index)

        # Load chunks
        with open(pkl_path, "rb") as f:
            chunks = pickle.load(f)

        all_chunks.extend(chunks)

        # Track offset for index merging
        chunk_offsets.append((current_offset, len(chunks)))
        current_offset += len(chunks)

    if not index_list:
        return ""

    # -------------------------------------------------
    # 3️⃣ Merge FAISS indexes
    # -------------------------------------------------
    merged_index = faiss.IndexFlatIP(index_list[0].d)

    for idx in index_list:
        xb = idx.reconstruct_n(0, idx.ntotal)
        merged_index.add(xb)

    # -------------------------------------------------
    # 4️⃣ Generate Query Embedding
    # -------------------------------------------------
    model = get_embed_model()

    query_embedding = model.encode(
        [question],
        normalize_embeddings=True
    )

    # -------------------------------------------------
    # 5️⃣ FAISS Search
    # -------------------------------------------------
    distances, faiss_indices = merged_index.search(
        np.array(query_embedding).astype("float32"),
        k
    )

    # -------------------------------------------------
    # 6️⃣ BM25 Search
    # -------------------------------------------------
    tokenized_chunks = [chunk.split() for chunk in all_chunks]
    bm25 = BM25Okapi(tokenized_chunks)

    tokenized_query = question.split()
    bm25_scores = bm25.get_scores(tokenized_query)

    bm25_top_indices = np.argsort(bm25_scores)[::-1][:k]

    # -------------------------------------------------
    # 7️⃣ Combine Results
    # -------------------------------------------------
    combined_indices = list(set(
        faiss_indices[0].tolist() + bm25_top_indices.tolist()
    ))

    ranked_chunks = []

    for idx in combined_indices:
        embed_score = 0

        if idx in faiss_indices[0]:
            pos = list(faiss_indices[0]).index(idx)
            embed_score = 1 / (1 + distances[0][pos])

        keyword_score = bm25_scores[idx]

        # Hybrid scoring
        hybrid_score = 0.6 * embed_score + 0.4 * keyword_score

        ranked_chunks.append((all_chunks[idx], hybrid_score))

    # -------------------------------------------------
    # 8️⃣ Sort and Build Context
    # -------------------------------------------------
    ranked_chunks = sorted(ranked_chunks, key=lambda x: x[1], reverse=True)

    context = ""
    for chunk, score in ranked_chunks[:k]:
        context += chunk + "\n\n"

    context = context[:max_chars]

    print("🔥 Hybrid Retrieved Context Preview:\n", context)

    return context


def add_to_rag(college_id, new_text):
    import os
    import pickle
    import faiss
    import numpy as np

    pkl_path = os.path.join(VECTOR_DIR, f"{college_id}.pkl")
    index_path = os.path.join(VECTOR_DIR, f"{college_id}.index")

    # -------- Load existing chunks --------
    if os.path.exists(pkl_path):
        with open(pkl_path, "rb") as f:
            chunks = pickle.load(f)
    else:
        chunks = []

    # -------- Avoid duplicates --------
    if new_text[:200] in " ".join(chunks):
        print("⚠️ Already exists in RAG")
        return

    # -------- Add new chunk --------
    chunks.append(new_text)

    with open(pkl_path, "wb") as f:
        pickle.dump(chunks, f)

    # -------- Update FAISS --------
    model = get_embed_model()

    new_embedding = model.encode(
        [new_text],
        normalize_embeddings=True
    ).astype("float32")

    if os.path.exists(index_path):
        index = faiss.read_index(index_path)
        index.add(new_embedding)
    else:
        dim = new_embedding.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(new_embedding)

    faiss.write_index(index, index_path)

    print("✅ Added new content to RAG")