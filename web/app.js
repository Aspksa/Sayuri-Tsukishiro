const byId = (id) => document.getElementById(id);

let settingsByKey = {};
let refreshTimer = null;
let diskSearchTimer = null;
let currentDiskFolderId = null;

function setStatus(kind, text) {
  const pill = byId('status-pill');
  pill.className = `status-pill ${kind}`;
  pill.querySelector('strong').textContent = text;
}

function formatTime(value) {
  try {
    return new Date(value).toLocaleTimeString('ru-RU', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  } catch {
    return value;
  }
}

function formatDate(value) {
  try {
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return value;
  }
}

function formatUptime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours} ч ${minutes} мин`;
  if (minutes > 0) return `${minutes} мин`;
  return `${total} сек`;
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} ГБ`;
}

function showView(name) {
  document.querySelectorAll('.view').forEach((view) => {
    view.classList.toggle('active', view.id === `view-${name}`);
  });
  document.querySelectorAll('.nav-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === name);
  });

  const titles = {
    home: ['СИСТЕМА', 'Главная'],
    disk: ['ФАЙЛЫ И ДОКУМЕНТЫ', 'Диск Sayuri'],
    settings: ['СИСТЕМА И АРХИТЕКТУРА', 'Настройки']
  };
  const [eyebrow, title] = titles[name] || titles.home;
  byId('page-title').textContent = title;
  byId('page-eyebrow').textContent = eyebrow;

  if (name === 'disk') {
    history.replaceState(null, '', '#disk');
    loadDisk().catch(showDiskError);
  } else if (name === 'settings') {
    history.replaceState(null, '', '#settings');
  } else {
    history.replaceState(null, '', '#home');
  }
}

function renderSettings(settings) {
  settingsByKey = Object.fromEntries(settings.map((item) => [item.key, item]));
  const container = byId('settings-form');
  container.replaceChildren();

  for (const item of settings) {
    const row = document.createElement('label');
    row.className = 'setting-row';

    const copy = document.createElement('span');
    copy.className = 'setting-copy';

    const title = document.createElement('strong');
    title.textContent = item.label;

    const description = document.createElement('small');
    description.textContent = item.description;
    copy.append(title, description);

    let control;
    if (item.type === 'boolean') {
      const wrapper = document.createElement('span');
      wrapper.className = 'switch';
      control = document.createElement('input');
      control.type = 'checkbox';
      control.checked = Boolean(item.value);
      const track = document.createElement('span');
      track.className = 'switch-track';
      wrapper.append(control, track);
      row.append(copy, wrapper);
    } else {
      control = document.createElement('input');
      control.className = 'number-input';
      control.type = 'number';
      control.value = String(item.value);
      if (item.minimum !== null) control.min = String(item.minimum);
      if (item.maximum !== null) control.max = String(item.maximum);
      row.append(copy, control);
    }

    control.dataset.settingKey = item.key;
    if (item.restart_required) {
      const badge = document.createElement('em');
      badge.className = 'restart-badge';
      badge.textContent = 'после перезапуска';
      copy.append(badge);
    }
    container.append(row);
  }
}

function collectSettings() {
  const changes = {};
  document.querySelectorAll('[data-setting-key]').forEach((control) => {
    const key = control.dataset.settingKey;
    const spec = settingsByKey[key];
    if (!spec) return;
    changes[key] = spec.type === 'boolean' ? control.checked : Number(control.value);
  });
  return changes;
}

function renderEvents(events) {
  const container = byId('events');
  container.replaceChildren();
  if (!events.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Событий пока нет.';
    container.append(empty);
    return;
  }

  for (const event of events) {
    const row = document.createElement('div');
    row.className = 'event';
    const time = document.createElement('time');
    time.textContent = formatTime(event.created_at);
    const body = document.createElement('strong');
    body.textContent = `${event.event_type}: ${event.message}`;
    row.append(time, body);
    container.append(row);
  }
}

function renderArchitecture(modules) {
  const container = byId('architecture');
  container.replaceChildren();

  for (const module of modules) {
    const row = document.createElement('article');
    row.className = 'architecture-item';

    const head = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = module.name;
    const description = document.createElement('p');
    description.textContent = module.description || 'Системный модуль Саюри.';
    head.append(title, description);

    const meta = document.createElement('div');
    meta.className = 'architecture-meta';
    const version = document.createElement('code');
    version.textContent = `версия ${module.version}`;
    const status = document.createElement('span');
    status.textContent = module.status;
    meta.append(version, status);

    row.append(head, meta);
    container.append(row);
  }
}

function diskTypeLabel(name, contentType) {
  const extension = name.includes('.') ? name.split('.').pop().toUpperCase().slice(0, 5) : '';
  if (extension) return extension;
  if (contentType?.startsWith('image/')) return 'IMG';
  return 'ФАЙЛ';
}

function openDiskFolder(folderId) {
  currentDiskFolderId = folderId || null;
  byId('disk-search-input').value = '';
  loadDisk().catch(showDiskError);
}

function renderBreadcrumbs(items) {
  const container = byId('disk-breadcrumbs');
  container.replaceChildren();

  const root = document.createElement('button');
  root.type = 'button';
  root.textContent = 'Диск Sayuri';
  root.addEventListener('click', () => openDiskFolder(null));
  container.append(root);

  for (const item of items) {
    const separator = document.createElement('span');
    separator.textContent = '›';
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.name;
    button.addEventListener('click', () => openDiskFolder(item.id));
    container.append(separator, button);
  }
}

function createDiskRow({kind, item}) {
  const row = document.createElement('div');
  row.className = 'disk-row';

  const nameCell = document.createElement('div');
  nameCell.className = 'disk-name-cell';

  const icon = document.createElement('span');
  icon.className = `disk-file-icon ${kind === 'folder' ? 'folder' : ''}`;
  icon.textContent = kind === 'folder' ? 'П' : diskTypeLabel(item.name, item.content_type);

  const name = document.createElement(kind === 'folder' ? 'button' : 'strong');
  name.className = 'disk-name';
  name.textContent = item.name;
  if (kind === 'folder') {
    name.type = 'button';
    name.addEventListener('click', () => openDiskFolder(item.id));
  }
  nameCell.append(icon, name);

  const size = document.createElement('span');
  size.className = 'disk-secondary';
  size.textContent = kind === 'folder' ? 'Папка' : formatBytes(item.size_bytes);

  const date = document.createElement('span');
  date.className = 'disk-secondary';
  date.textContent = formatDate(item.created_at);

  const actions = document.createElement('div');
  actions.className = 'disk-row-actions';

  if (kind === 'file') {
    const download = document.createElement('button');
    download.type = 'button';
    download.textContent = 'Скачать';
    download.addEventListener('click', () => {
      window.location.href = `/api/disk/files/${encodeURIComponent(item.id)}/download`;
    });
    actions.append(download);
  }

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'danger-action';
  remove.textContent = 'Удалить';
  remove.addEventListener('click', async () => {
    const label = kind === 'folder' ? 'папку' : 'файл';
    if (!window.confirm(`Удалить ${label} «${item.name}»?`)) return;
    try {
      const url = kind === 'folder'
        ? `/api/disk/folders/${encodeURIComponent(item.id)}`
        : `/api/disk/files/${encodeURIComponent(item.id)}`;
      const response = await fetch(url, {method: 'DELETE'});
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
      showDiskMessage('Удалено.');
      await loadDisk();
    } catch (error) {
      showDiskError(error);
    }
  });
  actions.append(remove);

  row.append(nameCell, size, date, actions);
  return row;
}

function renderDisk(data) {
  byId('disk-files-count').textContent = String(data.stats.files);
  byId('disk-folders-count').textContent = String(data.stats.folders);
  byId('disk-bytes').textContent = formatBytes(data.stats.bytes);
  byId('disk-max-file').textContent = formatBytes(data.stats.max_file_size);
  renderBreadcrumbs(data.breadcrumb);

  const container = byId('disk-list');
  container.replaceChildren();

  if (!data.folders.length && !data.files.length) {
    const empty = document.createElement('div');
    empty.className = 'disk-empty';
    const title = document.createElement('strong');
    title.textContent = byId('disk-search-input').value ? 'Ничего не найдено' : 'Папка пока пустая';
    const copy = document.createElement('span');
    copy.textContent = 'Загрузите файлы или создайте новую папку.';
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  for (const folder of data.folders) {
    container.append(createDiskRow({kind: 'folder', item: folder}));
  }
  for (const file of data.files) {
    container.append(createDiskRow({kind: 'file', item: file}));
  }
}

async function loadDisk() {
  const params = new URLSearchParams();
  if (currentDiskFolderId) params.set('folder_id', currentDiskFolderId);
  const query = byId('disk-search-input').value.trim();
  if (query) params.set('q', query);

  const response = await fetch(`/api/disk?${params.toString()}`, {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderDisk(data);
}

function showDiskMessage(text) {
  const target = byId('disk-message');
  target.className = 'disk-message';
  target.textContent = text;
}

function showDiskError(error) {
  const target = byId('disk-message');
  target.className = 'disk-message error';
  target.textContent = `Ошибка: ${error instanceof Error ? error.message : String(error)}`;
}

async function createDiskFolder(event) {
  event.preventDefault();
  const input = byId('new-folder-name');
  const name = input.value.trim();
  if (!name) return;

  try {
    const response = await fetch('/api/disk/folders', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, parent_id: currentDiskFolderId})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    input.value = '';
    byId('new-folder-form').classList.add('hidden');
    showDiskMessage('Папка создана.');
    await loadDisk();
  } catch (error) {
    showDiskError(error);
  }
}

async function uploadDiskFiles(files) {
  const queue = Array.from(files || []);
  if (!queue.length) return;

  for (let index = 0; index < queue.length; index += 1) {
    const file = queue[index];
    showDiskMessage(`Загрузка ${index + 1} из ${queue.length}: ${file.name}`);

    const params = new URLSearchParams();
    if (currentDiskFolderId) params.set('folder_id', currentDiskFolderId);

    try {
      const response = await fetch(`/api/disk/upload?${params.toString()}`, {
        method: 'POST',
        headers: {
          'Content-Type': file.type || 'application/octet-stream',
          'X-Sayuri-Filename': encodeURIComponent(file.name)
        },
        body: file
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    } catch (error) {
      showDiskError(error);
      return;
    }
  }

  showDiskMessage(`Загружено файлов: ${queue.length}.`);
  byId('disk-file-input').value = '';
  await loadDisk();
}

async function loadSettings() {
  const response = await fetch('/api/settings', {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  renderSettings(data.settings);
  configureRefreshTimer();
}

async function saveSettings() {
  const button = byId('save-settings');
  const state = byId('save-state');
  button.disabled = true;
  state.textContent = 'Сохранение…';

  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({settings: collectSettings()})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    renderSettings(data.settings);
    state.textContent = 'Настройки сохранены';
    configureRefreshTimer();
    await refreshSystem();
  } catch (error) {
    state.textContent = `Ошибка: ${String(error)}`;
  } finally {
    button.disabled = false;
  }
}

async function loadEvents() {
  const configured = settingsByKey['events.display_limit']?.value;
  const limit = Number(configured) || 12;
  const response = await fetch(`/api/events?limit=${encodeURIComponent(limit)}`, {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  renderEvents(data.events);
}

async function loadSystem() {
  const response = await fetch('/api/system', {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();

  setStatus('ready', 'Система готова');
  byId('project-version').textContent = data.project.version;
  byId('sidebar-version').textContent = `версия ${data.project.version}`;
  byId('runtime-version').textContent = `Python ${data.core.python}`;

  byId('home-system-status').textContent = data.status.toUpperCase();
  byId('home-agent-status').textContent = data.agent.status.toUpperCase();
  byId('home-agent-detail').textContent = data.agent.execution_enabled ? 'выполнение включено' : 'выполнение пока отключено';
  byId('home-disk-status').textContent = data.disk.status.toUpperCase();
  byId('home-disk-detail').textContent = `${data.disk.files} файлов · ${formatBytes(data.disk.bytes)}`;

  byId('core-state').textContent = data.core.status.toUpperCase();
  byId('core-detail').textContent = `версия ${data.core.version} · Python ${data.core.python}`;

  byId('db-state').textContent = data.database.status.toUpperCase();
  byId('db-detail').textContent = `SQLite · схема ${data.database.schema_version} · ${formatBytes(data.database.size_bytes)}`;

  byId('server-state').textContent = String(data.server.port);
  byId('server-detail').textContent = `${data.server.host} · только локально`;

  byId('event-count').textContent = String(data.events.count);
  byId('event-errors').textContent = `ошибок: ${data.events.errors}`;

  byId('agent-message').textContent = data.agent.message;
  byId('agent-provider').textContent = `ИИ-провайдер: ${data.agent.provider_connected ? 'подключён' : 'не подключён'}`;
  byId('agent-memory').textContent = `Память: ${data.agent.memory_connected ? 'подключена' : 'не подключена'}`;
  byId('agent-tools').textContent = `Инструменты: ${data.agent.tools_connected ? 'подключены' : 'не подключены'}`;

  renderArchitecture(data.architecture);
  byId('updated-at').textContent = `Обновлено ${formatTime(data.time_utc)}`;
}

async function refreshSystem() {
  try {
    await Promise.all([loadSystem(), loadEvents()]);
  } catch (error) {
    setStatus('error', 'Нет связи с ядром');
    byId('updated-at').textContent = `Ошибка: ${String(error)}`;
  }
}

function configureRefreshTimer() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  const seconds = Number(settingsByKey['ui.refresh_seconds']?.value) || 10;
  refreshTimer = window.setInterval(refreshSystem, seconds * 1000);
}

document.querySelectorAll('.nav-item').forEach((button) => {
  button.addEventListener('click', () => showView(button.dataset.view));
});

byId('save-settings').addEventListener('click', saveSettings);
byId('refresh-system').addEventListener('click', refreshSystem);

byId('upload-button').addEventListener('click', () => byId('disk-file-input').click());
byId('disk-file-input').addEventListener('change', (event) => uploadDiskFiles(event.target.files));
byId('new-folder-button').addEventListener('click', () => {
  byId('new-folder-form').classList.remove('hidden');
  byId('new-folder-name').focus();
});
byId('cancel-folder-button').addEventListener('click', () => {
  byId('new-folder-form').classList.add('hidden');
  byId('new-folder-name').value = '';
});
byId('new-folder-form').addEventListener('submit', createDiskFolder);
byId('disk-search-input').addEventListener('input', () => {
  if (diskSearchTimer) window.clearTimeout(diskSearchTimer);
  diskSearchTimer = window.setTimeout(() => loadDisk().catch(showDiskError), 250);
});

const dropZone = byId('disk-drop-zone');
for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('active');
  });
}
for (const eventName of ['dragleave', 'drop']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('active');
  });
}
dropZone.addEventListener('drop', (event) => uploadDiskFiles(event.dataTransfer.files));

const initialHash = location.hash;
const initialView = initialHash === '#disk'
  ? 'disk'
  : (initialHash === '#settings' || initialHash.startsWith('#system-') ? 'settings' : 'home');
showView(initialView);

Promise.all([loadSettings(), loadSystem()])
  .then(loadEvents)
  .catch((error) => {
    setStatus('error', 'Ошибка запуска интерфейса');
    byId('updated-at').textContent = String(error);
  });
