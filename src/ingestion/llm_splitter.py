import os
import json
import re
from typing import List, Dict, Any
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Tải biến môi trường từ file .env
load_dotenv()

class LLMVietnameseLegalSplitter:
    def __init__(self, doc_name: str):
        self.doc_name = doc_name
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set in .env file or environment variables.")
        
        # Cấu hình client OpenAI để gọi DeepSeek API
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com/v1"
        )
        
        # Đọc prompt template
        prompt_path = Path("prompts/chunking_prompt.txt")
        if not prompt_path.exists():
            raise FileNotFoundError(f"Chunking prompt template not found at {prompt_path}")
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def clean_id(self, text: str) -> str:
        if not text:
            return ""
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^a-zA-Z0-9_]', '_', text.lower())
        return re.sub(r'_+', '_', text).strip('_')

    def extract_json_from_response(self, response_text: str) -> List[Dict]:
        """Trích xuất mảng JSON từ phản hồi của LLM."""
        try:
            # Cố gắng tìm phần JSON giữa các ký tự ```json và ```
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Fallback: cố gắng tìm mảng JSON trực tiếp
                json_match = re.search(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            return json.loads(json_str)
        except Exception as e:
            print(f"Error parsing JSON from LLM response: {e}")
            print(f"Raw response: {response_text}")
            return []

    def _batch_split(self, text: str) -> List[Dict]:
        """
        Chia text thành các batch để tránh vượt quá context window.
        
        """
        max_chars_per_batch = 10000 # 
        chunks = []
        
        # Tách text thành các đoạn dựa trên regex cơ bản (vd: Chương/Điều) để tránh cắt giữa câu
        # Giữ lại các chỉ số (index) để sau này đối chiếu
        split_points = [0]
        # Tìm các vị trí bắt đầu của "Điều" để làm điểm cắt an toàn
        for match in re.finditer(r'\n(?=Điều\s+\d+)', text):
            if match.start() - split_points[-1] > max_chars_per_batch:
                split_points.append(match.start())
        
        if split_points[-1] != len(text):
            split_points.append(len(text))

        

        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i+1]
            batch_text = text[start:end]

            # Write down batch text in log folder (temporarily)
            with open(f"log/{self.doc_name}_batch_{i}.md", "w", encoding="utf-8") as f:
                f.write(batch_text)
            
            print(f"  Sending batch {i+1}/{len(split_points)-1} to LLM (chars: {len(batch_text)})...")
            
            prompt = self.prompt_template.replace("{text}", batch_text)
            
            try:
                response = self.client.chat.completions.create(
                    model="deepseek-v4-flash", # Sử dụng deepseek-chat cho v4
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that strictly outputs JSON arrays according to instructions."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={ "type": "json_object" } # Khuyến khích model trả về JSON hợp lệ nếu có
                )
                
                llm_output = response.choices[0].message.content
                batch_chunks_info = self.extract_json_from_response(llm_output)
                
                # Ánh xạ lại chỉ mục và tạo chunk objects
                for info in batch_chunks_info:
                    meta = info.get("metadata", {})
                    
                    # Content chính xác được trích xuất từ text gốc
                    full_content = info.get("content", "")
                    if not full_content:
                        continue

                    
                    
                    # Cập nhật metadata
                    meta["doc_name"] = self.doc_name
                    
                    # Tạo ID
                    article_id = self.clean_id(meta.get("article", ""))
                    clause_id = self.clean_id(meta.get("clause", ""))
                    if clause_id:
                        chunk_id = f"{self.clean_id(self.doc_name)}_{article_id}_{clause_id}"
                    else:
                        chunk_id = f"{self.clean_id(self.doc_name)}_{article_id}"
                        
                    chunks.append({
                        "content": full_content,
                        "metadata": meta
                    })
            except Exception as e:
                print(f"  Error processing batch {i+1}: {e}")
                
        return chunks

    def split_text(self, text: str) -> List[Dict[str, Any]]:
        print(f"Starting LLM chunking for {self.doc_name}...")
        return self._batch_split(text)
