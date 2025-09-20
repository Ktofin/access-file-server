# server.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse  # ← ЭТОТ ИМПОРТ БЫЛ ПРОПУЩЕН!
from pydantic import BaseModel
from typing import Dict, List
import uvicorn
import uuid
import os
from datetime import datetime
import json

app = FastAPI(title="Access File Transfer Server")

# Хранилища в памяти (в продакшене — Redis или БД)
pending_commands: Dict[str, List[dict]] = {}
client_files: Dict[str, List[dict]] = {}
uploaded_files_dir = "uploaded_files"

os.makedirs(uploaded_files_dir, exist_ok=True)

class ScanCommand(BaseModel):
    client_id: str

class UploadCommand(BaseModel):
    client_id: str
    filepath: str

class CommandResponse(BaseModel):
    command_id: str
    type: str
    status: str

# 1. Запросить сканирование файлов
@app.post("/command/scan", response_model=CommandResponse)
async def create_scan_command(cmd: ScanCommand):
    command_id = str(uuid.uuid4())
    new_command = {
        "command_id": command_id,
        "type": "scan",
        "status": "pending"
    }
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    print(f"[+] SCAN команда для {cmd.client_id}: {command_id}")
    return CommandResponse(command_id=command_id, type="scan", status="pending")

# 2. Запросить загрузку файла
@app.post("/command/upload", response_model=CommandResponse)
async def create_upload_command(cmd: UploadCommand):
    command_id = str(uuid.uuid4())
    new_command = {
        "command_id": command_id,
        "type": "upload",
        "filepath": cmd.filepath,
        "status": "pending"
    }
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    print(f"[+] UPLOAD команда для {cmd.client_id}: {cmd.filepath}")
    return CommandResponse(command_id=command_id, type="upload", status="pending")

# 3. Получить команды для клиента
@app.get("/commands/{client_id}")
async def get_commands(client_id: str):
    commands = pending_commands.get(client_id, [])
    pending = [cmd for cmd in commands if cmd["status"] == "pending"]
    return {"commands": pending}

# 4. Клиент отправляет список найденных файлов
@app.post("/files/report")
async def report_files(client_id: str = Form(...), files_json: str = Form(...)):
    try:
        files_list = json.loads(files_json)
        client_files[client_id] = [
            {"filepath": f, "reported_at": datetime.now().isoformat()} for f in files_list
        ]
        print(f"[+] Клиент {client_id} прислал {len(files_list)} файлов")
        return {"status": "success", "count": len(files_list)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

# 5. Получить список файлов клиента для веб-интерфейса
@app.get("/client/{client_id}/files")
async def get_client_files(client_id: str):
    return {"client_id": client_id, "files": client_files.get(client_id, [])}

# 6. Загрузка файла от клиента
@app.post("/upload/")
async def upload_file(command_id: str = Form(...), client_id: str = Form(...), file: UploadFile = File(...)):
    commands = pending_commands.get(client_id, [])
    command = next((c for c in commands if c["command_id"] == command_id), None)
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")

    safe_filename = file.filename.replace("/", "_").replace("\\", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(uploaded_files_dir, f"{client_id}_{timestamp}_{safe_filename}")

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    command["status"] = "completed"
    command["saved_as"] = save_path

    print(f"[+] Файл от {client_id} сохранён: {save_path}")
    return {"status": "success", "saved_as": save_path}

# 7. Главная страница — веб-интерфейс
@app.get("/", response_class=HTMLResponse)
async def main_page():
    return """
    <html>
        <head><title>📁 Access File Transfer</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            input, button { padding: 10px; font-size: 16px; margin: 5px; }
            .file-list { margin-top: 30px; }
            .file-item { padding: 15px; border: 1px solid #eee; margin: 10px 0; border-radius: 5px; }
            .file-path { font-weight: bold; word-break: break-all; }
            .status { color: #666; font-size: 14px; }
        </style>
        </head>
        <body>
            <div class="container">
                <h1>📁 Access File Transfer</h1>
                <div>
                    <input type="text" id="clientId" placeholder="ID клиента (например: client_office_01)" value="client_office_01" />
                    <button onclick="scanFiles()">🔍 Запросить список файлов Access</button>
                </div>
                <div id="filesContainer" class="file-list"></div>
            </div>

            <script>
                async function scanFiles() {
                    const clientId = document.getElementById('clientId').value;
                    const res = await fetch('/command/scan', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId})
                    });
                    const data = await res.json();
                    alert('Команда отправлена: ' + data.command_id);
                    loadFiles();
                }

                async function loadFiles() {
                    const clientId = document.getElementById('clientId').value;
                    const res = await fetch('/client/' + clientId + '/files');
                    const data = await res.json();

                    const container = document.getElementById('filesContainer');
                    container.innerHTML = `
                        <h3>Файлы клиента: ${clientId}</h3>
                        ${data.files.length ? data.files.map(f => `
                            <div class="file-item">
                                <div class="file-path">${f.filepath}</div>
                                <div class="status">Найден: ${new Date(f.reported_at).toLocaleString()}</div>
                                <button onclick="uploadFile('${clientId}', '${encodeURIComponent(f.filepath)}')">⬇️ Загрузить</button>
                            </div>
                        `).join('') : '<p>Файлов пока нет. Нажмите "Запросить", если ещё не делали.</p>'}
                    `;
                }

                async function uploadFile(clientId, filepath) {
                    const res = await fetch('/command/upload', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId, filepath: decodeURIComponent(filepath)})
                    });
                    const data = await res.json();
                    alert('Команда загрузки отправлена: ' + data.command_id);
                }

                // Автообновление каждые 5 сек
                setInterval(loadFiles, 5000);
                // Загрузить сразу при открытии
                loadFiles();
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)