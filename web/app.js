const byId = (id) => document.getElementById(id);

let settingsByKey = {};
let refreshTimer = null;
let diskSearchTimer = null;
let moveItems = [];
let viewerItem = null;
let diskDragItems = [];
let diskHoverTimer = null;
let diskUndoTimer = null;
let diskUndoAction = null;

const diskState = {
  folderId: null,
  scope: 'all',
  sort: 'name',
  direction: 'asc',
  category: 'all',
  viewMode: localStorage.getItem('sayuri-disk-view') === 'list' ? 'list' : 'tiles',
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
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  } catch {
    return value;
  }
}

function formatDate(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch {
    return value;
  }
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} ГБ`;
}

function diskKey(kind, id) {
  return `${kind}:${id}`;
}

function selectedDiskItems() {
  return Array.from(diskState.selected.values()).map(({kind, id}) => ({kind, id}));
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

function applyDiskScopeUI() {
  document.querySelectorAll('.disk-scope').forEach((button) => {
    button.classList.toggle('active', button.dataset.diskScope === diskState.scope);
  });
  const normalActions = diskState.scope === 'all';
  byId('new-folder-button').disabled = !normalActions;
  byId('upload-button').disabled = !normalActions;
  byId('disk-drop-zone').classList.toggle('hidden', !normalActions);
  if (!normalActions) byId('new-folder-form').classList.add('hidden');
}

function setDiskScope(scope) {
  diskState.scope = scope;
  diskState.folderId = null;
  diskState.selected.clear();
  byId('disk-search-input').value = '';
  applyDiskScopeUI();
  clearDiskSelection();
  loadDisk().catch(showDiskError);
}

function openDiskFolder(folderId) {
  diskState.scope = 'all';
  diskState.folderId = folderId || null;
  byId('disk-search-input').value = '';
  applyDiskScopeUI();
  clearDiskSelection();
  loadDisk().catch(showDiskError);
}

function renderBreadcrumbs(items) {
  const container = byId('disk-breadcrumbs');
  container.replaceChildren();

  if (diskState.scope !== 'all') {
    const labels = {favorites: 'Избранное', recent: 'Недавние', trash: 'Корзина'};
    const label = document.createElement('strong');
    label.textContent = labels[diskState.scope] || 'Диск Sayuri';
    container.append(label);
    return;
  }

  const root = document.createElement('button');
  root.type = 'button';
  root.textContent = 'Диск Sayuri';
  root.className = 'breadcrumb-drop-target';
  root.addEventListener('click', () => openDiskFolder(null));
  attachFolderDropTarget(root, null, 'Диск Sayuri', false);
  container.append(root);

  for (const item of items) {
    const separator = document.createElement('span');
    separator.textContent = '›';
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.name;
    button.title = item.name;
    button.className = 'breadcrumb-drop-target';
    button.addEventListener('click', () => openDiskFolder(item.id));
    attachFolderDropTarget(button, item.id, item.name, false);
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
    documents: 'Документ', pdf: 'PDF', tables: 'Таблица',
    presentations: 'Презентация', images: 'Изображение',
    video: 'Видео', audio: 'Аудио', archives: 'Архив', other: 'Файл'
  };
  return labels[item.category] || 'Файл';
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

function syncSelectAllState() {
  const allRows = Array.from(document.querySelectorAll('.disk-row'));
  const checked = allRows.filter((row) => diskState.selected.has(diskKey(row.dataset.kind, row.dataset.id))).length;
  const selectAll = byId('disk-select-all');
  selectAll.checked = allRows.length > 0 && checked === allRows.length;
  selectAll.indeterminate = checked > 0 && checked < allRows.length;
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
    closeContextMenu();
    handler();
  });
  return button;
}

function contextActionsFor(item) {
  const actions = [];
  if (diskState.scope === 'trash') {
    actions.push(
      ['Восстановить', () => runDiskMutation('/api/disk/restore', {items: [{kind: item.kind, id: item.id}]}, 'Объект восстановлен.')],
      ['Удалить навсегда', () => permanentlyDelete([{kind: item.kind, id: item.id}], item.name), 'danger-action']
    );
    return actions;
  }

  if (item.kind === 'folder') {
    actions.push(['Открыть', () => openDiskFolder(item.id)]);
  } else {
    actions.push(['Открыть', () => openViewer(item.kind, item.id, 'preview')]);
    actions.push(['Скачать', () => {
      window.location.href = `/api/disk/files/${encodeURIComponent(item.id)}/download`;
    }]);
  }
  actions.push(
    ['Свойства', () => openViewer(item.kind, item.id, 'properties')],
    [item.favorite ? 'Убрать из избранного' : 'В избранное', () =>
      runDiskMutation('/api/disk/favorite', {
        items: [{kind: item.kind, id: item.id}], favorite: !item.favorite
      }, 'Избранное обновлено.')
    ],
    ['Переименовать', () => renameDiskItem(item)],
    ['Переместить', () => openMoveModal([{kind: item.kind, id: item.id}])],
    ['В корзину', () => trashDiskItems([{kind: item.kind, id: item.id}], item.name), 'danger-action']
  );
  return actions;
}

function showContextMenu(event, item) {
  event.preventDefault();
  const menu = byId('disk-context-menu');
  menu.replaceChildren();

  for (const [label, handler, className = ''] of contextActionsFor(item)) {
    const button = createMenuButton(label, handler, className);
    menu.append(button);
  }

  menu.classList.remove('hidden');
  const margin = 8;
  const width = 190;
  const estimatedHeight = Math.min(360, menu.children.length * 36 + 12);
  const left = Math.min(event.clientX, window.innerWidth - width - margin);
  const top = Math.min(event.clientY, window.innerHeight - estimatedHeight - margin);
  menu.style.left = `${Math.max(margin, left)}px`;
  menu.style.top = `${Math.max(margin, top)}px`;
}

function closeContextMenu() {
  byId('disk-context-menu').classList.add('hidden');
}

function fileCountLabel(value) {
  const count = Number(value) || 0;
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} файл`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${count} файла`;
  return `${count} файлов`;
}

function clearDragHover() {
  if (diskHoverTimer) window.clearTimeout(diskHoverTimer);
  diskHoverTimer = null;
  document.querySelectorAll('.disk-drop-target-active').forEach((element) => {
    element.classList.remove('disk-drop-target-active');
  });
}

function dragSelectionFor(item) {
  const key = diskKey(item.kind, item.id);
  if (diskState.selected.has(key) && diskState.selected.size > 0) {
    return selectedDiskItems();
  }

  diskState.selected.clear();
  diskState.selected.set(key, {kind: item.kind, id: item.id, name: item.name});
  document.querySelectorAll('.disk-row input[type="checkbox"]').forEach((checkbox) => {
    checkbox.checked = false;
  });
  const row = document.querySelector(`.disk-row[data-kind="${item.kind}"][data-id="${item.id}"]`);
  const checkbox = row?.querySelector('input[type="checkbox"]');
  if (checkbox) checkbox.checked = true;
  updateBulkToolbar();
  syncSelectAllState();
  return [{kind: item.kind, id: item.id}];
}

function startDiskDrag(event, item) {
  if (diskState.scope === 'trash') {
    event.preventDefault();
    return;
  }
  diskDragItems = dragSelectionFor(item);
  event.currentTarget.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('application/x-sayuri-disk', JSON.stringify(diskDragItems));
  event.dataTransfer.setData('text/plain', item.name);
}

function finishDiskDrag() {
  diskDragItems = [];
  clearDragHover();
  document.querySelectorAll('.dragging').forEach((element) => element.classList.remove('dragging'));
  byId('disk-trash-target')?.classList.remove('trash-drag-active');
}

async function moveDiskItems(items, destinationId, destinationName) {
  if (!items.length) return;
  try {
    const result = await postJson('/api/disk/move', {
      items,
      destination_id: destinationId
    });
    if (!result.count) {
      showDiskMessage('Объекты уже находятся в этой папке.');
      return;
    }
    closeViewer();
    await Promise.all([loadDisk(), loadSystem()]);
    showUndoToast(
      `Перемещено в «${destinationName || result.destination_name || 'Диск Sayuri'}»`,
      async () => {
        await postJson('/api/disk/undo-move', {moves: result.moves});
        await Promise.all([loadDisk(), loadSystem()]);
        showDiskMessage('Перемещение отменено.');
      }
    );
  } catch (error) {
    showDiskError(error);
  } finally {
    finishDiskDrag();
  }
}

async function trashByDrag(items) {
  if (!items.length) return;
  try {
    await postJson('/api/disk/trash', {items});
    await Promise.all([loadDisk(), loadSystem()]);
    showUndoToast('Перемещено в корзину', async () => {
      await postJson('/api/disk/restore', {items});
      await Promise.all([loadDisk(), loadSystem()]);
      showDiskMessage('Удаление отменено.');
    });
  } catch (error) {
    showDiskError(error);
  } finally {
    finishDiskDrag();
  }
}

function attachFolderDropTarget(element, folderId, folderName, autoOpen = true) {
  element.addEventListener('dragover', (event) => {
    if (!diskDragItems.length) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    element.classList.add('disk-drop-target-active');
  });

  element.addEventListener('dragenter', (event) => {
    if (!diskDragItems.length) return;
    event.preventDefault();
    clearDragHover();
    element.classList.add('disk-drop-target-active');

    const containsTarget = diskDragItems.some((item) => item.kind === 'folder' && item.id === folderId);
    if (autoOpen && !containsTarget && diskState.scope !== 'trash' && diskState.folderId !== folderId) {
      diskHoverTimer = window.setTimeout(() => {
        if (diskDragItems.length) openDiskFolder(folderId);
      }, 900);
    }
  });

  element.addEventListener('dragleave', (event) => {
    if (event.relatedTarget && element.contains(event.relatedTarget)) return;
    if (diskHoverTimer) window.clearTimeout(diskHoverTimer);
    diskHoverTimer = null;
    element.classList.remove('disk-drop-target-active');
  });

  element.addEventListener('drop', (event) => {
    if (!diskDragItems.length) return;
    event.preventDefault();
    event.stopPropagation();
    const items = diskDragItems.slice();
    clearDragHover();
    moveDiskItems(items, folderId, folderName);
  });
}

function showUndoToast(message, action) {
  if (diskUndoTimer) window.clearTimeout(diskUndoTimer);
  diskUndoAction = action;
  byId('disk-undo-message').textContent = message;
  byId('disk-undo-toast').classList.remove('hidden');
  diskUndoTimer = window.setTimeout(() => {
    byId('disk-undo-toast').classList.add('hidden');
    diskUndoAction = null;
  }, 8000);
}

function createDiskRow(item) {
  const row = document.createElement('div');
  row.className = `disk-row ${item.kind}`;
  row.dataset.kind = item.kind;
  row.dataset.id = item.id;
  row.addEventListener('contextmenu', (event) => showContextMenu(event, item));

  if (diskState.scope !== 'trash') {
    row.draggable = true;
    row.addEventListener('dragstart', (event) => startDiskDrag(event, item));
    row.addEventListener('dragend', finishDiskDrag);
  }

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
  icon.textContent = item.kind === 'folder' ? '📁' : diskTypeLabel(item);

  const textWrap = document.createElement('div');
  textWrap.className = 'disk-name-wrap';

  const name = document.createElement('button');
  name.className = 'disk-name disk-name-button';
  name.type = 'button';
  name.textContent = item.name;
  name.title = item.name;
  name.addEventListener('click', () => {
    if (item.kind === 'folder' && diskState.scope !== 'trash') {
      openDiskFolder(item.id);
    } else {
      openViewer(item.kind, item.id, item.kind === 'file' ? 'preview' : 'properties');
    }
  });

  const cardMeta = document.createElement('span');
  cardMeta.className = 'disk-card-meta';
  cardMeta.textContent = item.kind === 'folder'
    ? `${fileCountLabel(item.file_count)} · ${formatBytes(item.size_bytes)}`
    : `${diskCategoryLabel(item)} · ${formatBytes(item.size_bytes)}`;

  textWrap.append(name, cardMeta);

  if (item.favorite) {
    const favorite = document.createElement('span');
    favorite.className = 'favorite-mark';
    favorite.textContent = '★';
    favorite.title = 'В избранном';
    textWrap.append(favorite);
  }
  nameCell.append(icon, textWrap);

  const size = document.createElement('span');
  size.className = 'disk-secondary disk-col-size';
  size.textContent = formatBytes(item.size_bytes);

  const type = document.createElement('span');
  type.className = 'disk-secondary disk-col-type';
  type.textContent = diskCategoryLabel(item);

  const date = document.createElement('span');
  date.className = 'disk-secondary disk-col-date';
  date.textContent = formatDate(item.updated_at || item.created_at);

  const actions = document.createElement('div');
  actions.className = 'disk-row-actions';
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'icon-action';
  more.textContent = '•••';
  more.title = 'Действия';
  more.addEventListener('click', () => {
    const rect = more.getBoundingClientRect();
    showContextMenu({preventDefault() {}, clientX: rect.right, clientY: rect.bottom}, item);
  });
  actions.append(more);

  row.append(check, nameCell, size, type, date, actions);

  if (item.kind === 'folder' && diskState.scope !== 'trash') {
    attachFolderDropTarget(row, item.id, item.name, true);
  }

  return row;
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
  renderBreadcrumbs(data.breadcrumb);

  document.querySelectorAll('[data-view-mode]').forEach((button) => {
    button.classList.toggle('active', button.dataset.viewMode === diskState.viewMode);
  });
  byId('disk-panel').dataset.viewMode = diskState.viewMode;

  clearDiskSelection();
  const container = byId('disk-list');
  container.className = `disk-list ${diskState.viewMode}`;
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
      ? 'Перетащите файлы наверх или создайте папку.'
      : 'В этом разделе пока нет объектов.';
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  for (const item of entries) container.append(createDiskRow(item));
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
    closeViewer();
    await Promise.all([loadDisk(), loadSystem()]);
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
  try {
    await postJson('/api/disk/trash', {items});
    await Promise.all([loadDisk(), loadSystem()]);
    showUndoToast('Перемещено в корзину', async () => {
      await postJson('/api/disk/restore', {items});
      await Promise.all([loadDisk(), loadSystem()]);
      showDiskMessage('Удаление отменено.');
    });
  } catch (error) {
    showDiskError(error);
  }
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
    await loadDisk();
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
    name.title = file.name;
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
    await Promise.all([loadDisk(), loadSystem()]);
  }
}

function switchViewerTab(tab) {
  document.querySelectorAll('[data-viewer-tab]').forEach((button) => {
    button.classList.toggle('active', button.dataset.viewerTab === tab);
  });
  document.querySelectorAll('.viewer-tab').forEach((section) => {
    section.classList.toggle('active', section.id === `viewer-tab-${tab}`);
  });
}

function renderPropertyFields(item) {
  const body = byId('properties-body');
  body.replaceChildren();

  const fields = [
    ['Тип', item.kind === 'folder' ? 'Папка' : diskCategoryLabel(item)],
    ['Размер', formatBytes(item.size_bytes)],
    ['Путь', ['Диск Sayuri', ...(item.path || []).map((part) => part.name)].join(' / ')],
    ['Создан', formatDate(item.created_at)],
    ['Изменён', formatDate(item.updated_at)]
  ];

  if (item.kind === 'file') {
    fields.push(
      ['Формат', item.content_type || '—'],
      ['SHA-256', item.sha256 || '—'],
      ['Совпадений', String(item.duplicate_count || 0)]
    );
  } else {
    fields.push(
      ['Файлов внутри', String(item.direct_files || 0)],
      ['Папок внутри', String(item.direct_folders || 0)]
    );
  }
  if (item.trashed_at) fields.push(['В корзине с', formatDate(item.trashed_at)]);

  for (const [labelText, valueText] of fields) {
    const field = document.createElement('article');
    field.className = 'property-card';
    const label = document.createElement('span');
    label.textContent = labelText;
    const value = document.createElement('strong');
    value.textContent = valueText;
    if (labelText === 'SHA-256') value.className = 'property-hash';
    field.append(label, value);
    body.append(field);
  }
}

function renderViewerActions(item) {
  const actions = byId('properties-actions');
  actions.replaceChildren();

  if (item.trashed_at) {
    actions.append(
      createMenuButton('Восстановить', () =>
        runDiskMutation('/api/disk/restore', {items: [{kind: item.kind, id: item.id}]}, 'Объект восстановлен.')
      ),
      createMenuButton('Удалить навсегда', () =>
        permanentlyDelete([{kind: item.kind, id: item.id}], item.name), 'danger-action'
      )
    );
    return;
  }

  if (item.kind === 'file') {
    actions.append(createMenuButton('Скачать', () => {
      window.location.href = `/api/disk/files/${encodeURIComponent(item.id)}/download`;
    }));
  }
  actions.append(
    createMenuButton('Переместить', () => openMoveModal([{kind: item.kind, id: item.id}])),
    createMenuButton('В корзину', () => trashDiskItems([{kind: item.kind, id: item.id}], item.name), 'danger-action')
  );
}

function renderPreview(preview) {
  const stage = byId('file-preview-stage');
  stage.replaceChildren();

  if (preview.mode === 'pdf') {
    const frame = document.createElement('iframe');
    frame.className = 'preview-frame';
    frame.src = preview.url;
    frame.title = preview.name;
    stage.append(frame);
    return;
  }

  if (preview.mode === 'image') {
    const image = document.createElement('img');
    image.className = 'preview-image';
    image.src = preview.url;
    image.alt = preview.name;
    stage.append(image);
    return;
  }

  if (preview.mode === 'video') {
    const video = document.createElement('video');
    video.className = 'preview-media';
    video.src = preview.url;
    video.controls = true;
    stage.append(video);
    return;
  }

  if (preview.mode === 'audio') {
    const audioWrap = document.createElement('div');
    audioWrap.className = 'preview-audio';
    const audio = document.createElement('audio');
    audio.src = preview.url;
    audio.controls = true;
    audioWrap.append(audio);
    stage.append(audioWrap);
    return;
  }

  if (preview.mode === 'table') {
    const tableWrap = document.createElement('div');
    tableWrap.className = 'preview-table-wrap';
    const table = document.createElement('table');
    table.className = 'preview-table';
    for (const row of preview.rows || []) {
      const tr = document.createElement('tr');
      for (const value of row) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      }
      table.append(tr);
    }
    if (!table.children.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'В таблице не найдено отображаемых значений.';
      stage.append(empty);
      return;
    }
    tableWrap.append(table);
    stage.append(tableWrap);
    return;
  }

  if (['text', 'document', 'presentation', 'table-text'].includes(preview.mode)) {
    const pre = document.createElement('pre');
    pre.className = 'preview-text';
    pre.textContent = preview.text || 'Нет текста для отображения.';
    stage.append(pre);
    if (preview.truncated) {
      const note = document.createElement('div');
      note.className = 'preview-note';
      note.textContent = 'Показана только часть большого файла.';
      stage.append(note);
    }
    return;
  }

  const unsupported = document.createElement('div');
  unsupported.className = 'preview-unsupported';
  const icon = document.createElement('span');
  icon.textContent = '◇';
  const title = document.createElement('strong');
  title.textContent = 'Встроенный просмотр недоступен';
  const text = document.createElement('p');
  text.textContent = preview.message || 'Файл можно скачать и открыть внешним приложением.';
  unsupported.append(icon, title, text);
  stage.append(unsupported);
}

async function openViewer(kind, id, tab = 'preview') {
  try {
    const response = await fetch(`/api/disk/items/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {cache: 'no-store'});
    const item = await response.json();
    if (!response.ok) throw new Error(item?.error?.message || `HTTP ${response.status}`);
    item.kind = kind;
    viewerItem = item;

    byId('file-viewer-title').textContent = item.name;
    byId('file-viewer-title').title = item.name;
    byId('file-viewer-kind').textContent = kind === 'folder' ? 'СВОЙСТВА ПАПКИ' : 'ПРОСМОТР ФАЙЛА';
    byId('file-viewer-badge').textContent = kind === 'folder' ? 'ПАПКА' : diskTypeLabel(item);
    byId('property-hero-icon').textContent = kind === 'folder' ? 'П' : diskTypeLabel(item);
    byId('property-full-name').textContent = item.name;
    byId('property-name-input').value = item.name;
    byId('property-favorite-toggle').checked = Boolean(item.favorite);

    const downloadButton = byId('file-viewer-download');
    downloadButton.classList.toggle('hidden', kind !== 'file');
    downloadButton.onclick = () => {
      window.location.href = `/api/disk/files/${encodeURIComponent(item.id)}/download`;
    };

    renderPropertyFields(item);
    renderViewerActions(item);

    const previewTab = document.querySelector('[data-viewer-tab="preview"]');
    previewTab.classList.toggle('hidden', kind !== 'file');
    if (kind === 'folder') tab = 'properties';

    const modal = byId('file-viewer-modal');
    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
    switchViewerTab(tab);

    if (kind === 'file') {
      const stage = byId('file-preview-stage');
      stage.innerHTML = '<p class="muted">Загрузка предпросмотра…</p>';
      const previewResponse = await fetch(`/api/disk/files/${encodeURIComponent(id)}/preview`, {cache: 'no-store'});
      const preview = await previewResponse.json();
      if (!previewResponse.ok) throw new Error(preview?.error?.message || `HTTP ${previewResponse.status}`);
      renderPreview(preview);
    } else {
      byId('file-preview-stage').replaceChildren();
    }
  } catch (error) {
    showDiskError(error);
  }
}

function closeViewer() {
  byId('file-viewer-modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
  viewerItem = null;
}

async function saveViewerName() {
  if (!viewerItem) return;
  const name = byId('property-name-input').value.trim();
  if (!name || name === viewerItem.name) return;
  try {
    await postJson('/api/disk/rename', {
      kind: viewerItem.kind,
      id: viewerItem.id,
      name
    });
    showDiskMessage('Название сохранено.');
    await loadDisk();
    await openViewer(viewerItem.kind, viewerItem.id, 'properties');
  } catch (error) {
    showDiskError(error);
  }
}

async function saveViewerFavorite() {
  if (!viewerItem) return;
  const favorite = byId('property-favorite-toggle').checked;
  try {
    await postJson('/api/disk/favorite', {
      items: [{kind: viewerItem.kind, id: viewerItem.id}],
      favorite
    });
    viewerItem.favorite = favorite;
    showDiskMessage('Избранное обновлено.');
    await loadDisk();
  } catch (error) {
    byId('property-favorite-toggle').checked = !favorite;
    showDiskError(error);
  }
}

function updateMovePreview(name, path) {
  byId('move-selected-name').textContent = name || 'Диск Sayuri';
  byId('move-selected-path').textContent = path || 'Диск Sayuri';
}

async function openMoveModal(items) {
  moveItems = items;
  byId('move-items-count').textContent = `${items.length} объект(а)`;
  updateMovePreview('Диск Sayuri', 'Диск Sayuri');

  try {
    const response = await fetch('/api/disk/folders-tree', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);

    const rootRadio = document.querySelector('input[name="move-destination"][value=""]');
    rootRadio.checked = true;
    rootRadio.onchange = () => updateMovePreview('Диск Sayuri', 'Диск Sayuri');

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
      input.dataset.name = folder.name;
      input.dataset.path = `Диск Sayuri / ${folder.path}`;
      input.addEventListener('change', () => {
        if (input.checked) updateMovePreview(folder.name, input.dataset.path);
      });
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
  const destinationName = selected?.dataset?.name || 'Диск Sayuri';
  const items = moveItems.slice();
  closeMoveModal();
  await moveDiskItems(items, destinationId, destinationName);
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
document.querySelectorAll('[data-view-mode]').forEach((button) => {
  button.addEventListener('click', () => {
    diskState.viewMode = button.dataset.viewMode;
    localStorage.setItem('sayuri-disk-view', diskState.viewMode);
    if (diskState.data) renderDisk(diskState.data);
  });
});
document.querySelectorAll('[data-bulk-action]').forEach((button) => {
  button.addEventListener('click', () => handleBulkAction(button.dataset.bulkAction));
});
document.querySelectorAll('[data-viewer-tab]').forEach((button) => {
  button.addEventListener('click', () => switchViewerTab(button.dataset.viewerTab));
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

byId('file-viewer-close').addEventListener('click', closeViewer);
byId('property-rename-save').addEventListener('click', saveViewerName);
byId('property-favorite-toggle').addEventListener('change', saveViewerFavorite);
byId('move-close').addEventListener('click', closeMoveModal);
byId('move-cancel').addEventListener('click', closeMoveModal);
byId('move-confirm').addEventListener('click', confirmMove);

const trashTarget = byId('disk-trash-target');
trashTarget.addEventListener('dragover', (event) => {
  if (!diskDragItems.length) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  trashTarget.classList.add('trash-drag-active');
});
trashTarget.addEventListener('dragleave', () => trashTarget.classList.remove('trash-drag-active'));
trashTarget.addEventListener('drop', (event) => {
  if (!diskDragItems.length) return;
  event.preventDefault();
  event.stopPropagation();
  const items = diskDragItems.slice();
  trashTarget.classList.remove('trash-drag-active');
  trashByDrag(items);
});

byId('disk-undo-button').addEventListener('click', async () => {
  if (!diskUndoAction) return;
  const action = diskUndoAction;
  diskUndoAction = null;
  byId('disk-undo-toast').classList.add('hidden');
  if (diskUndoTimer) window.clearTimeout(diskUndoTimer);
  try {
    await action();
  } catch (error) {
    showDiskError(error);
  }
});

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

document.addEventListener('click', (event) => {
  if (!event.target.closest('#disk-context-menu') && !event.target.closest('.icon-action')) {
    closeContextMenu();
  }
});
window.addEventListener('resize', closeContextMenu);
window.addEventListener('scroll', closeContextMenu, true);

byId('file-viewer-modal').addEventListener('click', (event) => {
  if (event.target === byId('file-viewer-modal')) closeViewer();
});
byId('move-modal').addEventListener('click', (event) => {
  if (event.target === byId('move-modal')) closeMoveModal();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeContextMenu();
    if (!byId('move-modal').classList.contains('hidden')) closeMoveModal();
    if (!byId('file-viewer-modal').classList.contains('hidden')) closeViewer();
  }
});

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
