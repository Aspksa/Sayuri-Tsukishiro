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
let sayuriMemorySearchTimer = null;

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

function readLocalJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

const sayuriState = {
  profile: null,
  messages: readLocalJson('sayuri-chat-history', []),
  suppressOrbClick: false,
  orbDrag: null,
  chatDrag: null,
  visible: localStorage.getItem('sayuri-visible') !== '0',
  rememberPosition: localStorage.getItem('sayuri-remember-position') !== '0',
  rememberHistory: localStorage.getItem('sayuri-remember-history') !== '0'
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
  byId('sayuri-account-nav')?.classList.toggle('active', name === 'sayuri');

  const titles = {
    home: ['СИСТЕМА', 'Главная'],
    disk: ['ФАЙЛЫ И ДОКУМЕНТЫ', 'Диск Sayuri'],
    sayuri: ['ЛИЧНЫЙ КАБИНЕТ', 'Sayuri'],
    settings: ['СИСТЕМА И АРХИТЕКТУРА', 'Настройки']
  };
  const [eyebrow, title] = titles[name] || titles.home;
  byId('page-title').textContent = title;
  byId('page-eyebrow').textContent = eyebrow;

  if (name === 'disk') {
    history.replaceState(null, '', '#disk');
    loadDisk().catch(showDiskError);
  } else if (name === 'sayuri') {
    history.replaceState(null, '', '#sayuri');
    Promise.all([
      loadSayuriProfile(),
      loadSayuriMemory(),
      loadSayuriMemoryCandidates(),
      loadSayuriMemoryV3(),
      loadSayuriExperience()
    ]).catch(showSayuriProviderError);
  } else if (name === 'settings') {
    history.replaceState(null, '', '#settings');
  } else {
    history.replaceState(null, '', '#home');
  }
  updateSayuriContextUI();
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

const DNA_AUTO_EXTENSIONS = new Set([
  'pdf', 'txt', 'md', 'json', 'xml', 'csv', 'log', 'ini', 'cfg', 'yaml', 'yml',
  'docx', 'pptx', 'xlsx', 'odt', 'ods', 'odp',
  'png', 'jpg', 'jpeg', 'webp', 'tif', 'tiff', 'bmp'
]);

function shouldAutoAnalyzeDna(file) {
  const extension = (file.name.split('.').pop() || '').toLowerCase();
  return DNA_AUTO_EXTENSIONS.has(extension)
    || file.type === 'application/pdf'
    || file.type.startsWith('image/');
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
      const dnaEligible = shouldAutoAnalyzeDna(file);
      status.textContent = dnaEligible
        ? 'Файл загружен · ожидает ДНК'
        : (data?.file?.duplicate_of ? 'Готово · совпадение SHA-256' : 'Готово');
      resolve({data, file, row, status, bar, dnaEligible});
    });

    xhr.addEventListener('error', () => {
      row.classList.add('error');
      status.textContent = 'Ошибка соединения';
      reject(new Error('Ошибка соединения при загрузке.'));
    });

    xhr.send(file);
  });
}

async function analyzeUploadedDna(upload, index, total) {
  if (!upload?.dnaEligible || !upload?.data?.file?.id) return {analyzed: false, error: null};

  const {status, row, data} = upload;
  status.textContent = `Строю ДНК… ${index + 1} из ${total}`;
  byId('upload-summary').textContent = `ДНК: ${index + 1} из ${total}`;

  try {
    const response = await fetch(
      `/api/disk/files/${encodeURIComponent(data.file.id)}/dna/analyze`,
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
      }
    );
    const dna = await response.json();
    if (!response.ok) throw new Error(dna?.error?.message || `HTTP ${response.status}`);

    row.classList.remove('dna-error');
    row.classList.add('dna-ready');
    status.textContent = `Готово · ДНК ${Math.round(Number(dna.coverage_percent) || 0)}%`;
    data.dna = dna;
    return {analyzed: true, error: null};
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    row.classList.add('dna-error');
    status.textContent = `Файл загружен · ошибка ДНК: ${message}`;
    return {analyzed: false, error: message};
  }
}

async function uploadDiskFiles(files) {
  const queue = Array.from(files || []);
  if (!queue.length || diskState.scope !== 'all') return;

  byId('upload-items').replaceChildren();
  byId('upload-queue').classList.remove('hidden');
  byId('upload-summary').textContent = `0 из ${queue.length}`;

  const uploaded = [];
  let uploadErrors = 0;
  for (let index = 0; index < queue.length; index += 1) {
    try {
      uploaded.push(await uploadOneFile(queue[index], index, queue.length));
    } catch (error) {
      uploadErrors += 1;
      showDiskError(error);
    }
  }

  byId('disk-file-input').value = '';
  if (uploaded.length) {
    await loadDisk();
  }

  const dnaQueue = uploaded.filter((item) => item.dnaEligible);
  let dnaCompleted = 0;
  let dnaErrors = 0;
  for (let index = 0; index < dnaQueue.length; index += 1) {
    const result = await analyzeUploadedDna(dnaQueue[index], index, dnaQueue.length);
    if (result.analyzed) dnaCompleted += 1;
    if (result.error) dnaErrors += 1;
  }

  const parts = [`загружено ${uploaded.length}`];
  if (dnaQueue.length) parts.push(`ДНК ${dnaCompleted}/${dnaQueue.length}`);
  if (uploadErrors) parts.push(`ошибок загрузки ${uploadErrors}`);
  if (dnaErrors) parts.push(`ошибок ДНК ${dnaErrors}`);
  byId('upload-summary').textContent = parts.join(' · ');

  if (uploaded.length) {
    showDiskMessage(
      dnaErrors
        ? `Файлы загружены. ДНК построена для ${dnaCompleted} из ${dnaQueue.length}; ошибки видны в очереди.`
        : `Загружено файлов: ${uploaded.length}. ДНК построена автоматически.`
    );
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

function setDnaLoadState(kind = '', title = '', message = '') {
  const state = byId('dna-load-state');
  if (!state) return;
  state.className = kind ? `dna-load-state ${kind}` : 'dna-load-state hidden';
  byId('dna-load-state-title').textContent = title;
  byId('dna-load-state-text').textContent = message;
  byId('dna-load-retry').classList.toggle('hidden', kind !== 'error');
}

async function loadViewerDna(fileId, force = false) {
  if (!force && viewerDnaLoadedFor === fileId) return;
  const button = byId('dna-reanalyze');
  button.disabled = true;
  byId('dna-load-retry').disabled = true;
  byId('dna-document-type').textContent = force ? 'Переизучение документа…' : 'Изучение документа…';
  byId('dna-summary').textContent = 'Саюри разбирает структуру, текст, OCR и молекулы документа.';
  setDnaLoadState(
    'loading',
    force ? 'Переизучаю ДНК' : 'Строю ДНК документа',
    'Для сканированного PDF OCR может занять заметное время. Окно можно оставить открытым.'
  );

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
    setDnaLoadState(
      'ready',
      'ДНК готова',
      `Покрытие ${Math.round(Number(dna.coverage_percent) || 0)}% · молекул ${dna.molecules?.total ?? 0}`
    );
    return dna;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    viewerDnaLoadedFor = null;
    byId('dna-document-type').textContent = 'ДНК не построена';
    byId('dna-summary').textContent = 'Анализ документа завершился ошибкой. Оригинальный файл сохранён.';
    setDnaLoadState('error', 'Ошибка анализа ДНК', message);
    throw error;
  } finally {
    button.disabled = false;
    byId('dna-load-retry').disabled = false;
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
    updateSayuriContextUI();

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
  updateSayuriContextUI();
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


function currentSayuriContext() {
  const active = document.querySelector('.view.active');
  const view = active?.id?.replace('view-', '') || 'home';
  const titles = {
    home: 'Главная',
    disk: 'Диск Sayuri',
    sayuri: 'Личный кабинет Sayuri',
    settings: 'Настройки'
  };
  const context = {
    view,
    title: titles[view] || byId('page-title')?.textContent || 'Sayuri',
    route: location.hash || '#home'
  };
  if (view === 'disk') {
    context.disk = {
      scope: diskState.scope,
      folder_id: diskState.folderId,
      search: byId('disk-search-input')?.value?.trim() || '',
      selected_count: diskState.selected.size
    };
  }
  if (viewerItem) {
    context.current_document = {
      id: viewerItem.id,
      name: viewerItem.name,
      kind: viewerItem.kind,
      category: viewerItem.category || null
    };
  }
  return context;
}

function updateSayuriContextUI() {
  const context = currentSayuriContext();
  if (byId('sayuri-context-view')) byId('sayuri-context-view').textContent = context.view;
  if (byId('sayuri-context-title')) byId('sayuri-context-title').textContent = context.title;
  if (byId('sayuri-context-document')) {
    byId('sayuri-context-document').textContent = context.current_document?.name || '—';
  }
  if (byId('sayuri-chat-context')) {
    byId('sayuri-chat-context').textContent = context.current_document?.name
      ? `${context.title} · ${context.current_document.name}`
      : context.title;
  }
}

function setSayuriProviderMessage(text, kind = '') {
  const target = byId('sayuri-provider-message');
  if (!target) return;
  target.className = `sayuri-provider-message ${kind}`.trim();
  target.textContent = text;
}

function renderSayuriProfile(profile) {
  sayuriState.profile = profile;
  const provider = profile.provider || {};
  const configured = Boolean(provider.configured);
  byId('sayuri-connection-state').textContent = configured ? 'Ключ сохранён' : 'Не настроено';
  byId('sayuri-connection-state').classList.toggle('ready', configured);
  byId('sayuri-ai-badge').textContent = configured ? 'AI готов' : 'Нужен API-ключ';
  byId('sayuri-ai-badge').classList.toggle('ready', configured);
  byId('sayuri-key-mask').textContent = configured
    ? `Сохранён: ${provider.api_key_masked || '••••••••'} · пустое поле сохранит текущий ключ`
    : 'Ключ ещё не сохранён';
  byId('sayuri-orb-status').classList.toggle('ready', configured);
  byId('sayuri-chat-status').textContent = configured
    ? 'DeepSeek-V4-Flash · Cloud.ru · готово'
    : 'Откройте Личный кабинет Sayuri и добавьте ключ Cloud.ru';
  renderSayuriMemoryStats(profile.memory || {});
  renderSayuriExperience(profile.experience || {});
  renderSayuriAvatarManager(profile.avatars || {});
  renderSayuriActionCenter(profile.actions || {});
  applySayuriAvatarImages();
}


function avatarUrl(slot) {
  return sayuriState.profile?.avatars?.[slot]?.url || '/assets/sayuri-avatar.svg';
}

function applySayuriAvatarImages() {
  const targets = [
    ['#sayuri-orb img', 'orb'],
    ['#sayuri-chat-head img', 'chat'],
    ['.sayuri-account-nav img', 'profile'],
    ['.sayuri-profile-portrait img', 'hero']
  ];
  for (const [selector, slot] of targets) {
    const image = document.querySelector(selector);
    if (image) image.src = avatarUrl(slot);
  }
  document.querySelectorAll('.sayuri-message.assistant img').forEach((image) => {
    image.src = avatarUrl('chat');
  });
}

function renderSayuriMemoryStats(stats) {
  if (byId('sayuri-memory-personal')) byId('sayuri-memory-personal').textContent = String(stats.personal?.count ?? 0);
  if (byId('sayuri-memory-project')) byId('sayuri-memory-project').textContent = String(stats.project?.count ?? 0);
  if (byId('sayuri-memory-pending')) byId('sayuri-memory-pending').textContent = String(stats.intelligence?.pending_review ?? 0);
  if (byId('sayuri-memory-total')) byId('sayuri-memory-total').textContent = String(stats.total ?? 0);
  if (byId('sayuri-semantic-engine')) byId('sayuri-semantic-engine').textContent = stats.semantic?.engine || 'hybrid-semantic-v1';
  renderSayuriMemoryV3Stats(stats.v3 || {});
  renderMemoryIntelligenceSettings(stats.intelligence?.settings || {});
}



function setMemoryV3Message(text, kind = '') {
  const target = byId('sayuri-memory-v3-message');
  if (!target) return;
  target.className = `sayuri-memory-v3-message ${kind}`.trim();
  target.textContent = text;
}

function renderSayuriMemoryV3Stats(stats) {
  const mapping = {
    'memory-v3-working': stats.working,
    'memory-v3-episodes': stats.episodes,
    'memory-v3-knowledge': stats.knowledge,
    'memory-v3-nodes': stats.graph_nodes,
    'memory-v3-edges': stats.graph_edges,
    'memory-v3-conflicts': stats.open_conflicts,
    'memory-v3-consolidations': stats.consolidations,
    'memory-v3-stale': stats.stale_candidates
  };
  for (const [id, value] of Object.entries(mapping)) {
    if (byId(id)) byId(id).textContent = String(value ?? 0);
  }
}

function memoryV3Empty(container, text) {
  const empty = document.createElement('p');
  empty.className = 'muted';
  empty.textContent = text;
  container.append(empty);
}

function renderMemoryV3Working(payload) {
  const container = byId('memory-v3-working-list');
  if (!container) return;
  container.replaceChildren();
  const items = payload.working?.items || [];
  if (!items.length) {
    memoryV3Empty(container, 'Рабочая память пуста.');
    return;
  }
  for (const item of items) {
    const row = document.createElement('article');
    row.className = 'memory-v3-row';
    const title = document.createElement('strong');
    title.textContent = item.key === 'current_focus' ? 'Текущий фокус' : 'Текущий контекст';
    const text = document.createElement('p');
    if (item.value?.message) {
      text.textContent = item.value.message;
    } else {
      const documentName = item.value?.current_document?.name;
      const view = item.value?.title || item.value?.view || 'интерфейс';
      text.textContent = documentName ? `${view} · ${documentName}` : view;
    }
    const meta = document.createElement('small');
    meta.textContent = `обновлено ${formatDate(item.updated_at)} · TTL ${payload.working?.ttl_hours || 24} ч`;
    row.append(title, text, meta);
    container.append(row);
  }
}

function renderMemoryV3Knowledge(payload) {
  const container = byId('memory-v3-knowledge-list');
  if (!container) return;
  container.replaceChildren();
  const items = payload.knowledge || [];
  if (!items.length) {
    memoryV3Empty(container, 'Устойчивые знания ещё не сформированы.');
    return;
  }
  for (const item of items.slice(0, 20)) {
    const row = document.createElement('article');
    row.className = 'memory-v3-row knowledge';
    const head = document.createElement('div');
    head.className = 'memory-v3-row-head';
    const kind = document.createElement('span');
    kind.textContent = `${item.scope === 'personal' ? 'личная' : 'проектная'} · ${memoryKindLabel(item.kind)}`;
    const confidence = document.createElement('strong');
    confidence.textContent = `${Math.round((Number(item.confidence) || 0) * 100)}%`;
    head.append(kind, confidence);
    const text = document.createElement('p');
    text.textContent = item.statement;
    const meta = document.createElement('small');
    meta.textContent = `источников ${item.source_memory_ids?.length || 0} · действует с ${formatDate(item.valid_from)}`;
    row.append(head, text, meta);
    container.append(row);
  }
}

function renderMemoryV3Timeline(payload) {
  const container = byId('memory-v3-timeline');
  if (!container) return;
  container.replaceChildren();
  const items = payload.timeline || [];
  if (!items.length) {
    memoryV3Empty(container, 'Хронология пока пуста.');
    return;
  }
  for (const item of items.slice(0, 24)) {
    const row = document.createElement('article');
    row.className = 'memory-v3-timeline-row';
    const marker = document.createElement('span');
    marker.className = 'memory-v3-timeline-marker';
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = item.event_type.replaceAll('_', ' ');
    const text = document.createElement('p');
    text.textContent = item.summary;
    const meta = document.createElement('small');
    meta.textContent = `${item.scope || 'system'} · ${formatDate(item.occurred_at)}`;
    body.append(title, text, meta);
    row.append(marker, body);
    container.append(row);
  }
}

function renderMemoryV3Graph(payload) {
  const container = byId('memory-v3-graph');
  if (!container) return;
  container.replaceChildren();
  const nodes = payload.graph?.nodes || [];
  const edges = payload.graph?.edges || [];
  if (!nodes.length) {
    memoryV3Empty(container, 'Граф ещё не построен.');
    return;
  }
  const byNodeId = new Map(nodes.map((node) => [node.id, node]));
  const summary = document.createElement('div');
  summary.className = 'memory-v3-graph-summary';
  const typeCounts = {};
  for (const node of nodes) typeCounts[node.type] = (typeCounts[node.type] || 0) + 1;
  for (const [type, count] of Object.entries(typeCounts).sort()) {
    const chip = document.createElement('span');
    chip.textContent = `${type}: ${count}`;
    summary.append(chip);
  }
  container.append(summary);

  for (const edge of edges.slice(0, 24)) {
    const source = byNodeId.get(edge.source);
    const target = byNodeId.get(edge.target);
    if (!source || !target) continue;
    const row = document.createElement('article');
    row.className = 'memory-v3-graph-edge';
    const from = document.createElement('strong');
    from.textContent = source.label;
    const relation = document.createElement('span');
    relation.textContent = edge.relation.replaceAll('_', ' ');
    const to = document.createElement('strong');
    to.textContent = target.label;
    row.append(from, relation, to);
    container.append(row);
  }
}

function renderMemoryV3Conflicts(payload) {
  const container = byId('memory-v3-conflicts-list');
  if (!container) return;
  container.replaceChildren();
  const items = payload.conflicts || [];
  if (!items.length) {
    memoryV3Empty(container, 'Открытых противоречий нет.');
    return;
  }
  for (const item of items) {
    const card = document.createElement('article');
    card.className = 'memory-v3-conflict';
    const title = document.createElement('strong');
    title.textContent = item.scope === 'personal' ? 'Личная память: конфликт' : 'Проектная память: конфликт';

    const compare = document.createElement('div');
    compare.className = 'memory-v3-conflict-compare';
    const oldBox = document.createElement('div');
    const oldLabel = document.createElement('span');
    oldLabel.textContent = 'Раньше';
    const oldText = document.createElement('p');
    oldText.textContent = item.old_content;
    oldBox.append(oldLabel, oldText);

    const newBox = document.createElement('div');
    const newLabel = document.createElement('span');
    newLabel.textContent = 'Новое';
    const newText = document.createElement('p');
    newText.textContent = item.new_content;
    newBox.append(newLabel, newText);
    compare.append(oldBox, newBox);

    const controls = document.createElement('div');
    controls.className = 'memory-v3-conflict-actions';
    const options = [
      ['prefer_new', 'Новое актуально'],
      ['prefer_old', 'Старое актуально'],
      ['keep_both', 'Оба верны']
    ];
    for (const [resolution, label] of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = resolution === 'prefer_new' ? 'primary-button' : 'secondary-button';
      button.textContent = label;
      button.addEventListener('click', () => resolveMemoryV3Conflict(item.id, resolution));
      controls.append(button);
    }

    card.append(title, compare, controls);
    container.append(card);
  }
}

function renderMemoryV3Retention(payload) {
  const container = byId('memory-v3-retention-list');
  if (!container) return;
  container.replaceChildren();
  const items = payload.retention?.stale || [];
  if (!items.length) {
    memoryV3Empty(container, 'Устаревающих записей нет.');
    return;
  }
  for (const item of items.slice(0, 20)) {
    const row = document.createElement('article');
    row.className = 'memory-v3-retention-row';
    const score = document.createElement('strong');
    score.textContent = `${Math.round((Number(item.retention_score) || 0) * 100)}%`;
    const body = document.createElement('div');
    const text = document.createElement('p');
    text.textContent = item.content;
    const meta = document.createElement('small');
    meta.textContent = `${item.scope} · ${memoryKindLabel(item.kind)} · retrieval-вес снижен`;
    body.append(text, meta);
    row.append(score, body);
    container.append(row);
  }
}

function renderSayuriMemoryV3(payload) {
  renderSayuriMemoryV3Stats(payload.stats || {});
  renderMemoryV3Working(payload);
  renderMemoryV3Knowledge(payload);
  renderMemoryV3Timeline(payload);
  renderMemoryV3Graph(payload);
  renderMemoryV3Conflicts(payload);
  renderMemoryV3Retention(payload);
}

async function loadSayuriMemoryV3() {
  const response = await fetch('/api/sayuri/memory/v3', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderSayuriMemoryV3(data);
  return data;
}

async function maintainSayuriMemoryV3() {
  const button = byId('sayuri-memory-v3-maintain');
  button.disabled = true;
  setMemoryV3Message('Проверяю актуальность, знания, связи и консолидации…');
  try {
    const result = await postJson('/api/sayuri/memory/v3/maintenance', {});
    setMemoryV3Message(
      `Готово: знаний ${result.stats?.knowledge ?? 0}, консолидаций +${result.consolidation?.created ?? 0}, устаревающих ${result.retention?.stale_count ?? 0}.`,
      'ready'
    );
    await Promise.all([loadSayuriMemoryV3(), loadSayuriMemory(), loadSayuriProfile()]);
  } catch (error) {
    setMemoryV3Message(`Ошибка обслуживания: ${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    button.disabled = false;
  }
}

async function resolveMemoryV3Conflict(conflictId, resolution) {
  try {
    const result = await postJson(
      `/api/sayuri/memory/v3/conflicts/${encodeURIComponent(conflictId)}/resolve`,
      {resolution}
    );
    renderSayuriMemoryV3(result.dashboard || {});
    setMemoryV3Message('Противоречие разрешено, временная история сохранена.', 'ready');
    await Promise.all([loadSayuriMemory(), loadSayuriProfile()]);
  } catch (error) {
    setMemoryV3Message(`Ошибка разрешения конфликта: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

function renderSayuriExperience(stats) {
  if (byId('sayuri-experience-total')) byId('sayuri-experience-total').textContent = String(stats.total ?? 0);
  if (byId('sayuri-experience-positive')) byId('sayuri-experience-positive').textContent = String(stats.positive ?? 0);
  if (byId('sayuri-experience-negative')) byId('sayuri-experience-negative').textContent = String(stats.negative ?? 0);
  if (byId('sayuri-experience-learned')) byId('sayuri-experience-learned').textContent = String(stats.learned_strategies ?? 0);

  const container = byId('sayuri-experience-strategies');
  if (!container) return;
  container.replaceChildren();
  const strategies = stats.strategies || [];
  if (!strategies.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Опыт ещё не накоплен.';
    container.append(empty);
    return;
  }
  for (const item of strategies.slice(0, 12)) {
    const row = document.createElement('article');
    row.className = 'sayuri-experience-strategy';
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = item.strategy;
    const meta = document.createElement('small');
    meta.textContent = `положительных ${item.positive} · отрицательных ${item.negative} · нейтральных ${item.neutral}`;
    body.append(title, meta);
    const score = document.createElement('span');
    score.textContent = item.meaningful
      ? `${Math.round((Number(item.success_rate) || 0) * 100)}%`
      : '—';
    score.title = item.meaningful ? 'Сглаженная оценка успешности' : 'Пока нет оценённых исходов';
    row.append(body, score);
    container.append(row);
  }
}

async function loadSayuriExperience() {
  const response = await fetch('/api/sayuri/experience?limit=50', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderSayuriExperience(data.stats || {});
  if (sayuriState.profile) sayuriState.profile.experience = data.stats || {};
  return data;
}

async function rateSayuriMessage(messageIndex, rating) {
  const message = sayuriState.messages[messageIndex];
  const responseId = message?.metadata?.response_id;
  if (!responseId || message.metadata?.feedback) return;
  try {
    const result = await postJson('/api/sayuri/experience/feedback', {
      response_id: responseId,
      rating,
      prompt: message.metadata?.prompt || '',
      answer: message.content || '',
      context: currentSayuriContext()
    });
    message.metadata = {...message.metadata, feedback: rating};
    persistSayuriHistory();
    renderSayuriMessages();
    renderSayuriExperience(result.stats || {});
    loadSayuriMemoryV3().catch(() => {});
  } catch (error) {
    byId('sayuri-chat-status').textContent = `Не удалось сохранить оценку: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function createSayuriFeedbackControls(messageIndex, message) {
  if (message.role !== 'assistant' || !message.metadata?.response_id) return null;
  const controls = document.createElement('div');
  controls.className = 'sayuri-response-feedback';

  if (message.metadata.feedback) {
    const saved = document.createElement('span');
    saved.textContent = message.metadata.feedback === 'useful'
      ? 'Оценено: полезно'
      : 'Оценено: не помогло';
    controls.append(saved);
    return controls;
  }

  const useful = document.createElement('button');
  useful.type = 'button';
  useful.textContent = 'Полезно';
  useful.addEventListener('click', () => rateSayuriMessage(messageIndex, 'useful'));

  const notUseful = document.createElement('button');
  notUseful.type = 'button';
  notUseful.textContent = 'Не помогло';
  notUseful.addEventListener('click', () => rateSayuriMessage(messageIndex, 'not_useful'));

  controls.append(useful, notUseful);
  return controls;
}

function setMemoryCandidateMessage(text, kind = '') {
  const target = byId('sayuri-memory-candidate-message');
  if (!target) return;
  target.className = `sayuri-memory-candidate-message ${kind}`.trim();
  target.textContent = text;
}

function renderMemoryIntelligenceSettings(settings) {
  if (byId('memory-intelligence-candidates')) byId('memory-intelligence-candidates').checked = settings.candidate_generation !== false;
  if (byId('memory-intelligence-conflicts')) byId('memory-intelligence-conflicts').checked = settings.conflict_detection !== false;
  if (byId('memory-intelligence-context')) byId('memory-intelligence-context').checked = settings.context_linking !== false;
  if (byId('memory-intelligence-autosave')) byId('memory-intelligence-autosave').checked = settings.auto_save_high_confidence === true;
  if (byId('memory-intelligence-threshold')) {
    const value = Number(settings.auto_save_threshold ?? 0.96).toFixed(2).replace(/0$/, '');
    const hasOption = Array.from(byId('memory-intelligence-threshold').options).some((option) => option.value === value);
    byId('memory-intelligence-threshold').value = hasOption ? value : '0.96';
  }
}

function memoryRelationLabel(relation) {
  return {
    new: 'новое',
    duplicate: 'дубликат',
    conflict: 'возможное противоречие'
  }[relation] || relation;
}

function memoryCandidateStatusLabel(status) {
  return {
    pending: 'ждёт решения',
    accepted: 'сохранено',
    rejected: 'отклонено',
    duplicate: 'дубликат',
    conflict: 'проверить противоречие',
    auto_saved: 'сохранено автоматически'
  }[status] || status;
}

function renderSayuriMemoryCandidates(payload) {
  const intelligence = payload.intelligence || {};
  if (byId('sayuri-memory-pending')) {
    byId('sayuri-memory-pending').textContent = String(intelligence.pending_review ?? 0);
  }
  renderMemoryIntelligenceSettings(intelligence.settings || {});

  const container = byId('sayuri-memory-candidates');
  if (!container) return;
  container.replaceChildren();

  const candidates = payload.candidates || [];
  if (!candidates.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Новых кандидатов памяти пока нет.';
    container.append(empty);
    return;
  }

  for (const candidate of candidates) {
    const card = document.createElement('article');
    card.className = `sayuri-memory-candidate ${candidate.status} ${candidate.relation}`;

    const head = document.createElement('div');
    head.className = 'sayuri-memory-candidate-head';

    const badges = document.createElement('div');
    const scope = document.createElement('span');
    scope.className = `memory-scope ${candidate.scope}`;
    scope.textContent = candidate.scope === 'personal' ? 'ЛИЧНАЯ' : 'ПРОЕКТНАЯ';
    const kind = document.createElement('span');
    kind.textContent = memoryKindLabel(candidate.kind);
    const relation = document.createElement('span');
    relation.className = `memory-relation ${candidate.relation}`;
    relation.textContent = memoryRelationLabel(candidate.relation);
    badges.append(scope, kind, relation);

    const confidence = document.createElement('strong');
    confidence.textContent = `${Math.round((Number(candidate.confidence) || 0) * 100)}%`;
    confidence.title = 'Уверенность Memory Intelligence';
    head.append(badges, confidence);

    const text = document.createElement('p');
    text.textContent = candidate.content;

    const reason = document.createElement('small');
    const contextName = candidate.source_context?.current_document?.name;
    reason.textContent = contextName
      ? `${candidate.reason} · источник: ${contextName}`
      : candidate.reason;

    const footer = document.createElement('div');
    footer.className = 'sayuri-memory-candidate-footer';
    const status = document.createElement('span');
    status.textContent = memoryCandidateStatusLabel(candidate.status);
    footer.append(status);

    if (candidate.status === 'pending' || candidate.status === 'conflict') {
      const controls = document.createElement('div');
      const accept = document.createElement('button');
      accept.type = 'button';
      accept.className = 'primary-button';
      accept.textContent = candidate.status === 'conflict' ? 'Сохранить как новое' : 'Сохранить';
      accept.addEventListener('click', () => reviewSayuriMemoryCandidate(candidate.id, 'accept'));
      const reject = document.createElement('button');
      reject.type = 'button';
      reject.className = 'secondary-button';
      reject.textContent = 'Не запоминать';
      reject.addEventListener('click', () => reviewSayuriMemoryCandidate(candidate.id, 'reject'));
      controls.append(accept, reject);
      footer.append(controls);
    }

    card.append(head, text, reason, footer);
    container.append(card);
  }
}

async function loadSayuriMemoryCandidates() {
  const response = await fetch('/api/sayuri/memory/candidates?limit=100', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderSayuriMemoryCandidates(data);
  return data;
}

async function reviewSayuriMemoryCandidate(candidateId, decision) {
  try {
    const result = await postJson(
      `/api/sayuri/memory/candidates/${encodeURIComponent(candidateId)}/review`,
      {decision}
    );
    setMemoryCandidateMessage(
      decision === 'accept' ? 'Кандидат сохранён в долговременную память.' : 'Кандидат отклонён.',
      decision === 'accept' ? 'ready' : ''
    );
    await Promise.all([
      loadSayuriMemory(),
      loadSayuriMemoryCandidates(),
      loadSayuriMemoryV3(),
      loadSayuriProfile(),
      loadSayuriExperience(),
      loadSystem()
    ]);
  } catch (error) {
    setMemoryCandidateMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

async function saveMemoryIntelligenceSettings() {
  const settings = {
    candidate_generation: byId('memory-intelligence-candidates').checked,
    conflict_detection: byId('memory-intelligence-conflicts').checked,
    context_linking: byId('memory-intelligence-context').checked,
    auto_save_high_confidence: byId('memory-intelligence-autosave').checked,
    auto_save_threshold: Number(byId('memory-intelligence-threshold').value)
  };
  try {
    const result = await postJson('/api/sayuri/memory/intelligence', {settings});
    renderMemoryIntelligenceSettings(result.settings || {});
    setMemoryCandidateMessage('Настройки Memory Intelligence сохранены.', 'ready');
    await Promise.all([loadSayuriMemory(), loadSayuriMemoryCandidates(), loadSayuriProfile()]);
  } catch (error) {
    setMemoryCandidateMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

function createMemoryCandidateChatNotice(candidates) {
  const actionable = (candidates || []).filter((item) => item.status === 'pending' || item.status === 'conflict');
  if (!actionable.length) return null;
  const box = document.createElement('section');
  box.className = 'sayuri-memory-chat-notice';
  const title = document.createElement('strong');
  title.textContent = actionable.length === 1
    ? 'Я заметила возможное воспоминание'
    : `Я заметила кандидатов памяти: ${actionable.length}`;
  const text = document.createElement('small');
  text.textContent = 'Я не сохранила это автоматически. Проверьте кандидаты в Личном кабинете Sayuri.';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary-button';
  button.textContent = 'Открыть память';
  button.addEventListener('click', () => {
    showView('sayuri');
    loadSayuriMemoryCandidates().catch(showSayuriProviderError);
  });
  box.append(title, text, button);
  return box;
}

function setSayuriMemoryMessage(text, kind = '') {
  const target = byId('sayuri-memory-message');
  if (!target) return;
  target.className = `sayuri-memory-message ${kind}`.trim();
  target.textContent = text;
}

function memoryKindLabel(kind) {
  return {
    fact: 'Факт',
    preference: 'Предпочтение',
    decision: 'Решение',
    task: 'Задача',
    note: 'Заметка'
  }[kind] || kind;
}

function renderSayuriMemoryList(payload) {
  renderSayuriMemoryStats(payload.stats || {});
  const container = byId('sayuri-memory-list');
  if (!container) return;
  container.replaceChildren();
  const entries = payload.entries || [];
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'В выбранной области памяти пока нет записей.';
    container.append(empty);
    return;
  }
  for (const entry of entries) {
    const card = document.createElement('article');
    card.className = 'sayuri-memory-entry';

    const meta = document.createElement('div');
    meta.className = 'sayuri-memory-entry-meta';
    const scope = document.createElement('span');
    scope.className = `memory-scope ${entry.scope}`;
    scope.textContent = entry.scope === 'personal' ? 'ЛИЧНАЯ' : 'ПРОЕКТНАЯ';
    const kind = document.createElement('span');
    kind.textContent = memoryKindLabel(entry.kind);
    const importance = document.createElement('span');
    importance.textContent = `важность ${entry.importance}/5`;
    meta.append(scope, kind, importance);

    const body = document.createElement('p');
    body.textContent = entry.content;

    const footer = document.createElement('div');
    footer.className = 'sayuri-memory-entry-footer';
    const details = document.createElement('small');
    const semantic = entry.retrieval === 'hybrid-semantic-v1'
      ? ` · смысл ${Math.round((Number(entry.relevance) || 0) * 100)}%`
      : '';
    details.textContent = `${entry.source} · использовано ${entry.use_count || 0} раз${semantic} · ${formatDate(entry.updated_at)}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary-button danger-soft';
    remove.textContent = 'Удалить';
    remove.addEventListener('click', () => deleteSayuriMemory(entry.id));
    footer.append(details, remove);

    card.append(meta, body, footer);
    container.append(card);
  }
}

async function loadSayuriMemory() {
  const params = new URLSearchParams();
  const scope = byId('sayuri-memory-filter')?.value || '';
  const query = byId('sayuri-memory-search')?.value?.trim() || '';
  if (scope) params.set('scope', scope);
  if (query) params.set('q', query);
  params.set('limit', '150');
  const response = await fetch(`/api/sayuri/memory?${params.toString()}`, {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderSayuriMemoryList(data);
  return data;
}

async function saveSayuriMemory(event) {
  event.preventDefault();
  const text = byId('sayuri-memory-content').value.trim();
  if (!text) {
    setSayuriMemoryMessage('Введите то, что Sayuri должна помнить.', 'error');
    return;
  }
  try {
    const result = await postJson('/api/sayuri/memory', {
      scope: byId('sayuri-memory-scope').value,
      kind: byId('sayuri-memory-kind').value,
      importance: Number(byId('sayuri-memory-importance').value),
      content: text
    });
    byId('sayuri-memory-content').value = '';
    renderSayuriMemoryStats(result.stats || {});
    setSayuriMemoryMessage('Запись сохранена в долговременную память.', 'ready');
    await Promise.all([loadSayuriMemory(), loadSayuriMemoryV3(), loadSayuriProfile(), loadSystem()]);
  } catch (error) {
    setSayuriMemoryMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

async function deleteSayuriMemory(entryId) {
  if (!window.confirm('Удалить эту запись из долговременной памяти Sayuri?')) return;
  try {
    const response = await fetch(`/api/sayuri/memory/${encodeURIComponent(entryId)}`, {method: 'DELETE'});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    setSayuriMemoryMessage(data.deleted ? 'Запись удалена.' : 'Запись уже отсутствует.');
    await Promise.all([loadSayuriMemory(), loadSayuriProfile(), loadSystem()]);
  } catch (error) {
    setSayuriMemoryMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

function setSayuriAvatarMessage(text, kind = '') {
  const target = byId('sayuri-avatar-message');
  if (!target) return;
  target.className = `sayuri-avatar-message ${kind}`.trim();
  target.textContent = text;
}

function renderSayuriAvatarManager(slots) {
  const container = byId('sayuri-avatar-grid');
  if (!container) return;
  container.replaceChildren();
  const order = ['orb', 'chat', 'profile', 'hero'];

  for (const slotName of order) {
    const slot = slots[slotName];
    if (!slot) continue;
    const card = document.createElement('article');
    card.className = 'sayuri-avatar-slot';

    const preview = document.createElement('img');
    preview.src = slot.url;
    preview.alt = slot.label;

    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = slot.label;
    const recommend = document.createElement('span');
    recommend.textContent = `рекомендуется ${slot.recommended}×${slot.recommended}px`;
    const actual = document.createElement('small');
    actual.textContent = slot.custom
      ? `${slot.width || '?'}×${slot.height || '?'} · ${formatBytes(slot.size_bytes)} · ${slot.filename || ''}`
      : 'Сейчас используется стандартный образ Sayuri';
    copy.append(title, recommend, actual);

    const actions = document.createElement('div');
    actions.className = 'sayuri-avatar-slot-actions';
    const choose = document.createElement('button');
    choose.type = 'button';
    choose.className = 'secondary-button';
    choose.textContent = slot.custom ? 'Заменить' : 'Загрузить';
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.hidden = true;
    choose.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (file) uploadSayuriAvatar(slotName, file);
      input.value = '';
    });
    actions.append(choose, input);

    if (slot.custom) {
      const reset = document.createElement('button');
      reset.type = 'button';
      reset.className = 'secondary-button danger-soft';
      reset.textContent = 'Стандартный';
      reset.addEventListener('click', () => resetSayuriAvatar(slotName));
      actions.append(reset);
    }

    card.append(preview, copy, actions);
    container.append(card);
  }
}

async function uploadSayuriAvatar(slot, file) {
  if (file.size > 8 * 1024 * 1024) {
    setSayuriAvatarMessage('Файл больше 8 МБ.', 'error');
    return;
  }
  setSayuriAvatarMessage(`Загружаю «${file.name}»…`);
  try {
    const response = await fetch(`/api/sayuri/avatar/upload?slot=${encodeURIComponent(slot)}`, {
      method: 'POST',
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-Sayuri-Filename': encodeURIComponent(file.name)
      },
      body: file
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    if (!sayuriState.profile) sayuriState.profile = {};
    sayuriState.profile.avatars = data.slots;
    renderSayuriAvatarManager(data.slots);
    applySayuriAvatarImages();
    renderSayuriMessages();
    setSayuriAvatarMessage('Аватар сохранён локально и применён.', 'ready');
  } catch (error) {
    setSayuriAvatarMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

async function resetSayuriAvatar(slot) {
  if (!window.confirm('Вернуть для этого размера стандартный образ Sayuri?')) return;
  try {
    const response = await fetch(`/api/sayuri/avatar/${encodeURIComponent(slot)}`, {method: 'DELETE'});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
    if (!sayuriState.profile) sayuriState.profile = {};
    sayuriState.profile.avatars = data.slots;
    renderSayuriAvatarManager(data.slots);
    applySayuriAvatarImages();
    renderSayuriMessages();
    setSayuriAvatarMessage('Для этого размера восстановлен стандартный образ.', 'ready');
  } catch (error) {
    setSayuriAvatarMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
  }
}

async function loadSayuriProfile() {
  const response = await fetch('/api/sayuri/profile', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  renderSayuriProfile(data);
  return data;
}

function showSayuriProviderError(error) {
  setSayuriProviderMessage(`Ошибка: ${error instanceof Error ? error.message : String(error)}`, 'error');
}

async function saveSayuriProvider() {
  const button = byId('sayuri-save-provider');
  const apiKey = byId('sayuri-api-key').value.trim();
  if (!apiKey && !sayuriState.profile?.provider?.configured) {
    setSayuriProviderMessage('Вставьте API-ключ Cloud.ru.', 'error');
    return;
  }
  button.disabled = true;
  setSayuriProviderMessage('Сохраняю локально…');
  try {
    const data = await postJson('/api/sayuri/provider', {api_key: apiKey || null});
    byId('sayuri-api-key').value = '';
    renderSayuriProfile(data);
    setSayuriProviderMessage('Ключ сохранён локально. В GitHub он не попадает.', 'ready');
    await loadSystem();
  } catch (error) {
    showSayuriProviderError(error);
  } finally {
    button.disabled = false;
  }
}

async function testSayuriProvider() {
  const button = byId('sayuri-test-provider');
  button.disabled = true;
  setSayuriProviderMessage('Проверяю Cloud.ru и наличие DeepSeek-V4-Flash…');
  try {
    const data = await postJson('/api/sayuri/provider/test', {});
    if (!data.model_available) {
      throw new Error('Ключ работает, но DeepSeek-V4-Flash не найден среди доступных моделей.');
    }
    setSayuriProviderMessage(`Подключение готово · ${data.latency_ms} мс · DeepSeek-V4-Flash доступна.`, 'ready');
    await loadSayuriProfile();
    await loadSystem();
  } catch (error) {
    showSayuriProviderError(error);
  } finally {
    button.disabled = false;
  }
}

async function clearSayuriProvider() {
  if (!window.confirm('Удалить сохранённый API-ключ Cloud.ru с этого компьютера?')) return;
  try {
    const data = await postJson('/api/sayuri/provider', {clear: true});
    renderSayuriProfile(data);
    byId('sayuri-api-key').value = '';
    setSayuriProviderMessage('Локальный ключ удалён.');
    await loadSystem();
  } catch (error) {
    showSayuriProviderError(error);
  }
}


function actionStatusLabel(status) {
  return {
    pending: 'Ожидает подтверждения',
    executing: 'Выполняется',
    completed: 'Выполнено',
    cancelled: 'Отменено',
    expired: 'Истекло',
    failed: 'Ошибка'
  }[status] || status;
}

function actionRiskLabel(risk) {
  return {
    low: 'низкий риск',
    medium: 'средний риск',
    high: 'высокий риск'
  }[risk] || risk;
}

function renderSayuriActionCenter(actions) {
  const toolsContainer = byId('sayuri-tool-list');
  if (toolsContainer) {
    toolsContainer.replaceChildren();
    for (const tool of actions.available_tools || []) {
      const item = document.createElement('article');
      item.className = 'sayuri-tool-chip';
      const text = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = tool.label;
      const meta = document.createElement('small');
      meta.textContent = `${actionRiskLabel(tool.risk)} · подтверждение обязательно`;
      text.append(title, meta);
      const state = document.createElement('span');
      state.textContent = 'разрешено';
      item.append(text, state);
      toolsContainer.append(item);
    }
  }

  const history = byId('sayuri-actions-history');
  if (!history) return;
  history.replaceChildren();
  const recent = actions.recent || [];
  if (!recent.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Подтверждённых действий пока не было.';
    history.append(empty);
    return;
  }
  for (const action of recent) {
    const row = document.createElement('article');
    row.className = `sayuri-action-history-row ${action.status}`;
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = action.title;
    const meta = document.createElement('small');
    meta.textContent = `${action.tool} · ${actionRiskLabel(action.risk)} · ${formatDate(action.created_at)}`;
    body.append(title, meta);
    const status = document.createElement('span');
    status.textContent = actionStatusLabel(action.status);
    row.append(body, status);
    history.append(row);
  }
}

async function loadSayuriActions() {
  const response = await fetch('/api/sayuri/actions?limit=20', {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  if (!sayuriState.profile) sayuriState.profile = {};
  sayuriState.profile.actions = {
    confirmation_required: true,
    available_tools: data.tools || [],
    recent: data.actions || []
  };
  renderSayuriActionCenter(sayuriState.profile.actions);
  return data;
}

function actionResultSummary(action) {
  if (action.status === 'completed') {
    if (action.tool === 'disk.create_folder') {
      return `Готово: папка «${action.result?.folder?.name || action.title}» создана.`;
    }
    if (action.tool === 'disk.trash_current') return 'Готово: объект перемещён в корзину.';
    if (action.tool === 'disk.set_favorite') {
      return action.result?.favorite ? 'Готово: объект добавлен в избранное.' : 'Готово: объект убран из избранного.';
    }
    if (action.tool === 'disk.move_current') return 'Готово: объект перемещён.';
    if (action.tool === 'memory.remember') return 'Готово: решение сохранено в проектную память.';
    return 'Действие выполнено.';
  }
  if (action.status === 'cancelled') return 'Действие отменено.';
  if (action.status === 'expired') return 'Время подтверждения истекло. Отправьте команду ещё раз.';
  if (action.status === 'failed') return `Действие не выполнено: ${action.error || 'неизвестная ошибка'}`;
  if (action.status === 'executing') return 'Действие уже выполняется.';
  return 'Действие ожидает подтверждения.';
}

function createSayuriActionCard(action, messageIndex) {
  const card = document.createElement('section');
  card.className = `sayuri-action-proposal ${action.status || 'pending'}`;

  const head = document.createElement('div');
  head.className = 'sayuri-action-proposal-head';
  const titleWrap = document.createElement('div');
  const eyebrow = document.createElement('span');
  eyebrow.textContent = 'ДЕЙСТВИЕ SAYURI';
  const title = document.createElement('strong');
  title.textContent = action.title;
  titleWrap.append(eyebrow, title);
  const risk = document.createElement('em');
  risk.textContent = actionRiskLabel(action.risk);
  head.append(titleWrap, risk);

  const description = document.createElement('p');
  description.textContent = action.description;

  const status = document.createElement('div');
  status.className = 'sayuri-action-proposal-status';
  status.textContent = actionStatusLabel(action.status);

  card.append(head, description, status);

  if (action.status === 'pending') {
    const warning = document.createElement('small');
    warning.textContent = 'Ничего не изменится, пока вы не нажмёте «Подтвердить».';
    const controls = document.createElement('div');
    controls.className = 'sayuri-action-proposal-controls';
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'primary-button';
    confirm.textContent = 'Подтвердить';
    confirm.addEventListener('click', () => confirmSayuriAction(messageIndex, action.id));
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'secondary-button';
    cancel.textContent = 'Отменить';
    cancel.addEventListener('click', () => cancelSayuriAction(messageIndex, action.id));
    controls.append(confirm, cancel);
    card.append(warning, controls);
  } else {
    const result = document.createElement('small');
    result.className = 'sayuri-action-result';
    result.textContent = actionResultSummary(action);
    card.append(result);
  }
  return card;
}

function updateSayuriMessageAction(messageIndex, action) {
  const message = sayuriState.messages[messageIndex];
  if (!message) return;
  message.metadata = {...(message.metadata || {}), action};
  message.content = actionResultSummary(action);
  persistSayuriHistory();
  renderSayuriMessages();
}

async function refreshAfterSayuriAction() {
  const tasks = [
    loadSystem(),
    loadSayuriProfile(),
    loadSayuriActions(),
    loadSayuriMemory(),
    loadSayuriMemoryV3(),
    loadSayuriExperience()
  ];
  if (document.querySelector('#view-disk.active')) tasks.push(loadDisk());
  await Promise.allSettled(tasks);
  updateSayuriContextUI();
}

async function confirmSayuriAction(messageIndex, actionId) {
  byId('sayuri-chat-status').textContent = 'Выполняю подтверждённое действие…';
  try {
    const action = await postJson(`/api/sayuri/actions/${encodeURIComponent(actionId)}/confirm`, {});
    updateSayuriMessageAction(messageIndex, action);
    byId('sayuri-chat-status').textContent = action.status === 'completed'
      ? 'Действие выполнено · подтверждено Господином'
      : actionResultSummary(action);
    await refreshAfterSayuriAction();
  } catch (error) {
    byId('sayuri-chat-status').textContent = `Ошибка действия: ${error instanceof Error ? error.message : String(error)}`;
  }
}

async function cancelSayuriAction(messageIndex, actionId) {
  try {
    const action = await postJson(`/api/sayuri/actions/${encodeURIComponent(actionId)}/cancel`, {});
    updateSayuriMessageAction(messageIndex, action);
    byId('sayuri-chat-status').textContent = 'Действие отменено.';
    await loadSayuriActions().catch(() => {});
  } catch (error) {
    byId('sayuri-chat-status').textContent = `Ошибка отмены: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function persistSayuriHistory() {
  if (sayuriState.rememberHistory) {
    localStorage.setItem('sayuri-chat-history', JSON.stringify(sayuriState.messages.slice(-40)));
  } else {
    localStorage.removeItem('sayuri-chat-history');
  }
}

function addSayuriMessage(role, content, metadata = null) {
  sayuriState.messages.push({role, content, metadata});
  if (sayuriState.messages.length > 40) sayuriState.messages = sayuriState.messages.slice(-40);
  persistSayuriHistory();
  renderSayuriMessages();
}

function renderSayuriMessages() {
  const container = byId('sayuri-chat-messages');
  if (!container) return;
  container.replaceChildren();

  if (!sayuriState.messages.length) {
    const welcome = document.createElement('article');
    welcome.className = 'sayuri-message assistant';
    const avatar = document.createElement('img');
    avatar.src = avatarUrl('chat');
    avatar.alt = '';
    const bubble = document.createElement('div');
    bubble.textContent = 'Я рядом, Господин. Откройте любой раздел проекта — я буду учитывать текущий экран в разговоре.';
    welcome.append(avatar, bubble);
    container.append(welcome);
    return;
  }

  sayuriState.messages.forEach((message, messageIndex) => {
    const row = document.createElement('article');
    row.className = `sayuri-message ${message.role}`;
    if (message.role === 'assistant') {
      const avatar = document.createElement('img');
      avatar.src = avatarUrl('chat');
      avatar.alt = '';
      row.append(avatar);
    }
    const bubble = document.createElement('div');
    const text = document.createElement('p');
    text.className = 'sayuri-message-text';
    text.textContent = message.content;
    bubble.append(text);
    if (message.metadata?.action) {
      bubble.append(createSayuriActionCard(message.metadata.action, messageIndex));
    }
    if (message.metadata?.memory_candidates) {
      const notice = createMemoryCandidateChatNotice(message.metadata.memory_candidates);
      if (notice) bubble.append(notice);
    }
    const feedback = createSayuriFeedbackControls(messageIndex, message);
    if (feedback) bubble.append(feedback);
    row.append(bubble);
    container.append(row);
  });
  container.scrollTop = container.scrollHeight;
}

function openSayuriChat() {
  byId('sayuri-chat-window').classList.remove('hidden');
  updateSayuriContextUI();
  renderSayuriMessages();
  window.setTimeout(() => byId('sayuri-chat-input').focus(), 0);
}

function closeSayuriChat() {
  byId('sayuri-chat-window').classList.add('hidden');
}

async function sendSayuriMessage(text) {
  const message = text.trim();
  if (!message) return;

  const history = sayuriState.messages
    .filter((item) => item.role === 'user' || item.role === 'assistant')
    .slice(-16)
    .map(({role, content}) => ({role, content}));

  addSayuriMessage('user', message);
  byId('sayuri-chat-input').value = '';
  byId('sayuri-chat-send').disabled = true;
  byId('sayuri-chat-status').textContent = 'Sayuri думает через DeepSeek-V4-Flash…';

  try {
    const context = currentSayuriContext();
    const planned = await postJson('/api/sayuri/actions/plan', {
      text: message,
      context
    });
    if (planned.action) {
      addSayuriMessage(
        'assistant',
        'Я подготовила изменение проекта. Проверьте его и подтвердите выполнение.',
        {action: planned.action}
      );
      byId('sayuri-chat-status').textContent = 'Действие подготовлено · ожидает подтверждения';
      loadSayuriActions().catch(() => {});
      return;
    }

    const result = await postJson('/api/sayuri/chat', {
      message,
      history,
      context
    });
    addSayuriMessage('assistant', result.answer, {
      model: result.model,
      usage: result.usage,
      memory_used: result.memory_used,
      memory_saved: result.memory_saved,
      memory_candidates: result.memory_candidates || [],
      response_id: result.response_id || null,
      semantic_memory: result.semantic_memory || null,
      memory_v3: result.memory_v3 || null,
      memory_v3_used: result.memory_v3_used || 0,
      experience_used: result.experience_used || 0,
      prompt: message
    });
    if (result.memory_saved) {
      loadSayuriMemory().catch(() => {});
      loadSayuriMemoryV3().catch(() => {});
      loadSayuriProfile().catch(() => {});
    }
    if (result.memory_candidates?.length) {
      loadSayuriMemoryCandidates().catch(() => {});
      loadSayuriProfile().catch(() => {});
    }
    byId('sayuri-chat-status').textContent = result.model === 'local-memory'
      ? 'Память Sayuri · сохранено локально'
      : `DeepSeek-V4-Flash · память ${result.memory_used || 0} · знания ${result.memory_v3_used || 0} · опыт ${result.experience_used || 0}`;
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error);
    addSayuriMessage('assistant', `Не удалось получить ответ: ${text}`);
    byId('sayuri-chat-status').textContent = 'Ошибка подключения к AI';
  } finally {
    byId('sayuri-chat-send').disabled = false;
  }
}

function openSayuriContextMenu(event) {
  event.preventDefault();
  const menu = byId('sayuri-context-menu');
  menu.classList.remove('hidden');
  const margin = 10;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(margin, Math.min(event.clientX, window.innerWidth - rect.width - margin))}px`;
  menu.style.top = `${Math.max(margin, Math.min(event.clientY, window.innerHeight - rect.height - margin))}px`;
}

function closeSayuriContextMenu() {
  byId('sayuri-context-menu').classList.add('hidden');
}

function runSayuriAction(action) {
  closeSayuriContextMenu();
  if (action === 'account') {
    showView('sayuri');
    return;
  }
  openSayuriChat();
  const prompts = {
    see: 'Sayuri, опиши, что ты видишь сейчас в интерфейсе проекта и какой контекст у тебя есть.',
    explain: 'Sayuri, объясни текущий раздел проекта: что здесь находится и чем ты можешь мне помочь.',
    improve: 'Sayuri, оцени текущий раздел проекта и предложи наиболее полезные улучшения. Отдели факты от предложений.'
  };
  if (prompts[action]) sendSayuriMessage(prompts[action]);
}

function applySayuriPreferences() {
  const orb = byId('sayuri-orb');
  orb.classList.toggle('hidden', !sayuriState.visible);
  byId('sayuri-visible-toggle').checked = sayuriState.visible;
  byId('sayuri-position-toggle').checked = sayuriState.rememberPosition;
  byId('sayuri-history-toggle').checked = sayuriState.rememberHistory;

  const orbPosition = readLocalJson('sayuri-orb-position', null);
  if (sayuriState.rememberPosition && orbPosition) {
    orb.style.left = `${orbPosition.left}px`;
    orb.style.top = `${orbPosition.top}px`;
    orb.style.right = 'auto';
    orb.style.bottom = 'auto';
  }

  const chatPosition = readLocalJson('sayuri-chat-position', null);
  const chat = byId('sayuri-chat-window');
  if (sayuriState.rememberPosition && chatPosition) {
    chat.style.left = `${chatPosition.left}px`;
    chat.style.top = `${chatPosition.top}px`;
    chat.style.right = 'auto';
    chat.style.bottom = 'auto';
  }
}

function clampFloating(element, left, top) {
  const margin = 8;
  return {
    left: Math.max(margin, Math.min(left, window.innerWidth - element.offsetWidth - margin)),
    top: Math.max(margin, Math.min(top, window.innerHeight - element.offsetHeight - margin))
  };
}

function beginOrbDrag(event) {
  if (event.button !== 0) return;
  const orb = byId('sayuri-orb');
  const rect = orb.getBoundingClientRect();
  sayuriState.orbDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    left: rect.left,
    top: rect.top,
    moved: false
  };
  orb.setPointerCapture?.(event.pointerId);
}

function moveOrbDrag(event) {
  const drag = sayuriState.orbDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const dx = event.clientX - drag.startX;
  const dy = event.clientY - drag.startY;
  if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
  if (!drag.moved) return;
  const orb = byId('sayuri-orb');
  const pos = clampFloating(orb, drag.left + dx, drag.top + dy);
  orb.style.left = `${pos.left}px`;
  orb.style.top = `${pos.top}px`;
  orb.style.right = 'auto';
  orb.style.bottom = 'auto';
}

function endOrbDrag(event) {
  const drag = sayuriState.orbDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  sayuriState.suppressOrbClick = drag.moved;
  sayuriState.orbDrag = null;
  if (drag.moved && sayuriState.rememberPosition) {
    const rect = byId('sayuri-orb').getBoundingClientRect();
    localStorage.setItem('sayuri-orb-position', JSON.stringify({left: rect.left, top: rect.top}));
  }
}

function beginChatDrag(event) {
  if (event.button !== 0 || event.target.closest('button')) return;
  const chat = byId('sayuri-chat-window');
  const rect = chat.getBoundingClientRect();
  sayuriState.chatDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    left: rect.left,
    top: rect.top
  };
  byId('sayuri-chat-drag').setPointerCapture?.(event.pointerId);
}

function moveChatDrag(event) {
  const drag = sayuriState.chatDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const chat = byId('sayuri-chat-window');
  const pos = clampFloating(
    chat,
    drag.left + event.clientX - drag.startX,
    drag.top + event.clientY - drag.startY
  );
  chat.style.left = `${pos.left}px`;
  chat.style.top = `${pos.top}px`;
  chat.style.right = 'auto';
  chat.style.bottom = 'auto';
}

function endChatDrag(event) {
  const drag = sayuriState.chatDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  sayuriState.chatDrag = null;
  if (sayuriState.rememberPosition) {
    const rect = byId('sayuri-chat-window').getBoundingClientRect();
    localStorage.setItem('sayuri-chat-position', JSON.stringify({left: rect.left, top: rect.top}));
  }
}

function resetSayuriLayout() {
  localStorage.removeItem('sayuri-orb-position');
  localStorage.removeItem('sayuri-chat-position');
  const orb = byId('sayuri-orb');
  const chat = byId('sayuri-chat-window');
  for (const element of [orb, chat]) {
    element.style.left = '';
    element.style.top = '';
    element.style.right = '';
    element.style.bottom = '';
  }
  setSayuriProviderMessage('Положение Sayuri сброшено.');
}

function initializeSayuri() {
  applySayuriPreferences();
  renderSayuriMessages();
  updateSayuriContextUI();

  byId('sayuri-orb').addEventListener('click', () => {
    if (sayuriState.suppressOrbClick) {
      sayuriState.suppressOrbClick = false;
      return;
    }
    if (byId('sayuri-chat-window').classList.contains('hidden')) openSayuriChat();
    else closeSayuriChat();
  });
  byId('sayuri-orb').addEventListener('contextmenu', openSayuriContextMenu);
  byId('sayuri-orb').addEventListener('pointerdown', beginOrbDrag);
  byId('sayuri-orb').addEventListener('pointermove', moveOrbDrag);
  byId('sayuri-orb').addEventListener('pointerup', endOrbDrag);
  byId('sayuri-orb').addEventListener('pointercancel', endOrbDrag);

  byId('sayuri-chat-drag').addEventListener('pointerdown', beginChatDrag);
  byId('sayuri-chat-drag').addEventListener('pointermove', moveChatDrag);
  byId('sayuri-chat-drag').addEventListener('pointerup', endChatDrag);
  byId('sayuri-chat-drag').addEventListener('pointercancel', endChatDrag);

  byId('sayuri-chat-close').addEventListener('click', closeSayuriChat);
  byId('sayuri-chat-clear').addEventListener('click', () => {
    sayuriState.messages = [];
    persistSayuriHistory();
    renderSayuriMessages();
  });
  byId('sayuri-chat-form').addEventListener('submit', (event) => {
    event.preventDefault();
    sendSayuriMessage(byId('sayuri-chat-input').value);
  });
  byId('sayuri-chat-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      byId('sayuri-chat-form').requestSubmit();
    }
  });

  byId('sayuri-account-nav').addEventListener('click', () => showView('sayuri'));
  byId('sayuri-open-chat-account').addEventListener('click', openSayuriChat);
  byId('sayuri-save-provider').addEventListener('click', saveSayuriProvider);
  byId('sayuri-test-provider').addEventListener('click', testSayuriProvider);
  byId('sayuri-clear-provider').addEventListener('click', clearSayuriProvider);
  byId('sayuri-key-toggle').addEventListener('click', () => {
    const input = byId('sayuri-api-key');
    const visible = input.type === 'text';
    input.type = visible ? 'password' : 'text';
    byId('sayuri-key-toggle').textContent = visible ? 'Показать' : 'Скрыть';
  });
  byId('sayuri-visible-toggle').addEventListener('change', (event) => {
    sayuriState.visible = event.target.checked;
    localStorage.setItem('sayuri-visible', sayuriState.visible ? '1' : '0');
    applySayuriPreferences();
  });
  byId('sayuri-position-toggle').addEventListener('change', (event) => {
    sayuriState.rememberPosition = event.target.checked;
    localStorage.setItem('sayuri-remember-position', sayuriState.rememberPosition ? '1' : '0');
    if (!sayuriState.rememberPosition) {
      localStorage.removeItem('sayuri-orb-position');
      localStorage.removeItem('sayuri-chat-position');
    }
  });
  byId('sayuri-history-toggle').addEventListener('change', (event) => {
    sayuriState.rememberHistory = event.target.checked;
    localStorage.setItem('sayuri-remember-history', sayuriState.rememberHistory ? '1' : '0');
    persistSayuriHistory();
  });
  byId('sayuri-reset-layout').addEventListener('click', resetSayuriLayout);

  byId('sayuri-memory-form').addEventListener('submit', saveSayuriMemory);
  byId('sayuri-memory-filter').addEventListener('change', () => loadSayuriMemory().catch(showSayuriProviderError));
  byId('sayuri-memory-refresh').addEventListener('click', () => loadSayuriMemory().catch(showSayuriProviderError));
  byId('memory-candidates-refresh').addEventListener('click', () => loadSayuriMemoryCandidates().catch(showSayuriProviderError));
  byId('memory-intelligence-save').addEventListener('click', saveMemoryIntelligenceSettings);
  byId('sayuri-memory-search').addEventListener('input', () => {
    if (sayuriMemorySearchTimer) window.clearTimeout(sayuriMemorySearchTimer);
    sayuriMemorySearchTimer = window.setTimeout(() => loadSayuriMemory().catch(showSayuriProviderError), 250);
  });
  byId('sayuri-avatar-refresh').addEventListener('click', () => loadSayuriProfile().catch(showSayuriProviderError));
  byId('sayuri-actions-refresh').addEventListener('click', () => loadSayuriActions().catch(showSayuriProviderError));
  byId('sayuri-experience-refresh').addEventListener('click', () => loadSayuriExperience().catch(showSayuriProviderError));
  byId('sayuri-memory-v3-refresh').addEventListener('click', () => loadSayuriMemoryV3().catch(showSayuriProviderError));
  byId('sayuri-memory-v3-maintain').addEventListener('click', maintainSayuriMemoryV3);

  document.querySelectorAll('[data-sayuri-action]').forEach((button) => {
    button.addEventListener('click', () => runSayuriAction(button.dataset.sayuriAction));
  });
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
byId('dna-load-retry').addEventListener('click', () => {
  if (viewerItem?.kind === 'file') {
    loadViewerDna(viewerItem.id, true).catch(showDiskError);
  }
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
  if (!event.target.closest('#sayuri-context-menu') && !event.target.closest('#sayuri-orb')) {
    closeSayuriContextMenu();
  }
});
window.addEventListener('resize', () => {
  closeContextMenu();
  closeSayuriContextMenu();
  updateSayuriContextUI();
});
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
    closeSayuriContextMenu();
    if (!byId('move-modal').classList.contains('hidden')) closeMoveModal();
    if (!byId('file-viewer-modal').classList.contains('hidden')) closeViewer();
    if (!byId('sayuri-chat-window').classList.contains('hidden')) closeSayuriChat();
  }
});

const initialHash = location.hash;
const initialView = initialHash === '#disk'
  ? 'disk'
  : initialHash === '#sayuri'
    ? 'sayuri'
    : (initialHash === '#settings' || initialHash.startsWith('#system-') ? 'settings' : 'home');
initializeSayuri();
showView(initialView);

Promise.all([loadSettings(), loadSystem(), loadSayuriProfile()])
  .then(loadEvents)
  .catch((error) => {
    setStatus('error', 'Ошибка запуска интерфейса');
    byId('updated-at').textContent = String(error);
  });
