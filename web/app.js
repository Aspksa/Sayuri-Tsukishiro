const byId = (id) => document.getElementById(id);

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

function renderModules(modules) {
  const container = byId('modules');
  container.replaceChildren();
  const entries = Object.entries(modules);
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Модули пока не зарегистрированы.';
    container.append(empty);
    return;
  }
  for (const [name, version] of entries) {
    const row = document.createElement('div');
    row.className = 'module';
    const title = document.createElement('strong');
    title.textContent = name;
    const code = document.createElement('code');
    code.textContent = `версия ${version}`;
    row.append(title, code);
    container.append(row);
  }
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
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = `${event.event_type}: ${event.message}`;
    body.append(title);
    row.append(time, body);
    container.append(row);
  }
}

async function loadHealth() {
  const response = await fetch('/api/health', {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  setStatus('ready', 'Система готова');
  byId('project-version').textContent = data.project_version;
  byId('runtime-version').textContent = `Python ${data.runtime.python}`;
  byId('core-state').textContent = 'ГОТОВО';
  byId('db-state').textContent = data.database.status.toUpperCase();
  byId('db-detail').textContent = `SQLite · схема ${data.database.schema_version}`;
  byId('server-state').textContent = String(data.server.port);
  byId('server-detail').textContent = `${data.server.host} · только локально`;
  byId('event-count').textContent = String(data.database.events);
  byId('updated-at').textContent = `Обновлено ${formatTime(data.time_utc)}`;
  renderModules(data.modules);
}

async function loadEvents() {
  const response = await fetch('/api/events?limit=12', {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const {events} = await response.json();
  renderEvents(events);
}

async function refresh() {
  try {
    await Promise.all([loadHealth(), loadEvents()]);
  } catch (error) {
    setStatus('error', 'Нет связи с ядром');
    byId('updated-at').textContent = `Ошибка: ${String(error)}`;
  }
}

byId('refresh').addEventListener('click', refresh);
refresh();
setInterval(refresh, 10000);
