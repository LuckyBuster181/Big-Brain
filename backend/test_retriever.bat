@echo off
cd /d "C:\Users\maxi1\Documents\KI\Jarvis\backend"
echo ==== Retriever-Test %DATE% %TIME% ==== > retriever_log.txt
call venv\Scripts\activate.bat
python -m rag.retriever "Wie werden Notizen im Vault in Chunks aufgeteilt?" --top-k 3 >> retriever_log.txt 2>&1
echo. >> retriever_log.txt
python -m rag.retriever "Was ist der aktuelle Stand des Jarvis Backends?" --top-k 3 >> retriever_log.txt 2>&1
echo. >> retriever_log.txt
echo ==== FERTIG ==== >> retriever_log.txt
notepad retriever_log.txt
