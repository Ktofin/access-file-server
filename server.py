# server.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Dict, List
import uvicorn
import uuid
import os
from datetime import datetime
import json

app = FastAPI(title="Access File Transfer Server")

# Папка для сохранения файлов
uploaded_files_dir = "uploaded_files"
os.makedirs(uploaded_files_dir, exist_ok=True)

# Хранилища в памяти
pending_commands: Dict[str, List[dict]] = {}     # команды для клиентов
client_files: Dict[str, List[dict]] = {}         # списки файлов от клиентов
uploaded_files_metadata: List[dict] = []         # метаданные загруженных файлов
clients_registry: Dict[str, dict] = {}           # client_id → {ip, vnc_port, vnc_status, last_seen}

# Модели
class ScanCommand(BaseModel):
    client_id: str

class UploadCommand(BaseModel):
    client_id: str
    filepath: str

class CommandResponse(BaseModel):
    command_id: str
    type: str
    status: str

class ClientStatus(BaseModel):
    client_id: str
    ip: str
    vnc_port: int
    vnc_status: str  # "running" / "stopped"

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

        if client_id in pending_commands:
            for cmd in pending_commands[client_id]:
                if cmd["type"] == "scan" and cmd["status"] == "pending":
                    cmd["status"] = "completed"
                    cmd["completed_at"] = datetime.now().isoformat()
                    cmd["file_count"] = len(files_list)
                    break

        print(f"[+] Клиент {client_id} прислал {len(files_list)} файлов")
        return {"status": "success", "count": len(files_list)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

# 5. Получить список файлов клиента
@app.get("/client/{client_id}/files")
async def get_client_files(client_id: str):
    return {"client_id": client_id, "files": client_files.get(client_id, [])}

# 6. API: получить список всех клиентов (с IP и статусом VNC)
@app.get("/api/clients")
async def get_all_clients():
    return {"clients": clients_registry}

# 7. Клиент отправляет свой IP и статус VNC
@app.post("/client/status")
async def receive_client_status(status: ClientStatus):
    clients_registry[status.client_id] = {
        "ip": status.ip,
        "vnc_port": status.vnc_port,
        "vnc_status": status.vnc_status,
        "last_seen": datetime.now().isoformat()
    }
    return {"status": "ok"}

# 8. API: получить список загруженных файлов
@app.get("/api/downloaded-files")
async def get_downloaded_files():
    return {"files": uploaded_files_metadata}

# 9. Загрузка файла от клиента
@app.post("/upload/")
async def upload_file(
    command_id: str = Form(...),
    client_id: str = Form(...),
    file: UploadFile = File(...)
):
    commands = pending_commands.get(client_id, [])
    command = next((c for c in commands if c["command_id"] == command_id), None)

    if not command:
        raise HTTPException(status_code=404, detail="Command not found")

    safe_filename = file.filename.replace("/", "_").replace("\\", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(uploaded_files_dir, f"{client_id}_{timestamp}_{safe_filename}")

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    command["status"] = "completed"
    command["saved_as"] = save_path
    command["filename"] = file.filename
    command["size"] = len(content)
    command["completed_at"] = datetime.now().isoformat()

    uploaded_files_metadata.append({
        "command_id": command_id,
        "client_id": client_id,
        "filename": file.filename,
        "saved_path": save_path,
        "size": len(content),
        "uploaded_at": command["completed_at"]
    })

    print(f"[+] Файл сохранён: {save_path}")
    return {
        "status": "success",
        "command_id": command_id,
        "message": "Файл успешно загружен на сервер"
    }

# 10. Скачать файл
@app.get("/download/{command_id}")
async def download_file(command_id: str):
    file_record = next((f for f in uploaded_files_metadata if f["command_id"] == command_id), None)

    if not file_record or not os.path.exists(file_record["saved_path"]):
        raise HTTPException(status_code=404, detail="Файл не найден")

    return FileResponse(
        path=file_record["saved_path"],
        filename=file_record["filename"],
        media_type="application/octet-stream"
    )

# 11. Главная страница
@app.get("/", response_class=HTMLResponse)
async def main_page():
    return """
    <html>
        <head><title>📁 Access File Transfer</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #f5f5f5; }
            .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            input, button { padding: 10px; font-size: 16px; margin: 5px; }
            .section { margin-top: 40px; }
            .file-item { padding: 15px; border: 1px solid #eee; margin: 10px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
            .file-info { flex: 1; }
            .file-name { font-weight: bold; word-break: break-all; }
            .file-meta { color: #666; font-size: 14px; }
            .btn { padding: 8px 15px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; }
            .btn:hover { background: #218838; }
            .btn-upload { background: #007bff; }
            .btn-upload:hover { background: #0056b3; }
            .vnc-ok { color: green; }
            .vnc-down { color: red; }
        </style>
        </head>
        <body>
            <div class="container">
                <h1>📁 Access File Transfer</h1>
                <div>
                    <input type="text" id="clientId" placeholder="ID клиента (например: client_office_01)" value="client_office_01" />
                    <button onclick="scanFiles()">🔍 Запросить список файлов Access</button>
                </div>

                <div id="clientsInfo" class="section"></div>
                <div id="filesContainer" class="section"></div>

                <div class="section">
                    <h3>⬇️ Загруженные файлы</h3>
                    <div id="downloadedFilesContainer">
                        <p>Здесь появятся файлы после загрузки.</p>
                    </div>
                </div>
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
                    alert('✅ Команда сканирования отправлена: ' + data.command_id);
                    loadFiles();
                }

                async function loadClientsInfo() {
                    const clientId = document.getElementById('clientId').value;
                    const res = await fetch('/api/clients');
                    const allClients = await res.json();
                    const clientData = allClients.clients[clientId];
                    const container = document.getElementById('clientsInfo');

                    if (clientData) {
                        const vncStatus = clientData.vnc_status === "running" 
                            ? '<span class="vnc-ok">✅ VNC работает</span>' 
                            : '<span class="vnc-down">❌ VNC не отвечает</span>';
                        container.innerHTML = `
                            <h3>📡 Информация о клиенте: ${clientId}</h3>
                            <p><strong>IP:</strong> ${clientData.ip} | <strong>Порт VNC:</strong> ${clientData.vnc_port}</p>
                            <p>${vncStatus}</p>
                            <button class="btn btn-upload" onclick="connectVNC('${clientData.ip}', ${clientData.vnc_port})">
                                🖥️ Подключиться по VNC
                            </button>
                        `;
                    } else {
                        container.innerHTML = `
                            <h3>📡 Информация о клиенте: ${clientId}</h3>
                            <p>Клиент ещё не отправил свой IP. Убедитесь, что клиент запущен.</p>
                        `;
                    }
                }

                function connectVNC(ip, port) {
                    window.location.href = 'vnc://' + ip + ':' + port;
                }

                async function loadFiles() {
                    const clientId = document.getElementById('clientId').value;
                    const res = await fetch('/client/' + clientId + '/files');
                    const data = await res.json();

                    const container = document.getElementById('filesContainer');
                    container.innerHTML = `
                        <h3>📁 Файлы клиента: ${clientId}</h3>
                        ${data.files.length ? data.files.map(f => `
                            <div class="file-item">
                                <div class="file-info">
                                    <div class="file-name">${f.filepath}</div>
                                    <div class="file-meta">Найден: ${new Date(f.reported_at).toLocaleString()}</div>
                                </div>
                                <button class="btn btn-upload" onclick="uploadFile('${clientId}', '${encodeURIComponent(f.filepath)}')">📤 Загрузить на сервер</button>
                            </div>
                        `).join('') : '<p>Файлов пока нет. Нажмите "Запросить", если ещё не делали.</p>'}
                    `;
                }

                async function uploadFile(clientId, filepath) {
                    if (!confirm("Вы уверены, что хотите загрузить этот файл на сервер?")) return;

                    const res = await fetch('/command/upload', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId, filepath: decodeURIComponent(filepath)})
                    });
                    const data = await res.json();
                    alert(data.message || "Команда загрузки создана.");
                    loadDownloadedFiles();
                }

                async function loadDownloadedFiles() {
                    const res = await fetch('/api/downloaded-files');
                    const data = await res.json();

                    const container = document.getElementById('downloadedFilesContainer');
                    container.innerHTML = `
                        ${data.files.length ? data.files.map(f => `
                            <div class="file-item">
                                <div class="file-info">
                                    <div class="file-name">${f.filename} (${(f.size / 1024).toFixed(1)} КБ)</div>
                                    <div class="file-meta">Клиент: ${f.client_id} | ${new Date(f.uploaded_at).toLocaleString()}</div>
                                </div>
                                <button class="btn" onclick="location.href='/download/${f.command_id}'">⬇️ Скачать на компьютер</button>
                            </div>
                        `).join('') : '<p>Нет загруженных файлов.</p>'}
                    `;
                }

                // Загружаем при открытии
                loadClientsInfo();
                loadFiles();
                loadDownloadedFiles();

                // Автообновление каждые 10 сек
                setInterval(() => {
                    loadClientsInfo();
                    loadFiles();
                    loadDownloadedFiles();
                }, 10000);
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)