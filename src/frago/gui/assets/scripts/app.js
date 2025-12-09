/**
 * Frago GUI - Main Application JavaScript
 *
 * Updated for 011-gui-tasks-redesign:
 * - 默认启动页从 home 改为 tips
 * - 新增 Tasks 页面逻辑
 * - 新增任务详情页逻辑
 */

// === State ===
let currentPage = 'tips';  // 默认启动页改为 tips
let config = {};
let isTaskRunning = false;

// 011-gui-tasks-redesign: 任务相关状态
let tasksData = [];          // 任务列表缓存
let currentTaskId = null;    // 当前查看的任务 ID
let taskDetailStepsOffset = 0;  // 任务详情步骤偏移量
let tasksPollingInterval = null;  // 任务列表轮询定时器
let taskDetailPollingInterval = null;  // 任务详情轮询定时器
const POLLING_INTERVAL_MS = 3000;  // 轮询间隔：3秒

// === Initialization ===
window.addEventListener('pywebviewready', () => {
    initApp();
});

async function initApp() {
    try {
        // Load configuration
        config = await pywebview.api.get_config();
        applyTheme(config.theme);
        applyFontSize(config.font_size);
        loadSettingsForm();

        // Load initial data
        // 011-gui-tasks-redesign: 添加 loadTasks 调用
        await Promise.all([
            loadRecipes(),
            loadSkills(),
            loadHistory(),
            loadTasks()
        ]);

        // Start status polling
        startStatusPolling();

        // Setup event listeners
        setupEventListeners();

        console.log('Frago GUI initialized');
    } catch (error) {
        console.error('Failed to initialize:', error);
        showToast('初始化失败: ' + error.message, 'error');
    }
}

// === Theme ===
function applyTheme(theme) {
    if (theme === 'light') {
        document.body.setAttribute('data-theme', 'light');
    } else {
        document.body.removeAttribute('data-theme');
    }
}

function applyFontSize(size) {
    document.documentElement.style.setProperty('--font-size-base', size + 'px');
}

// === Page Navigation ===
function switchPage(page) {
    // Update nav tabs
    // 011-gui-tasks-redesign: 任务详情页不显示 nav tab 激活状态
    const isDetailPage = page === 'task_detail' || page === 'recipe_detail';
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.toggle('active', !isDetailPage && tab.dataset.page === page);
    });

    // Update pages
    document.querySelectorAll('.page').forEach(p => {
        // 支持带下划线的页面 ID（如 page-task-detail）
        const pageId = 'page-' + page.replace(/_/g, '-');
        p.classList.toggle('active', p.id === pageId);
    });

    currentPage = page;

    // Load data for specific pages
    if (page === 'recipes') {
        loadRecipes();
    } else if (page === 'skills') {
        loadSkills();
    } else if (page === 'history') {
        loadHistory();
    } else if (page === 'tasks') {
        // 011-gui-tasks-redesign: 切换到 tasks 页时刷新任务列表并启动轮询
        loadTasks();
        startTasksPolling();
    }

    // 011-gui-tasks-redesign: 离开 tasks 页时停止轮询
    if (page !== 'tasks') {
        stopTasksPolling();
    }

    // 离开任务详情页时停止详情轮询
    if (page !== 'task_detail') {
        stopTaskDetailPolling();
    }
}

// === Event Listeners ===
function setupEventListeners() {
    // Navigation tabs
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => switchPage(tab.dataset.page));
    });

    // 移除所有窗口控制按钮事件监听，使用原生窗口标题栏

    // Send button
    document.getElementById('send-btn')?.addEventListener('click', sendMessage);

    // Input keyboard shortcuts
    document.getElementById('input-text')?.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            sendMessage();
        }
    });

    // Refresh buttons
    document.getElementById('refresh-recipes-btn')?.addEventListener('click', refreshRecipes);
    document.getElementById('refresh-skills-btn')?.addEventListener('click', refreshSkills);
    document.getElementById('clear-history-btn')?.addEventListener('click', clearHistory);

    // Recipe detail page buttons
    document.getElementById('recipe-detail-back-btn')?.addEventListener('click', backToRecipeList);
    document.getElementById('recipe-delete-btn')?.addEventListener('click', confirmDeleteRecipe);

    // 011-gui-tasks-redesign: Tasks 页面事件监听
    document.getElementById('refresh-tasks-btn')?.addEventListener('click', refreshTasks);
    document.getElementById('task-detail-back-btn')?.addEventListener('click', backToTaskList);

    // Tasks 页面输入区域事件监听
    document.getElementById('task-send-btn')?.addEventListener('click', sendTaskFromTasksPage);
    document.getElementById('task-input-text')?.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            sendTaskFromTasksPage();
        }
    });

    // Settings form
    document.getElementById('save-settings-btn')?.addEventListener('click', saveSettings);
    document.getElementById('setting-font-size')?.addEventListener('input', (e) => {
        document.getElementById('font-size-value').textContent = e.target.value + 'px';
    });
}

// === Message Sending ===
async function sendMessage() {
    const input = document.getElementById('input-text');
    const prompt = input.value.trim();

    if (!prompt) {
        showToast('请输入内容', 'warning');
        return;
    }

    if (isTaskRunning) {
        showToast('已有任务运行中', 'warning');
        return;
    }

    // Add user message
    addMessage(prompt, 'user');
    input.value = '';

    // Show progress
    showProgress(true);
    isTaskRunning = true;
    updateSendButton();

    try {
        const taskId = await pywebview.api.run_agent(prompt);
        pollTaskStatus(taskId);
    } catch (error) {
        showProgress(false);
        isTaskRunning = false;
        updateSendButton();
        addMessage('错误: ' + error.message, 'error');
    }
}

function updateSendButton() {
    const btn = document.getElementById('send-btn');
    if (btn) {
        btn.disabled = isTaskRunning;
        btn.textContent = isTaskRunning ? '运行中...' : '发送';
    }
}

async function pollTaskStatus(taskId) {
    try {
        const status = await pywebview.api.get_task_status();

        if (status.status === 'running') {
            updateProgress(status.progress);
            setTimeout(() => pollTaskStatus(taskId), 500);
        } else {
            showProgress(false);
            isTaskRunning = false;
            updateSendButton();

            if (status.status === 'error') {
                addMessage('错误: ' + status.error, 'error');
            }
        }
    } catch (error) {
        showProgress(false);
        isTaskRunning = false;
        updateSendButton();
    }
}

// === Output Management ===
function addMessage(content, type = 'assistant') {
    const container = document.getElementById('output-container');
    if (!container) return;

    // Remove placeholder
    const placeholder = container.querySelector('.output-placeholder');
    if (placeholder) {
        placeholder.remove();
    }

    const message = document.createElement('div');
    message.className = 'message message-' + type;
    message.textContent = content;
    container.appendChild(message);

    // Auto scroll
    if (config.auto_scroll_output) {
        container.scrollTop = container.scrollHeight;
    }
}

function clearOutput() {
    const container = document.getElementById('output-container');
    if (container) {
        container.innerHTML = '<div class="output-placeholder">响应将显示在这里...</div>';
    }
}

// === Progress Bar ===
function showProgress(show) {
    const container = document.getElementById('progress-container');
    if (container) {
        container.style.display = show ? 'block' : 'none';
        if (show) {
            updateProgress(0);
        }
    }
}

function updateProgress(progress, step = '') {
    const fill = document.getElementById('progress-fill');
    const stepEl = document.getElementById('progress-step');

    if (fill) {
        fill.style.width = (progress * 100) + '%';
    }
    if (stepEl) {
        stepEl.textContent = step;
    }
}

// === Recipes ===
let currentRecipeName = null;

async function loadRecipes() {
    const container = document.getElementById('recipe-list');
    if (!container) return;

    try {
        const recipes = await pywebview.api.get_recipes();
        renderRecipeList(recipes, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📦</div><p>加载失败</p></div>';
    }
}

async function refreshRecipes() {
    const container = document.getElementById('recipe-list');
    if (container) {
        container.innerHTML = '<div class="loading">刷新中...</div>';
    }

    try {
        const recipes = await pywebview.api.refresh_recipes();
        renderRecipeList(recipes, container);
        showToast('配方列表已刷新', 'success');
    } catch (error) {
        showToast('刷新失败', 'error');
    }
}

function renderRecipeList(recipes, container) {
    if (!recipes || recipes.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📦</div><p>暂无配方</p></div>';
        return;
    }

    container.innerHTML = recipes.map(recipe => `
        <div class="recipe-card" onclick="openRecipeDetail('${escapeHtml(recipe.name)}')">
            <div class="recipe-name">${escapeHtml(recipe.name)}</div>
            <div class="recipe-description">${escapeHtml(recipe.description || '无描述')}</div>
            <div class="recipe-meta">
                <span class="recipe-category">${escapeHtml(recipe.category || 'atomic')}</span>
                ${recipe.source ? `<span class="recipe-source">${escapeHtml(recipe.source)}</span>` : ''}
                ${recipe.runtime ? `<span class="recipe-runtime">${escapeHtml(recipe.runtime)}</span>` : ''}
            </div>
        </div>
    `).join('');
}

async function openRecipeDetail(name) {
    currentRecipeName = name;

    // Switch to detail page
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-recipe-detail').classList.add('active');

    // Update nav tabs (none should be active for detail page)
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));

    // Load detail content
    const container = document.getElementById('recipe-detail-content');
    const titleEl = document.getElementById('recipe-detail-title');
    const deleteBtn = document.getElementById('recipe-delete-btn');

    container.innerHTML = '<div class="loading">加载中...</div>';
    titleEl.textContent = name;
    deleteBtn.style.display = 'none';

    try {
        const detail = await pywebview.api.get_recipe_detail(name);

        if (detail.error) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">❌</div><p>${escapeHtml(detail.error)}</p></div>`;
            return;
        }

        // Show delete button only for User source
        if (detail.source === 'User') {
            deleteBtn.style.display = 'block';
        }

        renderRecipeDetail(detail, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">❌</div><p>加载失败</p></div>';
    }
}

function renderRecipeDetail(detail, container) {
    const tagsHtml = (detail.tags || []).map(tag =>
        `<span class="recipe-tag">${escapeHtml(tag)}</span>`
    ).join('');

    // Simple markdown rendering
    let markdownHtml = '';
    if (detail.metadata_content) {
        markdownHtml = renderSimpleMarkdown(detail.metadata_content);
    } else {
        markdownHtml = '<p class="empty-state-text">无配方文档</p>';
    }

    container.innerHTML = `
        <div class="recipe-detail-header">
            <div class="recipe-detail-name">${escapeHtml(detail.name)}</div>
            <div class="recipe-detail-desc">${escapeHtml(detail.description || '无描述')}</div>
            <div class="recipe-detail-meta">
                <span class="recipe-category">${escapeHtml(detail.category || 'atomic')}</span>
                ${detail.source ? `<span class="recipe-source">${escapeHtml(detail.source)}</span>` : ''}
                ${detail.runtime ? `<span class="recipe-runtime">${escapeHtml(detail.runtime)}</span>` : ''}
            </div>
            ${tagsHtml ? `<div class="recipe-detail-tags">${tagsHtml}</div>` : ''}
        </div>
        <div class="recipe-markdown">${markdownHtml}</div>
    `;
}

function renderSimpleMarkdown(md) {
    // Basic markdown to HTML conversion
    let html = escapeHtml(md);

    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold and italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // Blockquotes
    html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');

    // Paragraphs (double newlines)
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';

    // Clean up empty paragraphs
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<h[1-4]>)/g, '$1');
    html = html.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');
    html = html.replace(/<p>(<blockquote>)/g, '$1');
    html = html.replace(/(<\/blockquote>)<\/p>/g, '$1');

    return html;
}

function backToRecipeList() {
    currentRecipeName = null;
    switchPage('recipes');
}

async function confirmDeleteRecipe() {
    if (!currentRecipeName) return;

    showConfirmDialog(
        '删除配方',
        `确定要删除配方 "${currentRecipeName}" 吗？此操作不可撤销。`,
        async () => {
            try {
                const result = await pywebview.api.delete_recipe(currentRecipeName);
                if (result.status === 'ok') {
                    showToast(result.message, 'success');
                    backToRecipeList();
                } else {
                    showToast(result.message, 'error');
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }
    );
}

function showConfirmDialog(title, message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-dialog-overlay';
    overlay.innerHTML = `
        <div class="confirm-dialog">
            <div class="confirm-dialog-title">${escapeHtml(title)}</div>
            <div class="confirm-dialog-message">${escapeHtml(message)}</div>
            <div class="confirm-dialog-actions">
                <button class="confirm-dialog-cancel">取消</button>
                <button class="confirm-dialog-confirm">确认删除</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    overlay.querySelector('.confirm-dialog-cancel').addEventListener('click', () => {
        overlay.remove();
    });

    overlay.querySelector('.confirm-dialog-confirm').addEventListener('click', () => {
        overlay.remove();
        onConfirm();
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
        }
    });
}

// === Skills ===
async function loadSkills() {
    const container = document.getElementById('skill-grid');
    if (!container) return;

    try {
        const skills = await pywebview.api.get_skills();
        renderSkillList(skills, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📚</div><p>加载失败</p></div>';
    }
}

async function refreshSkills() {
    const container = document.getElementById('skill-grid');
    if (container) {
        container.innerHTML = '<div class="loading">刷新中...</div>';
    }

    try {
        const skills = await pywebview.api.refresh_skills();
        renderSkillList(skills, container);
        showToast('Skills 列表已刷新', 'success');
    } catch (error) {
        showToast('刷新失败', 'error');
    }
}

function renderSkillList(skills, container) {
    if (!skills || skills.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📚</div><p>暂无 Skills</p></div>';
        return;
    }

    container.innerHTML = skills.map(skill => `
        <div class="skill-card">
            <div class="skill-icon">${skill.icon || '📄'}</div>
            <div class="skill-name">${skill.name}</div>
            <div class="skill-description">${skill.description || '无描述'}</div>
        </div>
    `).join('');
}

// === History ===
async function loadHistory() {
    const container = document.getElementById('history-list');
    if (!container) return;

    try {
        const history = await pywebview.api.get_history(50, 0);
        renderHistory(history, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📜</div><p>加载失败</p></div>';
    }
}

function renderHistory(history, container) {
    if (!history || history.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📜</div><p>暂无历史记录</p></div>';
        return;
    }

    container.innerHTML = history.map(item => `
        <div class="history-item" onclick="toggleHistoryItem(this)">
            <div class="history-header">
                <span class="history-input">${escapeHtml(item.input_text)}</span>
                <span class="history-timestamp">${formatTimestamp(item.timestamp)}</span>
            </div>
            <span class="history-status ${item.status}">${item.status === 'completed' ? '成功' : '失败'}</span>
            <div class="history-output">${escapeHtml(item.output || item.error || '')}</div>
        </div>
    `).join('');
}

function toggleHistoryItem(element) {
    element.classList.toggle('expanded');
}

async function clearHistory() {
    if (!confirm('确定要清空所有历史记录吗？')) {
        return;
    }

    try {
        await pywebview.api.clear_history();
        loadHistory();
        showToast('历史记录已清空', 'success');
    } catch (error) {
        showToast('清空失败', 'error');
    }
}

// === Settings ===
function loadSettingsForm() {
    document.getElementById('setting-theme').value = config.theme || 'dark';
    document.getElementById('setting-font-size').value = config.font_size || 14;
    document.getElementById('font-size-value').textContent = (config.font_size || 14) + 'px';
    document.getElementById('setting-show-status').checked = config.show_system_status !== false;
    document.getElementById('setting-confirm-exit').checked = config.confirm_on_exit !== false;
    document.getElementById('setting-auto-scroll').checked = config.auto_scroll_output !== false;
}

async function saveSettings() {
    const newConfig = {
        theme: document.getElementById('setting-theme').value,
        font_size: parseInt(document.getElementById('setting-font-size').value),
        show_system_status: document.getElementById('setting-show-status').checked,
        confirm_on_exit: document.getElementById('setting-confirm-exit').checked,
        auto_scroll_output: document.getElementById('setting-auto-scroll').checked
    };

    try {
        const result = await pywebview.api.update_config(newConfig);
        if (result.status === 'ok') {
            config = result.config;
            applyTheme(config.theme);
            applyFontSize(config.font_size);
            showToast('设置已保存', 'success');
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('保存失败', 'error');
    }
}

// === Status Bar ===
function startStatusPolling() {
    updateStatus();
    setInterval(updateStatus, 5000);
}

async function updateStatus() {
    try {
        const status = await pywebview.api.get_system_status();

        document.getElementById('cpu-status').textContent = 'CPU: ' + status.cpu_percent.toFixed(0) + '%';
        document.getElementById('memory-status').textContent = 'MEM: ' + status.memory_percent.toFixed(0) + '%';

        const indicator = document.getElementById('connection-status');
        const dot = indicator?.querySelector('.indicator-dot');
        const text = indicator?.querySelector('.indicator-text');

        if (dot && text) {
            dot.className = 'indicator-dot ' + (status.chrome_connected ? 'connected' : 'disconnected');
            text.textContent = status.chrome_connected ? '已连接' : '未连接';
        }
    } catch (error) {
        // Ignore status polling errors
    }
}


// === Toast Notifications ===
window.showToast = function(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
};

// === Stream Message Handler (called by Python) ===
window.handleStreamMessage = function(message) {
    if (message.type === 'assistant') {
        addMessage(message.content, 'assistant');
    } else if (message.type === 'progress') {
        updateProgress(message.progress, message.step);
    } else if (message.type === 'error') {
        addMessage(message.content, 'error');
    } else if (message.type === 'system') {
        addMessage(message.content, 'system');
    }
};

// === Progress Update Handler (called by Python) ===
window.updateProgress = updateProgress;

// === Utilities ===
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return isoString;
    }
}

// ============================================================
// 011-gui-tasks-redesign: Tasks 页面逻辑
// ============================================================

// Tasks 页面任务运行状态
let isTaskPageTaskRunning = false;

/**
 * 从 Tasks 页面发送任务
 * 执行 frago agent {prompt} 命令
 */
async function sendTaskFromTasksPage() {
    const input = document.getElementById('task-input-text');
    const prompt = input?.value.trim();

    if (!prompt) {
        showToast('请输入任务描述', 'warning');
        return;
    }

    if (isTaskPageTaskRunning) {
        showToast('已有任务运行中，请稍候', 'warning');
        return;
    }

    // 清空输入框
    input.value = '';

    // 更新状态
    isTaskPageTaskRunning = true;
    updateTaskSendButton();

    try {
        // 调用后端 API 启动 agent 任务
        const result = await pywebview.api.start_agent_task(prompt);

        if (result.status === 'ok') {
            showToast('任务已启动', 'success');
            // 立即刷新任务列表以显示新任务
            await loadTasks();
        } else {
            showToast('启动失败: ' + (result.error || '未知错误'), 'error');
        }

    } catch (error) {
        showToast('启动任务失败: ' + (error.message || error), 'error');
    } finally {
        isTaskPageTaskRunning = false;
        updateTaskSendButton();
    }
}

/**
 * 更新 Tasks 页面发送按钮状态
 */
function updateTaskSendButton() {
    const btn = document.getElementById('task-send-btn');
    if (btn) {
        btn.disabled = isTaskPageTaskRunning;
        btn.textContent = isTaskPageTaskRunning ? '运行中...' : '发送';
    }
}

/**
 * 加载任务列表
 */
async function loadTasks() {
    const listEl = document.getElementById('tasks-list');
    const emptyEl = document.getElementById('tasks-empty');
    if (!listEl) return;

    try {
        const tasks = await pywebview.api.get_tasks();
        tasksData = tasks || [];

        if (tasksData.length === 0) {
            listEl.innerHTML = '';
            listEl.style.display = 'none';
            if (emptyEl) emptyEl.style.display = 'block';
        } else {
            if (emptyEl) emptyEl.style.display = 'none';
            listEl.style.display = 'flex';
            renderTasksList(tasksData, listEl);
        }
    } catch (error) {
        console.error('Failed to load tasks:', error);
        listEl.innerHTML = '<div class="empty-state"><div class="empty-state__icon">❌</div><p class="empty-state__description">加载任务失败</p></div>';
        if (emptyEl) emptyEl.style.display = 'none';
    }
}

/**
 * 刷新任务列表
 */
async function refreshTasks() {
    const listEl = document.getElementById('tasks-list');
    if (listEl) {
        listEl.innerHTML = '<div class="loading">刷新中...</div>';
    }

    try {
        await loadTasks();
        showToast('任务列表已刷新', 'success');
    } catch (error) {
        showToast('刷新失败', 'error');
    }
}

/**
 * 渲染任务列表
 * @param {Array} tasks - 任务数组
 * @param {HTMLElement} container - 容器元素
 */
function renderTasksList(tasks, container) {
    container.innerHTML = tasks.map(task => `
        <div class="task-card" onclick="openTaskDetail('${escapeHtml(task.session_id)}')">
            <div class="task-card__header">
                <div class="task-card__name">${escapeHtml(task.name)}</div>
                <span class="task-status task-status--${task.status}">${getStatusLabel(task.status)}</span>
            </div>
            <div class="task-card__time">${formatTimestamp(task.started_at)}</div>
            <div class="task-card__stats">
                <span>⏱️ ${formatDuration(task.duration_ms)}</span>
                <span>📊 ${task.step_count} 步骤</span>
                <span>🔧 ${task.tool_call_count} 工具调用</span>
            </div>
        </div>
    `).join('');
}

/**
 * 获取状态标签
 * @param {string} status - 状态值
 * @returns {string} - 状态标签
 */
function getStatusLabel(status) {
    const labels = {
        'running': '进行中',
        'completed': '已完成',
        'error': '出错',
        'cancelled': '已取消'
    };
    return labels[status] || status;
}

/**
 * 格式化持续时间
 * @param {number} ms - 毫秒数
 * @returns {string} - 格式化字符串
 */
function formatDuration(ms) {
    if (!ms || ms <= 0) return '0s';

    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
        return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
    } else {
        return `${seconds}s`;
    }
}

/**
 * 打开任务详情页
 * @param {string} sessionId - 会话 ID
 */
async function openTaskDetail(sessionId) {
    currentTaskId = sessionId;
    taskDetailStepsOffset = 0;

    // 切换到详情页
    switchPage('task_detail');

    // 更新标题
    const titleEl = document.getElementById('task-detail-title');
    const contentEl = document.getElementById('task-detail-content');

    if (titleEl) titleEl.textContent = '任务详情';
    if (contentEl) contentEl.innerHTML = '<div class="loading">加载中...</div>';

    try {
        const detail = await pywebview.api.get_task_detail(sessionId);
        renderTaskDetail(detail, contentEl);

        // 如果任务正在运行，启动轮询
        if (detail.status === 'running') {
            startTaskDetailPolling();
        }
    } catch (error) {
        console.error('Failed to load task detail:', error);
        if (contentEl) {
            contentEl.innerHTML = '<div class="empty-state"><div class="empty-state__icon">❌</div><p class="empty-state__description">加载失败</p></div>';
        }
    }
}

/**
 * 渲染任务详情
 * @param {Object} detail - 任务详情对象
 * @param {HTMLElement} container - 容器元素
 */
function renderTaskDetail(detail, container) {
    if (!container) return;

    // 更新标题
    const titleEl = document.getElementById('task-detail-title');
    if (titleEl) {
        titleEl.textContent = detail.name || `Task ${detail.session_id.substring(0, 8)}...`;
    }

    const statusClass = `task-status--${detail.status}`;
    const statusLabel = getStatusLabel(detail.status);

    container.innerHTML = `
        <div class="task-detail__info">
            <div class="task-detail__status ${statusClass}">${statusLabel}</div>
            <div class="task-detail__meta">
                <span>开始: ${formatTimestamp(detail.started_at)}</span>
                ${detail.ended_at ? `<span>结束: ${formatTimestamp(detail.ended_at)}</span>` : ''}
                <span>耗时: ${formatDuration(detail.duration_ms)}</span>
            </div>
            <div class="task-detail__stats">
                <span>📊 ${detail.step_count} 步骤</span>
                <span>💬 ${detail.user_message_count || 0} 用户消息</span>
                <span>🤖 ${detail.assistant_message_count || 0} 助手消息</span>
                <span>🔧 ${detail.tool_call_count || 0} 工具调用</span>
            </div>
        </div>
        <div class="task-detail__steps">
            <h3>步骤记录</h3>
            <div id="task-steps-list">
                ${renderSteps(detail.steps || [])}
            </div>
            ${detail.has_more_steps ? '<button class="btn-load-more" onclick="loadMoreSteps()">加载更多</button>' : ''}
        </div>
    `;

    taskDetailStepsOffset = detail.steps_offset + (detail.steps?.length || 0);
}

/**
 * 渲染步骤列表
 * @param {Array} steps - 步骤数组
 * @returns {string} - HTML 字符串
 */
function renderSteps(steps) {
    if (!steps || steps.length === 0) {
        return '<div class="empty-state"><p class="empty-state__description">暂无步骤记录</p></div>';
    }

    return steps.map(step => `
        <div class="step step--${step.type}">
            <div class="step__header">
                <span class="step__number">#${step.step_id}</span>
                <span class="step__type">${getStepTypeLabel(step.type)}</span>
                <span class="step__time">${formatTimestamp(step.timestamp)}</span>
            </div>
            <div class="step__content">${escapeHtml(step.content)}</div>
        </div>
    `).join('');
}

/**
 * 获取步骤类型标签
 * @param {string} type - 步骤类型
 * @returns {string} - 标签
 */
function getStepTypeLabel(type) {
    const labels = {
        'user_message': '用户消息',
        'assistant_message': '助手消息',
        'tool_call': '工具调用',
        'tool_result': '工具结果',
        'system_event': '系统事件'
    };
    return labels[type] || type;
}

/**
 * 加载更多步骤
 */
async function loadMoreSteps() {
    if (!currentTaskId) return;

    try {
        const moreSteps = await pywebview.api.get_task_steps(currentTaskId, taskDetailStepsOffset, 50);
        const stepsListEl = document.getElementById('task-steps-list');

        if (stepsListEl && moreSteps.steps) {
            stepsListEl.innerHTML += renderSteps(moreSteps.steps);
            taskDetailStepsOffset += moreSteps.steps.length;

            // 更新或移除"加载更多"按钮
            const loadMoreBtn = document.querySelector('.btn-load-more');
            if (loadMoreBtn) {
                if (!moreSteps.has_more) {
                    loadMoreBtn.remove();
                }
            }
        }
    } catch (error) {
        console.error('Failed to load more steps:', error);
        showToast('加载更多步骤失败', 'error');
    }
}

/**
 * 返回任务列表
 */
function backToTaskList() {
    currentTaskId = null;
    stopTaskDetailPolling();
    switchPage('tasks');
}

// ============================================================
// 011-gui-tasks-redesign: 实时更新 - 轮询机制
// ============================================================

/**
 * 启动任务列表轮询
 */
function startTasksPolling() {
    stopTasksPolling();  // 先停止已有的轮询

    tasksPollingInterval = setInterval(async () => {
        if (currentPage !== 'tasks') {
            stopTasksPolling();
            return;
        }

        try {
            const newTasks = await pywebview.api.get_tasks();

            // 检查是否有变化
            if (hasTasksChanged(tasksData, newTasks)) {
                tasksData = newTasks || [];
                const listEl = document.getElementById('tasks-list');
                const emptyEl = document.getElementById('tasks-empty');

                if (tasksData.length === 0) {
                    listEl.innerHTML = '';
                    listEl.style.display = 'none';
                    if (emptyEl) emptyEl.style.display = 'block';
                } else {
                    if (emptyEl) emptyEl.style.display = 'none';
                    listEl.style.display = 'flex';
                    renderTasksList(tasksData, listEl);
                }
            }
        } catch (error) {
            console.error('Tasks polling error:', error);
        }
    }, POLLING_INTERVAL_MS);
}

/**
 * 停止任务列表轮询
 */
function stopTasksPolling() {
    if (tasksPollingInterval) {
        clearInterval(tasksPollingInterval);
        tasksPollingInterval = null;
    }
}

/**
 * 检查任务列表是否有变化
 */
function hasTasksChanged(oldTasks, newTasks) {
    if (!oldTasks || !newTasks) return true;
    if (oldTasks.length !== newTasks.length) return true;

    for (let i = 0; i < oldTasks.length; i++) {
        const oldTask = oldTasks[i];
        const newTask = newTasks[i];

        // 检查关键字段是否变化
        if (oldTask.session_id !== newTask.session_id ||
            oldTask.status !== newTask.status ||
            oldTask.step_count !== newTask.step_count ||
            oldTask.duration_ms !== newTask.duration_ms) {
            return true;
        }
    }

    return false;
}

/**
 * 启动任务详情轮询（仅对运行中的任务）
 */
function startTaskDetailPolling() {
    stopTaskDetailPolling();

    taskDetailPollingInterval = setInterval(async () => {
        if (currentPage !== 'task_detail' || !currentTaskId) {
            stopTaskDetailPolling();
            return;
        }

        try {
            const detail = await pywebview.api.get_task_detail(currentTaskId);

            // 如果任务已完成，停止轮询
            if (detail.status !== 'running') {
                stopTaskDetailPolling();
            }

            // 更新详情页（保留当前滚动位置）
            updateTaskDetailInPlace(detail);
        } catch (error) {
            console.error('Task detail polling error:', error);
        }
    }, POLLING_INTERVAL_MS);
}

/**
 * 停止任务详情轮询
 */
function stopTaskDetailPolling() {
    if (taskDetailPollingInterval) {
        clearInterval(taskDetailPollingInterval);
        taskDetailPollingInterval = null;
    }
}

/**
 * 就地更新任务详情（保留滚动位置）
 */
function updateTaskDetailInPlace(detail) {
    // 更新状态
    const statusEl = document.querySelector('.task-detail__status');
    if (statusEl) {
        statusEl.className = `task-detail__status task-status--${detail.status}`;
        statusEl.textContent = getStatusLabel(detail.status);
    }

    // 更新统计数据
    const statsEl = document.querySelector('.task-detail__stats');
    if (statsEl) {
        statsEl.innerHTML = `
            <span>📊 ${detail.step_count} 步骤</span>
            <span>💬 ${detail.user_message_count || 0} 用户消息</span>
            <span>🤖 ${detail.assistant_message_count || 0} 助手消息</span>
            <span>🔧 ${detail.tool_call_count || 0} 工具调用</span>
        `;
    }

    // 更新元信息（持续时间等）
    const metaEl = document.querySelector('.task-detail__meta');
    if (metaEl) {
        metaEl.innerHTML = `
            <span>开始: ${formatTimestamp(detail.started_at)}</span>
            ${detail.ended_at ? `<span>结束: ${formatTimestamp(detail.ended_at)}</span>` : ''}
            <span>耗时: ${formatDuration(detail.duration_ms)}</span>
        `;
    }
}
