const byId = (id) => document.getElementById(id);

let settingsByKey = {};
let refreshTimer = null;
let diskSearchTimer = null;
let moveItems = [];
let viewerItem = null;
let viewerDnaLoadedFor = null;
let diskDragItems = [];
let diskHoverTimer = null;
let diskUndoTimer = null;
let diskUndoAction = null;

const phoneState = {
  selectedSerial: null,
  selectedDevice: null,
  nativeSessions: new Set(),
  frameTimer: null,
  reconnectTimer: null,
  frameLoading: false,
  frameGeneration: 0,
  frameUrl: null,
  h264Available: false,
  h264Abort: null,
  h264Decoder: null,
  h264Generation: 0,
  h264Width: 0,
  h264Height: 0,
  h264Frames: 0,
  h264StartedAt: 0,
  audioAvailable: false,
  audioEnabled: false,
  audioAbort: null,
  audioDecoder: null,
  audioContext: null,
  audioGeneration: 0,
  audioNextTime: 0,
  audioPackets: 0,
  videoMode: 'png',
  pointer: null,
  viewActive: false,
  floatingOpen: localStorage.getItem('sayuri-phone-float-open') === '1',
  floatingMinimized: false,
  rotation: Number(localStorage.getItem('sayuri-phone-rotation') || 0) % 360,
  drag: null,
  resizeObserver: null,
  textBuffer: '',
  textTimer: null,
  keyboardCaptured: localStorage.getItem('sayuri-phone-keyboard-capture') === '1',
  qualityProfile: localStorage.getItem('sayuri-phone-quality-profile') || 'quality',
  recordingSessions: new Set(),
  apps: [],
  companionTimer: null,
  companionStatus: null,
  companionSerial: null,
  notificationEvents: [],
  notificationLastSequence: 0,
  notificationDrawerOpen: false,
  lastFrameAt: 0
};

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
  phoneState.viewActive = name === 'phone';
  if (!phoneState.viewActive && !phoneState.floatingOpen) {
    stopPhoneVideo();
    stopPhoneReconnectLoop();
    stopPhoneCompanionPolling();
  }

  document.querySelectorAll('.view').forEach((view) => {
    view.classList.toggle('active', view.id === `view-${name}`);
  });
  document.querySelectorAll('.nav-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === name);
  });

  const titles = {
    home: ['СИСТЕМА', 'Главная'],
    disk: ['ФАЙЛЫ И ДОКУМЕНТЫ', 'Диск Sayuri'],
    phone: ['ANDROID И УСТРОЙСТВА', 'Телефон Sayuri'],
    settings: ['СИСТЕМА И АРХИТЕКТУРА', 'Настройки']
  };
  const [eyebrow, title] = titles[name] || titles.home;
  byId('page-title').textContent = title;
  byId('page-eyebrow').textContent = eyebrow;

  if (name === 'disk') {
    history.replaceState(null, '', '#disk');
    loadDisk().catch(showDiskError);
  } else if (name === 'phone') {
    history.replaceState(null, '', '#phone');
    loadPhone().catch(showPhoneError);
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
    actions.push(['ДНК документа', () => openViewer(item.kind, item.id, 'dna')]);
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
  if (tab === 'dna' && viewerItem?.kind === 'file') {
    loadViewerDna(viewerItem.id).catch(showDiskError);
  }
}

function dnaField(labelText, valueText) {
  const field = document.createElement('article');
  field.className = 'dna-field';
  const label = document.createElement('span');
  label.textContent = labelText;
  const value = document.createElement('strong');
  value.textContent = valueText;
  field.append(label, value);
  return field;
}

function renderDnaList(container, items, emptyText, renderer) {
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'dna-empty';
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  for (const item of items) container.append(renderer(item));
}

function renderDocumentDna(dna) {
  byId('dna-coverage').textContent = String(dna.coverage_percent ?? 0);
  byId('dna-progress-bar').style.width = `${Math.max(0, Math.min(100, Number(dna.coverage_percent) || 0))}%`;
  byId('dna-document-type').textContent = dna.classification?.document_type || 'Документ';
  byId('dna-summary').textContent = dna.summary || 'ДНК построена.';
  byId('dna-facts-count').textContent = String(dna.molecules?.total ?? 0);
  byId('dna-entities-count').textContent = String(dna.entities?.length ?? 0);
  byId('dna-words-count').textContent = String(dna.anatomy?.words ?? 0);
  byId('dna-checks-count').textContent = String(dna.checks?.length ?? 0);

  const pipeline = byId('dna-pipeline');
  pipeline.replaceChildren();
  for (const stage of dna.stages || []) {
    const chip = document.createElement('div');
    chip.className = `dna-stage ${stage.status || 'pending'}`;
    const dot = document.createElement('span');
    const label = document.createElement('strong');
    label.textContent = stage.label;
    chip.append(dot, label);
    pipeline.append(chip);
  }

  const anatomy = byId('dna-anatomy');
  anatomy.replaceChildren();
  const pathText = ['Диск Sayuri', ...((dna.identity?.path || []).map((part) => part.name))].join(' / ');
  const anatomyFields = [
    ['Формат', (dna.identity?.format || '—').toUpperCase()],
    ['Путь', pathText],
    ['Размер', formatBytes(dna.identity?.size_bytes)],
    ['Строк', String(dna.anatomy?.lines ?? 0)],
    ['Абзацев', String(dna.anatomy?.paragraphs ?? 0)],
    ['Слов', String(dna.anatomy?.words ?? 0)],
    ['Табличных строк', String(dna.anatomy?.table_rows ?? 0)],
    ['Заголовков', String(dna.anatomy?.headings?.length ?? 0)],
    ['Определение типа', `${Math.round((Number(dna.classification?.confidence) || 0) * 100)}%`]
  ];
  const anatomyGrid = document.createElement('div');
  anatomyGrid.className = 'dna-field-grid';
  for (const [label, value] of anatomyFields) anatomyGrid.append(dnaField(label, value));
  anatomy.append(anatomyGrid);

  if (dna.anatomy?.headings?.length) {
    const headingBlock = document.createElement('div');
    headingBlock.className = 'dna-subblock';
    const title = document.createElement('span');
    title.className = 'dna-subtitle';
    title.textContent = 'Найденные заголовки';
    const chips = document.createElement('div');
    chips.className = 'dna-heading-chips';
    for (const heading of dna.anatomy.headings) {
      const chip = document.createElement('span');
      chip.textContent = heading.text;
      chip.title = `Строка ${heading.line}`;
      chips.append(chip);
    }
    headingBlock.append(title, chips);
    anatomy.append(headingBlock);
  }

  const molecules = byId('dna-molecules');
  const facts = (dna.molecules?.facts || []).slice(0, 120);
  renderDnaList(molecules, facts, 'Структурированные молекулы не найдены.', (fact) => {
    const row = document.createElement('article');
    row.className = 'dna-fact';
    const type = document.createElement('span');
    type.className = 'dna-fact-type';
    type.textContent = fact.label;
    const body = document.createElement('div');
    const value = document.createElement('strong');
    value.textContent = fact.value;
    const source = document.createElement('small');
    source.textContent = fact.source?.line ? `Строка ${fact.source.line} · уверенность ${Math.round((fact.confidence || 0) * 100)}%` : 'Источник сохранён';
    if (fact.source?.excerpt) source.title = fact.source.excerpt;
    body.append(value, source);
    row.append(type, body);
    return row;
  });
  if ((dna.molecules?.facts || []).length > facts.length) {
    const note = document.createElement('p');
    note.className = 'dna-limit-note';
    note.textContent = `Показаны первые ${facts.length} из ${dna.molecules.facts.length} молекул.`;
    molecules.append(note);
  }

  const entities = byId('dna-entities');
  renderDnaList(entities, (dna.entities || []).slice(0, 100), 'Кандидаты сущностей пока не выделены.', (entity) => {
    const row = document.createElement('article');
    row.className = 'dna-entity';
    const category = document.createElement('span');
    category.textContent = entity.category;
    const body = document.createElement('div');
    const value = document.createElement('strong');
    value.textContent = entity.value;
    const role = document.createElement('small');
    role.textContent = `${entity.role} · ${Math.round((entity.confidence || 0) * 100)}%`;
    body.append(value, role);
    row.append(category, body);
    return row;
  });

  const checks = byId('dna-checks');
  renderDnaList(checks, dna.checks || [], 'Замечаний нет.', (check) => {
    const row = document.createElement('article');
    row.className = `dna-check ${check.level || 'info'}`;
    const marker = document.createElement('span');
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = check.title;
    const message = document.createElement('p');
    message.textContent = check.message;
    body.append(title, message);
    row.append(marker, body);
    return row;
  });

  const relations = byId('dna-relations');
  relations.replaceChildren();
  const relationNote = document.createElement('div');
  relationNote.className = 'dna-relation-note';
  const relationTitle = document.createElement('strong');
  relationTitle.textContent = dna.relations?.status || 'Связи';
  const relationText = document.createElement('p');
  relationText.textContent = dna.relations?.note || 'Связи будут показаны после проверки.';
  relationNote.append(relationTitle, relationText);
  relations.append(relationNote);

  const method = byId('dna-method-note');
  method.textContent = dna.method?.note || '';
  method.classList.toggle('hidden', !method.textContent);
}

async function loadViewerDna(fileId, force = false) {
  if (!force && viewerDnaLoadedFor === fileId) return;
  const button = byId('dna-reanalyze');
  button.disabled = true;
  if (!force) {
    byId('dna-document-type').textContent = 'Изучение документа…';
    byId('dna-summary').textContent = 'Саюри разбирает структуру и молекулы документа.';
  }
  try {
    let response;
    if (force) {
      response = await fetch(`/api/disk/files/${encodeURIComponent(fileId)}/dna/analyze`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
      });
    } else {
      response = await fetch(`/api/disk/files/${encodeURIComponent(fileId)}/dna`, {cache: 'no-store'});
    }
    const dna = await response.json();
    if (!response.ok) throw new Error(dna?.error?.message || `HTTP ${response.status}`);
    viewerDnaLoadedFor = fileId;
    renderDocumentDna(dna);
  } finally {
    button.disabled = false;
  }
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
    const dnaTab = document.querySelector('[data-viewer-tab="dna"]');
    previewTab.classList.toggle('hidden', kind !== 'file');
    dnaTab.classList.toggle('hidden', kind !== 'file');
    viewerDnaLoadedFor = null;
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
  viewerDnaLoadedFor = null;
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

function showPhoneMessage(text, kind = 'ready') {
  const target = byId('phone-message');
  target.className = `phone-message ${kind}`;
  target.textContent = text;
}

function hidePhoneMessage() {
  byId('phone-message').className = 'phone-message hidden';
  byId('phone-message').textContent = '';
}

function showPhoneError(error) {
  showPhoneMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
}

function phoneDeviceLabel(device) {
  return device.model || device.product || device.device || device.serial;
}

function phoneStatusActive() {
  return phoneState.viewActive || phoneState.floatingOpen;
}

function phoneStreamActive() {
  return phoneState.floatingOpen && !phoneState.floatingMinimized;
}

function stopPhoneFrameLoop() {
  phoneState.frameGeneration += 1;
  if (phoneState.frameTimer) {
    window.clearTimeout(phoneState.frameTimer);
    phoneState.frameTimer = null;
  }
  phoneState.frameLoading = false;
}

function stopPhoneH264Stream() {
  phoneState.h264Generation += 1;
  if (phoneState.h264Abort) {
    phoneState.h264Abort.abort();
    phoneState.h264Abort = null;
  }
  if (phoneState.h264Decoder) {
    try {
      phoneState.h264Decoder.close();
    } catch {}
    phoneState.h264Decoder = null;
  }
  phoneState.h264Width = 0;
  phoneState.h264Height = 0;
  phoneState.h264Frames = 0;
  phoneState.h264StartedAt = 0;
  if (phoneState.videoMode === 'h264') phoneState.videoMode = 'png';
  const canvas = byId('phone-video-canvas');
  canvas.classList.add('hidden');
  canvas.style.width = '';
  canvas.style.height = '';
  canvas.style.transform = '';
  byId('phone-screen-shell').classList.remove('h264-active');
  byId('phone-live-badge').classList.remove('h264');
}

function stopPhoneVideo() {
  stopPhoneH264Stream();
  stopPhoneFrameLoop();
}

function stopPhoneReconnectLoop() {
  if (phoneState.reconnectTimer) {
    window.clearTimeout(phoneState.reconnectTimer);
    phoneState.reconnectTimer = null;
  }
}

function schedulePhoneReconnect(delay = 2500) {
  if (!phoneStatusActive() || phoneState.selectedSerial) return;
  stopPhoneReconnectLoop();
  phoneState.reconnectTimer = window.setTimeout(async () => {
    phoneState.reconnectTimer = null;
    if (!phoneStatusActive() || phoneState.selectedSerial) return;
    try {
      await loadPhone();
    } catch (error) {
      byId('phone-frame-status').textContent =
        `Ожидание телефона: ${error instanceof Error ? error.message : String(error)}`;
      schedulePhoneReconnect(3500);
    }
  }, delay);
}

function clearPhoneFrameImage() {
  const image = byId('phone-screen');
  const canvas = byId('phone-video-canvas');
  image.classList.add('hidden');
  image.removeAttribute('src');
  image.style.width = '';
  image.style.height = '';
  canvas.classList.add('hidden');
  canvas.style.width = '';
  canvas.style.height = '';
  canvas.style.transform = '';
  byId('phone-screen-shell').classList.remove('h264-active');
  byId('phone-screen-placeholder').classList.remove('hidden');
  if (phoneState.frameUrl) {
    URL.revokeObjectURL(phoneState.frameUrl);
    phoneState.frameUrl = null;
  }
}

function handlePhoneDisconnected(message = 'Телефон отключён.') {
  stopPhoneVideo();
  stopPhoneAudio();
  stopPhoneCompanionPolling();
  phoneState.selectedSerial = null;
  phoneState.selectedDevice = null;
  phoneState.pointer = null;
  clearPhoneFrameImage();

  byId('phone-selected-device').textContent = '—';
  byId('phone-live-title').textContent = 'Телефон Sayuri';
  byId('phone-live-subtitle').textContent = 'Sayuri ждёт повторного подключения Android';
  byId('phone-live-badge').textContent = 'ОТКЛЮЧЁН';
  byId('phone-live-badge').classList.remove('live');
  byId('phone-frame-status').textContent = message;
  byId('phone-open-native').disabled = true;
  document.querySelectorAll('[data-phone-key]').forEach((button) => {
    button.disabled = true;
  });
  showPhoneMessage(
    'Связь с телефоном потеряна. Проверьте USB-кабель или отладку — Sayuri подключится снова автоматически.',
    'error'
  );
  schedulePhoneReconnect(1200);
}

function schedulePhoneFrame(delay = 420) {
  if (!phoneStreamActive() || !phoneState.selectedSerial) return;
  if (phoneState.nativeSessions.has(phoneState.selectedSerial)) return;
  if (phoneState.frameTimer) window.clearTimeout(phoneState.frameTimer);
  phoneState.frameTimer = window.setTimeout(() => refreshPhoneFrame(), delay);
}

function activePhoneSurface() {
  const canvas = byId('phone-video-canvas');
  if (!canvas.classList.contains('hidden') && canvas.width && canvas.height) {
    return {
      element: canvas,
      width: canvas.width,
      height: canvas.height
    };
  }
  const image = byId('phone-screen');
  if (!image.classList.contains('hidden') && image.naturalWidth && image.naturalHeight) {
    return {
      element: image,
      width: image.naturalWidth,
      height: image.naturalHeight
    };
  }
  return null;
}

function fitPhoneImage() {
  const surface = activePhoneSurface();
  const stage = byId('phone-screen-shell');
  if (!surface) return;

  const stageWidth = Math.max(1, stage.clientWidth - 18);
  const stageHeight = Math.max(1, stage.clientHeight - 18);
  const sideways = phoneState.rotation === 90 || phoneState.rotation === 270;
  const visualWidth = sideways ? surface.height : surface.width;
  const visualHeight = sideways ? surface.width : surface.height;
  const scale = Math.min(stageWidth / visualWidth, stageHeight / visualHeight);

  surface.element.style.width = `${Math.max(1, surface.width * scale)}px`;
  surface.element.style.height = `${Math.max(1, surface.height * scale)}px`;
  surface.element.style.transform = `rotate(${phoneState.rotation}deg)`;
  byId('phone-rotation-state').textContent = `${phoneState.rotation}°`;
}


function readPhoneStreamExact(readerState, size) {
  return (async () => {
    while (readerState.length < size) {
      const {value, done} = await readerState.reader.read();
      if (done) throw new Error('Поток телефона завершился.');
      if (!value?.length) continue;
      readerState.chunks.push(value);
      readerState.length += value.length;
    }

    const output = new Uint8Array(size);
    let offset = 0;
    while (offset < size) {
      const chunk = readerState.chunks[0];
      const take = Math.min(chunk.length, size - offset);
      output.set(chunk.subarray(0, take), offset);
      offset += take;
      readerState.length -= take;
      if (take === chunk.length) {
        readerState.chunks.shift();
      } else {
        readerState.chunks[0] = chunk.subarray(take);
      }
    }
    return output;
  })();
}

function phoneReadUint32(bytes, offset = 0) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(offset, false);
}

function phoneReadUint64(bytes, offset = 0) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (typeof view.getBigUint64 === 'function') return Number(view.getBigUint64(offset, false));
  return view.getUint32(offset, false) * 4294967296 + view.getUint32(offset + 4, false);
}

function findH264SpsCodec(data) {
  for (let i = 0; i + 7 < data.length; i += 1) {
    let nal = -1;
    if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1) {
      nal = i + 3;
    } else if (
      data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 0 && data[i + 3] === 1
    ) {
      nal = i + 4;
    }
    if (nal < 0 || nal + 3 >= data.length || (data[nal] & 0x1f) !== 7) continue;
    const hex = (value) => value.toString(16).padStart(2, '0');
    return `avc1.${hex(data[nal + 1])}${hex(data[nal + 2])}${hex(data[nal + 3])}`;
  }
  return null;
}

function configurePhoneVideoDecoder(payload, generation) {
  if (phoneState.h264Decoder) return phoneState.h264Decoder;
  const codec = findH264SpsCodec(payload);
  if (!codec) throw new Error('В первом H.264 keyframe не найден SPS.');

  const canvas = byId('phone-video-canvas');
  const context = canvas.getContext('2d', {alpha: false, desynchronized: true});
  if (!context) throw new Error('Canvas 2D недоступен.');

  const decoder = new VideoDecoder({
    output(frame) {
      try {
        if (generation !== phoneState.h264Generation || !phoneStreamActive()) return;
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
          fitPhoneImage();
        }
        context.drawImage(frame, 0, 0, canvas.width, canvas.height);
        phoneState.h264Frames += 1;
        if (!phoneState.h264StartedAt) phoneState.h264StartedAt = performance.now();
        const elapsed = Math.max(1, performance.now() - phoneState.h264StartedAt);
        const fps = Math.min(120, phoneState.h264Frames * 1000 / elapsed);
        byId('phone-frame-status').textContent =
          `H.264 · ${canvas.width}×${canvas.height} · ~${fps.toFixed(0)} FPS`;
        byId('phone-live-badge').textContent = phoneState.qualityProfile === 'economy' ? 'H264 30' : 'H264 60';
        byId('phone-live-badge').classList.add('live', 'h264');
      } finally {
        frame.close();
      }
    },
    error(error) {
      if (generation !== phoneState.h264Generation) return;
      fallbackPhoneVideo(`WebCodecs: ${error?.message || String(error)}`);
    }
  });

  decoder.configure({
    codec,
    codedWidth: phoneState.h264Width || undefined,
    codedHeight: phoneState.h264Height || undefined,
    hardwareAcceleration: 'prefer-hardware',
    optimizeForLatency: true
  });
  phoneState.h264Decoder = decoder;
  return decoder;
}

async function consumePhoneH264Stream(response, generation) {
  if (!response.body) throw new Error('Браузер не поддерживает streaming fetch.');
  const readerState = {
    reader: response.body.getReader(),
    chunks: [],
    length: 0
  };

  const magic = await readPhoneStreamExact(readerState, 4);
  if (String.fromCharCode(...magic) !== 'SYH1') {
    throw new Error('Неизвестный протокол H.264 Sayuri.');
  }

  while (generation === phoneState.h264Generation && phoneStreamActive()) {
    const typeBytes = await readPhoneStreamExact(readerState, 1);
    const type = typeBytes[0];

    if (type === 1) {
      const payload = await readPhoneStreamExact(readerState, 8);
      phoneState.h264Width = phoneReadUint32(payload, 0);
      phoneState.h264Height = phoneReadUint32(payload, 4);
      if (!phoneState.h264Width || !phoneState.h264Height) {
        throw new Error('Некорректный размер H.264 сессии.');
      }
      const canvas = byId('phone-video-canvas');
      canvas.width = phoneState.h264Width;
      canvas.height = phoneState.h264Height;
      byId('phone-screen').classList.add('hidden');
      byId('phone-screen-placeholder').classList.add('hidden');
      canvas.classList.remove('hidden');
      byId('phone-screen-shell').classList.add('h264-active');
      fitPhoneImage();
      continue;
    }

    if (type !== 2) throw new Error(`Неизвестная запись H.264: ${type}`);
    const header = await readPhoneStreamExact(readerState, 13);
    const flags = header[0];
    const pts = phoneReadUint64(header, 1);
    const size = phoneReadUint32(header, 9);
    if (!size || size > 32 * 1024 * 1024) throw new Error('Некорректный размер H.264 кадра.');
    const payload = await readPhoneStreamExact(readerState, size);

    const decoder = configurePhoneVideoDecoder(payload, generation);
    const key = Boolean(flags & 1);
    if (!key && decoder.decodeQueueSize > 3) continue;
    decoder.decode(new EncodedVideoChunk({
      type: key ? 'key' : 'delta',
      timestamp: pts,
      data: payload
    }));
  }
}

function stopPhoneAudio({keepPreference = false} = {}) {
  phoneState.audioGeneration += 1;
  if (phoneState.audioAbort) {
    phoneState.audioAbort.abort();
    phoneState.audioAbort = null;
  }
  if (phoneState.audioDecoder) {
    try {
      phoneState.audioDecoder.close();
    } catch {}
    phoneState.audioDecoder = null;
  }
  if (phoneState.audioContext) {
    const context = phoneState.audioContext;
    phoneState.audioContext = null;
    context.close().catch(() => {});
  }
  phoneState.audioNextTime = 0;
  phoneState.audioPackets = 0;
  if (!keepPreference) phoneState.audioEnabled = false;
  const button = byId('phone-audio');
  if (button) {
    button.classList.remove('active');
    button.textContent = 'Звук: выкл';
  }
}

function canUsePhoneAudio() {
  return Boolean(
    phoneState.audioAvailable
    && typeof window.AudioDecoder === 'function'
    && typeof window.EncodedAudioChunk === 'function'
    && (window.AudioContext || window.webkitAudioContext)
    && window.ReadableStream
  );
}

function parsePhoneOpusHead(payload) {
  if (payload.length < 19) throw new Error('Некорректный OpusHead.');
  const signature = String.fromCharCode(...payload.subarray(0, 8));
  if (signature !== 'OpusHead') throw new Error('OpusHead не найден.');
  const channels = payload[9];
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  const sampleRate = view.getUint32(12, true) || 48000;
  if (!channels || channels > 8) throw new Error('Некорректное число Opus-каналов.');
  return {channels, sampleRate};
}

function playPhoneAudioData(audioData, generation) {
  try {
    if (
      generation !== phoneState.audioGeneration
      || !phoneState.audioEnabled
      || !phoneState.audioContext
    ) return;

    const context = phoneState.audioContext;
    const channels = audioData.numberOfChannels;
    const frames = audioData.numberOfFrames;
    const buffer = context.createBuffer(channels, frames, audioData.sampleRate);

    for (let channel = 0; channel < channels; channel += 1) {
      audioData.copyTo(buffer.getChannelData(channel), {
        planeIndex: channel,
        format: 'f32-planar'
      });
    }

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    const now = context.currentTime;
    if (
      !phoneState.audioNextTime
      || phoneState.audioNextTime < now - 0.05
      || phoneState.audioNextTime > now + 0.30
    ) {
      phoneState.audioNextTime = now + 0.035;
    }
    source.start(phoneState.audioNextTime);
    phoneState.audioNextTime += buffer.duration;
  } finally {
    audioData.close();
  }
}

function configurePhoneAudioDecoder(opusHead, generation) {
  if (phoneState.audioDecoder) return phoneState.audioDecoder;
  const {channels, sampleRate} = parsePhoneOpusHead(opusHead);

  const decoder = new AudioDecoder({
    output(audioData) {
      playPhoneAudioData(audioData, generation);
    },
    error(error) {
      if (generation !== phoneState.audioGeneration) return;
      stopPhoneAudio();
      byId('phone-frame-status').textContent =
        `Видео работает · звук отключён: ${error?.message || String(error)}`;
    }
  });

  decoder.configure({
    codec: 'opus',
    sampleRate,
    numberOfChannels: channels,
    description: opusHead
  });
  phoneState.audioDecoder = decoder;
  return decoder;
}

async function consumePhoneOpusStream(response, generation) {
  if (!response.body) throw new Error('Браузер не поддерживает streaming audio fetch.');
  const readerState = {
    reader: response.body.getReader(),
    chunks: [],
    length: 0
  };

  const magic = await readPhoneStreamExact(readerState, 4);
  if (String.fromCharCode(...magic) !== 'SYA1') {
    throw new Error('Неизвестный аудиопротокол Sayuri.');
  }

  while (
    generation === phoneState.audioGeneration
    && phoneState.audioEnabled
    && phoneStreamActive()
  ) {
    const typeBytes = await readPhoneStreamExact(readerState, 1);
    const type = typeBytes[0];

    if (type === 1) {
      const lengthBytes = await readPhoneStreamExact(readerState, 4);
      const size = phoneReadUint32(lengthBytes, 0);
      if (!size || size > 64 * 1024) throw new Error('Некорректный Opus config.');
      const opusHead = await readPhoneStreamExact(readerState, size);
      configurePhoneAudioDecoder(opusHead, generation);
      continue;
    }

    if (type !== 2) throw new Error(`Неизвестная запись Opus: ${type}`);
    const header = await readPhoneStreamExact(readerState, 12);
    const pts = phoneReadUint64(header, 0);
    const size = phoneReadUint32(header, 8);
    if (!size || size > 2 * 1024 * 1024) throw new Error('Некорректный размер Opus пакета.');
    const payload = await readPhoneStreamExact(readerState, size);

    if (!phoneState.audioDecoder) {
      throw new Error('Opus media получен до конфигурации.');
    }
    if (phoneState.audioDecoder.decodeQueueSize > 10) continue;
    phoneState.audioDecoder.decode(new EncodedAudioChunk({
      type: 'key',
      timestamp: pts,
      data: payload
    }));
    phoneState.audioPackets += 1;
  }
}

async function startPhoneAudio() {
  if (!phoneState.selectedSerial || !phoneStreamActive()) return;
  if (!canUsePhoneAudio()) {
    throw new Error('Этот браузер не поддерживает WebCodecs AudioDecoder/Opus.');
  }

  stopPhoneAudio({keepPreference: true});
  phoneState.audioEnabled = true;
  const generation = phoneState.audioGeneration;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextClass({latencyHint: 'interactive'});
  phoneState.audioContext = context;
  await context.resume();

  const controller = new AbortController();
  phoneState.audioAbort = controller;
  const button = byId('phone-audio');
  button.classList.add('active');
  button.textContent = 'Звук: вкл';

  try {
    const response = await fetch(
      `/api/phone/audio?serial=${encodeURIComponent(phoneState.selectedSerial)}`,
      {cache: 'no-store', signal: controller.signal}
    );
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      let code = null;
      try {
        const data = await response.json();
        message = data?.error?.message || message;
        code = data?.error?.code || null;
      } catch {}
      if (response.status === 409 || code === 'SAYURI-PHONE-409') {
        handlePhoneDisconnected(message);
        return;
      }
      throw new Error(message);
    }
    await consumePhoneOpusStream(response, generation);
    if (
      generation === phoneState.audioGeneration
      && phoneState.audioEnabled
      && phoneStreamActive()
    ) {
      throw new Error('Аудиопоток завершился.');
    }
  } catch (error) {
    if (controller.signal.aborted || generation !== phoneState.audioGeneration) return;
    stopPhoneAudio();
    throw error;
  }
}

async function togglePhoneAudio() {
  if (!phoneState.selectedSerial) return;
  if (phoneState.audioEnabled) {
    stopPhoneAudio();
    byId('phone-frame-status').textContent = 'Звук телефона выключен';
    return;
  }
  try {
    await startPhoneAudio();
  } catch (error) {
    showPhoneError(error);
  }
}

function canUsePhoneH264() {
  return Boolean(
    phoneState.h264Available
    && typeof window.VideoDecoder === 'function'
    && typeof window.EncodedVideoChunk === 'function'
    && window.ReadableStream
  );
}

async function startPhoneH264Stream() {
  stopPhoneVideo();
  if (!phoneStreamActive() || !phoneState.selectedSerial || !canUsePhoneH264()) {
    startPhoneFrameLoop();
    return;
  }
  if (phoneState.nativeSessions.has(phoneState.selectedSerial)) return;

  const generation = phoneState.h264Generation;
  const controller = new AbortController();
  phoneState.h264Abort = controller;
  phoneState.videoMode = 'h264';
  phoneState.h264Frames = 0;
  phoneState.h264StartedAt = 0;
  byId('phone-frame-status').textContent = 'Запускаю H.264 поток…';
  byId('phone-live-badge').textContent = 'H264';
  byId('phone-live-badge').classList.add('h264');

  try {
    const response = await fetch(
      `/api/phone/stream?serial=${encodeURIComponent(phoneState.selectedSerial)}&profile=${encodeURIComponent(phoneState.qualityProfile)}`,
      {cache: 'no-store', signal: controller.signal}
    );
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      let code = null;
      try {
        const data = await response.json();
        message = data?.error?.message || message;
        code = data?.error?.code || null;
      } catch {}
      if (response.status === 409 || code === 'SAYURI-PHONE-409') {
        handlePhoneDisconnected(message);
        return;
      }
      throw new Error(message);
    }
    await consumePhoneH264Stream(response, generation);
    if (generation === phoneState.h264Generation && phoneStreamActive()) {
      throw new Error('H.264 поток завершился.');
    }
  } catch (error) {
    if (controller.signal.aborted || generation !== phoneState.h264Generation) return;
    fallbackPhoneVideo(error instanceof Error ? error.message : String(error));
  }
}

function fallbackPhoneVideo(reason) {
  stopPhoneH264Stream();
  if (!phoneStreamActive() || !phoneState.selectedSerial) return;
  phoneState.videoMode = 'png';
  byId('phone-frame-status').textContent = `PNG fallback · ${reason}`;
  byId('phone-live-badge').textContent = 'PNG';
  byId('phone-live-badge').classList.remove('h264');
  startPhoneFrameLoop();
}

function startPreferredPhoneVideo() {
  stopPhoneVideo();
  if (!phoneStreamActive() || !phoneState.selectedSerial) return;
  if (phoneState.nativeSessions.has(phoneState.selectedSerial)) {
    byId('phone-frame-status').textContent = 'Встроенный экран на паузе: открыт scrcpy 60 FPS';
    byId('phone-live-badge').textContent = '60 FPS';
    byId('phone-live-badge').classList.remove('live', 'h264');
    return;
  }
  if (canUsePhoneH264()) {
    startPhoneH264Stream();
  } else {
    phoneState.videoMode = 'png';
    startPhoneFrameLoop();
  }
}

async function refreshPhoneFrame() {
  if (!phoneStreamActive() || !phoneState.selectedSerial || phoneState.frameLoading) return;
  const generation = phoneState.frameGeneration;
  const serial = phoneState.selectedSerial;
  phoneState.frameLoading = true;
  try {
    const response = await fetch(
      `/api/phone/frame?serial=${encodeURIComponent(serial)}&t=${Date.now()}`,
      {cache: 'no-store'}
    );
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      let code = null;
      try {
        const data = await response.json();
        message = data?.error?.message || message;
        code = data?.error?.code || null;
      } catch {}
      if (response.status === 409 || code === 'SAYURI-PHONE-409') {
        handlePhoneDisconnected(message);
        return;
      }
      throw new Error(message);
    }

    const blob = await response.blob();
    if (generation !== phoneState.frameGeneration || serial !== phoneState.selectedSerial) return;

    const nextUrl = URL.createObjectURL(blob);
    const image = byId('phone-screen');
    const previousUrl = phoneState.frameUrl;
    image.onload = () => {
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      byId('phone-screen-placeholder').classList.add('hidden');
      image.classList.remove('hidden');
      fitPhoneImage();
    };
    image.src = nextUrl;
    phoneState.frameUrl = nextUrl;
    phoneState.lastFrameAt = Date.now();

    const width = response.headers.get('X-Sayuri-Phone-Width');
    const height = response.headers.get('X-Sayuri-Phone-Height');
    byId('phone-frame-status').textContent = width && height
      ? `LIVE · ${width}×${height}`
      : 'LIVE · локально';
    byId('phone-live-badge').textContent = 'LIVE';
    byId('phone-live-badge').classList.add('live');
    schedulePhoneFrame(420);
  } catch (error) {
    if (generation !== phoneState.frameGeneration) return;
    byId('phone-frame-status').textContent =
      `Кадр временно недоступен: ${error instanceof Error ? error.message : String(error)}`;
    byId('phone-live-badge').textContent = 'ПОВТОР';
    byId('phone-live-badge').classList.remove('live');
    schedulePhoneFrame(1800);
  } finally {
    phoneState.frameLoading = false;
  }
}

function startPhoneFrameLoop() {
  stopPhoneFrameLoop();
  if (!phoneStreamActive() || !phoneState.selectedSerial) return;
  if (phoneState.nativeSessions.has(phoneState.selectedSerial)) {
    byId('phone-frame-status').textContent = 'Встроенный экран на паузе: открыт режим 60 FPS';
    byId('phone-live-badge').textContent = '60 FPS';
    byId('phone-live-badge').classList.remove('live');
    return;
  }
  byId('phone-frame-status').textContent = 'Получаю экран телефона…';
  schedulePhoneFrame(0);
}

function selectedPhoneDevice(devices) {
  const authorized = devices.filter((device) => device.authorized);
  if (!authorized.length) return null;
  const existing = authorized.find((device) => device.serial === phoneState.selectedSerial);
  return existing || authorized[0];
}

function updatePhoneFloatingState() {
  const device = phoneState.selectedDevice;
  const nativeButton = byId('phone-open-native');
  const keyButtons = document.querySelectorAll('[data-phone-key]');
  const proControls = document.querySelectorAll(
    '#phone-quality-profile, #phone-capture, #phone-record, #phone-audio, #phone-paste, #phone-copy, #phone-file, #phone-apps'
  );

  if (!device) {
    stopPhoneVideo();
    stopPhoneAudio();
    phoneState.selectedSerial = null;
    phoneState.selectedDevice = null;
    byId('phone-selected-device').textContent = '—';
    byId('phone-live-title').textContent = 'Телефон Sayuri';
    byId('phone-live-subtitle').textContent = 'Ожидание устройства';
    byId('phone-live-badge').textContent = 'ОЖИДАНИЕ';
    byId('phone-live-badge').classList.remove('live');
    byId('phone-frame-status').textContent = 'Sayuri ждёт авторизованное устройство';
    nativeButton.disabled = true;
    keyButtons.forEach((button) => { button.disabled = true; });
    proControls.forEach((control) => { control.disabled = true; });
    byId('phone-app-drawer').classList.add('hidden');
    clearPhoneFrameImage();
    schedulePhoneReconnect(2500);
    return;
  }

  stopPhoneReconnectLoop();
  phoneState.selectedSerial = device.serial;
  byId('phone-selected-device').textContent = phoneDeviceLabel(device);
  byId('phone-live-title').textContent = phoneDeviceLabel(device);
  byId('phone-live-subtitle').textContent =
    `${device.connection === 'wifi' ? 'Wi-Fi' : 'USB'} · ${device.serial}`;
  nativeButton.disabled = false;
  proControls.forEach((control) => { control.disabled = false; });
  byId('phone-audio').disabled = !phoneState.audioAvailable;

  const nativeOpen = phoneState.nativeSessions.has(device.serial);
  nativeButton.textContent = nativeOpen ? 'СТОП 60 FPS' : '60 FPS';
  keyButtons.forEach((button) => { button.disabled = false; });

  const recording = phoneState.recordingSessions.has(device.serial);
  const recordButton = byId('phone-record');
  recordButton.classList.toggle('recording', recording);
  recordButton.textContent = recording ? '■ Стоп' : '● Запись';

  if (nativeOpen) {
    stopPhoneVideo();
    stopPhoneAudio();
    byId('phone-frame-status').textContent = 'Пауза встроенного экрана: открыт scrcpy 60 FPS';
    byId('phone-live-badge').textContent = '60 FPS';
    byId('phone-live-badge').classList.remove('live');
  } else if (
    phoneStreamActive()
    && !phoneState.frameTimer
    && !phoneState.h264Abort
  ) {
    startPreferredPhoneVideo();
  }
}

function selectPhone(device) {
  if (!device?.authorized) return;
  const changed = phoneState.selectedSerial !== device.serial;
  if (changed && phoneState.audioEnabled) stopPhoneAudio();
  stopPhoneReconnectLoop();
  phoneState.selectedSerial = device.serial;
  phoneState.selectedDevice = device;
  updatePhoneFloatingState();
  document.querySelectorAll('.phone-device-card').forEach((card) => {
    card.classList.toggle('selected', card.dataset.serial === device.serial);
  });
  if (changed && phoneStreamActive()) startPreferredPhoneVideo();
}

function renderPhone(data) {
  const runtime = data.runtime || {};
  const devices = Array.isArray(data.devices) ? data.devices : [];
  const sessions = new Set(data.control_sessions || []);
  phoneState.nativeSessions = sessions;
  phoneState.recordingSessions = new Set(data.recording_sessions || []);
  phoneState.h264Available = Boolean(data.capabilities?.embedded_h264_stream);
  phoneState.audioAvailable = Boolean(data.capabilities?.embedded_audio);
  if (!phoneState.audioAvailable && phoneState.audioEnabled) {
    stopPhoneAudio();
  }

  byId('phone-runtime-state').textContent = runtime.ready ? 'ГОТОВ' : 'НЕ УСТАНОВЛЕН';
  byId('phone-runtime-detail').textContent = runtime.ready
    ? `scrcpy ${data.backend_version} · ADB готов`
    : 'Нужен локальный scrcpy / ADB runtime';
  byId('phone-device-count').textContent = String(devices.length);
  byId('phone-device-detail').textContent = `авторизовано: ${data.authorized_devices || 0}`;
  byId('phone-control-state').textContent = sessions.size
    ? '60 FPS'
    : (phoneState.floatingOpen && data.authorized_devices ? 'ПЛАВАЕТ' : (data.authorized_devices ? 'ГОТОВО' : 'ОЖИДАНИЕ'));

  const selected = selectedPhoneDevice(devices);
  const selectedChanged = selected?.serial !== phoneState.selectedSerial;
  phoneState.selectedDevice = selected;
  phoneState.selectedSerial = selected?.serial || null;
  if (selectedChanged) resetPhoneCompanion(phoneState.selectedSerial);

  const launcher = byId('phone-float-launcher');
  launcher.classList.toggle('connected', Boolean(selected));

  const list = byId('phone-device-list');
  list.replaceChildren();

  if (!devices.length) {
    const empty = document.createElement('div');
    empty.className = 'phone-empty';
    const title = document.createElement('strong');
    title.textContent = runtime.ready ? 'Телефон пока не найден' : 'Runtime телефона ещё не готов';
    const copy = document.createElement('p');
    copy.textContent = runtime.ready
      ? 'Подключите Android по USB и подтвердите запрос отладки на самом телефоне.'
      : 'После перезапуска Sayuri переносимый scrcpy/ADB runtime будет подготовлен автоматически на Windows x64.';
    empty.append(title, copy);
    list.append(empty);
    updatePhoneFloatingState();
    return;
  }

  for (const device of devices) {
    const card = document.createElement('article');
    card.dataset.serial = device.serial;
    card.className =
      `phone-device-card ${device.authorized ? 'authorized' : 'blocked'} ${device.serial === phoneState.selectedSerial ? 'selected' : ''}`;

    if (device.authorized) {
      card.tabIndex = 0;
      card.addEventListener('click', (event) => {
        if (!event.target.closest('button')) selectPhone(device);
      });
      card.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectPhone(device);
        }
      });
    }

    const icon = document.createElement('div');
    icon.className = 'phone-device-icon';
    icon.textContent = '▯';

    const info = document.createElement('div');
    info.className = 'phone-device-info';
    const title = document.createElement('strong');
    title.textContent = phoneDeviceLabel(device);
    const serial = document.createElement('code');
    serial.textContent = device.serial;
    const meta = document.createElement('span');
    meta.textContent = device.authorized
      ? `${device.connection === 'wifi' ? 'Wi-Fi' : 'USB'} · доступ разрешён`
      : `Состояние: ${device.state}`;
    info.append(title, serial, meta);

    const actions = document.createElement('div');
    actions.className = 'phone-device-actions';

    if (device.authorized) {
      const openButton = document.createElement('button');
      openButton.type = 'button';
      openButton.className = 'primary-button';
      openButton.textContent = 'Показать';
      openButton.addEventListener('click', () => {
        selectPhone(device);
        openPhoneFloat();
      });
      actions.append(openButton);
    }

    if (device.connection === 'wifi') {
      const disconnectButton = document.createElement('button');
      disconnectButton.type = 'button';
      disconnectButton.className = 'phone-link-button';
      disconnectButton.textContent = 'Отключить Wi-Fi';
      disconnectButton.addEventListener('click', async () => {
        try {
          const result = await postJson('/api/phone/disconnect', {serial: device.serial});
          showPhoneMessage(result.status || 'Отключено');
          await loadPhone();
        } catch (error) {
          showPhoneError(error);
        }
      });
      actions.append(disconnectButton);
    }

    card.append(icon, info, actions);
    list.append(card);
  }

  updatePhoneFloatingState();
  if (selected && phoneStatusActive() && !phoneState.companionTimer) {
    loadPhoneCompanion().catch(() => schedulePhoneCompanionPolling(4000));
  } else if (!selected) {
    renderPhoneCompanionStatus(null);
  }

  if (
    selected
    && phoneStreamActive()
    && !sessions.has(selected.serial)
    && (selectedChanged || (!phoneState.frameTimer && !phoneState.h264Abort))
  ) {
    startPreferredPhoneVideo();
  }
}

async function loadPhone() {
  const response = await fetch('/api/phone', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderPhone(data);
}

function mapPhoneDisplayPoint(rx, ry) {
  const x = Math.max(0, Math.min(1, rx));
  const y = Math.max(0, Math.min(1, ry));
  if (phoneState.rotation === 90) return {x: y, y: 1 - x};
  if (phoneState.rotation === 180) return {x: 1 - x, y: 1 - y};
  if (phoneState.rotation === 270) return {x: 1 - y, y: x};
  return {x, y};
}

function phonePointFromEvent(event) {
  const surface = activePhoneSurface();
  if (!surface) return null;
  const rect = surface.element.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  if (
    event.clientX < rect.left || event.clientX > rect.right
    || event.clientY < rect.top || event.clientY > rect.bottom
  ) return null;

  const rx = (event.clientX - rect.left) / rect.width;
  const ry = (event.clientY - rect.top) / rect.height;
  return mapPhoneDisplayPoint(rx, ry);
}

async function sendPhoneTap(point) {
  if (!phoneState.selectedSerial || !point) return;
  await postJson('/api/phone/input/tap', {
    serial: phoneState.selectedSerial,
    x: point.x,
    y: point.y
  });
  if (phoneState.videoMode === 'png') schedulePhoneFrame(70);
}

async function sendPhoneSwipe(startPoint, endPoint, durationMs) {
  if (!phoneState.selectedSerial || !startPoint || !endPoint) return;
  await postJson('/api/phone/input/swipe', {
    serial: phoneState.selectedSerial,
    x1: startPoint.x,
    y1: startPoint.y,
    x2: endPoint.x,
    y2: endPoint.y,
    duration_ms: Math.max(80, Math.min(1200, durationMs))
  });
  if (phoneState.videoMode === 'png') schedulePhoneFrame(70);
}

async function sendPhoneKey(key) {
  if (!phoneState.selectedSerial) return;
  try {
    await postJson('/api/phone/input/key', {
      serial: phoneState.selectedSerial,
      key
    });
    if (phoneState.videoMode === 'png') schedulePhoneFrame(70);
  } catch (error) {
    showPhoneError(error);
  }
}

async function sendPhoneText(text) {
  if (!phoneState.selectedSerial || !text) return;
  const result = await postJson('/api/phone/input/text', {
    serial: phoneState.selectedSerial,
    text
  });
  if (phoneState.videoMode === 'png') schedulePhoneFrame(70);
  return result;
}

function queuePhoneText(character) {
  phoneState.textBuffer += character;
  if (phoneState.textTimer) window.clearTimeout(phoneState.textTimer);
  phoneState.textTimer = window.setTimeout(async () => {
    const text = phoneState.textBuffer;
    phoneState.textBuffer = '';
    phoneState.textTimer = null;
    if (!text) return;
    try {
      await sendPhoneText(text);
    } catch (error) {
      showPhoneError(error);
    }
  }, 80);
}

async function toggleNativePhoneWindow() {
  if (!phoneState.selectedSerial) return;
  const nativeOpen = phoneState.nativeSessions.has(phoneState.selectedSerial);
  if (!nativeOpen) {
    stopPhoneVideo();
    stopPhoneAudio();
  }
  try {
    const result = await postJson(
      nativeOpen ? '/api/phone/control/stop' : '/api/phone/control/start',
      {
        serial: phoneState.selectedSerial,
        profile: phoneState.qualityProfile
      }
    );
    showPhoneMessage(result.status || 'Готово');
    await loadPhone();
  } catch (error) {
    showPhoneError(error);
  }
}

function defaultPhoneFloatLayout() {
  return {
    left: Math.max(16, window.innerWidth - 420),
    top: 84,
    width: 370,
    height: Math.min(760, Math.max(520, window.innerHeight - 120))
  };
}

function loadPhoneFloatLayout() {
  const fallback = defaultPhoneFloatLayout();
  try {
    const saved = JSON.parse(localStorage.getItem('sayuri-phone-float-layout') || '{}');
    return {
      left: Number.isFinite(saved.left) ? saved.left : fallback.left,
      top: Number.isFinite(saved.top) ? saved.top : fallback.top,
      width: Number.isFinite(saved.width) ? saved.width : fallback.width,
      height: Number.isFinite(saved.height) ? saved.height : fallback.height
    };
  } catch {
    return fallback;
  }
}

function clampPhoneFloat() {
  const floating = byId('phone-float');
  const rect = floating.getBoundingClientRect();
  const maxLeft = Math.max(8, window.innerWidth - Math.min(rect.width, window.innerWidth - 16) - 8);
  const maxTop = Math.max(8, window.innerHeight - Math.min(rect.height, window.innerHeight - 16) - 8);
  const left = Math.max(8, Math.min(maxLeft, parseFloat(floating.style.left) || rect.left || 8));
  const top = Math.max(8, Math.min(maxTop, parseFloat(floating.style.top) || rect.top || 8));
  floating.style.left = `${left}px`;
  floating.style.top = `${top}px`;
}

function savePhoneFloatLayout() {
  const floating = byId('phone-float');
  if (floating.classList.contains('hidden') || phoneState.floatingMinimized) return;
  const rect = floating.getBoundingClientRect();
  localStorage.setItem('sayuri-phone-float-layout', JSON.stringify({
    left: Math.round(rect.left),
    top: Math.round(rect.top),
    width: Math.round(rect.width),
    height: Math.round(rect.height)
  }));
}

function applyPhoneRotation() {
  if (![0, 90, 180, 270].includes(phoneState.rotation)) phoneState.rotation = 0;
  localStorage.setItem('sayuri-phone-rotation', String(phoneState.rotation));
  byId('phone-rotation-state').textContent = `${phoneState.rotation}°`;
  fitPhoneImage();
}

function rotatePhoneFloat() {
  phoneState.rotation = (phoneState.rotation + 90) % 360;
  applyPhoneRotation();
}

function openPhoneFloat() {
  const floating = byId('phone-float');
  phoneState.floatingOpen = true;
  phoneState.floatingMinimized = false;
  localStorage.setItem('sayuri-phone-float-open', '1');
  floating.classList.remove('hidden', 'minimized');
  byId('phone-float-launcher').classList.add('hidden');

  const layout = loadPhoneFloatLayout();
  floating.style.left = `${layout.left}px`;
  floating.style.top = `${layout.top}px`;
  floating.style.width = `${layout.width}px`;
  floating.style.height = `${layout.height}px`;
  clampPhoneFloat();
  applyPhoneRotation();

  loadPhone()
    .then(() => {
      if (phoneState.selectedSerial) startPreferredPhoneVideo();
      else schedulePhoneReconnect(600);
    })
    .catch(showPhoneError);
}

function closePhoneFloat() {
  savePhoneFloatLayout();
  phoneState.floatingOpen = false;
  phoneState.floatingMinimized = false;
  localStorage.setItem('sayuri-phone-float-open', '0');
  byId('phone-float').classList.add('hidden');
  byId('phone-float-launcher').classList.remove('hidden');
  stopPhoneVideo();
  stopPhoneAudio();
  if (!phoneState.viewActive) {
    stopPhoneReconnectLoop();
    stopPhoneCompanionPolling();
  }
}

function togglePhoneFloatMinimize() {
  const floating = byId('phone-float');
  phoneState.floatingMinimized = !phoneState.floatingMinimized;
  floating.classList.toggle('minimized', phoneState.floatingMinimized);
  byId('phone-float-minimize').textContent = phoneState.floatingMinimized ? '□' : '—';
  byId('phone-float-minimize').title = phoneState.floatingMinimized ? 'Развернуть' : 'Свернуть';
  if (phoneState.floatingMinimized) {
    stopPhoneVideo();
    stopPhoneAudio();
  } else {
    clampPhoneFloat();
    fitPhoneImage();
    startPreferredPhoneVideo();
  }
}

function initializePhoneFloatingWindow() {
  const floating = byId('phone-float');
  const layout = loadPhoneFloatLayout();
  floating.style.left = `${layout.left}px`;
  floating.style.top = `${layout.top}px`;
  floating.style.width = `${layout.width}px`;
  floating.style.height = `${layout.height}px`;
  applyPhoneRotation();
  setPhoneQualityProfile(phoneState.qualityProfile);
  updatePhoneKeyboardCaptureUI();

  if (phoneState.floatingOpen) {
    floating.classList.remove('hidden');
    byId('phone-float-launcher').classList.add('hidden');
    loadPhone().then(startPreferredPhoneVideo).catch(showPhoneError);
  }

  if (window.ResizeObserver) {
    phoneState.resizeObserver = new ResizeObserver(() => {
      fitPhoneImage();
      savePhoneFloatLayout();
    });
    phoneState.resizeObserver.observe(floating);
  }
}

function startPhoneFloatDrag(event) {
  if (event.button !== 0 || event.target.closest('button, input')) return;
  const floating = byId('phone-float');
  const rect = floating.getBoundingClientRect();
  phoneState.drag = {
    pointerId: event.pointerId,
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top
  };
  byId('phone-float-drag').setPointerCapture?.(event.pointerId);
  floating.classList.add('dragging');
  event.preventDefault();
}

function movePhoneFloat(event) {
  if (!phoneState.drag || phoneState.drag.pointerId !== event.pointerId) return;
  const floating = byId('phone-float');
  const rect = floating.getBoundingClientRect();
  const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
  const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
  const left = Math.max(8, Math.min(maxLeft, event.clientX - phoneState.drag.offsetX));
  const top = Math.max(8, Math.min(maxTop, event.clientY - phoneState.drag.offsetY));
  floating.style.left = `${left}px`;
  floating.style.top = `${top}px`;
}

function endPhoneFloatDrag(event) {
  if (!phoneState.drag || phoneState.drag.pointerId !== event.pointerId) return;
  phoneState.drag = null;
  byId('phone-float').classList.remove('dragging');
  savePhoneFloatLayout();
}

function safePhoneKeyboardCharacter(value) {
  return /^[\p{L}\p{N} .,_@+\-]$/u.test(value);
}

function handlePhoneKeyboard(event) {
  if (!phoneState.keyboardCaptured || !phoneState.selectedSerial || event.ctrlKey || event.altKey || event.metaKey) return;
  const keyMap = {
    Backspace: 'DELETE',
    Enter: 'ENTER',
    Escape: 'BACK',
    ArrowUp: 'ARROW_UP',
    ArrowDown: 'ARROW_DOWN',
    ArrowLeft: 'ARROW_LEFT',
    ArrowRight: 'ARROW_RIGHT',
    Tab: 'TAB',
    ' ': 'SPACE'
  };
  const mapped = keyMap[event.key];
  if (mapped) {
    event.preventDefault();
    sendPhoneKey(mapped);
    return;
  }
  if (event.key.length === 1 && safePhoneKeyboardCharacter(event.key)) {
    event.preventDefault();
    queuePhoneText(event.key);
  }
}

function updatePhoneKeyboardCaptureUI() {
  const button = byId('phone-keyboard-capture');
  button.classList.toggle('active', phoneState.keyboardCaptured);
  button.textContent = phoneState.keyboardCaptured ? 'КЛАВ: ТЕЛЕФОН' : 'КЛАВ: SAYURI';
  byId('phone-keyboard-hint').textContent = phoneState.keyboardCaptured
    ? 'Клавиатура ПК захвачена телефоном · Esc = Назад · выключите захват, чтобы печатать в Sayuri'
    : 'Клавиатура Sayuri · включите захват, чтобы печатать с ПК прямо в Android';
}

function togglePhoneKeyboardCapture() {
  phoneState.keyboardCaptured = !phoneState.keyboardCaptured;
  localStorage.setItem('sayuri-phone-keyboard-capture', phoneState.keyboardCaptured ? '1' : '0');
  updatePhoneKeyboardCaptureUI();
  if (phoneState.keyboardCaptured) {
    byId('phone-screen-shell').focus({preventScroll: true});
  }
}

function setPhoneQualityProfile(value, {restart = false} = {}) {
  const allowed = new Set(['economy', 'balanced', 'quality']);
  const next = allowed.has(value) ? value : 'quality';
  const changed = phoneState.qualityProfile !== next;
  phoneState.qualityProfile = next;
  localStorage.setItem('sayuri-phone-quality-profile', phoneState.qualityProfile);
  byId('phone-quality-profile').value = phoneState.qualityProfile;
  if (restart && changed && phoneStreamActive() && phoneState.selectedSerial) {
    startPreferredPhoneVideo();
  }
}

async function capturePhoneToDisk() {
  if (!phoneState.selectedSerial) return;
  const button = byId('phone-capture');
  button.disabled = true;
  try {
    const result = await postJson('/api/phone/capture', {
      serial: phoneState.selectedSerial
    });
    byId('phone-frame-status').textContent = `Снимок сохранён в Диск Sayuri: ${result.file?.name || 'PNG'}`;
  } catch (error) {
    showPhoneError(error);
  } finally {
    button.disabled = false;
  }
}

async function togglePhoneRecording() {
  if (!phoneState.selectedSerial) return;
  const recording = phoneState.recordingSessions.has(phoneState.selectedSerial);
  const button = byId('phone-record');
  button.disabled = true;
  try {
    const result = await postJson(
      recording ? '/api/phone/recording/stop' : '/api/phone/recording/start',
      {
        serial: phoneState.selectedSerial,
        profile: phoneState.qualityProfile,
        audio: true
      }
    );
    byId('phone-frame-status').textContent = recording
      ? `Запись сохранена в Диск Sayuri: ${result.file?.name || result.name || 'MP4'}`
      : 'Запись экрана и звука начата';
    await loadPhone();
  } catch (error) {
    showPhoneError(error);
  } finally {
    button.disabled = false;
  }
}

async function setPhoneClipboard(text, {paste = false} = {}) {
  if (!phoneState.selectedSerial) return;
  return postJson('/api/phone/clipboard', {
    serial: phoneState.selectedSerial,
    text,
    paste
  });
}

async function getPhoneClipboard() {
  if (!phoneState.selectedSerial) return null;
  const response = await fetch(
    `/api/phone/clipboard?serial=${encodeURIComponent(phoneState.selectedSerial)}`,
    {cache: 'no-store'}
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  return data;
}

async function pasteComputerClipboardToPhone() {
  if (!phoneState.selectedSerial) return;
  try {
    if (!navigator.clipboard?.readText) {
      throw new Error('Браузер не разрешает чтение буфера обмена.');
    }
    const text = await navigator.clipboard.readText();
    if (!text) throw new Error('Буфер обмена ПК пуст.');
    const result = await setPhoneClipboard(text, {paste: true});
    byId('phone-frame-status').textContent =
      `ПК→Тел · вставлено символов: ${result.characters ?? text.length}`;
  } catch (error) {
    showPhoneError(error);
  }
}

async function copyPhoneClipboardToComputer() {
  if (!phoneState.selectedSerial) return;
  try {
    const result = await getPhoneClipboard();
    const text = result?.text ?? '';
    if (!navigator.clipboard?.writeText) {
      byId('phone-text-input').value = text;
      throw new Error('Браузер не разрешает запись в буфер ПК; текст помещён в строку ввода.');
    }
    await navigator.clipboard.writeText(text);
    byId('phone-frame-status').textContent =
      `Тел→ПК · скопировано символов: ${result.characters ?? text.length}`;
  } catch (error) {
    showPhoneError(error);
  }
}

async function uploadComputerFileToPhone(file) {
  if (!phoneState.selectedSerial || !file) return;
  const response = await fetch('/api/phone/files/upload', {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Sayuri-Filename': encodeURIComponent(file.name),
      'X-Sayuri-Phone-Serial': phoneState.selectedSerial
    },
    body: file
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  byId('phone-frame-status').textContent = `Файл отправлен: ${data.name}`;
  return data;
}

async function pushDiskItemsToPhone(items) {
  if (!phoneState.selectedSerial) return;
  const files = items.filter((item) => item?.kind === 'file' && item?.id);
  if (!files.length) throw new Error('Перетащите файл, а не папку.');
  for (const item of files.slice(0, 20)) {
    await postJson('/api/phone/files/push', {
      serial: phoneState.selectedSerial,
      file_id: item.id
    });
  }
  byId('phone-frame-status').textContent = `На телефон отправлено файлов: ${Math.min(files.length, 20)}`;
}

async function loadPhoneApps() {
  if (!phoneState.selectedSerial) return;
  const drawer = byId('phone-app-drawer');
  drawer.classList.remove('hidden');
  byId('phone-app-list').innerHTML = '<span class="phone-app-loading">Загрузка…</span>';
  try {
    const response = await fetch(
      `/api/phone/apps?serial=${encodeURIComponent(phoneState.selectedSerial)}`,
      {cache: 'no-store'}
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    phoneState.apps = Array.isArray(data.apps) ? data.apps : [];
    renderPhoneApps();
  } catch (error) {
    byId('phone-app-list').textContent = `Ошибка: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function renderPhoneApps() {
  const list = byId('phone-app-list');
  const query = byId('phone-app-search').value.trim().toLowerCase();
  list.replaceChildren();
  const apps = phoneState.apps.filter((app) => {
    const haystack = `${app.label || ''} ${app.package || ''}`.toLowerCase();
    return !query || haystack.includes(query.toLowerCase());
  });
  if (!apps.length) {
    const empty = document.createElement('span');
    empty.className = 'phone-app-loading';
    empty.textContent = 'Приложения не найдены';
    list.append(empty);
    return;
  }
  for (const app of apps.slice(0, 200)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'phone-app-item';
    const label = document.createElement('strong');
    label.textContent = app.label || app.package;
    const packageName = document.createElement('small');
    packageName.textContent = app.package;
    button.append(label, packageName);
    button.addEventListener('click', async () => {
      try {
        await postJson('/api/phone/apps/launch', {
          serial: phoneState.selectedSerial,
          package: app.package
        });
        drawer.classList.add('hidden');
        if (phoneState.videoMode === 'png') schedulePhoneFrame(120);
      } catch (error) {
        showPhoneError(error);
      }
    });
    list.append(button);
  }
}

function stopPhoneCompanionPolling() {
  if (phoneState.companionTimer) {
    window.clearTimeout(phoneState.companionTimer);
    phoneState.companionTimer = null;
  }
}

function schedulePhoneCompanionPolling(delay = 3000) {
  stopPhoneCompanionPolling();
  if (!phoneStatusActive() || !phoneState.selectedSerial) return;
  phoneState.companionTimer = window.setTimeout(() => {
    phoneState.companionTimer = null;
    loadPhoneCompanion().catch(() => {
      schedulePhoneCompanionPolling(5000);
    });
  }, delay);
}

function resetPhoneCompanion(serial) {
  stopPhoneCompanionPolling();
  phoneState.companionStatus = null;
  phoneState.companionSerial = serial || null;
  phoneState.notificationEvents = [];
  phoneState.notificationLastSequence = 0;
  renderPhoneNotifications();
}

function renderPhoneCompanionStatus(status) {
  phoneState.companionStatus = status || null;
  const copy = byId('phone-companion-status');
  const enable = byId('phone-companion-enable');
  const disable = byId('phone-companion-disable');
  const live = byId('phone-companion-live-state');
  const notificationButton = byId('phone-notifications');

  if (!phoneState.selectedSerial) {
    copy.textContent = 'Подключите авторизованный Android.';
    enable.disabled = true;
    disable.classList.add('hidden');
    live.textContent = 'Companion не подключён';
    notificationButton.disabled = true;
    return;
  }

  if (!status?.installed) {
    copy.textContent = 'Sayuri Companion ещё не установлен на телефоне.';
    enable.textContent = 'Companion не установлен';
    enable.disabled = true;
    disable.classList.add('hidden');
    live.textContent = 'Нужен Sayuri Companion';
    notificationButton.disabled = true;
    return;
  }

  enable.disabled = false;
  notificationButton.disabled = !status.paired;
  disable.classList.toggle('hidden', !status.paired);

  if (!status.paired) {
    copy.textContent = 'Companion установлен. Нажмите «Сопрячь Companion» и подтвердите подключение на телефоне.';
    enable.textContent = 'Сопрячь Companion';
    live.textContent = 'Готов к сопряжению';
    return;
  }

  if (!status.last_seen_at) {
    copy.textContent = 'Сопряжение создано. Подтвердите подключение в приложении Sayuri Companion на телефоне.';
    enable.textContent = 'Повторить сопряжение';
    live.textContent = 'Ожидаю подтверждение';
    return;
  }

  enable.textContent = 'Пересопрячь';
  if (!status.notification_access) {
    copy.textContent = 'Companion связан с Sayuri. На телефоне разрешите Sayuri Companion доступ к уведомлениям.';
    live.textContent = 'Нет доступа к уведомлениям';
  } else {
    copy.textContent = `Companion готов · событий: ${status.events || 0}`;
    live.textContent = 'Уведомления подключены';
  }
}

function applyPhoneNotificationEvent(event) {
  if (!event || !event.type) return;
  phoneState.notificationLastSequence = Math.max(
    phoneState.notificationLastSequence,
    Number(event.sequence) || 0
  );

  if (event.type === 'notification_removed') {
    phoneState.notificationEvents = phoneState.notificationEvents.filter((item) => !(
      item.package === event.package
      && Number(item.notification_id || 0) === Number(event.notification_id || 0)
      && String(item.tag || '') === String(event.tag || '')
    ));
    return;
  }

  if (event.type !== 'notification_posted') return;

  phoneState.notificationEvents = phoneState.notificationEvents.filter((item) => !(
    item.package === event.package
    && Number(item.notification_id || 0) === Number(event.notification_id || 0)
    && String(item.tag || '') === String(event.tag || '')
  ));
  phoneState.notificationEvents.push(event);
  if (phoneState.notificationEvents.length > 80) {
    phoneState.notificationEvents.splice(0, phoneState.notificationEvents.length - 80);
  }
}

function renderPhoneNotifications() {
  const list = byId('phone-notification-list');
  const count = byId('phone-notification-count');
  if (!list || !count) return;

  const events = phoneState.notificationEvents.slice().reverse();
  count.textContent = String(events.length);
  count.classList.toggle('has-items', events.length > 0);
  list.replaceChildren();

  if (!events.length) {
    const empty = document.createElement('span');
    empty.className = 'phone-notification-empty';
    empty.textContent = 'Новых уведомлений нет';
    list.append(empty);
    return;
  }

  for (const event of events.slice(0, 50)) {
    const row = document.createElement('article');
    row.className = 'phone-notification-item';

    const top = document.createElement('div');
    top.className = 'phone-notification-item-head';
    const app = document.createElement('strong');
    app.textContent = event.package || 'Android';
    const time = document.createElement('time');
    time.textContent = formatTime(event.event_time || event.received_at * 1000);
    top.append(app, time);

    const title = document.createElement('b');
    title.textContent = event.title || 'Уведомление';
    const body = document.createElement('p');
    body.textContent = event.text || event.subtext || '';
    row.append(top, title);
    if (body.textContent) row.append(body);
    list.append(row);
  }
}

async function loadPhoneNotificationEvents() {
  if (!phoneState.selectedSerial || !phoneState.companionStatus?.paired) return;
  const params = new URLSearchParams({
    serial: phoneState.selectedSerial,
    limit: '100',
    after: String(phoneState.notificationLastSequence || 0)
  });
  const response = await fetch(`/api/phone/companion/events?${params}`, {
    cache: 'no-store'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  for (const event of data.events || []) applyPhoneNotificationEvent(event);
  renderPhoneNotifications();
}

async function loadPhoneCompanion() {
  if (!phoneState.selectedSerial) {
    renderPhoneCompanionStatus(null);
    return;
  }
  const serial = phoneState.selectedSerial;
  if (phoneState.companionSerial !== serial) resetPhoneCompanion(serial);

  const response = await fetch(
    `/api/phone/companion?serial=${encodeURIComponent(serial)}`,
    {cache: 'no-store'}
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  if (serial !== phoneState.selectedSerial) return;

  renderPhoneCompanionStatus(data);
  if (data.paired) {
    try {
      await loadPhoneNotificationEvents();
    } catch {}
  }
  schedulePhoneCompanionPolling(data.last_seen_at ? 2200 : 1600);
}

async function enablePhoneCompanion() {
  if (!phoneState.selectedSerial) return;
  const button = byId('phone-companion-enable');
  button.disabled = true;
  try {
    const result = await postJson('/api/phone/companion/enable', {
      serial: phoneState.selectedSerial
    });
    showPhoneMessage(
      result.status || 'Подтвердите сопряжение в Sayuri Companion на телефоне.'
    );
    await loadPhoneCompanion();
  } catch (error) {
    showPhoneError(error);
  } finally {
    button.disabled = false;
  }
}

async function disablePhoneCompanion() {
  if (!phoneState.selectedSerial) return;
  try {
    await postJson('/api/phone/companion/disable', {
      serial: phoneState.selectedSerial
    });
    resetPhoneCompanion(phoneState.selectedSerial);
    await loadPhoneCompanion();
  } catch (error) {
    showPhoneError(error);
  }
}

function togglePhoneNotifications() {
  const drawer = byId('phone-notification-drawer');
  phoneState.notificationDrawerOpen = drawer.classList.contains('hidden');
  drawer.classList.toggle('hidden', !phoneState.notificationDrawerOpen);
  if (phoneState.notificationDrawerOpen) {
    loadPhoneNotificationEvents().catch(showPhoneError);
  }
}

async function pairPhone(event) {
  event.preventDefault();
  const address = byId('phone-pair-address').value.trim();
  const pairingCode = byId('phone-pair-code').value.trim();
  if (!address || !pairingCode) {
    showPhoneMessage('Укажите адрес сопряжения и 6-значный код.', 'error');
    return;
  }
  try {
    const result = await postJson('/api/phone/pair', {
      address,
      pairing_code: pairingCode
    });
    byId('phone-pair-code').value = '';
    showPhoneMessage(result.message || 'Телефон сопряжён.');
    await loadPhone();
  } catch (error) {
    showPhoneError(error);
  }
}

async function connectPhone(event) {
  event.preventDefault();
  const address = byId('phone-connect-address').value.trim();
  if (!address) {
    showPhoneMessage('Укажите адрес подключения из раздела «Беспроводная отладка».', 'error');
    return;
  }
  try {
    const result = await postJson('/api/phone/connect', {address});
    showPhoneMessage(result.message || 'Телефон подключён.');
    await loadPhone();
  } catch (error) {
    showPhoneError(error);
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
byId('dna-reanalyze').addEventListener('click', () => {
  if (viewerItem?.kind === 'file') {
    loadViewerDna(viewerItem.id, true).catch(showDiskError);
  }
});

byId('save-settings').addEventListener('click', saveSettings);
byId('refresh-system').addEventListener('click', refreshSystem);
byId('phone-refresh').addEventListener('click', () => {
  hidePhoneMessage();
  loadPhone().catch(showPhoneError);
});
byId('phone-pair-form').addEventListener('submit', pairPhone);
byId('phone-connect-form').addEventListener('submit', connectPhone);
byId('phone-open-floating').addEventListener('click', openPhoneFloat);
byId('phone-float-launcher').addEventListener('click', openPhoneFloat);
byId('phone-float-close').addEventListener('click', closePhoneFloat);
byId('phone-float-minimize').addEventListener('click', togglePhoneFloatMinimize);
byId('phone-float-rotate').addEventListener('click', rotatePhoneFloat);
byId('phone-open-native').addEventListener('click', toggleNativePhoneWindow);
byId('phone-keyboard-capture').addEventListener('click', togglePhoneKeyboardCapture);
byId('phone-quality-profile').addEventListener('change', (event) => {
  setPhoneQualityProfile(event.target.value, {restart: true});
});
byId('phone-capture').addEventListener('click', capturePhoneToDisk);
byId('phone-record').addEventListener('click', togglePhoneRecording);
byId('phone-audio').addEventListener('click', togglePhoneAudio);
byId('phone-paste').addEventListener('click', pasteComputerClipboardToPhone);
byId('phone-copy').addEventListener('click', copyPhoneClipboardToComputer);
byId('phone-file').addEventListener('click', () => byId('phone-file-picker').click());
byId('phone-file-picker').addEventListener('change', async (event) => {
  const files = Array.from(event.target.files || []);
  try {
    for (const file of files.slice(0, 20)) await uploadComputerFileToPhone(file);
  } catch (error) {
    showPhoneError(error);
  } finally {
    event.target.value = '';
  }
});
byId('phone-apps').addEventListener('click', loadPhoneApps);
byId('phone-app-close').addEventListener('click', () => byId('phone-app-drawer').classList.add('hidden'));
byId('phone-app-search').addEventListener('input', renderPhoneApps);
byId('phone-companion-enable').addEventListener('click', enablePhoneCompanion);
byId('phone-companion-disable').addEventListener('click', disablePhoneCompanion);
byId('phone-notifications').addEventListener('click', togglePhoneNotifications);
byId('phone-notification-close').addEventListener('click', () => {
  phoneState.notificationDrawerOpen = false;
  byId('phone-notification-drawer').classList.add('hidden');
});

document.querySelectorAll('[data-phone-key]').forEach((button) => {
  button.addEventListener('click', () => sendPhoneKey(button.dataset.phoneKey));
});

byId('phone-text-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = byId('phone-text-input');
  const text = input.value;
  if (!text.trim()) return;
  try {
    await setPhoneClipboard(text, {paste: true});
    input.value = '';
    byId('phone-frame-status').textContent = 'Unicode-текст вставлен через Android clipboard';
  } catch (error) {
    showPhoneError(error);
  }
});

const phoneFloatHeader = byId('phone-float-drag');
phoneFloatHeader.addEventListener('pointerdown', startPhoneFloatDrag);
phoneFloatHeader.addEventListener('pointermove', movePhoneFloat);
phoneFloatHeader.addEventListener('pointerup', endPhoneFloatDrag);
phoneFloatHeader.addEventListener('pointercancel', endPhoneFloatDrag);

const phoneScreen = byId('phone-screen');
const phoneScreenStage = byId('phone-screen-shell');

phoneScreenStage.addEventListener('dragover', (event) => {
  if (!phoneState.selectedSerial) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
  phoneScreenStage.classList.add('phone-file-drop-active');
});
phoneScreenStage.addEventListener('dragleave', (event) => {
  if (event.relatedTarget && phoneScreenStage.contains(event.relatedTarget)) return;
  phoneScreenStage.classList.remove('phone-file-drop-active');
});
phoneScreenStage.addEventListener('drop', async (event) => {
  if (!phoneState.selectedSerial) return;
  event.preventDefault();
  event.stopPropagation();
  phoneScreenStage.classList.remove('phone-file-drop-active');
  try {
    const diskPayload = event.dataTransfer.getData('application/x-sayuri-disk');
    if (diskPayload) {
      await pushDiskItemsToPhone(JSON.parse(diskPayload));
      return;
    }
    const files = Array.from(event.dataTransfer.files || []);
    if (!files.length) throw new Error('Нет файлов для отправки.');
    for (const file of files.slice(0, 20)) await uploadComputerFileToPhone(file);
  } catch (error) {
    showPhoneError(error);
  }
});

phoneScreenStage.addEventListener('contextmenu', (event) => {
  event.preventDefault();
  sendPhoneKey('BACK');
});
phoneScreenStage.addEventListener('pointerdown', (event) => {
  if (!phoneState.selectedSerial) return;
  const point = phonePointFromEvent(event);
  if (!point) return;
  phoneState.pointer = {
    pointerId: event.pointerId,
    point,
    startedAt: performance.now()
  };
  phoneScreenStage.setPointerCapture?.(event.pointerId);
  if (phoneState.keyboardCaptured) phoneScreenStage.focus({preventScroll: true});
  event.preventDefault();
});
phoneScreenStage.addEventListener('pointerup', async (event) => {
  const gesture = phoneState.pointer;
  phoneState.pointer = null;
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  const endPoint = phonePointFromEvent(event);
  if (!endPoint) return;
  const dx = endPoint.x - gesture.point.x;
  const dy = endPoint.y - gesture.point.y;
  const distance = Math.hypot(dx, dy);
  const duration = performance.now() - gesture.startedAt;
  try {
    if (distance < 0.018 && duration < 650) {
      await sendPhoneTap(endPoint);
    } else {
      await sendPhoneSwipe(gesture.point, endPoint, duration);
    }
  } catch (error) {
    showPhoneError(error);
  }
});
phoneScreenStage.addEventListener('pointercancel', () => {
  phoneState.pointer = null;
});
phoneScreenStage.addEventListener('wheel', async (event) => {
  if (!phoneState.selectedSerial) return;
  event.preventDefault();
  const down = event.deltaY > 0;
  const start = mapPhoneDisplayPoint(0.5, down ? 0.72 : 0.30);
  const end = mapPhoneDisplayPoint(0.5, down ? 0.30 : 0.72);
  try {
    await sendPhoneSwipe(start, end, 220);
  } catch (error) {
    showPhoneError(error);
  }
}, {passive: false});

phoneScreenStage.addEventListener('keydown', handlePhoneKeyboard);
window.addEventListener('resize', () => {
  if (phoneState.floatingOpen) {
    clampPhoneFloat();
    fitPhoneImage();
  }
});

initializePhoneFloatingWindow();

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
  : initialHash === '#phone'
    ? 'phone'
    : (initialHash === '#settings' || initialHash.startsWith('#system-') ? 'settings' : 'home');
showView(initialView);

Promise.all([loadSettings(), loadSystem()])
  .then(loadEvents)
  .catch((error) => {
    setStatus('error', 'Ошибка запуска интерфейса');
    byId('updated-at').textContent = String(error);
  });
