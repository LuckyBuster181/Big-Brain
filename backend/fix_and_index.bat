@echo off
cd /d "C:\Users\maxi1\Documents\KI\Jarvis\backend"
echo ==== %DATE% %TIME% ==== > run_log.txt
echo --- python --version --- >> run_log.txt
call venv\Scripts\activate.bat
python --version >> run_log.txt 2>&1
echo. >> run_log.txt
echo --- pip show chromadb (vorher) --- >> run_log.txt
pip show chromadb >> run_log.txt 2>&1
echo. >> run_log.txt
echo --- pip install --force-reinstall --no-cache-dir chromadb --- >> run_log.txt
pip install --force-reinstall --no-cache-dir chromadb >> run_log.txt 2>&1
echo. >> run_log.txt
echo --- python -m rag.embeddings --- >> run_log.txt
python -m rag.embeddings >> run_log.txt 2>&1
echo. >> run_log.txt
echo ==== FERTIG ==== >> run_log.txt
notepad run_log.txt
