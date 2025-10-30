# server.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
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
pending_commands: Dict[str, List[dict]] = {}
client_files: Dict[str, List[dict]] = {}
uploaded_files_metadata: List[dict] = []
clients_registry: Dict[str, dict] = {}

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
    vnc_status: str
    device_type: str  # ← добавлено

# Эндпоинты
@app.post("/command/scan", response_model=CommandResponse)
async def create_scan_command(cmd: ScanCommand):
    command_id = str(uuid.uuid4())
    new_command = {"command_id": command_id, "type": "scan", "status": "pending"}
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    return CommandResponse(command_id=command_id, type="scan", status="pending")

@app.post("/command/upload", response_model=CommandResponse)
async def create_upload_command(cmd: UploadCommand):
    command_id = str(uuid.uuid4())
    new_command = {"command_id": command_id, "type": "upload", "filepath": cmd.filepath, "status": "pending"}
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    return CommandResponse(command_id=command_id, type="upload", status="pending")

@app.get("/commands/{client_id}")
async def get_commands(client_id: str):
    commands = pending_commands.get(client_id, [])
    pending = [cmd for cmd in commands if cmd["status"] == "pending"]
    return {"commands": pending}

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
                    break
        return {"status": "success", "count": len(files_list)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

@app.get("/client/{client_id}/files")
async def get_client_files(client_id: str):
    return {"client_id": client_id, "files": client_files.get(client_id, [])}

@app.get("/api/clients")
async def get_all_clients():
    return {"clients": clients_registry}

@app.post("/client/status")
async def receive_client_status(status: ClientStatus):
    clients_registry[status.client_id] = {
        "ip": status.ip,
        "vnc_port": status.vnc_port,
        "vnc_status": status.vnc_status,
        "device_type": status.device_type,
        "last_seen": datetime.now().isoformat()
    }
    return {"status": "ok"}

@app.get("/api/downloaded-files")
async def get_downloaded_files():
    return {"files": uploaded_files_metadata}

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
    return {"status": "success", "command_id": command_id, "message": "Файл успешно загружен"}

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

# Главная страница
@app.get("/", response_class=HTMLResponse)
async def main_page():
    return """
    <html>
        <head>
            <title>📁 Access File Transfer — Центр управления</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f9f9f9; }
                .container { max-width: 1000px; margin: 0 auto; }
                h1 { text-align: center; color: #2c3e50; }
                .client-card {
                    background: white;
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    padding: 16px;
                    margin: 12px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                .client-card h3 {
                    margin-top: 0;
                    color: #2980b9;
                    display: flex;
                    align-items: center;
                }
                .vnc-address {
                    background: #f1f1f1;
                    padding: 6px 10px;
                    border-radius: 4px;
                    font-family: monospace;
                    display: inline-block;
                    margin-right: 8px;
                }
                .btn {
                    padding: 6px 12px;
                    margin: 4px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                }
                .btn-primary { background: #3498db; color: white; }
                .btn-success { background: #2ecc71; color: white; }
                .btn-download { background: #27ae60; color: white; }
                .files-section {
                    margin-top: 12px;
                    padding-top: 12px;
                    border-top: 1px dashed #eee;
                }
                .file-item {
                    padding: 8px 0;
                    border-bottom: 1px solid #f5f5f5;
                }
                .file-path {
                    font-family: monospace;
                    font-size: 14px;
                    word-break: break-all;
                }
                .file-meta {
                    font-size: 12px;
                    color: #7f8c8d;
                }
                .status-ok { color: #27ae60; }
                .status-down { color: #e74c3c; }
                .device-type {
                    font-size: 13px;
                    color: #8e44ad;
                    font-weight: bold;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📁 Access File Transfer — Центр управления</h1>
                <div id="clientsList"></div>

                <div class="client-card">
                    <h3>⬇️ Загруженные файлы</h3>
                    <div id="downloadedFilesContainer">
                        <p>Нет загруженных файлов.</p>
                    </div>
                </div>
            </div>

            <script>
                async function loadAllClients() {
                    const res = await fetch('/api/clients');
                    const data = await res.json();
                    const container = document.getElementById('clientsList');
                    
                    if (Object.keys(data.clients).length === 0) {
                        container.innerHTML = '<p style="text-align:center; color:#7f8c8d;">Нет подключённых клиентов</p>';
                        return;
                    }

                    container.innerHTML = '';
                    for (const [clientId, info] of Object.entries(data.clients)) {
                        const vncAddr = `${info.ip}:${info.vnc_port}`;
                        const statusClass = info.vnc_status === "running" ? "status-ok" : "status-down";
                        const statusText = info.vnc_status === "running" ? "✅ VNC работает" : "❌ VNC не отвечает";

                        const div = document.createElement('div');
                        div.className = 'client-card';
                        div.innerHTML = `
                            <h3>🖥️ ${clientId}</h3>
                            <p class="device-type">Тип устройства: ${info.device_type || "не указан"}</p>
                            <p>
                                <strong>IP для VNC:</strong> 
                                <span class="vnc-address" id="vnc-${clientId}">${vncAddr}</span>
                                <button class="btn btn-primary" onclick="copyVNC('${clientId}')">📋 Копировать</button>
                            </p>
                            <p><span class="${statusClass}">${statusText}</span></p>
                            <button class="btn btn-success" onclick="showFiles('${clientId}')">📂 Показать файлы</button>
                            <div id="files-${clientId}" class="files-section" style="display:none;"></div>
                        `;
                        container.appendChild(div);
                    }
                }

                function copyVNC(clientId) {
                    const el = document.getElementById(`vnc-${clientId}`);
                    if (el) {
                        navigator.clipboard.writeText(el.innerText).then(() => {
                            alert(`Скопировано: ${el.innerText}`);
                        }).catch(() => {
                            alert('Не удалось скопировать. Выделите и скопируйте вручную.');
                        });
                    }
                }

                async function showFiles(clientId) {
                    const filesDiv = document.getElementById(`files-${clientId}`);
                    filesDiv.style.display = 'block';

                    const res = await fetch(`/client/${clientId}/files`);
                    const data = await res.json();

                    // Получаем тип устройства
                    const clientsRes = await fetch('/api/clients');
                    const clientsData = await clientsRes.json();
                    const devType = clientsData.clients[clientId]?.device_type || "неизвестен";

                    let scanLabel = "файлы";
                    if (devType.includes("Nuvision")) scanLabel = "файлы Access (.accdb, .mdb)";
                    else if (devType.includes("Toshiba")) scanLabel = "архивы (.gz)";
                    else if (devType === "GE") scanLabel = "логи (.log)";

                    if (data.files.length === 0) {
                        filesDiv.innerHTML = `
                            <p>Файлов пока нет.</p>
                            <button class="btn btn-primary" onclick="requestScan('${clientId}')">
                                🔍 Запросить список ${scanLabel}
                            </button>
                        `;
                    } else {
                        filesDiv.innerHTML = data.files.map(f => `
                            <div class="file-item">
                                <div class="file-path">${f.filepath}</div>
                                <div class="file-meta">Найден: ${new Date(f.reported_at).toLocaleString()}</div>
                                <button class="btn btn-success" onclick="uploadFile('${clientId}', '${encodeURIComponent(f.filepath)}')" style="margin-top:6px;">
                                    📤 Загрузить на сервер
                                </button>
                            </div>
                        `).join('');
                    }
                }

                async function requestScan(clientId) {
                    await fetch('/command/scan', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId})
                    });
                    alert('Команда на поиск файлов отправлена. Обновление через 6 сек...');
                    setTimeout(() => showFiles(clientId), 6000);
                }

                async function uploadFile(clientId, filepath) {
                    if (!confirm("Загрузить этот файл на сервер?")) return;
                    await fetch('/command/upload', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId, filepath: decodeURIComponent(filepath)})
                    });
                    alert("Команда загрузки создана.");
                    loadDownloadedFiles();
                }

                async function loadDownloadedFiles() {
                    const res = await fetch('/api/downloaded-files');
                    const data = await res.json();
                    const container = document.getElementById('downloadedFilesContainer');
                    if (data.files.length === 0) {
                        container.innerHTML = '<p>Нет загруженных файлов.</p>';
                    } else {
                        container.innerHTML = data.files.map(f => `
                            <div class="file-item">
                                <div><strong>${f.filename}</strong> (${(f.size / 1024).toFixed(1)} КБ)</div>
                                <div class="file-meta">С компьютера: ${f.client_id} | ${new Date(f.uploaded_at).toLocaleString()}</div>
                                <button class="btn btn-download" onclick="location.href='/download/${f.command_id}'" style="margin-top:6px;">
                                    ⬇️ Скачать
                                </button>
                            </div>
                        `).join('');
                    }
                }

                // Загрузка при старте
                loadAllClients();
                loadDownloadedFiles();

                // Автообновление каждые 12 сек
                setInterval(() => {
                    loadAllClients();
                    loadDownloadedFiles();
                }, 12000);
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)