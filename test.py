from src.retrieval.retrieval import retrieve_from_knowledge_graph

# Sử dụng đơn giản
result = retrieve_from_knowledge_graph("Nhân dân có vai trò gì?")
print(result["cypher"])     # Cypher query đã sinh
print(result["results"])    # Kết quả từ Neo4j
print(result["error"])      # None nếu thành công

# # Hoặc sử dụng class trực tiếp để tùy chỉnh
# from src.retrieval.retrieval import KnowledgeGraphRetriever

# retriever = KnowledgeGraphRetriever(
#     neo4j_uri="bolt://my-server:7687",
#     llm_model="deepseek-chat",
#     max_retries=3,
# )
# result = retriever.retrieve("Văn bản nào sửa đổi Luật BHXH?")
# retriever.close()
