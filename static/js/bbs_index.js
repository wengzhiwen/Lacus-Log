(() => {
  const config = window.BBS_CONFIG || {};
  const csrfToken = config.csrfToken || '';

  const boardListEl = document.getElementById('bbs-board-list');
  const postListEl = document.getElementById('bbs-post-list');
  const statusBarEl = document.getElementById('bbs-status-bar');
  const paginationEl = document.getElementById('bbs-pagination');
  const searchInput = document.getElementById('bbs-search-input');
  const searchBtn = document.getElementById('bbs-search-btn');
  const filterMineEl = document.getElementById('bbs-filter-mine');
  const createBtn = document.getElementById('bbs-create-post-btn');

  const editorPanel = document.getElementById('bbs-editor-panel');
  const editorCloseBtn = document.getElementById('bbs-editor-close');
  const editorCancelBtn = document.getElementById('bbs-editor-cancel');
  const editorForm = document.getElementById('bbs-editor-form');
  const editorBoardSelect = document.getElementById('bbs-editor-board');
  const editorTitleInput = document.getElementById('bbs-editor-title-input');
  const editorContentInput = document.getElementById('bbs-editor-content');
  const editorMessage = document.getElementById('bbs-editor-message');

  const state = {
    boards: [],
    selectedBoardId: null,
    page: 1,
    perPage: 20,
    keyword: '',
    mineOnly: false,
    loadingBoards: false,
    loadingPosts: false
  };

  function setStatus(message) {
    if (!statusBarEl) return;
    statusBarEl.textContent = message || '';
  }

  function setEditorMessage(type, text) {
    if (!editorMessage) return;
    if (!text) {
      editorMessage.style.display = 'none';
      editorMessage.textContent = '';
      return;
    }
    editorMessage.textContent = text;
    editorMessage.className = `bbs-modal-message ${type}`;
    editorMessage.style.display = 'block';
  }

  async function request(url, options = {}) {
    const headers = options.headers || {};
    if (options.method && options.method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = csrfToken;
    }
    const response = await fetch(url, {
      credentials: 'include',
      ...options,
      headers
    });
    if (response.status === 401) {
      await (window.handle401 ? window.handle401() : Promise.resolve());
      throw new Error('UNAUTHORIZED');
    }
    const data = await response.json();
    if (!response.ok || data.success === false) {
      const error = data.error || {};
      throw new Error(error.message || '请求失败');
    }
    return data;
  }

  function renderBoards() {
    if (!boardListEl) return;
    boardListEl.innerHTML = '';
    state.boards.forEach((board) => {
      const li = document.createElement('li');
      li.className = board.id === state.selectedBoardId ? 'active' : '';
      li.textContent = board.name;
      li.dataset.boardId = board.id;
      li.addEventListener('click', () => {
        state.selectedBoardId = board.id;
        state.page = 1;
        renderBoards();
        loadPosts();
      });
      boardListEl.appendChild(li);
    });
  }

  function renderEditorBoards() {
    if (!editorBoardSelect) return;
    editorBoardSelect.innerHTML = '';
    state.boards.forEach((board) => {
      const option = document.createElement('option');
      option.value = board.id;
      option.textContent = board.name;
      editorBoardSelect.appendChild(option);
    });
    if (state.selectedBoardId) {
      editorBoardSelect.value = state.selectedBoardId;
    }
  }

  function renderPosts(items, meta) {
    if (!postListEl) return;
    postListEl.innerHTML = '';
    if (!items.length) {
      postListEl.innerHTML = '<div class="empty">暂无帖子</div>';
      paginationEl.innerHTML = '';
      return;
    }

    items.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'bbs-post-card';
      card.dataset.postId = item.id;

      const tags = [];
      if (item.is_pinned) tags.push('<span class="tag tag-info">置顶</span>');
      if (item.status === 'hidden') tags.push('<span class="tag tag-warning">隐藏</span>');
      if (item.related_battle_record_missing) {
        tags.push('<span class="tag tag-warning">关联记录丢失</span>');
      }

      const lastReply = item.last_reply
        ? `<span>最后回复：${item.last_reply.author?.display_name || '-'} · ${item.last_reply.time?.display || '-'}</span>`
        : '<span>暂无回复</span>';

      card.innerHTML = `
        <div class="card-header">
          <div class="title">${item.title}</div>
          <div class="tags">${tags.join(' ')}</div>
        </div>
        <div class="card-meta">
          <span>作者：${item.author?.display_name || '-'}</span>
          <span>创建：${item.created_at?.display || '-'}</span>
        </div>
        <div class="card-meta">
          <span>回复数：${item.reply_count}</span>
          ${lastReply}
        </div>
      `;

      card.addEventListener('click', () => {
        window.BBSModal && window.BBSModal.open(item.id);
      });

      postListEl.appendChild(card);
    });

    renderPagination(meta);
  }

  function renderPagination(meta) {
    if (!paginationEl) return;
    paginationEl.innerHTML = '';
    if (!meta || meta.total <= meta.per_page) return;

    const totalPages = Math.ceil(meta.total / meta.per_page);

    const prevBtn = document.createElement('button');
    prevBtn.textContent = '上一页';
    prevBtn.className = 'btn btn-secondary';
    prevBtn.disabled = meta.page <= 1;
    prevBtn.addEventListener('click', () => {
      if (state.page > 1) {
        state.page -= 1;
        loadPosts();
      }
    });
    paginationEl.appendChild(prevBtn);

    const pageInfo = document.createElement('span');
    pageInfo.className = 'page-info';
    pageInfo.textContent = `第 ${meta.page} / ${totalPages} 页`;
    paginationEl.appendChild(pageInfo);

    const nextBtn = document.createElement('button');
    nextBtn.textContent = '下一页';
    nextBtn.className = 'btn btn-secondary';
    nextBtn.disabled = !meta.has_more;
    nextBtn.addEventListener('click', () => {
      state.page += 1;
      loadPosts();
    });
    paginationEl.appendChild(nextBtn);
  }

  async function loadBoards() {
    state.loadingBoards = true;
    try {
      const res = await request('/api/bbs/boards?is_active=1');
      state.boards = res.data.items || [];
      if (!state.selectedBoardId && state.boards.length) {
        state.selectedBoardId = state.boards[0].id;
      }
      renderBoards();
      renderEditorBoards();
    } catch (error) {
      setStatus(error.message || '板块加载失败');
    } finally {
      state.loadingBoards = false;
    }
  }

  async function loadPosts() {
    if (!state.selectedBoardId) {
      postListEl.innerHTML = '<div class="empty">请先选择板块</div>';
      return;
    }
    state.loadingPosts = true;
    setStatus('加载帖子中...');
    const params = new URLSearchParams();
    params.set('board_id', state.selectedBoardId);
    params.set('page', state.page);
    params.set('per_page', state.perPage);
    if (state.keyword) params.set('keyword', state.keyword);
    if (state.mineOnly) params.set('mine', '1');
    try {
      const res = await request(`/api/bbs/posts?${params.toString()}`);
      renderPosts(res.data.items || [], res.meta);
      setStatus('');
    } catch (error) {
      postListEl.innerHTML = `<div class="error">${error.message || '帖子加载失败'}</div>`;
      setStatus(error.message || '帖子加载失败');
    } finally {
      state.loadingPosts = false;
    }
  }

  function openEditor() {
    if (!editorPanel) return;
    editorPanel.classList.remove('hidden');
    editorPanel.setAttribute('aria-hidden', 'false');
    editorTitleInput.value = '';
    editorContentInput.value = '';
    setEditorMessage(null, '');
    renderEditorBoards();
    if (state.selectedBoardId) {
      editorBoardSelect.value = state.selectedBoardId;
    }
  }

  function closeEditor() {
    if (!editorPanel) return;
    editorPanel.classList.add('hidden');
    editorPanel.setAttribute('aria-hidden', 'true');
    setEditorMessage(null, '');
  }

  async function submitEditor(event) {
    event.preventDefault();
    const boardId = editorBoardSelect.value;
    const title = editorTitleInput.value.trim();
    const content = editorContentInput.value.trim();
    if (!boardId || !title || !content) {
      setEditorMessage('error', '请完整填写必填项');
      return;
    }

    try {
      const res = await request('/api/bbs/posts', {
        method: 'POST',
        body: JSON.stringify({
          board_id: boardId,
          title,
          content
        })
      });
      closeEditor();
      window.showMessage && window.showMessage('帖子发布成功', 'success', 3000);
      state.selectedBoardId = boardId;
      state.page = 1;
      await loadPosts();
      const postId = res.data?.post?.id;
      if (postId && window.BBSModal) {
        window.BBSModal.open(postId);
      }
    } catch (error) {
      setEditorMessage('error', error.message || '发布失败');
    }
  }

  function bindEvents() {
    searchBtn?.addEventListener('click', () => {
      state.keyword = searchInput.value.trim();
      state.page = 1;
      loadPosts();
    });
    searchInput?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        state.keyword = searchInput.value.trim();
        state.page = 1;
        loadPosts();
      }
    });
    filterMineEl?.addEventListener('change', () => {
      state.mineOnly = filterMineEl.checked;
      state.page = 1;
      loadPosts();
    });
    createBtn?.addEventListener('click', openEditor);
    editorCloseBtn?.addEventListener('click', closeEditor);
    editorCancelBtn?.addEventListener('click', closeEditor);
    editorForm?.addEventListener('submit', submitEditor);

    window.addEventListener('bbs:postUpdated', (event) => {
      const currentId = window.BBSModal?.getCurrentPostId?.();
      const updatedId = event.detail?.postId;
      if (currentId && updatedId === currentId) {
        loadPosts();
      }
    });
  }

  async function init() {
    bindEvents();
    await loadBoards();
    await loadPosts();
    if (config.initialPostId && window.BBSModal) {
      window.BBSModal.open(config.initialPostId);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
