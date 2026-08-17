/**
 * OpenClaw 控制台前端逻辑
 * 提供实时监控和数据展示功能
 */

// 全局变量
let responseTimeChart = null;
let timeDistributionChart = null;
let autoRefreshInterval = null;
let traceAutoRefreshInterval = null;

// 分页状态
let currentPage = 1;
let pageSize = 10;  // 默认每页10条
let allMetrics = [];  // 存储所有metrics数据
let lastMetricsHash = '';  // 用于检测数据变化，避免无意义的DOM重建

// 会话过滤状态（'' = 全部会话，'__none__' = 无会话，其他为会话ID）
let sessionFilter = '';

// 会话配色（AntV category10 色板），同一会话ID固定映射同一颜色
const SESSION_COLORS = ['#5B8FF9', '#5AD8A6', '#F6BD16', '#E86452', '#6DC8EC',
                        '#945FB9', '#FF9845', '#1E9493', '#FF99C3', '#61DDAA'];

// Trace数据
let allTraces = [];

// 当前页签
let currentPageName = 'overview';

// KPI 卡片增强状态
let metricCardEnhanced = false;

// Chart.js 默认配置（移至initCharts中设置，避免defer加载时Chart未定义）

/**
 * 页签切换
 */
function switchPage(pageName) {
    // 隐藏所有page-content divs
    document.querySelectorAll('.page-content').forEach(p => {
        p.style.display = 'none';
    });
    // 隐藏概览页
    const overview = document.getElementById('page-overview');
    if (overview) overview.style.display = 'none';

    // 显示选中的页签
    const target = document.getElementById('page-' + pageName);
    if (target) {
        target.style.display = 'block';
    }
    currentPageName = pageName;

    // 切换到追踪页签时刷新数据
    if (pageName === 'trace') {
        refreshTraces();
    }
}

/**
 * 初始化图表
 */
function getThemeColors() {
    const style = getComputedStyle(document.documentElement);
    return {
        textPrimary: style.getPropertyValue('--text-primary').trim(),
        textSecondary: style.getPropertyValue('--text-secondary').trim(),
        textMuted: style.getPropertyValue('--text-muted').trim(),
        border: style.getPropertyValue('--border').trim(),
        surface: style.getPropertyValue('--surface').trim(),
        success: style.getPropertyValue('--success').trim(),
        primary: style.getPropertyValue('--primary').trim(),
    };
}

function initCharts() {
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
    const colors = getThemeColors();
    Chart.defaults.color = colors.textSecondary;

    const ctx1 = document.getElementById('responseTimeChart').getContext('2d');
    responseTimeChart = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '总耗时',
                data: [],
                borderColor: colors.primary,
                backgroundColor: colors.primary + '1a',
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: colors.primary,
                pointHoverBorderColor: colors.surface,
                pointHoverBorderWidth: 2
            }, {
                label: '模型耗时',
                data: [],
                borderColor: colors.success,
                backgroundColor: colors.success + '1a',
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: colors.success,
                pointHoverBorderColor: colors.surface,
                pointHoverBorderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    align: 'end',
                    labels: {
                        usePointStyle: true,
                        padding: 20,
                        font: {
                            size: 13,
                            weight: '400'
                        },
                        color: colors.textPrimary
                    }
                },
                tooltip: {
                    backgroundColor: colors.surface,
                    titleColor: colors.textPrimary,
                    bodyColor: colors.textSecondary,
                    borderColor: colors.border,
                    borderWidth: 1,
                    padding: 12,
                    displayColors: true,
                    titleFont: {
                        weight: '500',
                        size: 13
                    },
                    bodyFont: {
                        size: 12
                    },
                    cornerRadius: 4,
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + context.parsed.y.toFixed(0) + 'ms';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false,
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: colors.textMuted
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: colors.border,
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: colors.textMuted,
                        callback: function(value) {
                            return value + 'ms';
                        }
                    }
                }
            }
        }
    });

    const ctx2 = document.getElementById('timeDistributionChart').getContext('2d');
    timeDistributionChart = new Chart(ctx2, {
        type: 'bar',
        data: {
            labels: ['代理处理', '模型响应'],
            datasets: [{
                data: [0, 0],
                backgroundColor: [
                    hexToRgba(colors.primary, 0.8),
                    hexToRgba(colors.success, 0.8)
                ],
                borderColor: [
                    colors.primary,
                    colors.success
                ],
                borderWidth: 0,
                borderRadius: 4,
                barThickness: 60
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: colors.surface,
                    titleColor: colors.textPrimary,
                    bodyColor: colors.textSecondary,
                    borderColor: colors.border,
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 4,
                    callbacks: {
                        label: function(context) {
                            return '平均: ' + context.parsed.y.toFixed(2) + 'ms';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false,
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 13,
                            weight: '500'
                        },
                        color: colors.textPrimary
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: colors.border,
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: colors.textMuted,
                        callback: function(value) {
                            return value + 'ms';
                        }
                    }
                }
            }
        }
    });
}

function hexToRgba(hex, alpha) {
    const normalized = hex.replace('#', '');
    if (normalized.length === 3) {
        const r = parseInt(normalized[0] + normalized[0], 16);
        const g = parseInt(normalized[1] + normalized[1], 16);
        const b = parseInt(normalized[2] + normalized[2], 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    if (normalized.length === 6) {
        const r = parseInt(normalized.substring(0, 2), 16);
        const g = parseInt(normalized.substring(2, 4), 16);
        const b = parseInt(normalized.substring(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    return hex;
}

let serverAvailable = true;

/**
 * 检查服务器状态
 */
async function checkServerStatus() {
    try {
        const response = await fetch('/', { method: 'GET', cache: 'no-cache' });
        serverAvailable = response.ok;

        const statusBadge = document.querySelector('.status-badge');
        const statusText = statusBadge.querySelector('span:last-child');

        if (serverAvailable) {
            statusBadge.style.background = '#dcfce7';
            statusBadge.querySelector('.status-dot').style.background = '#22c55e';
            statusText.textContent = '已连接';
        } else {
            statusBadge.style.background = '#fee2e2';
            statusBadge.querySelector('.status-dot').style.background = '#ef4444';
            statusText.textContent = '离线';
        }

        return serverAvailable;
    } catch (error) {
        serverAvailable = false;
        console.warn('服务器状态检查失败:', error);
        return false;
    }
}

/**
 * 刷新数据
 */
async function refreshData() {
    const isServerUp = await checkServerStatus();

    if (!isServerUp) {
        showErrorBanner(`代理服务器离线 (${new Date().toLocaleTimeString()}) - 请启动服务器后刷新页面`);
        return;
    }

    try {
        const response = await fetch('/metrics');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        document.getElementById('sessionStart').textContent = new Date(data.session_start).toLocaleString('zh-CN', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });

        const summary = await fetch('/metrics/summary').then(r => {
            if (!r.ok) {
                throw new Error(`HTTP ${r.status}: ${r.statusText}`);
            }
            return r.json();
        });

        document.getElementById('totalRequests').textContent = summary.total_requests;
        document.getElementById('avgTotalTime').textContent = (summary.avg_total_time * 1000).toFixed(0);
        document.getElementById('avgProxyTime').textContent = (summary.avg_proxy_processing_time * 1000).toFixed(2);
        document.getElementById('avgModelTime').textContent = (summary.avg_model_response_time * 1000).toFixed(0);
        document.getElementById('avgGapTime').textContent = (summary.avg_inter_request_gap ? (summary.avg_inter_request_gap * 1000).toFixed(0) : 'N/A');
        document.getElementById('maxResponseTime').textContent = (summary.max_total_time ? (summary.max_total_time * 1000).toFixed(0) : 'N/A');
        document.getElementById('successRequests').textContent = summary.success_requests || 0;
        document.getElementById('failedRequests').textContent = summary.failed_requests || 0;
        document.getElementById('successRate').textContent = (summary.success_rate || 0).toFixed(1);

        updateCharts(data.metrics);
        updateSessionFilterOptions(data.metrics);
        updateTable(data.metrics);
        renderSparklines(allMetrics);

        hideErrorBanner();

    } catch (error) {
        console.error('获取指标数据失败:', error);
        showErrorBanner(`无法连接到代理服务器 (${new Date().toLocaleTimeString()}) - 请确保服务器正在运行`);
    }
}

/**
 * 更新图表
 */
function updateCharts(metrics) {
    if (!metrics || metrics.length === 0) return;

    const labels = metrics.map((m, i) => `#${i + 1}`);
    const totalTimeData = metrics.map(m => (m.total_time || m.time_to_first_byte || 0) * 1000);
    const modelTimeData = metrics.map(m => (m.model_response_time || m.time_to_first_byte || 0) * 1000);

    responseTimeChart.data.labels = labels;
    responseTimeChart.data.datasets[0].data = totalTimeData;
    responseTimeChart.data.datasets[1].data = modelTimeData;
    responseTimeChart.update();

    const avgProxyTime = metrics.reduce((sum, m) => sum + (m.proxy_processing_time || 0) * 1000, 0) / metrics.length || 0;
    const avgModelTime = metrics.reduce((sum, m) => sum + (m.model_response_time || m.time_to_first_byte || 0) * 1000, 0) / metrics.length || 0;

    timeDistributionChart.data.datasets[0].data = [avgProxyTime, avgModelTime];
    timeDistributionChart.update();
}

/**
 * 更新表格（数据接收入口，刷新时调用）
 */
function updateTable(metrics) {
    allMetrics = (metrics || []).slice(-100).reverse();
    renderTable();
}

/**
 * 按当前会话过滤条件筛选
 */
function filterMetricsBySession(metrics) {
    if (!sessionFilter) return metrics;
    if (sessionFilter === '__none__') return metrics.filter(m => !m.session_id);
    return metrics.filter(m => m.session_id === sessionFilter);
}

/**
 * 渲染表格（会话过滤 + 分页 + 行生成）
 */
function renderTable() {
    const tableBody = document.getElementById('requestsTableBody');
    const filteredMetrics = filterMetricsBySession(allMetrics);

    if (filteredMetrics.length === 0) {
        const emptyText = allMetrics.length === 0 ? '暂无请求记录' : '无符合过滤条件的请求记录';
        tableBody.innerHTML = `
            <tr>
                <td colspan="12">
                    <div class="loading-state">
                        <div style="color: #4E5969;">${emptyText}</div>
                    </div>
                </td>
            </tr>
        `;
        updatePagination(0);
        lastMetricsHash = '';
        return;
    }

    // 检测数据是否变化，避免无变化时重建DOM
    const currentHash = sessionFilter + '|' + filteredMetrics.map(m => m.request_id + ':' + m.status_code + ':' + (m.total_time || 0)).join('|');
    if (currentHash === lastMetricsHash) {
        return;
    }
    lastMetricsHash = currentHash;

    const totalPages = Math.ceil(filteredMetrics.length / pageSize);
    if (currentPage > totalPages && totalPages > 0) {
        currentPage = totalPages;
    }

    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const pageMetrics = filteredMetrics.slice(startIndex, endIndex);

    tableBody.innerHTML = pageMetrics.map(m => generateTableRow(m)).join('');

    updatePagination(filteredMetrics.length);
}

/**
 * 生成表格行
 */
function generateTableRow(m) {
    const totalTime = (m.total_time || m.time_to_first_byte || 0) * 1000;
    const proxyTime = (m.proxy_processing_time || 0) * 1000;
    const firstTokenLatency = (m.first_token_latency || 0) * 1000;
    const modelTime = (m.model_response_time || m.time_to_first_byte || 0) * 1000;
    const timestamp = new Date(m.request_received_time * 1000).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    const requestId = m.request_id || 'unknown';
    const statusCode = m.status_code || 200;
    const inputTokens = m.input_tokens || 0;
    const outputTokens = m.output_tokens || 0;

    let latencyClass = 'latency-fast';
    if (totalTime > 3000) latencyClass = 'latency-slow';
    else if (totalTime > 1500) latencyClass = 'latency-medium';

    const firstTokenDisplay = m.stream && firstTokenLatency > 0
        ? `${firstTokenLatency.toFixed(0)}ms`
        : 'N/A';

    const toolCallBadge = m.has_tool_call
        ? '<span class="badge badge-tool">有工具</span>'
        : '<span class="badge badge-no-tool">无</span>';

    let statusBadgeClass = 'badge-status-success';
    if (statusCode >= 400) statusBadgeClass = 'badge-status-error';
    else if (statusCode >= 300) statusBadgeClass = 'badge-status-warning';
    const statusBadge = `<span class="badge ${statusBadgeClass}">${statusCode}</span>`;

    const inputTokensDisplay = inputTokens > 0 ? inputTokens : 'N/A';
    const outputTokensDisplay = outputTokens > 0 ? outputTokens : 'N/A';

    return `
        <tr>
            <td ${m.session_id ? `style="box-shadow: inset 3px 0 0 ${sessionColor(m.session_id)}"` : ''}>
                <span class="latency-indicator ${latencyClass}"></span>
                <span class="timestamp">${timestamp}</span>
            </td>
            <td>${generateSessionCell(m)}</td>
            <td>
                <span class="badge ${m.stream ? 'badge-stream' : 'badge-standard'}">
                    ${m.stream ? '流式传输' : '标准请求'}
                </span>
            </td>
            <td>${toolCallBadge}</td>
            <td>${statusBadge}</td>
            <td class="metric-value-cell">${inputTokensDisplay}</td>
            <td class="metric-value-cell">${outputTokensDisplay}</td>
            <td class="metric-value-cell">${totalTime.toFixed(0)}ms</td>
            <td class="metric-value-cell">${proxyTime.toFixed(2)}ms</td>
            <td class="metric-value-cell">${firstTokenDisplay}</td>
            <td class="metric-value-cell">${modelTime.toFixed(0)}ms</td>
            <td>
                <a class="log-link" onclick="showLogModal('request', '${requestId}')">请求</a>
                <span style="margin: 0 4px; color: #E5E6EB;">|</span>
                <a class="log-link" onclick="showLogModal('response', '${requestId}')">响应</a>
            </td>
        </tr>
    `;
}

/**
 * 更新分页控件
 */
function updatePagination(totalItems) {
    const totalPages = Math.ceil(totalItems / pageSize);
    const pageInfo = document.getElementById('pageInfo');
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');

    if (totalItems === 0) {
        pageInfo.textContent = '第 0 页 / 共 0 页';
        prevBtn.disabled = true;
        nextBtn.disabled = true;
        return;
    }

    pageInfo.textContent = `第 ${currentPage} 页 / 共 ${totalPages} 页`;
    prevBtn.disabled = currentPage === 1;
    nextBtn.disabled = currentPage === totalPages;
}

function goToPrevPage() {
    if (currentPage > 1) {
        currentPage--;
        lastMetricsHash = '';
        renderTable();
    }
}

function goToNextPage() {
    const totalPages = Math.ceil(filterMetricsBySession(allMetrics).length / pageSize);
    if (currentPage < totalPages) {
        currentPage++;
        lastMetricsHash = '';
        renderTable();
    }
}

function changePageSize(newSize) {
    pageSize = parseInt(newSize);
    currentPage = 1;
    lastMetricsHash = '';
    renderTable();
}

/**
 * 设置会话过滤条件（空字符串 = 全部会话）
 */
function setSessionFilter(value) {
    sessionFilter = value;
    currentPage = 1;
    lastMetricsHash = '';
    document.getElementById('sessionFilter').value = value;
    renderTable();
}

/**
 * 会话固定配色：按会话ID哈希映射色板，同一会话颜色稳定
 */
function sessionColor(sessionId) {
    let h = 0;
    for (let i = 0; i < sessionId.length; i++) {
        h = (h * 31 + sessionId.charCodeAt(i)) >>> 0;
    }
    return SESSION_COLORS[h % SESSION_COLORS.length];
}

/**
 * HTML转义（会话ID来自客户端请求头，属不可信输入）
 */
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 生成会话单元格内容
 * 实线徽章 = 请求头携带；虚线徽章 = 消息链自动推断；点击徽章可切换过滤
 */
function generateSessionCell(m) {
    if (!m.session_id) {
        return '<span class="session-none">-</span>';
    }
    const color = sessionColor(m.session_id);
    const sid = escapeHtml(m.session_id);
    const label = m.session_id.length > 16 ? escapeHtml(m.session_id.slice(0, 16)) + '&hellip;' : sid;
    const sourceText = m.session_source === 'header' ? '来自请求头' : '自动推断';
    const styleCls = m.session_source === 'inferred' ? ' badge-session-inferred' : '';
    return `<span class="badge badge-session${styleCls}" data-session="${sid}" ` +
        `style="color:${color};border-color:${color};background:${color}1a" ` +
        `title="会话: ${sid}（${sourceText}）&#10;点击筛选该会话">${label}</span>`;
}

/**
 * 更新会话过滤器下拉选项（保持当前选中项）
 */
function updateSessionFilterOptions(metrics) {
    const counts = new Map();
    let noneCount = 0;
    (metrics || []).forEach(m => {
        if (m.session_id) {
            counts.set(m.session_id, (counts.get(m.session_id) || 0) + 1);
        } else {
            noneCount++;
        }
    });

    const select = document.getElementById('sessionFilter');
    const options = ['<option value="">全部会话</option>'];
    counts.forEach((n, sid) => {
        const label = sid.length > 28 ? sid.slice(0, 28) + '…' : sid;
        options.push(`<option value="${escapeHtml(sid)}">${escapeHtml(label)} (${n})</option>`);
    });
    if (noneCount > 0) {
        options.push(`<option value="__none__">无会话 (${noneCount})</option>`);
    }
    select.innerHTML = options.join('');

    // 恢复之前的选中项；会话已不存在时重置为全部
    if (sessionFilter && (sessionFilter === '__none__' ? noneCount > 0 : counts.has(sessionFilter))) {
        select.value = sessionFilter;
    } else {
        sessionFilter = '';
        select.value = '';
    }

    document.getElementById('sessionCount').textContent =
        counts.size > 0 ? `共 ${counts.size} 个会话` : '';
}

/**
 * JSON语法高亮
 */
function syntaxHighlight(json) {
    if (typeof json !== 'string') {
        json = JSON.stringify(json, null, 2);
    }

    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
        let cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'json-key';
            } else {
                cls = 'json-string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        } else if (/null/.test(match)) {
            cls = 'json-null';
        }
        return '<span class="' + cls + '">' + match + '</span>';
    });
}

/**
 * 显示日志模态框
 */
async function showLogModal(type, requestId) {
    const modal = document.getElementById('logModal');
    const modalTitle = document.getElementById('modalTitle');
    const logContent = document.getElementById('logContent');

    modalTitle.textContent = type === 'request' ? '请求日志' : '响应日志';
    logContent.textContent = '加载中...';
    modal.style.display = 'flex';

    try {
        const response = await fetch(`/logs/${type}/${requestId}`);
        if (!response.ok) {
            logContent.textContent = `错误: ${response.status} ${response.statusText}`;
            return;
        }
        const data = await response.json();
        const highlightedJson = syntaxHighlight(data);
        logContent.innerHTML = `<pre class="json-content">${highlightedJson}</pre>`;
    } catch (error) {
        logContent.textContent = `获取日志失败: ${error.message}`;
    }
}

/**
 * 复制日志内容
 */
async function copyLogContent() {
    const logContent = document.getElementById('logContent');
    // 获取纯文本内容（去掉 HTML 高亮标签）
    const text = logContent.innerText || logContent.textContent;
    try {
        await navigator.clipboard.writeText(text);
        const btn = document.querySelector('.modal-copy-btn');
        const label = btn.querySelector('span');
        label.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(() => {
            label.textContent = '复制';
            btn.classList.remove('copied');
        }, 2000);
    } catch (error) {
        // 降级方案
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        const btn = document.querySelector('.modal-copy-btn');
        const label = btn.querySelector('span');
        label.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(() => {
            label.textContent = '复制';
            btn.classList.remove('copied');
        }, 2000);
    }
}

function closeModal() {
    const modal = document.getElementById('logModal');
    modal.style.display = 'none';
}

/**
 * 切换侧边栏 (移动端)
 */
function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.sidebar-overlay');

    sidebar.classList.toggle('mobile-open');
    overlay.classList.toggle('active');
}

function toggleSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
}

/**
 * 清空指标数据
 */
async function clearMetrics() {
    if (confirm('确定要清空所有指标数据吗？')) {
        try {
            const response = await fetch('/metrics', { method: 'DELETE' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            refreshData();
            alert('指标数据已清空');
        } catch (error) {
            alert('清空指标数据失败: ' + error.message);
        }
    }
}

/**
 * 显示错误横幅
 */
function showErrorBanner(message) {
    const errorBanner = document.getElementById('errorBanner');
    if (errorBanner) {
        errorBanner.style.display = 'flex';
        errorBanner.querySelector('.error-message').textContent = message;
    }
}

function hideErrorBanner() {
    const errorBanner = document.getElementById('errorBanner');
    if (errorBanner) {
        errorBanner.style.display = 'none';
    }
}

// ===================== Trace 相关功能 =====================

/**
 * 刷新追踪数据
 */
async function refreshTraces() {
    try {
        const response = await fetch('/traces');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        allTraces = data.traces || [];
        document.getElementById('traceCount').textContent = data.total || 0;
        renderTraceList(allTraces);
    } catch (error) {
        console.error('获取追踪数据失败:', error);
    }
}

async function clearTraces() {
    if (confirm('确定要清空所有追踪数据吗？')) {
        try {
            const response = await fetch('/traces', { method: 'DELETE' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            refreshTraces();
        } catch (error) {
            alert('清空追踪数据失败: ' + error.message);
        }
    }
}

function renderTraceList(traces) {
    const container = document.getElementById('tracesContainer');
    if (!traces || traces.length === 0) {
        container.innerHTML = '<div class="loading-state"><div style="color: #4E5969;">暂无追踪记录</div></div>';
        return;
    }
    container.innerHTML = traces.map(t => generateTraceCard(t)).join('');
}

/**
 * 生成追踪卡片 — 对话故事流设计
 */
function generateTraceCard(trace) {
    const summary = trace.summary || {};
    const steps = trace.steps || [];
    const runStep = steps.find(s => s.type === 'run');
    const detail = runStep?.detail || {};
    const query = detail.query || '';
    const duration = formatDuration(trace.duration_seconds || 0);
    const startTime = trace.started_at ? formatStartTime(trace.started_at) : '';

    const modelCalls = summary.model_calls || 0;
    const toolCalls = summary.tool_calls || 0;

    const waterfallHtml = generateWaterfall(steps, trace.duration_seconds || 0);
    const ganttHtml = generateGantt(steps, trace.duration_seconds || 0);

    return `
    <div class="trace-card">
        <div class="trace-card-header" onclick="toggleTraceExpand(this)">
            <div class="trace-header-left">
                <div class="trace-header-avatar">Q</div>
                <div class="trace-header-content">
                    <div class="trace-header-query">${escapeHtml(query || '对话追踪 #' + (trace.trace_id || '').substring(0,8))}</div>
                    <div class="trace-header-meta">
                        <span class="trace-header-time">${startTime}</span>
                        <span class="trace-header-stats">
                            <span class="trace-stat model"><span class="trace-stat-dot model"></span>${modelCalls}次模型调用</span>
                            <span class="trace-stat tool"><span class="trace-stat-dot tool"></span>${toolCalls}次工具调用</span>
                        </span>
                    </div>
                </div>
            </div>
            <div class="trace-header-right">
                <span class="trace-header-duration">${duration}</span>
                <div class="trace-expand-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                </div>
            </div>
        </div>
        <div class="trace-card-body" style="display: none;">
            <div class="trace-stats-bar">
                <div class="trace-stat-card">
                    <div class="trace-stat-card-icon model"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4"/></svg></div>
                    <div class="trace-stat-card-text">
                        <span class="trace-stat-card-label">模型调用</span>
                        <span class="trace-stat-card-value">${modelCalls}</span>
                    </div>
                </div>
                <div class="trace-stat-card">
                    <div class="trace-stat-card-icon tool"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></div>
                    <div class="trace-stat-card-text">
                        <span class="trace-stat-card-label">工具调用</span>
                        <span class="trace-stat-card-value">${toolCalls}</span>
                    </div>
                </div>
                <div class="trace-stat-card">
                    <div class="trace-stat-card-icon token"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/></svg></div>
                    <div class="trace-stat-card-text">
                        <span class="trace-stat-card-label">Token</span>
                        <span class="trace-stat-card-value">in ${formatTokenCount(summary.tokens_in)} / out ${formatTokenCount(summary.tokens_out)}</span>
                    </div>
                </div>
                <div class="trace-stat-card">
                    <div class="trace-stat-card-icon time"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
                    <div class="trace-stat-card-text">
                        <span class="trace-stat-card-label">模型耗时</span>
                        <span class="trace-stat-card-value">${formatDuration(summary.model_time_seconds || 0)}</span>
                    </div>
                </div>
            </div>
            <div class="trace-gantt-wrap">${ganttHtml}</div>
            <div class="trace-waterfall">${waterfallHtml}</div>
        </div>
    </div>`;
}

/**
 * 甘特图时间轴
 */
function generateGantt(steps, totalDuration) {
    if (totalDuration <= 0) return '';

    // 只取子步骤（depth > 0）
    const childSteps = steps.filter(s => s.depth > 0);
    let segmentsHtml = '';
    let stepAnnotationsHtml = '';
    let idleAnnotationsHtml = '';

    const tagMap = {model: 'AI', tool: '工具', run: '主'};

    for (const step of childSteps) {
        const offset = step.offset_seconds || 0;
        const duration = step.duration_seconds || 0;
        const leftPct = (offset / totalDuration * 100).toFixed(1);
        const widthPct = (duration / totalDuration * 100).toFixed(1);
        const typeClass = `type-${step.type}`;
        const labelMap = {model: 'AI思考', tool: step.name || '工具', run: '主流程'};
        const label = labelMap[step.type] || '';
        segmentsHtml += `<div class="trace-gantt-segment ${typeClass}" style="left:${leftPct}%;width:${Math.max(widthPct,0.5)}%;" title="${label} ${formatDuration(duration)}"></div>`;

        const centerPct = ((offset + duration / 2) / totalDuration * 100).toFixed(1);
        const tag = tagMap[step.type] || '';
        stepAnnotationsHtml += `<div class="trace-gantt-annotation" style="left:${centerPct}%"><span class="trace-gantt-annotation-text ${typeClass}">${tag} ${formatDuration(duration)}</span></div>`;
    }

    // 计算间隔等待时间 -> 标注在上方
    let prevEnd = 0;
    const gaps = [];
    for (const step of childSteps) {
        const offset = step.offset_seconds || 0;
        if (offset > prevEnd + 0.01) {
            gaps.push({start: prevEnd, duration: offset - prevEnd});
        }
        prevEnd = (step.offset_seconds || 0) + (step.duration_seconds || 0);
    }
    if (totalDuration > prevEnd + 0.01) {
        gaps.push({start: prevEnd, duration: totalDuration - prevEnd});
    }

    for (const gap of gaps) {
        const centerPct = ((gap.start + gap.duration / 2) / totalDuration * 100).toFixed(1);
        idleAnnotationsHtml += `<div class="trace-gantt-annotation" style="left:${centerPct}%"><span class="trace-gantt-annotation-text type-idle">间隔 ${formatDuration(gap.duration)}</span></div>`;
    }

    return `
    <div class="trace-gantt-legend">
        <span class="trace-gantt-legend-item"><span class="trace-gantt-legend-dot ai"></span>AI思考</span>
        <span class="trace-gantt-legend-item"><span class="trace-gantt-legend-dot tool"></span>工具调用</span>
        <span class="trace-gantt-legend-item"><span class="trace-gantt-legend-dot idle"></span>间隔等待</span>
    </div>
    ${idleAnnotationsHtml ? `<div class="trace-gantt-annotations-above">${idleAnnotationsHtml}</div>` : ''}
    <div class="trace-gantt">${segmentsHtml}</div>
    ${stepAnnotationsHtml ? `<div class="trace-gantt-annotations">${stepAnnotationsHtml}</div>` : ''}`;
}

/**
 * 瀑布流步骤生成
 */
function generateWaterfall(steps, totalDuration) {
    if (!steps || steps.length === 0) return '<div style="color:#86909C;text-align:center;padding:20px;">无步骤数据</div>';
    let html = '';
    for (const step of steps) {
        const d = step.detail || {};
        const duration = formatDuration(step.duration_seconds || 0);

        // 标签文字
        const tagMap = {run: '主流程', model: 'AI 思考', tool: '工具调用'};
        const tag = tagMap[step.type] || step.type;

        // 关键信息（直接显示在步骤卡片上）
        let keyInfoHtml = '';
        if (step.type === 'run') {
            keyInfoHtml = `
                <span class="trace-key-item"><span class="trace-key-item-label">Token</span><span class="trace-key-item-value">in ${formatTokenCount(d.tokens_in)} / out ${formatTokenCount(d.tokens_out)}</span></span>
                <span class="trace-key-item"><span class="trace-key-item-label">缓存</span><span class="trace-key-item-value">${formatTokenCount(d.tokens_cache)}</span></span>`;
            if (d.query) keyInfoHtml += `<span class="trace-key-item"><span class="trace-key-item-label">用户问</span><span class="trace-key-item-value">${escapeHtml(d.query.length > 40 ? d.query.substring(0,40)+'...' : d.query)}</span></span>`;
        } else if (step.type === 'model') {
            keyInfoHtml = `
                <span class="trace-key-item"><span class="trace-key-item-label">TTFT</span><span class="trace-key-item-value">${formatDuration(d.ttft_seconds || 0)}</span></span>
                <span class="trace-key-item"><span class="trace-key-item-label">流量</span><span class="trace-key-item-value">${formatBytes(d.bytes_request || 0)} / ${formatBytes(d.bytes_response || 0)}</span></span>`;
        } else if (step.type === 'tool') {
            const mainKey = d.command ? '命令' : d.file ? '文件' : d.skill ? '技能' : '';
            const mainVal = d.command || d.file || d.skill || '';
            const shortVal = mainVal.length > 50 ? mainVal.substring(0,50)+'...' : mainVal;
            if (mainKey) keyInfoHtml += `<span class="trace-key-item"><span class="trace-key-item-label">${mainKey}</span><span class="trace-key-item-value">${escapeHtml(shortVal)}</span></span>`;
            if (d.result_summary) {
                const shortResult = String(d.result_summary).substring(0, 50) + (String(d.result_summary).length > 50 ? '...' : '');
                keyInfoHtml += `<span class="trace-key-item"><span class="trace-key-item-label">结果</span><span class="trace-key-item-value">${escapeHtml(shortResult)}</span></span>`;
            }
        }

        // 详情展开按钮
        let detailToggleHtml = '';
        const hasDeepDetail = step.type === 'tool' && (d.command || d.result_summary) ||
                             step.type === 'run' && (d.reply_summary || d.query);
        if (hasDeepDetail) {
            detailToggleHtml = `<div class="trace-event-detail-toggle" onclick="toggleTraceDetail(this)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                <span class="trace-detail-toggle-label"> 查看详情</span>
            </div>
            <div class="trace-event-detail" style="display:none;">${generateStepDetail(step)}</div>`;
        }

        html += `
        <div class="trace-event type-${step.type}">
            <div class="trace-event-header">
                <div class="trace-event-title">
                    <span class="trace-event-tag type-${step.type}">${tag}</span>
                    <span class="trace-event-name">${escapeHtml(step.name || '')}</span>
                </div>
                <span class="trace-event-time">${duration}</span>
            </div>
            <div class="trace-event-key-info">${keyInfoHtml}</div>
            ${detailToggleHtml}
        </div>`;
    }
    return html;
}

function toggleTraceExpand(headerEl) {
    const card = headerEl.closest('.trace-card');
    const body = card.querySelector('.trace-card-body');
    const icon = headerEl.querySelector('.trace-expand-icon svg');
    const isExpanded = body.style.display !== 'none';
    body.style.display = isExpanded ? 'none' : 'block';
    icon.style.transform = isExpanded ? '' : 'rotate(180deg)';
}

function toggleTraceDetail(toggleEl) {
    const detail = toggleEl.nextElementSibling;
    if (!detail) return;
    const icon = toggleEl.querySelector('svg');
    const isExpanded = detail.style.display !== 'none';
    detail.style.display = isExpanded ? 'none' : 'block';
    icon.style.transform = isExpanded ? '' : 'rotate(180deg)';
    // 用专门的数据节点来保存文字，避免 childNodes 索引漂移
    const labelSpan = toggleEl.querySelector('.trace-detail-toggle-label');
    if (labelSpan) labelSpan.textContent = isExpanded ? ' 查看详情' : ' 收起详情';
}

function generateStepDetail(step) {
    const detail = step.detail || {};
    let gridHtml = '';
    let fullHtml = '';

    if (step.type === 'run') {
        gridHtml = [
            ['Token输入', formatTokenCount(detail.tokens_in || 0)],
            ['Token输出', formatTokenCount(detail.tokens_out || 0)],
            ['Token缓存', formatTokenCount(detail.tokens_cache || 0)],
        ].map(([l,v]) => `<div class="trace-detail-item"><span class="trace-detail-label">${l}</span><span class="trace-detail-value">${v}</span></div>`).join('');
        if (detail.query) fullHtml += `<div class="trace-detail-full"><div class="trace-detail-full-label">用户查询</div><div class="trace-detail-full-content">${escapeHtml(detail.query)}</div></div>`;
        if (detail.reply_summary) fullHtml += `<div class="trace-detail-full"><div class="trace-detail-full-label">模型回复</div><div class="trace-detail-full-content">${escapeHtml(detail.reply_summary)}</div></div>`;
    } else if (step.type === 'model') {
        gridHtml = [
            ['TTFT', formatDuration(detail.ttft_seconds || 0)],
            ['请求大小', formatBytes(detail.bytes_request || 0)],
            ['响应大小', formatBytes(detail.bytes_response || 0)],
            ['上下文长度', (detail.in_context_query_chars || 0) + ' chars'],
        ].map(([l,v]) => `<div class="trace-detail-item"><span class="trace-detail-label">${l}</span><span class="trace-detail-value">${v}</span></div>`).join('');
    } else if (step.type === 'tool') {
        const labelMap = {command: '执行命令', file: '文件路径', skill: '技能名称', url: 'URL'};
        const fields = Object.entries(detail).filter(([k]) => k !== 'result_summary');
        gridHtml = fields.map(([k,v]) => {
            const label = labelMap[k] || k;
            const val = String(v).length > 80 ? String(v).substring(0,80)+'...' : String(v);
            return `<div class="trace-detail-item"><span class="trace-detail-label">${label}</span><span class="trace-detail-value">${escapeHtml(val)}</span></div>`;
        }).join('');
        if (detail.result_summary) {
            const r = String(detail.result_summary).length > 500 ? String(detail.result_summary).substring(0,500)+'...' : String(detail.result_summary);
            fullHtml += `<div class="trace-detail-full"><div class="trace-detail-full-label">执行结果</div><div class="trace-detail-full-content">${escapeHtml(r)}</div></div>`;
        }
    }
    return `<div class="trace-detail-grid">${gridHtml}</div>${fullHtml}`;
}

function formatStartTime(isoStr) {
    try {
        const d = new Date(isoStr);
        return d.toLocaleString('zh-CN', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit'});
    } catch { return isoStr; }
}

/**
 * 格式化时间
 */
function formatDuration(seconds, isOffset) {
    if (!seconds || seconds === 0) {
        return isOffset ? '+0ms' : '0ms';
    }
    if (seconds < 1) {
        const ms = Math.round(seconds * 1000);
        return isOffset ? `+${ms}ms` : `${ms}ms`;
    }
    if (seconds < 60) {
        const rounded = seconds.toFixed(1);
        return isOffset ? `+${rounded}s` : `${rounded}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return isOffset ? `+${mins}m${secs}s` : `${mins}m${secs}s`;
}

/**
 * 格式化Token数量
 */
function formatTokenCount(count) {
    if (!count || count === 0) return '0';
    if (count >= 1000) return (count / 1000).toFixed(1) + 'k';
    return String(count);
}

/**
 * 格式化字节数
 */
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0B';
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return bytes + 'B';
}

/**
 * HTML转义
 */
function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ===================== 主题切换 =====================

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    setTheme(next);
}

function toggleThemeFromSettings(checkbox) {
    setTheme(checkbox.checked ? 'dark' : 'light');
}

function initTheme() {
    const saved = localStorage.getItem('openclaw-theme') || 'light';
    setTheme(saved);
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('openclaw-theme', theme);
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
    });
    const settingsToggle = document.getElementById('settingsThemeToggle');
    if (settingsToggle) {
        settingsToggle.checked = theme === 'dark';
    }
    const settingsLabel = document.getElementById('themeLabel');
    if (settingsLabel) {
        settingsLabel.textContent = theme === 'dark' ? '深色' : '浅色';
    }
    // 更新 Chart.js 图表颜色
    updateChartTheme(theme);
}

function updateChartTheme(theme) {
    const colors = getThemeColors();

    Chart.defaults.color = colors.textSecondary;

    if (responseTimeChart) {
        responseTimeChart.data.datasets[0].borderColor = colors.primary;
        responseTimeChart.data.datasets[0].backgroundColor = colors.primary + '1a';
        responseTimeChart.data.datasets[0].pointHoverBackgroundColor = colors.primary;
        responseTimeChart.data.datasets[1].borderColor = colors.success;
        responseTimeChart.data.datasets[1].backgroundColor = colors.success + '1a';
        responseTimeChart.data.datasets[1].pointHoverBackgroundColor = colors.success;
        responseTimeChart.options.scales.x.ticks.color = colors.textMuted;
        responseTimeChart.options.scales.y.ticks.color = colors.textMuted;
        responseTimeChart.options.scales.y.grid.color = colors.border;
        responseTimeChart.options.plugins.legend.labels.color = colors.textPrimary;
        responseTimeChart.options.plugins.tooltip.backgroundColor = colors.surface;
        responseTimeChart.options.plugins.tooltip.titleColor = colors.textPrimary;
        responseTimeChart.options.plugins.tooltip.bodyColor = colors.textSecondary;
        responseTimeChart.options.plugins.tooltip.borderColor = colors.border;
        responseTimeChart.update();
    }
    if (timeDistributionChart) {
        timeDistributionChart.data.datasets[0].backgroundColor = [hexToRgba(colors.primary, 0.8), hexToRgba(colors.success, 0.8)];
        timeDistributionChart.data.datasets[0].borderColor = [colors.primary, colors.success];
        timeDistributionChart.options.scales.x.ticks.color = colors.textPrimary;
        timeDistributionChart.options.scales.y.ticks.color = colors.textMuted;
        timeDistributionChart.options.scales.y.grid.color = colors.border;
        timeDistributionChart.options.plugins.tooltip.backgroundColor = colors.surface;
        timeDistributionChart.options.plugins.tooltip.titleColor = colors.textPrimary;
        timeDistributionChart.options.plugins.tooltip.bodyColor = colors.textSecondary;
        timeDistributionChart.options.plugins.tooltip.borderColor = colors.border;
        timeDistributionChart.update();
    }
    if (allMetrics.length) {
        renderSparklines(allMetrics);
    }
}

// ===================== KPI Sparklines =====================

function enhanceMetricCards() {
    if (metricCardEnhanced) return;
    document.querySelectorAll('.metric-card').forEach((card, index) => {
        card.dataset.metricIndex = String(index);
        const valueEl = card.querySelector('.metric-value');
        if (!valueEl) return;
        const trend = document.createElement('span');
        trend.className = 'metric-trend';
        trend.id = 'trend-' + index;
        trend.textContent = '';
        const row = document.createElement('div');
        row.className = 'metric-value-row';
        valueEl.parentNode.insertBefore(row, valueEl);
        row.appendChild(valueEl);
        row.appendChild(trend);
        const canvas = document.createElement('canvas');
        canvas.className = 'sparkline';
        canvas.id = 'sparkline-' + index;
        canvas.height = 40;
        card.appendChild(canvas);
    });
    metricCardEnhanced = true;
}

function renderSparklines(metrics) {
    if (!metrics || metrics.length < 2) return;
    const n = Math.min(metrics.length, 20);
    const recent = metrics.slice(-n);
    const getVal = (m, cfg, idx, arr) => {
        if (cfg.compute) return cfg.compute(m, idx, arr);
        if (!cfg.key) return idx + 1;
        let v = m[cfg.key];
        if (v == null) v = 0;
        if (cfg.ms) v = v * 1000;
        return v;
    };
    const configs = [
        { key: null },
        { key: 'total_time', ms: true },
        { key: 'proxy_processing_time', ms: true },
        { key: 'model_response_time', ms: true },
        { key: 'inter_request_gap', ms: true },
        { key: 'total_time', ms: true },
        { key: 'status_code', compute: m => m.status_code === 200 ? 1 : 0 },
        { key: 'status_code', compute: m => m.status_code !== 200 ? 1 : 0 },
        { key: 'status_code', compute: (m, i, arr) => {
            const slice = arr.slice(0, i + 1);
            const ok = slice.filter(x => x.status_code === 200).length;
            return ok / (slice.length || 1) * 100;
        }},
    ];
    document.querySelectorAll('.metric-card').forEach((card) => {
        const idx = parseInt(card.dataset.metricIndex || '0', 10);
        const cfg = configs[idx] || configs[0];
        const values = recent.map((m, i) => getVal(m, cfg, i, recent));
        drawSparkline('sparkline-' + idx, values);
        const lastIdx = values.length - 1;
        if (lastIdx > 0) {
            const diff = values[lastIdx] - values[lastIdx - 1];
            const trendEl = document.getElementById('trend-' + idx);
            if (trendEl && diff !== 0) {
                const pct = Math.abs((diff / (values[lastIdx - 1] || 1)) * 100).toFixed(1);
                const arrow = diff > 0 ? '↑' : '↓';
                trendEl.textContent = `${arrow} ${pct}%`;
                trendEl.classList.add(diff > 0 ? 'up' : 'down');
            }
        }
    });
}

function drawSparkline(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    ctx.scale(dpr, dpr);
    const width = rect.width;
    const height = rect.height;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const primary = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#0064C8';
    ctx.clearRect(0, 0, width, height);

    // 业界 KPI sparkline 通常只做极淡的趋势提示：
    // 1px 细线 + 几乎透明的填充，不抢数字的风头
    const strokeColor = hexToRgba(primary, 0.35);
    const fillTop = hexToRgba(primary, 0.08);
    const fillBottom = hexToRgba(primary, 0);

    // 填充区域（极淡）
    ctx.beginPath();
    data.forEach((v, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 8) - 4;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, fillTop);
    gradient.addColorStop(1, fillBottom);
    ctx.fillStyle = gradient;
    ctx.fill();

    // 细线
    ctx.beginPath();
    data.forEach((v, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 8) - 4;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 1;
    ctx.lineJoin = 'round';
    ctx.stroke();
}

// ===================== 事件监听器 =====================

document.addEventListener('DOMContentLoaded', function() {
    // 初始化主题
    initTheme();

    // 主题切换按钮
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            setTheme(this.getAttribute('data-theme'));
        });
    });

    // 侧边栏导航点击事件
    const sidebarItems = document.querySelectorAll('.sidebar-nav-item');
    sidebarItems.forEach(item => {
        item.addEventListener('click', function() {
            sidebarItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
            const pageName = this.getAttribute('data-page');
            syncNavigation('sidebar', this);
            switchPage(pageName);

            if (window.innerWidth <= 768) {
                toggleSidebar();
            }
        });
    });

    // 顶部导航点击事件
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            navItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
            const pageName = this.getAttribute('data-page');
            syncNavigation('header', this);
            switchPage(pageName);
        });
    });

    // 自动刷新开关 (概览)
    const toggle = document.getElementById('autoRefreshToggle');
    toggle.addEventListener('click', function() {
        this.classList.toggle('active');
        if (this.classList.contains('active')) {
            autoRefreshInterval = setInterval(refreshData, 5000);
        } else {
            clearInterval(autoRefreshInterval);
        }
    });

    // 自动刷新开关 (追踪)
    const traceToggle = document.getElementById('traceAutoRefreshToggle');
    traceToggle.addEventListener('click', function() {
        this.classList.toggle('active');
        if (this.classList.contains('active')) {
            traceAutoRefreshInterval = setInterval(refreshTraces, 5000);
        } else {
            clearInterval(traceAutoRefreshInterval);
        }
    });

    // 分页按钮
    document.getElementById('prevPage').addEventListener('click', goToPrevPage);
    document.getElementById('nextPage').addEventListener('click', goToNextPage);
    document.getElementById('pageSize').addEventListener('change', function(e) {
        changePageSize(e.target.value);
    });

    // 会话过滤器
    document.getElementById('sessionFilter').addEventListener('change', function(e) {
        setSessionFilter(e.target.value);
    });

    // 点击会话徽章切换过滤（事件委托，避免对不可信会话ID生成内联事件）
    document.getElementById('requestsTableBody').addEventListener('click', function(e) {
        const badge = e.target.closest('.badge-session');
        if (!badge) return;
        const sid = badge.getAttribute('data-session');
        setSessionFilter(sessionFilter === sid ? '' : sid);
    });

    // 模态框外部点击关闭
    document.getElementById('logModal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeModal();
        }
    });

    // 页面加载初始化
    window.addEventListener('load', async function() {
        const isServerUp = await checkServerStatus();

        if (isServerUp) {
            enhanceMetricCards();
            initCharts();
            refreshData();
            autoRefreshInterval = setInterval(refreshData, 5000);
        } else {
            showErrorBanner('代理服务器未启动 - 请先启动代理服务器后刷新此页面');
            setTimeout(() => {
                window.location.reload();
            }, 5000);
        }
    });
});

/**
 * 同步导航状态
 */
function syncNavigation(source, element) {
    const pageName = element.getAttribute('data-page');
    const index = Array.from(element.parentElement.children).indexOf(element);

    if (source === 'sidebar') {
        const navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(item => item.classList.remove('active'));
        const targetNavItem = document.querySelector(`.nav-item[data-page="${pageName}"]`);
        if (targetNavItem) targetNavItem.classList.add('active');
    } else {
        const sidebarItems = document.querySelectorAll('.sidebar-nav-item');
        sidebarItems.forEach(item => item.classList.remove('active'));
        const targetSidebarItem = document.querySelector(`.sidebar-nav-item[data-page="${pageName}"]`);
        if (targetSidebarItem) targetSidebarItem.classList.add('active');
    }
}