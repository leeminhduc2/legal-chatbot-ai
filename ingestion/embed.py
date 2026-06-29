"""
Embedding files with chromadb with given json files in data/chunked folder
"""
import json
from typing import Dict, Any
import chromadb
from pathlib import Path
import uuid
from FlagEmbedding import BGEM3FlagModel
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import torch

# 1. Tạo "bộ chuyển đổi" (Wrapper Class) cho bge-m3
class BGEM3CustomEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = 'BAAI/bge-m3', use_fp16: bool = True):
        # Khởi tạo mô hình bên trong wrapper
        self.model = BGEM3FlagModel(model_name, use_fp16=use_fp16)

    def __call__(self, input: Documents) -> Embeddings:
        # Mã hóa đầu vào
        # Chỉ lấy return_dense=True vì ChromaDB chủ yếu dùng dense vectors để tính toán KNN
        output = self.model.encode(
            input, 
            return_dense=True, 
            return_sparse=False, 
            return_colbert_vecs=False
        )
        
        # Lấy mảng dense_vecs (numpy array) và chuyển thành list of lists (List[List[float]])
        embeddings = torch.nn.functional.normalize(output['dense_vecs']).tolist()
        return embeddings

    @staticmethod
    def name() -> str:
        return "my-ef"

    def get_config(self) -> Dict[str, Any]:
        return dict(model=self.model)

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "EmbeddingFunction":
        return BGEM3CustomEmbeddingFunction(config['model'])


def embed_json_file(file_path: str | Path):
    """Read json file that contains chunks and save them into ChromaDB."""
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"[ERROR] File not found: {file_path}")
        return
        
    print(f"Read file: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)
        
    print(f"Đã lấy được {len(chunks)} chunks. Đang lưu vào ChromaDB...")
    
    def sanitize_metadata(meta):
        sanitized = {}
        for k, v in meta.items():
            if v is None:
                continue
            if isinstance(v, list): ## Temporarily ignore list items
                continue
            else:
                sanitized[k] = v
        return sanitized

    # Trích xuất dữ liệu thành các mảng song song và làm sạch metadata
    documents = [chunk["content"] for chunk in chunks]
    metadatas = [sanitize_metadata(chunk["metadata"]) for chunk in chunks]
    
    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
    out_embeddings = model.encode(documents, batch_size=12)
    
    # Trích xuất vector chuẩn (dense) và chuyển thành list cho ChromaDB
    dense_embeddings = out_embeddings['dense_vecs'].tolist()
    
    # Lưu vào ChromaDB theo từng batch (vd: 100 chunks mỗi batch) để tăng tốc độ
    batch_size = 1000
    for i in range(0, len(chunks), batch_size):
        end = min(i + batch_size, len(chunks))
        collection.add(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=[str(uuid.uuid4()) for _ in range(i, end)],    
        )
        print(f"  - Saved {end}/{len(chunks)} chunks...")
        
    print("Done!")

if __name__ == "__main__":
    # Khởi tạo client một lần để tái sử dụng
    client = chromadb.PersistentClient(path="data/chroma/chroma_db2")
    collection = client.get_or_create_collection(name="legal-texts_tt74",embedding_function=BGEM3CustomEmbeddingFunction(model_name = 'BAAI/bge-m3', use_fp16=True))
    # Chỉ định đường dẫn tới file JSON bạn muốn đọc
    target_file = Path("data\chunked\TT 74.2026_BTC.json")
    embed_json_file(target_file)
    # Query the database (for testing purpose)
    results = collection.query(
        query_texts=[
            "Cơ quan có thẩm quyền sẽ cấp những chứng chỉ gì liên quan đến lĩnh vực năng lực nguyên tử ?"
        ],
        n_results=10
    )

    for i, query_results in enumerate(results["documents"]):
        print(f"Query {i+1}:")
        for j, doc in enumerate(query_results):
            print(f"  {j+1}. {doc}")
            print(f"     {results['distances'][i][j]}")
        print()