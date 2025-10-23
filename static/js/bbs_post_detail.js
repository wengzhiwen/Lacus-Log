(function(){
  "use strict";

  const config = window.BBS_CONFIG || {};
  const modal = document.getElementById('bbs-post-modal');
  if (!modal) return;

  const closeBtn = document.getElementById('bbs-modal-close');
  const titleEl = document.getElementById('bbs-modal-title');
  const metaEl = document.getElementById('bbs-modal-meta');
  const actionsEl = document.getElementById('bbs-modal-actions');
  const contentEl = document.getElementById('bbs-post-content');
  const messageEl = document.getElementById('bbs-modal-message');
  const repliesContainer = document.getElementById('bbs-replies-container');
  const replyEditorTitle = document.getElementById('bbs-reply-editor-title');
  const replyTextarea = document.getElementById('bbs-reply-content');
  const replySubmitBtn = document.getElementById('bbs-reply-submit');
  const replyResetBtn = document.getElementById('bbs-reply-reset');
  const replyHint = document.getElementById('bbs-reply-hint');
  const relatedPilotsEl = document.getElementById('bbs-related-pilots');

  const editForm = document.getElementById('bbs-post-edit-form');
  const editTitleInput = document.getElementById('bbs-edit-title');
  const editContentInput = document.getElementById('bbs-edit-content');
  const editCancelBtn = document.getElementById('bbs-edit-cancel');
  const editSaveBtn = document.getElementById('bbs-edit-save');

  const viewContainer = document.getElementById('bbs-post-view');

  const state = {
    postId: null,
    postData: null,
    parentReplyId: null,
    replyingToName: '',
    loading: false,
    submittingReply: false,
    editingReplyId: null,
    editingDraft: ''
  };

  const currentUser = config.currentUser || { id: null, roles: [] };
  const isAdmin = () => (currentUser.roles || []).includes('gicho');

  function setMessage(type, text) {
    if (!messageEl) return;
    if (!text) {
      messageEl.style.display = 'none';
      messageEl.textContent = '';
      return;
    }
    messageEl.textContent = text;
    messageEl.className = `bbs-modal-message ${type}`;
    messageEl.style.display = 'block';
  }

  function showModal() {
    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
  }

  function hideModal() {
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
    state.postId = null;
    state.postData = null;
    resetReplyContext();
    setMessage(null, '');
  }

  function resetReplyContext() {
    state.parentReplyId = null;
    state.replyingToName = '';
    replyTextarea.value = '';
    replyHint.style.display = 'none';
    replyResetBtn.style.display = 'none';
    replyEditorTitle.textContent = '发表回复';
  }

  function resetEditingContext() {
    state.editingReplyId = null;
    state.editingDraft = '';
  }

  function setReplySubmitting(isSubmitting) {
    if (!replySubmitBtn) return;
    if (!replySubmitBtn.dataset.defaultText) {
      replySubmitBtn.dataset.defaultText = replySubmitBtn.textContent || '提交回复';
    }
    state.submittingReply = isSubmitting;
    replySubmitBtn.disabled = isSubmitting;
    replySubmitBtn.textContent = isSubmitting ? '提交中...' : replySubmitBtn.dataset.defaultText;
  }

  async function request(url, options = {}) {
    const headers = options.headers || {};
    if (options.method && options.method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = config.csrfToken || '';
    }
    try {
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
    } catch (error) {
      throw error;
    }
  }

  function formatDate(meta) {
    if (!meta || !meta.display) return '未知时间';
    return meta.display;
  }

  function canEditPost(post) {
    if (!post) return false;
    if (isAdmin()) return true;
    return post.author && post.author.id === currentUser.id;
  }

  function canManagePilots() {
    return isAdmin();
  }

  function canHidePost(post) {
    return canEditPost(post);
  }

  function buildActionButton(text, className, onClick, extraAttrs = {}) {
    const btn = document.createElement('button');
    btn.textContent = text;
    btn.className = `btn ${className}`;
    Object.entries(extraAttrs).forEach(([key, value]) => {
      btn.setAttribute(key, value);
    });
    btn.addEventListener('click', onClick);
    return btn;
  }

  function renderPostContent(post) {
    titleEl.textContent = post.title;
    const authorName = post.author?.display_name || post.author?.nickname || '未知作者';
    const statusLabel = post.status === 'hidden' ? '<span class="tag tag-warning">隐藏</span>' : '';
    const pinLabel = post.is_pinned ? '<span class="tag tag-info">置顶</span>' : '';
    metaEl.innerHTML = `
      <div class="author">
        <span class="name">${authorName}</span>
        ${pinLabel}
        ${statusLabel}
      </div>
      <div class="time">
        <span>发布:${formatDate(post.created_at)}</span>
        <span>最后活跃:${formatDate(post.last_active_at)}</span>
      </div>
    `;

    contentEl.textContent = post.content || '';
  }

  function renderActions(post) {
    actionsEl.innerHTML = '';
    if (canEditPost(post)) {
      actionsEl.appendChild(buildActionButton('编辑帖子', 'btn-secondary', () => toggleEditMode(true)));
    }
    if (canHidePost(post)) {
      if (post.status === 'hidden') {
        actionsEl.appendChild(buildActionButton('取消隐藏', 'btn-secondary', () => togglePostHidden(false)));
      } else {
        actionsEl.appendChild(buildActionButton('隐藏帖子', 'btn-danger', () => togglePostHidden(true)));
      }
    }
    if (isAdmin()) {
      const pinText = post.is_pinned ? '取消置顶' : '置顶';
      actionsEl.appendChild(buildActionButton(pinText, 'btn-secondary', () => togglePin(!post.is_pinned)));
    }
  }

  function renderPilots(pilotData) {
    relatedPilotsEl.innerHTML = '';
    const actionBar = document.createElement('div');
    actionBar.className = 'bbs-related-actions';
    const recordMissing = Boolean(state.postData?.post?.related_battle_record_missing);

    if (state.postData?.post?.related_battle_record_id && !recordMissing) {
      const recordBtn = document.createElement('button');
      recordBtn.className = 'btn btn-primary btn-compact';
      recordBtn.textContent = '查看开播记录';
      recordBtn.addEventListener('click', () => {
        const recordId = state.postData.post.related_battle_record_id;
        window.open(`/battle-records/${recordId}`, '_blank');
      });
      actionBar.appendChild(recordBtn);
    }

    if (pilotData && pilotData.length) {
      const primaryPilot = pilotData[0];
      const pilotLabel = (() => {
        const nickname = primaryPilot.pilot_name || '';
        const realName = primaryPilot.pilot_real_name || '';
        if (nickname && realName) {
          return `${nickname}(${realName})`;
        }
        return nickname || realName || '查看主播业绩';
      })();
      const pilotBtn = document.createElement('button');
      pilotBtn.className = 'btn btn-secondary btn-compact';
      pilotBtn.textContent = pilotLabel;
      pilotBtn.addEventListener('click', () => {
        if (primaryPilot.pilot_id) {
          window.open(`/pilots/${primaryPilot.pilot_id}/performance`, '_blank');
        }
      });
      actionBar.appendChild(pilotBtn);
    }

    if (actionBar.children.length > 0) {
      relatedPilotsEl.appendChild(actionBar);
    }

    if (recordMissing) {
      const warning = document.createElement('div');
      warning.className = 'hint';
      warning.textContent = '关联的开播记录已被删除，无法跳转。';
      relatedPilotsEl.appendChild(warning);
    }
  }

  function renderReplies(replies) {
    repliesContainer.innerHTML = '';
    if (!replies || !replies.length) {
      repliesContainer.innerHTML = '<div class="empty">暂无回复</div>';
      return;
    }

    replies.forEach((reply) => {
      const topEl = buildReplyItem(reply);
      repliesContainer.appendChild(topEl);
    });
  }

  function buildReplyItem(reply, depth = 0) {
    const container = document.createElement('div');
    container.className = `bbs-reply-item depth-${depth}`;
    const authorName = reply.author?.display_name || reply.author?.nickname || '未知用户';
    const statusLabel = reply.status === 'hidden' ? '<span class="tag tag-warning">隐藏</span>' : '';

    const header = document.createElement('div');
    header.className = 'reply-header';
    header.innerHTML = `
      <span class="author">${authorName}</span>
      <span class="time">${formatDate(reply.created_at)}</span>
      ${statusLabel}
    `;
    container.appendChild(header);

    const isEditing = state.editingReplyId === reply.id;
    let body;
    if (isEditing) {
      body = document.createElement('textarea');
      body.className = 'reply-edit-textarea';
      body.value = state.editingDraft;
      body.rows = 4;
      body.addEventListener('input', (event) => {
        state.editingDraft = event.target.value;
      });
    } else {
      body = document.createElement('pre');
      body.className = 'reply-content';
      body.textContent = reply.content || '';
    }
    container.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'reply-actions';

    if (!isEditing && depth === 0) {
      const replyBtn = document.createElement('button');
      replyBtn.textContent = '回复';
      replyBtn.className = 'btn btn-link';
      replyBtn.addEventListener('click', () => {
        state.parentReplyId = reply.id;
        state.replyingToName = authorName;
        replyEditorTitle.textContent = `回复 ${authorName}`;
        replyHint.style.display = 'block';
        replyHint.textContent = `将作为对"${authorName}"的回复`;
        replyResetBtn.style.display = 'inline-flex';
        replyTextarea.focus();
      });
      actions.appendChild(replyBtn);
    }

    const isReplyAuthor = reply.author && reply.author.id === currentUser.id;
    if (isAdmin() || isReplyAuthor) {
      if (isEditing) {
        const saveBtn = document.createElement('button');
        saveBtn.textContent = '保存';
        saveBtn.className = 'btn btn-primary btn-compact';
        saveBtn.addEventListener('click', () => submitReplyEdit(reply.id, body.value));
        actions.appendChild(saveBtn);

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = '取消';
        cancelBtn.className = 'btn btn-secondary btn-compact';
        cancelBtn.addEventListener('click', () => {
          resetEditingContext();
          renderReplies(state.postData.replies);
        });
        actions.appendChild(cancelBtn);
      } else {
        const editBtn = document.createElement('button');
        editBtn.textContent = '编辑';
        editBtn.className = 'btn btn-link';
        editBtn.addEventListener('click', () => editReply(reply));
        actions.appendChild(editBtn);

        const hideBtn = document.createElement('button');
        hideBtn.textContent = '隐藏';
        hideBtn.className = 'btn btn-link';
        hideBtn.addEventListener('click', () => hideReply(reply));
        actions.appendChild(hideBtn);
      }
    }

    container.appendChild(actions);

    if (reply.children && reply.children.length) {
      const childrenContainer = document.createElement('div');
      childrenContainer.className = 'reply-children';
      reply.children.forEach((child) => {
        childrenContainer.appendChild(buildReplyItem(child, depth + 1));
      });
      container.appendChild(childrenContainer);
    }

    return container;
  }

  function toggleEditMode(show) {
    if (show) {
      editTitleInput.value = state.postData.post.title;
      editContentInput.value = state.postData.post.content;
      viewContainer.classList.add('hidden');
      editForm.classList.remove('hidden');
    } else {
      viewContainer.classList.remove('hidden');
      editForm.classList.add('hidden');
    }
  }

  async function togglePostHidden(targetHidden) {
    if (!state.postId) return;
    const confirmMessage = targetHidden ? '确认隐藏该帖子?' : '确认取消隐藏该帖子?';
    if (!window.confirm(confirmMessage)) return;
    try {
      const path = targetHidden ? 'hide' : 'unhide';
      await request(`/api/bbs/posts/${state.postId}/${path}`, {
        method: 'POST'
      });
      await loadPost(state.postId);
      window.showMessage && window.showMessage('帖子状态已更新', 'success', 3000);
    } catch (error) {
      setMessage('error', error.message || '操作失败');
    }
  }

  async function togglePin(isPinned) {
    if (!state.postId) return;
    try {
      await request(`/api/bbs/posts/${state.postId}/pin`, {
        method: 'POST',
        body: JSON.stringify({ is_pinned: isPinned })
      });
      await loadPost(state.postId);
      window.showMessage && window.showMessage('置顶状态已更新', 'success', 3000);
    } catch (error) {
      setMessage('error', error.message || '操作失败');
    }
  }

  function editReply(reply) {
    state.editingReplyId = reply.id;
    state.editingDraft = reply.content || '';
    renderReplies(state.postData.replies);
  }

  async function submitReplyEdit(replyId, content) {
    const trimmed = (content || '').trim();
    if (!trimmed) {
      setMessage('error', '回复内容不能为空');
      return;
    }
    try {
      await request(`/api/bbs/replies/${replyId}`, {
        method: 'PATCH',
        body: JSON.stringify({ content: trimmed })
      });
      resetEditingContext();
      await loadPost(state.postId);
      window.showMessage && window.showMessage('回复已更新', 'success', 3000);
    } catch (error) {
      setMessage('error', error.message || '回复更新失败');
    }
  }

  async function hideReply(reply) {
    if (!window.confirm('确认隐藏该回复?')) return;
    try {
      await request(`/api/bbs/replies/${reply.id}/hide`, {
        method: 'POST'
      });
      await loadPost(state.postId);
      window.showMessage && window.showMessage('回复已隐藏', 'success', 3000);
    } catch (error) {
      setMessage('error', error.message || '操作失败');
    }
  }

  function bindMetaLinks() {
    const viewBtn = document.getElementById('bbs-view-record-btn');
    if (viewBtn) {
      viewBtn.addEventListener('click', () => {
        const recordId = viewBtn.dataset.record;
        if (recordId) {
          window.open(`/battle-records/${recordId}`, '_blank');
        }
      });
    }
  }

  async function submitReply() {
    if (!state.postId) return;
    if (state.submittingReply) return;
    const content = replyTextarea.value.trim();
    if (!content) {
      setMessage('error', '回复内容不能为空');
      return;
    }
    setReplySubmitting(true);
    try {
      await request(`/api/bbs/posts/${state.postId}/replies`, {
        method: 'POST',
        body: JSON.stringify({
          content,
          parent_reply_id: state.parentReplyId
        })
      });
      replyTextarea.value = '';
      resetReplyContext();
      await loadPost(state.postId);
    } catch (error) {
      setMessage('error', error.message || '回复失败');
    } finally {
      setReplySubmitting(false);
    }
  }

  async function savePostEdit() {
    if (!state.postId) return;
    const title = editTitleInput.value.trim();
    const content = editContentInput.value.trim();
    if (!title || !content) {
      setMessage('error', '标题和内容不能为空');
      return;
    }
    try {
      await request(`/api/bbs/posts/${state.postId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title,
          content
        })
      });
      toggleEditMode(false);
      await loadPost(state.postId);
      window.showMessage && window.showMessage('帖子已更新', 'success', 3000);
    } catch (error) {
      setMessage('error', error.message || '帖子更新失败');
    }
  }

  function renderPostDetail(data) {
    state.postData = data;
    resetEditingContext();
    renderPostContent(data.post);
    renderActions(data.post);
    renderPilots(data.pilots);
    renderReplies(data.replies);
    bindMetaLinks();
    toggleEditMode(false);
  }

  async function loadPost(postId) {
    if (!postId) return;
    state.loading = true;
    setMessage(null, '');
    try {
      const res = await request(`/api/bbs/posts/${postId}`);
      renderPostDetail(res.data);
      window.dispatchEvent(new CustomEvent('bbs:postUpdated', { detail: { postId } }));
    } catch (error) {
      setMessage('error', error.message || '加载帖子失败');
    } finally {
      state.loading = false;
    }
  }

  function openPostModal(postId) {
    if (!postId) return;
    state.postId = postId;
    showModal();
    loadPost(postId);
  }

  function registerEvents() {
    closeBtn?.addEventListener('click', hideModal);
    modal.addEventListener('click', (event) => {
      if (event.target === modal) {
        hideModal();
      }
    });
    replySubmitBtn?.addEventListener('click', submitReply);
    replyResetBtn?.addEventListener('click', resetReplyContext);
    editCancelBtn?.addEventListener('click', () => toggleEditMode(false));
    editSaveBtn?.addEventListener('click', savePostEdit);
  }

  registerEvents();

  window.BBSModal = {
    open: openPostModal,
    close: hideModal,
    refresh() {
      if (state.postId) {
        loadPost(state.postId);
      }
    },
    getCurrentPostId() {
      return state.postId;
    }
  };
})();
