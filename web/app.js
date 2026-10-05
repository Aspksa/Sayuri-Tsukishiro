const byId = (id) => document.getElementById(id);

let settingsByKey = {};
let refreshTimer = null;
let diskSearchTimer = null;
let moveItems = [];

const diskState = {
  folderId: null,
  scope: 'all',
  sort: 'name',
  direction: 'asc',
  category: 'all',
  data: null,
  selected: new Map()
};

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
  if (!value) return '—';
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
    Promise.all([loadDisk(), loadDiskActions()]).catch(showDiskError);
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

function diskKey(kind, id) {
  return `${kind}:${id}`;
}

function selectedDiskItems() {
  return Array.from(diskState.selected.values()).map(({kind, id}) => ({kind, id}));
}

function clearDiskSelection() {
  diskState.selected.clear();
  const selectAll = byId('disk-select-all');
  if (selectAll) {
    selectAll.checked = false;
    selectAll.indeterminate = false;
  }
  updateBulkToolbar();
}

function updateBulkToolbar() {
  const count = diskState.selected.size;
  byId('disk-selected-count').textContent = `Выбрано: ${count}`;
  byId('disk-bulk-toolbar').classList.toggle('hidden', count === 0);
  document.querySelectorAll('.trash-only').forEach((item) => {
    item.classList.toggle('hidden', diskState.scope !== 'trash');
  });
  document.querySelectorAll('.normal-only').forEach((item) => {
    item.classList.toggle('hidden', diskState.scope === 'trash');
  });
}

function setDiskScope(scope) {
  diskState.scope = scope;
  diskState.folderId = null;
  diskState.selected.clear();
  byId('disk-search-input').value = '';
  document.querySelectorAll('.disk-scope').forEach((button) => {
    button.classList.toggle('active', button.dataset.diskScope === scope);
  });
  const normalActions = scope === 'all';
  byId('new-folder-button').disabled = !normalActions;
  byId('upload-button').disabled = !normalActions;
  byId('disk-drop-zone').classList.toggle('hidden', !normalActions);
  byId('new-folder-form').classList.add('hidden');
  loadDisk().catch(showDiskError);
}

function openDiskFolder(folderId) {
  if (diskState.scope !== 'all') setDiskScope('all');
  diskState.folderId = folderId || null;
  byId('disk-search-input').value = '';
  clearDiskSelection();
  loadDisk().catch(showDiskError);
}

function renderBreadcrumbs(items) {
  const container = byId('disk-breadcrumbs');
  container.replaceChildren();

  if (diskState.scope !== 'all') {
    const labels = {
      favorites: 'Избранное',
      recent: 'Недавние',
      trash: 'Корзина'
    };
    const label = document.createElement('strong');
    label.textContent = labels[diskState.scope] || 'Диск Sayuri';
    container.append(label);
    return;
  }

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

function diskTypeLabel(item) {
  if (item.kind === 'folder') return 'ПАПКА';
  const extension = item.name.includes('.') ? item.name.split('.').pop().toUpperCase().slice(0, 5) : '';
  return extension || 'ФАЙЛ';
}

function diskCategoryLabel(item) {
  if (item.kind === 'folder') return 'Папка';
  const labels = {
    documents: 'Документ',
    pdf: 'PDF',
    tables: 'Таблица',
    presentations: 'Презентация',
    images: 'Изображение',
    video: 'Видео',
    audio: 'Аудио',
    archives: 'Архив',
    other: 'Файл'
  };
  return labels[item.category] || 'Файл';
}

function createMenuButton(label, handler, className = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener('click', (event) => {
    event.preventDefault();
    const details = button.closest('details');
    if (details) details.open = false;
    handler();
  });
  return button;
}

function createDiskRow(item) {
  const row = document.createElement('div');
  row.className = 'disk-row';
  row.dataset.kind = item.kind;
  row.dataset.id = item.id;

  const check = document.createElement('label');
  check.className = 'disk-check';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = diskState.selected.has(diskKey(item.kind, item.id));
  const fake = document.createElement('span');
  check.append(checkbox, fake);
  checkbox.addEventListener('change', () => {
    const key = diskKey(item.kind, item.id);
    if (checkbox.checked) {
      diskState.selected.set(key, {kind: item.kind, id: item.id, name: item.name});
    } else {
      diskState.selected.delete(key);
    }
    syncSelectAllState();
    updateBulkToolbar();
  });

  const nameCell = document.createElement('div');
  nameCell.className = 'disk-name-cell';

  const icon = document.createElement('span');
  icon.className = `disk-file-icon ${item.kind === 'folder' ? 'folder' : ''}`;
  icon.textContent = item.kind === 'folder' ? 'П' : diskTypeLabel(item);

  const textWrap = document.createElement('div');
  textWrap.className = 'disk-name-wrap';
  const name = document.createElement(item.kind === 'folder' && diskState.scope !== 'trash' ? 'button' : 'strong');
  name.className = 'disk-name';
  name.textContent = item.name;
  if (name.tagName === 'BUTTON') {
    name.type = 'button';
    name.addEventListener('click', () => openDiskFolder(item.id));
  }
  textWrap.append(name);

  if (item.favorite) {
    const favorite = document.createElement('span');
    favorite.className = 'favorite-mark';
    favorite.textContent = '★';
    favorite.title = 'В избранном';
    textWrap.append(favorite);
  }
  nameCell.append(icon, textWrap);

  const size = document.createElement('span');
  size.className = 'disk-secondary';
  size.textContent = formatBytes(item.size_bytes);

  const type = document.createElement('span');
  type.className = 'disk-secondary';
  type.textContent = diskCategoryLabel(item);

  const date = document.createElement('span');
  date.className = 'disk-secondary';
  date.textContent = formatDate(item.updated_at || item.created_at);

  const actions = document.createElement('div');
  actions.className = 'disk-row-actions';

  const info = document.createElement('button');
  info.type = 'button';
  info.className = 'icon-action';
  info.textContent = 'ⓘ';
  info.title = 'Свойства';
  info.addEventListener('click', () => openProperties(item.kind, item.id));
  actions.append(info);

  const menu = document.createElement('details');
  menu.className = 'disk-menu';
  const summary = document.createElement('summary');
  summary.textContent = '•••';
  summary.title = 'Действия';
  const menuBody = document.createElement('div');
  menuBody.className = 'disk-menu-body';

  if (diskState.scope === 'trash') {
    menuBody.append(
      createMenuButton('Восстановить', () => runDiskMutation('/api/disk/restore', {items: [{kind: item.kind, id: item.id}]}, 'Объект восстановлен.')),
      createMenuButton('Удалить навсегда', () => permanentlyDelete([{kind: item.kind, id: item.id}], item.name), 'danger-action')
    );
  } else {
    if (item.kind === 'file') {
      menuBody.append(createMenuButton('Скачать', () => {
        window.location.href = `/api/disk/files/${encodeURIComponent(item.id)}/download`;
      }));
    }
    menuBody.append(
      createMenuButton(item.favorite ? 'Убрать из избранного' : 'В избранное', () =>
        runDiskMutation('/api/disk/favorite', {
          items: [{kind: item.kind, id: item.id}],
          favorite: !item.favorite
        }, item.favorite ? 'Убрано из избранного.' : 'Добавлено в избранное.')
      ),
      createMenuButton('Переименовать', () => renameDiskItem(item)),
      createMenuButton('Переместить', () => openMoveModal([{kind: item.kind, id: item.id}])),
      createMenuButton('В корзину', () => trashDiskItems([{kind: item.kind, id: item.id}], item.name), 'danger-action')
    );
  }

  menu.append(summary, menuBody);
  actions.append(menu);

  row.append(check, nameCell, size, type, date, actions);
  return row;
}

function syncSelectAllState() {
  const allRows = Array.from(document.querySelectorAll('.disk-row'));
  const checked = allRows.filter((row) => diskState.selected.has(diskKey(row.dataset.kind, row.dataset.id))).length;
  const selectAll = byId('disk-select-all');
  selectAll.checked = allRows.length > 0 && checked === allRows.length;
  selectAll.indeterminate = checked > 0 && checked < allRows.length;
}

function renderDisk(data) {
  diskState.data = data;
  byId('disk-files-count').textContent = String(data.stats.files);
  byId('disk-folders-count').textContent = String(data.stats.folders);
  byId('disk-bytes').textContent = formatBytes(data.stats.bytes);
  byId('disk-favorites-count').textContent = String(data.stats.favorites);
  byId('disk-trash-count').textContent = String(data.stats.trash_items);
  byId('disk-scope-favorites').textContent = String(data.stats.favorites);
  byId('disk-scope-trash').textContent = String(data.stats.trash_items);
  byId('disk-rail-used').textContent = formatBytes(data.stats.bytes);
  renderBreadcrumbs(data.breadcrumb);

  clearDiskSelection();

  const container = byId('disk-list');
  container.replaceChildren();
  const entries = [
    ...data.folders.map((item) => ({...item, kind: 'folder'})),
    ...data.files.map((item) => ({...item, kind: 'file'}))
  ];

  if (!entries.length) {
    const empty = document.createElement('div');
    empty.className = 'disk-empty';
    const title = document.createElement('strong');
    title.textContent = byId('disk-search-input').value
      ? 'Ничего не найдено'
      : (diskState.scope === 'trash' ? 'Корзина пуста' : 'Здесь пока пусто');
    const copy = document.createElement('span');
    copy.textContent = diskState.scope === 'all'
      ? 'Загрузите файлы или создайте новую папку.'
      : 'В этом разделе пока нет объектов.';
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  for (const item of entries) {
    container.append(createDiskRow(item));
  }
  syncSelectAllState();
}

async function loadDisk() {
  const params = new URLSearchParams();
  if (diskState.scope === 'all' && diskState.folderId) params.set('folder_id', diskState.folderId);
  const query = byId('disk-search-input').value.trim();
  if (query) params.set('q', query);
  params.set('scope', diskState.scope);
  params.set('sort', diskState.sort);
  params.set('direction', diskState.direction);
  params.set('category', diskState.category);

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

async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  return data;
}

async function runDiskMutation(url, body, message) {
  try {
    await postJson(url, body);
    showDiskMessage(message);
    closeProperties();
    await Promise.all([loadDisk(), loadDiskActions(), loadSystem()]);
  } catch (error) {
    showDiskError(error);
  }
}

async function renameDiskItem(item) {
  const name = window.prompt('Новое имя:', item.name);
  if (!name || name.trim() === item.name) return;
  await runDiskMutation(
    '/api/disk/rename',
    {kind: item.kind, id: item.id, name: name.trim()},
    'Объект переименован.'
  );
}

async function trashDiskItems(items, name = '') {
  const description = items.length === 1 && name ? `«${name}»` : `${items.length} объект(а)`;
  if (!window.confirm(`Переместить ${description} в корзину?`)) return;
  await runDiskMutation('/api/disk/trash', {items}, 'Перемещено в корзину.');
}

async function permanentlyDelete(items, name = '') {
  const description = items.length === 1 && name ? `«${name}»` : `${items.length} объект(а)`;
  if (!window.confirm(`Удалить ${description} навсегда? Это действие нельзя отменить.`)) return;
  await runDiskMutation('/api/disk/delete-permanent', {items}, 'Удалено навсегда.');
}

async function createDiskFolder(event) {
  event.preventDefault();
  const input = byId('new-folder-name');
  const name = input.value.trim();
  if (!name) return;

  try {
    await postJson('/api/disk/folders', {name, parent_id: diskState.folderId});
    input.value = '';
    byId('new-folder-form').classList.add('hidden');
    showDiskMessage('Папка создана.');
    await Promise.all([loadDisk(), loadDiskActions()]);
  } catch (error) {
    showDiskError(error);
  }
}

function uploadOneFile(file, index, total) {
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams();
    if (diskState.folderId) params.set('folder_id', diskState.folderId);

    const row = document.createElement('div');
    row.className = 'upload-item';
    const label = document.createElement('div');
    label.className = 'upload-item-label';
    const name = document.createElement('strong');
    name.textContent = file.name;
    const status = document.createElement('span');
    status.textContent = 'Подготовка…';
    label.append(name, status);

    const progress = document.createElement('div');
    progress.className = 'upload-progress';
    const bar = document.createElement('span');
    progress.append(bar);
    row.append(label, progress);
    byId('upload-items').append(row);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/disk/upload?${params.toString()}`);
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.setRequestHeader('X-Sayuri-Filename', encodeURIComponent(file.name));

    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
      bar.style.width = `${percent}%`;
      status.textContent = `${percent}% · ${formatBytes(event.loaded)} из ${formatBytes(event.total)}`;
      byId('upload-summary').textContent = `${index + 1} из ${total} · ${percent}%`;
    });

    xhr.addEventListener('load', () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || '{}'); } catch {}
      if (xhr.status < 200 || xhr.status >= 300) {
        row.classList.add('error');
        status.textContent = data?.error?.message || `Ошибка HTTP ${xhr.status}`;
        reject(new Error(status.textContent));
        return;
      }
      bar.style.width = '100%';
      row.classList.add('done');
      status.textContent = data?.file?.duplicate_of
        ? 'Готово · найдено совпадение по SHA-256'
        : 'Готово';
      resolve(data);
    });

    xhr.addEventListener('error', () => {
      row.classList.add('error');
      status.textContent = 'Ошибка соединения';
      reject(new Error('Ошибка соединения при загрузке.'));
    });

    xhr.send(file);
  });
}

async function uploadDiskFiles(files) {
  const queue = Array.from(files || []);
  if (!queue.length || diskState.scope !== 'all') return;

  byId('upload-items').replaceChildren();
  byId('upload-queue').classList.remove('hidden');
  byId('upload-summary').textContent = `0 из ${queue.length}`;

  let completed = 0;
  for (let index = 0; index < queue.length; index += 1) {
    try {
      await uploadOneFile(queue[index], index, queue.length);
      completed += 1;
    } catch (error) {
      showDiskError(error);
      break;
    }
  }

  byId('upload-summary').textContent = `Готово: ${completed} из ${queue.length}`;
  byId('disk-file-input').value = '';
  if (completed) {
    showDiskMessage(`Загружено файлов: ${completed}.`);
    await Promise.all([loadDisk(), loadDiskActions(), loadSystem()]);
  }
}

async function openProperties(kind, id) {
  try {
    const response = await fetch(`/api/disk/items/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {cache: 'no-store'});
    const item = await response.json();
    if (!response.ok) throw new Error(item?.error?.message || `HTTP ${response.status}`);

    byId('properties-title').textContent = item.name;
    const body = byId('properties-body');
    body.replaceChildren();

    const fields = [
      ['Тип', kind === 'folder' ? 'Папка' : diskCategoryLabel({...item, kind})],
      ['Размер', formatBytes(item.size_bytes)],
      ['Путь', ['Диск Sayuri', ...(item.path || []).map((part) => part.name)].join(' / ')],
      ['Создан', formatDate(item.created_at)],
      ['Изменён', formatDate(item.updated_at)],
      ['Избранное', item.favorite ? 'Да' : 'Нет']
    ];
    if (kind === 'file') {
      fields.push(
        ['MIME-тип', item.content_type || '—'],
        ['SHA-256', item.sha256 || '—'],
        ['Совпадений по SHA-256', String(item.duplicate_count || 0)]
      );
    } else {
      fields.push(
        ['Файлов внутри', String(item.direct_files || 0)],
        ['Папок внутри', String(item.direct_folders || 0)]
      );
    }
    if (item.trashed_at) fields.push(['В корзине с', formatDate(item.trashed_at)]);

    for (const [labelText, valueText] of fields) {
      const field = document.createElement('div');
      field.className = 'property-field';
      const label = document.createElement('span');
      label.textContent = labelText;
      const value = document.createElement('strong');
      value.textContent = valueText;
      if (labelText === 'SHA-256') value.className = 'property-hash';
      field.append(label, value);
      body.append(field);
    }

    const actions = document.createElement('div');
    actions.className = 'properties-actions';
    if (item.trashed_at) {
      actions.append(
        createMenuButton('Восстановить', () =>
          runDiskMutation('/api/disk/restore', {items: [{kind, id}]}, 'Объект восстановлен.')
        ),
        createMenuButton('Удалить навсегда', () =>
          permanentlyDelete([{kind, id}], item.name), 'danger-action'
        )
      );
    } else {
      if (kind === 'file') {
        actions.append(createMenuButton('Скачать', () => {
          window.location.href = `/api/disk/files/${encodeURIComponent(id)}/download`;
        }));
      }
      actions.append(
        createMenuButton(item.favorite ? 'Убрать из избранного' : 'В избранное', () =>
          runDiskMutation('/api/disk/favorite', {items: [{kind, id}], favorite: !item.favorite}, 'Избранное обновлено.')
        ),
        createMenuButton('Переименовать', () => renameDiskItem({...item, kind})),
        createMenuButton('Переместить', () => openMoveModal([{kind, id}])),
        createMenuButton('В корзину', () => trashDiskItems([{kind, id}], item.name), 'danger-action')
      );
    }
    body.append(actions);

    const drawer = byId('disk-properties');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
  } catch (error) {
    showDiskError(error);
  }
}

function closeProperties() {
  const drawer = byId('disk-properties');
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
}

async function openMoveModal(items) {
  moveItems = items;
  try {
    const response = await fetch('/api/disk/folders-tree', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);

    const list = byId('move-folder-list');
    list.replaceChildren();
    const excluded = new Set(items.filter((item) => item.kind === 'folder').map((item) => item.id));

    for (const folder of data.folders) {
      const label = document.createElement('label');
      label.className = 'move-folder-option';
      label.style.setProperty('--depth', String(folder.depth || 0));
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'move-destination';
      input.value = folder.id;
      input.disabled = excluded.has(folder.id);
      const name = document.createElement('span');
      name.textContent = folder.path;
      label.append(input, name);
      list.append(label);
    }

    byId('move-modal').classList.remove('hidden');
  } catch (error) {
    showDiskError(error);
  }
}

function closeMoveModal() {
  moveItems = [];
  byId('move-modal').classList.add('hidden');
}

async function confirmMove() {
  const selected = document.querySelector('input[name="move-destination"]:checked');
  const destinationId = selected?.value || null;
  const items = moveItems.slice();
  closeMoveModal();
  await runDiskMutation('/api/disk/move', {items, destination_id: destinationId}, 'Объекты перемещены.');
}

async function loadDiskActions() {
  const response = await fetch('/api/disk/actions?limit=12', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);

  const labels = {
    created: 'Создана папка',
    uploaded: 'Загружен файл',
    renamed: 'Переименовано',
    moved: 'Перемещено',
    favorite_on: 'Добавлено в избранное',
    favorite_off: 'Убрано из избранного',
    trashed: 'Перемещено в корзину',
    restored: 'Восстановлено',
    deleted: 'Удалено навсегда'
  };

  const container = byId('disk-actions-list');
  container.replaceChildren();
  if (!data.actions.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Действий пока нет.';
    container.append(empty);
    return;
  }

  for (const action of data.actions) {
    const row = document.createElement('div');
    row.className = 'disk-action-row';
    const dot = document.createElement('span');
    dot.className = 'disk-action-dot';
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = labels[action.action] || action.action;
    const copy = document.createElement('span');
    copy.textContent = action.object_name;
    body.append(title, copy);
    const time = document.createElement('time');
    time.textContent = formatDate(action.created_at);
    row.append(dot, body, time);
    container.append(row);
  }
}

async function handleBulkAction(action) {
  const items = selectedDiskItems();
  if (!items.length) return;

  if (action === 'favorite') {
    await runDiskMutation('/api/disk/favorite', {items, favorite: true}, 'Добавлено в избранное.');
  } else if (action === 'move') {
    await openMoveModal(items);
  } else if (action === 'trash') {
    await trashDiskItems(items);
  } else if (action === 'restore') {
    await runDiskMutation('/api/disk/restore', {items}, 'Объекты восстановлены.');
  } else if (action === 'delete') {
    await permanentlyDelete(items);
  }
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
document.querySelectorAll('.disk-scope').forEach((button) => {
  button.addEventListener('click', () => setDiskScope(button.dataset.diskScope));
});
document.querySelectorAll('[data-bulk-action]').forEach((button) => {
  button.addEventListener('click', () => handleBulkAction(button.dataset.bulkAction));
});

byId('save-settings').addEventListener('click', saveSettings);
byId('refresh-system').addEventListener('click', refreshSystem);

byId('upload-button').addEventListener('click', () => byId('disk-file-input').click());
byId('disk-file-input').addEventListener('change', (event) => uploadDiskFiles(event.target.files));
byId('new-folder-button').addEventListener('click', () => {
  if (diskState.scope !== 'all') return;
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
byId('disk-category-filter').addEventListener('change', (event) => {
  diskState.category = event.target.value;
  loadDisk().catch(showDiskError);
});
byId('disk-sort').addEventListener('change', (event) => {
  const [sort, direction] = event.target.value.split(':');
  diskState.sort = sort;
  diskState.direction = direction;
  loadDisk().catch(showDiskError);
});
byId('disk-select-all').addEventListener('change', (event) => {
  diskState.selected.clear();
  document.querySelectorAll('.disk-row').forEach((row) => {
    if (event.target.checked) {
      diskState.selected.set(
        diskKey(row.dataset.kind, row.dataset.id),
        {kind: row.dataset.kind, id: row.dataset.id}
      );
    }
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox) checkbox.checked = event.target.checked;
  });
  updateBulkToolbar();
});

byId('properties-close').addEventListener('click', closeProperties);
byId('move-close').addEventListener('click', closeMoveModal);
byId('move-cancel').addEventListener('click', closeMoveModal);
byId('move-confirm').addEventListener('click', confirmMove);
byId('refresh-disk-actions').addEventListener('click', () => loadDiskActions().catch(showDiskError));

const dropZone = byId('disk-drop-zone');
for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (diskState.scope === 'all') dropZone.classList.add('active');
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
