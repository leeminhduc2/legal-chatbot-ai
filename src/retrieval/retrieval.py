"""
Knowledge Graph Retrieval Module

Chuyển đổi câu hỏi tự nhiên (tiếng Việt) thành Cypher query
và truy vấn Neo4j Knowledge Graph pháp luật.
"""

import os
import re
import logging
from typing import Optional
from pathlib import Path
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Tải biến môi trường
load_dotenv()

logger = logging.getLogger(__name__)

# ==============================================================================
# Danh sách các keyword Cypher chỉ đọc (whitelist)
# ==============================================================================
_READ_ONLY_KEYWORDS = {
    "MATCH", "OPTIONAL", "RETURN", "WHERE", "WITH", "ORDER", "BY",
    "LIMIT", "SKIP", "UNWIND", "COLLECT", "COUNT", "DISTINCT",
    "AS", "AND", "OR", "NOT", "IN", "IS", "NULL", "CONTAINS",
    "STARTS", "ENDS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "EXISTS", "CALL", "YIELD", "UNION", "ALL",
}

# Các keyword ghi (write) PHẢI bị chặn
_WRITE_KEYWORDS = {"CREATE", "DELETE", "DETACH", "SET", "MERGE", "REMOVE", "DROP"}


class KnowledgeGraphRetriever:
    """Truy vấn Neo4j Knowledge Graph bằng cách chuyển đổi text → Cypher qua LLM."""

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_base_url: str = "https://api.deepseek.com/v1",
        llm_model: str = "deepseek-v4-pro",
        max_retries: int = 2,
    ):
        # --- Neo4j config ---
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD", "")

        # --- LLM config ---
        api_key = llm_api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY chưa được cấu hình trong .env hoặc environment variables."
            )
        self.llm_client = OpenAI(api_key=api_key, base_url=llm_base_url)
        self.llm_model = llm_model
        self.max_retries = max_retries

        # --- Prompt template ---
        prompt_path = Path("prompts/text2cypher_prompt.txt")
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt template không tìm thấy tại {prompt_path}"
            )
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

        # --- Neo4j driver (lazy init) ---
        self._driver = None

    # ==========================================================================
    # Neo4j Connection
    # ==========================================================================

    def _get_driver(self):
        """Lazy-init Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password),
            )
            # Verify connectivity on first use
            self._driver.verify_connectivity()
            logger.info("Kết nối Neo4j thành công: %s", self.neo4j_uri)
        return self._driver

    def close(self):
        """Đóng kết nối Neo4j."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    # ==========================================================================
    # Schema Introspection – Đọc data model trực tiếp từ Neo4j
    # ==========================================================================

    def _get_graph_schema(self) -> str:
        """
        Đọc schema từ Neo4j database bao gồm:
        - Node labels và properties
        - Relationship types và properties
        - Sample data patterns

        Trả về chuỗi mô tả schema dạng human-readable để inject vào prompt.
        """
        driver = self._get_driver()

        schema_parts = []

        with driver.session() as session:
            # --- 1. Node labels và properties ---
            schema_parts.append("### Node Labels và Properties:")
            try:
                result = session.run("CALL db.schema.nodeTypeProperties()")
                node_props = {}
                for record in result:
                    label = record.get("nodeType", "")
                    # nodeType format: ":`Label`" → extract label name
                    label = label.strip(":` ")
                    prop = record.get("propertyName", "")
                    prop_type = record.get("propertyTypes", ["Unknown"])

                    if label not in node_props:
                        node_props[label] = []
                    type_str = prop_type[0] if isinstance(prop_type, list) and prop_type else str(prop_type)
                    node_props[label].append(f"{prop} ({type_str})")

                for label, props in node_props.items():
                    schema_parts.append(f"- (:{label})")
                    schema_parts.append(f"  Properties: {', '.join(props)}")
            except Exception as e:
                logger.warning("Không thể đọc node properties: %s. Thử phương pháp thay thế.", e)
                # Fallback: dùng db.labels()
                result = session.run("CALL db.labels()")
                labels = [record["label"] for record in result]
                for label in labels:
                    schema_parts.append(f"- (:{label})")
                    # Lấy sample properties từ 1 node
                    sample = session.run(
                        f"MATCH (n:`{label}`) RETURN keys(n) AS props LIMIT 1"
                    )
                    sample_record = sample.single()
                    if sample_record:
                        props = sample_record["props"]
                        schema_parts.append(f"  Properties: {', '.join(props)}")

            # --- 2. Relationship types và properties ---
            schema_parts.append("\n### Relationship Types:")
            try:
                result = session.run("CALL db.schema.relTypeProperties()")
                rel_props = {}
                for record in result:
                    rel_type = record.get("relType", "")
                    rel_type = rel_type.strip(":` ")
                    prop = record.get("propertyName", "")
                    prop_type = record.get("propertyTypes", ["Unknown"])

                    if rel_type not in rel_props:
                        rel_props[rel_type] = []
                    if prop:  # Relationship có thể không có properties
                        type_str = prop_type[0] if isinstance(prop_type, list) and prop_type else str(prop_type)
                        rel_props[rel_type].append(f"{prop} ({type_str})")

                for rel_type, props in rel_props.items():
                    if props:
                        schema_parts.append(f"- [:{rel_type}] — Properties: {', '.join(props)}")
                    else:
                        schema_parts.append(f"- [:{rel_type}]")
            except Exception as e:
                logger.warning("Không thể đọc relationship properties: %s. Thử phương pháp thay thế.", e)
                result = session.run("CALL db.relationshipTypes()")
                rel_types = [record["relationshipType"] for record in result]
                for rel_type in rel_types:
                    schema_parts.append(f"- [:{rel_type}]")

            # --- 3. Relationship patterns (node → rel → node) ---
            schema_parts.append("\n### Relationship Patterns (Node → Relationship → Node):")
            try:
                result = session.run(
                    """
                    CALL db.schema.visualization() YIELD nodes, relationships
                    UNWIND relationships AS rel
                    RETURN
                        [label IN labels(startNode(rel)) | label][0] AS from_label,
                        type(rel) AS rel_type,
                        [label IN labels(endNode(rel)) | label][0] AS to_label
                    """
                )
                for record in result:
                    from_l = record["from_label"]
                    rel_t = record["rel_type"]
                    to_l = record["to_label"]
                    schema_parts.append(f"- (:{from_l})-[:{rel_t}]->(:{to_l})")
            except Exception as e:
                logger.warning("Không thể đọc relationship patterns: %s", e)
                # Fallback: lấy sample patterns từ database
                try:
                    result = session.run(
                        """
                        MATCH (a)-[r]->(b)
                        WITH labels(a)[0] AS from_label, type(r) AS rel_type, labels(b)[0] AS to_label
                        RETURN DISTINCT from_label, rel_type, to_label
                        LIMIT 50
                        """
                    )
                    for record in result:
                        from_l = record["from_label"]
                        rel_t = record["rel_type"]
                        to_l = record["to_label"]
                        schema_parts.append(f"- (:{from_l})-[:{rel_t}]->(:{to_l})")
                except Exception as e2:
                    logger.warning("Fallback relationship pattern query cũng thất bại: %s", e2)

        return "\n".join(schema_parts)

    # ==========================================================================
    # Cypher Generation – LLM chuyển đổi text → Cypher
    # ==========================================================================

    def _generate_cypher(self, question: str, schema: str, error_context: Optional[str] = None) -> str:
        """
        Gọi DeepSeek LLM để chuyển câu hỏi tự nhiên thành Cypher query.

        Args:
            question: Câu hỏi của người dùng (tiếng Việt).
            schema: Mô tả graph schema (đọc động từ Neo4j).
            error_context: Nếu đang retry, chứa thông tin lỗi trước đó để LLM sửa.

        Returns:
            Cypher query string.
        """
        prompt = self.prompt_template.replace("{schema}", schema).replace("{question}", question)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Neo4j Cypher expert. Generate ONLY valid, read-only Cypher queries. "
                    "Output ONLY the Cypher query inside a ```cypher``` code block."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        # Nếu retry: thêm context lỗi để LLM sửa
        if error_context:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Cypher query trước đó bị lỗi khi chạy trên Neo4j:\n"
                        f"```\n{error_context}\n```\n"
                        f"Hãy sửa lại query cho đúng cú pháp và chỉ trả về Cypher."
                    ),
                }
            )

        response = self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=messages,
            temperature=0,  # Giảm randomness để Cypher chính xác hơn
        )

        raw_output = response.choices[0].message.content
        return self._extract_cypher(raw_output)

    @staticmethod
    def _extract_cypher(llm_output: str) -> str:
        """Trích xuất Cypher query từ response của LLM."""
        # Tìm code block ```cypher ... ```
        match = re.search(r"```cypher\s*(.*?)\s*```", llm_output, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: tìm bất kỳ code block nào
        match = re.search(r"```\s*(.*?)\s*```", llm_output, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback cuối: lấy toàn bộ text (loại bỏ dòng trống đầu/cuối)
        return llm_output.strip()

    # ==========================================================================
    # Cypher Validation – Chỉ cho phép read-only queries
    # ==========================================================================

    @staticmethod
    def _validate_cypher(cypher: str) -> tuple[bool, str]:
        """
        Kiểm tra Cypher query chỉ chứa read-only operations.

        Returns:
            (is_valid, error_message)
        """
        if not cypher:
            return False, "Cypher query rỗng."

        # Loại bỏ string literals để tránh false positive
        # (vd: WHERE n.name CONTAINS 'DELETE')
        sanitized = re.sub(r"'[^']*'", "", cypher)
        sanitized = re.sub(r'"[^"]*"', "", sanitized)

        # Kiểm tra write keywords
        tokens = re.findall(r"[A-Z]+", sanitized.upper())
        for token in tokens:
            if token in _WRITE_KEYWORDS:
                return False, f"Phát hiện write operation không được phép: {token}"

        # Kiểm tra cơ bản: phải có MATCH hoặc CALL
        upper = sanitized.upper()
        if "MATCH" not in upper and "CALL" not in upper:
            return False, "Query phải bắt đầu bằng MATCH hoặc CALL."

        return True, ""

    # ==========================================================================
    # Cypher Execution – Chạy query trên Neo4j
    # ==========================================================================

    def _execute_cypher(self, cypher: str) -> list[dict]:
        """
        Thực thi Cypher query trên Neo4j và trả về kết quả.

        Args:
            cypher: Cypher query đã được validate.

        Returns:
            Danh sách dict, mỗi dict là một record kết quả.
        """
        driver = self._get_driver()

        with driver.session() as session:
            result = session.run(cypher)
            records = []
            for record in result:
                records.append(dict(record))
            return records

    # ==========================================================================
    # Main Entry Point
    # ==========================================================================

    def retrieve(self, prompt: str) -> dict:
        """
        Pipeline chính: chuyển prompt → Cypher → truy vấn Neo4j → trả kết quả.

        Args:
            prompt: Câu hỏi tự nhiên của người dùng (tiếng Việt).

        Returns:
            dict chứa:
            - "cypher": Cypher query đã sinh
            - "results": Danh sách kết quả từ Neo4j
            - "error": Thông tin lỗi (nếu có)
        """
        logger.info("Bắt đầu retrieve từ Knowledge Graph: %s", prompt)

        # 1. Đọc schema động từ Neo4j
        try:
            schema = self._get_graph_schema()
            logger.info("Đã đọc graph schema thành công.")
        except Exception as e:
            logger.error("Không thể đọc graph schema: %s", e)
            return {
                "cypher": None,
                "results": [],
                "error": f"Không thể kết nối Neo4j để đọc schema: {e}",
            }

        # 2. Sinh Cypher qua LLM + retry loop
        cypher = None
        error_context = None
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # 2a. Gọi LLM sinh Cypher
                cypher = self._generate_cypher(
                    question=prompt,
                    schema=schema,
                    error_context=error_context,
                )
                logger.info("Attempt %d — Cypher sinh ra:\n%s", attempt, cypher)

                # 2b. Validate
                is_valid, validation_error = self._validate_cypher(cypher)
                if not is_valid:
                    logger.warning("Cypher validation thất bại: %s", validation_error)
                    error_context = f"Validation error: {validation_error}\nQuery: {cypher}"
                    last_error = validation_error
                    continue

                # 2c. Execute
                results = self._execute_cypher(cypher)
                logger.info("Truy vấn thành công, %d kết quả.", len(results))

                return {
                    "cypher": cypher,
                    "results": results,
                    "error": None,
                }

            except Exception as e:
                logger.warning("Attempt %d thất bại: %s", attempt, e)
                error_context = f"Neo4j error: {e}\nQuery: {cypher}"
                last_error = str(e)

        # Hết retry
        return {
            "cypher": cypher,
            "results": [],
            "error": f"Thất bại sau {self.max_retries} lần thử. Lỗi cuối: {last_error}",
        }


# ==============================================================================
# Convenience function (backward-compatible API)
# ==============================================================================

# Module-level retriever instance (lazy-initialized)
_retriever: Optional[KnowledgeGraphRetriever] = None


def retrieve_from_knowledge_graph(prompt: str) -> dict:
    """
    Hàm tiện ích để truy vấn Knowledge Graph.

    Tự động khởi tạo KnowledgeGraphRetriever từ biến môi trường trong .env.
    Chuyển câu hỏi tự nhiên thành Cypher, truy vấn Neo4j, trả kết quả.

    Args:
        prompt: Câu hỏi tự nhiên (tiếng Việt).

    Returns:
        dict:
            - "cypher": Câu lệnh Cypher đã sinh
            - "results": Danh sách kết quả (list[dict])
            - "error": Thông tin lỗi (None nếu thành công)

    Example:
        >>> result = retrieve_from_knowledge_graph("Điều 5 Luật BHXH 2024 quy định gì?")
        >>> print(result["cypher"])
        MATCH (a:Article)<-[:HAS_ARTICLE]-(d:Document)
        WHERE a.name CONTAINS 'Điều 5' AND d.name CONTAINS 'BHXH 2024'
        RETURN a.name, a.content, d.name AS document_name
        LIMIT 10
        >>> print(result["results"])
        [{"a.name": "Điều 5. ...", "a.content": "...", "document_name": "Luật BHXH 2024"}]
    """
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeGraphRetriever()
    return _retriever.retrieve(prompt)
