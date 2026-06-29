from src.ingestion.embed import embed_json_file
from src.ingestion.ingest import process_legal_documents
from src.retrieval.retrieval import retrieve_from_knowledge_graph
import argparse
import sys
from pathlib import Path

# Important: Add the root directory to sys.path so we can import from src
# if you run into "ModuleNotFoundError"
sys.path.append(str(Path(__file__).parent))



def main():
    # 1. Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Legal Chatbot CLI"
    )
    
    # 2. Add subparsers if you plan to have multiple commands (e.g., 'ingest', 'ask')
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # --- INGEST COMMAND ---
    ingest_parser = subparsers.add_parser("ingest", help="Ingest legal documents")
    # --- EMBED COMMAND ---
    embed_parser = subparsers.add_parser("embed", help = "Embed legal documents")
    # --- GRAPH RETRIEVAL COMMAND ---
    graph_retrieval_parser = subparsers.add_parser("graph-retrieve", help = "Retrieve legal document content in knowledge graph")
    
    # Add the argument that process_legal_documents expects (document_path)
    # We use a default value like "*.docx" to process all if no specific pattern is provided
    ingest_parser.add_argument(
        "--path", 
        type=str, 
        default="*.docx", 
        help="The glob pattern or file name to ingest (e.g., '*.docx' or 'Hien phap nam 2013.docx')"
    )
    
    # Add the argument that embed_json_file expects (file_path)
    embed_parser.add_argument(
        "--path",
        type=str,
        default="*.json",
        help="The glob pattern or file name to embed (e.g., '*.json' or 'TT 74.2026_BTC.json')"
    )

    # Add the argument 
    graph_retrieval_parser.add_argument(
        "-q",
        "--query",
        type=str,
        default="Ai là người ký ?",
        help = "The question you want to ask for :D")
    
    # 3. Parse the arguments
    args = parser.parse_args()
    
    # 4. Route to the correct function based on the command
    if args.command == "ingest":
        print(f"Starting ingestion for: {args.path}")
        # Call your function here!
        process_legal_documents(document_path=args.path)
    elif args.command == "embed":
        print(f"Starting embedding for: {args.path}")
        # Call your function here!
        if (args.path == "*.json"):
            json_files = list(Path("data\\chunked").glob("*.json"))
            for json_file in json_files:
                embed_json_file(file_path=json_file)
        else:
            embed_json_file(file_path=args.path)
    elif args.command == "graph-retrieve" :
        print(f"Start retrieving information for question {args.query}")
        result = retrieve_from_knowledge_graph(args.query)
        print("Generated Cypher Query from LLM:")
        print(result["cypher"])     # Cypher query đã sinh
        print("Neo4j's returned result:")
        print(result["results"])    # Kết quả từ Neo4j
        print(f"Error code : {result["error"]}")      # None nếu thành công


        
    elif args.command is None:
        # If the user just runs `python main.py` without a command
        parser.print_help()
    else:
        print(f"Unknown command: {args.command}")

if __name__ == "__main__":
    main()
