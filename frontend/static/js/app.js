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

// Trace数据
let allTraces = [];

// 当前页签
let currentPageName = 'overview';

// Chart.js 默认配置
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
Chart.defaults.color = '#4E5969';

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
function initCharts() {
    const ctx1 = document.getElementById('responseTimeChart').getContext('2d');
    responseTimeChart = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '总耗时',
                data: [],
                borderColor: '#0064C8',
                backgroundColor: 'rgba(0, 100, 200, 0.08)',
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: '#0064C8',
                pointHoverBorderColor: '#FFFFFF',
                pointHoverBorderWidth: 2
            }, {
                label: '模型耗时',
                data: [],
                borderColor: '#00A854',
                backgroundColor: 'rgba(0, 168, 84, 0.08)',
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: '#00A854',
                pointHoverBorderColor: '#FFFFFF',
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
                        color: '#1D2129'
                    }
                },
                tooltip: {
                    backgroundColor: '#FFFFFF',
                    titleColor: '#1D2129',
                    bodyColor: '#4E5969',
                    borderColor: '#E5E6EB',
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
                        color: '#86909C'
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: '#E5E6EB',
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: '#86909C',
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
                    'rgba(0, 100, 200, 0.8)',
                    'rgba(0, 168, 84, 0.8)'
                ],
                borderColor: [
                    '#0064C8',
                    '#00A854'
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
                    backgroundColor: '#FFFFFF',
                    titleColor: '#1D2129',
                    bodyColor: '#4E5969',
                    borderColor: '#E5E6EB',
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
                        color: '#1D2129'
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: '#E5E6EB',
                        drawBorder: false
                    },
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: '#86909C',
                        callback: function(value) {
                            return value + 'ms';
                        }
                    }
                }
            }
        }
    });
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
        updateTable(data.metrics);

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
 * 更新表格
 */
function updateTable(metrics) {
    const tableBody = document.getElementById('requestsTableBody');

    if (!metrics || metrics.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="11">
                    <div class="loading-state">
                        <div style="color: #4E5969;">暂无请求记录</div>
                    </div>
                </td>
            </tr>
        `;
        updatePagination(0);
        return;
    }

    allMetrics = metrics.slice(-100).reverse();

    const totalPages = Math.ceil(allMetrics.length / pageSize);
    if (currentPage > totalPages && totalPages > 0) {
        currentPage = totalPages;
    }

    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const pageMetrics = allMetrics.slice(startIndex, endIndex);

    tableBody.innerHTML = pageMetrics.map(m => generateTableRow(m)).join('');

    updatePagination(allMetrics.length);
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
            <td>
                <span class="latency-indicator ${latencyClass}"></span>
                <span class="timestamp">${timestamp}</span>
            </td>
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
        updateTable(allMetrics);
    }
}

function goToNextPage() {
    const totalPages = Math.ceil(allMetrics.length / pageSize);
    if (currentPage < totalPages) {
        currentPage++;
        updateTable(allMetrics);
    }
}

function changePageSize(newSize) {
    pageSize = parseInt(newSize);
    currentPage = 1;
    updateTable(allMetrics);
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

/**
 * 清空追踪数据
 */
async function clearTraces() {
    if (confirm('确定要清空所有追踪数据吗？')) {
        try {
            const response = await fetch('/traces', { method: 'DELETE' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            refreshTraces();
        } catch (error) {
            alert('清空追踪数据失败: ' + error.message);
        }
    }
}

/**
 * 渲染追踪列表
 */
function renderTraceList(traces) {
    const container = document.getElementById('tracesContainer');
    if (!traces || traces.length === 0) {
        container.innerHTML = `
            <div class="loading-state">
                <div style="color: #4E5969;">暂无追踪记录</div>
            </div>
        `;
        return;
    }

    container.innerHTML = traces.map(t => generateTraceCard(t)).join('');
}

/**
 * 生成追踪卡片
 */
function generateTraceCard(trace) {
    const traceId = trace.trace_id || trace.storage_id || '';
    const shortId = traceId.length > 8 ? traceId.substring(0, 8) + '...' : traceId;
    const duration = formatDuration(trace.duration_seconds || 0);
    const startTime = trace.started_at ? new Date(trace.started_at).toLocaleString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    }) : '';

    const summary = trace.summary || {};
    const modelCalls = summary.model_calls || 0;
    const toolCalls = summary.tool_calls || 0;

    // 从 steps 中提取 query
    const runStep = (trace.steps || []).find(s => s.type === 'run');
    const query = runStep && runStep.detail ? (runStep.detail.query || '') : '';
    const shortQuery = query.length > 30 ? query.substring(0, 30) + '...' : query;

    const stepsHtml = generateTimeline(trace.steps || [], trace.duration_seconds || 0);

    return `
        <div class="trace-card">
            <div class="trace-card-header" onclick="toggleTraceExpand(this)">
                <div class="trace-card-summary">
                    <span class="trace-badge trace-badge-id">${shortId}</span>
                    ${shortQuery ? `<span class="trace-badge trace-badge-query">${shortQuery}</span>` : ''}
                    <span class="trace-badge trace-badge-model">${modelCalls} 模型</span>
                    <span class="trace-badge trace-badge-tool">${toolCalls} 工具</span>
                    <span class="trace-duration">${duration}</span>
                    <span class="trace-time">${startTime}</span>
                </div>
                <div class="trace-expand-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                </div>
            </div>
            <div class="trace-card-body" style="display: none;">
                <div class="trace-summary-bar">
                    <div class="trace-summary-item">
                        <span class="trace-summary-label">模型调用</span>
                        <span class="trace-summary-value">${modelCalls}</span>
                    </div>
                    <div class="trace-summary-item">
                        <span class="trace-summary-label">工具调用</span>
                        <span class="trace-summary-value">${toolCalls}</span>
                    </div>
                    <div class="trace-summary-item">
                        <span class="trace-summary-label">Token输入</span>
                        <span class="trace-summary-value">${formatTokenCount(summary.tokens_in || 0)}</span>
                    </div>
                    <div class="trace-summary-item">
                        <span class="trace-summary-label">Token输出</span>
                        <span class="trace-summary-value">${formatTokenCount(summary.tokens_out || 0)}</span>
                    </div>
                    <div class="trace-summary-item">
                        <span class="trace-summary-label">模型耗时</span>
                        <span class="trace-summary-value">${formatDuration(summary.model_time_seconds || 0)}</span>
                    </div>
                </div>
                <div class="trace-progress-bar">
                    ${generateProgressBar(trace.steps || [], trace.duration_seconds || 0)}
                </div>
                <div class="trace-timeline">
                    ${stepsHtml}
                </div>
            </div>
        </div>
    `;
}

/**
 * 生成进度条
 */
function generateProgressBar(steps, totalDuration) {
    if (totalDuration <= 0) return '';
    return steps.map(step => {
        const leftPct = ((step.offset_seconds || 0) / totalDuration * 100).toFixed(1);
        const widthPct = ((step.duration_seconds || 0) / totalDuration * 100).toFixed(1);
        const typeClass = `type-${step.type}`;
        return `<div class="trace-progress-segment ${typeClass}" style="left: ${leftPct}%; width: ${Math.max(widthPct, 0.5)}%;"></div>`;
    }).join('');
}

/**
 * 生成 Timeline 步骤列表
 */
function generateTimeline(steps, totalDuration) {
    if (!steps || steps.length === 0) return '<div style="color: #86909C; text-align: center; padding: 20px;">无步骤数据</div>';

    let html = '';
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        const depth = step.depth || 0;
        const depthClass = `depth-${depth}`;

        const iconSvg = getStepIcon(step.type);
        const offset = formatDuration(step.offset_seconds || 0, true);
        const duration = formatDuration(step.duration_seconds || 0);
        const name = step.name || '';

        const isLast = (i === steps.length - 1) || (steps[i + 1] && steps[i + 1].depth === 0);
        const connector = depth > 0 ? (isLast ? '└──' : '├──') : '';

        const detailHtml = generateStepDetail(step);

        html += `
            <div class="trace-step ${depthClass}" onclick="toggleStepDetail(this)">
                <div class="trace-step-indent"></div>
                <div class="trace-step-icon type-${step.type}">
                    ${iconSvg}
                </div>
                <div class="trace-step-info">
                    <span class="trace-step-name">${connector ? connector + ' ' : ''}${name}</span>
                    <div class="trace-step-meta">
                        <span class="trace-step-offset">${offset}</span>
                        <span class="trace-step-duration">${duration}</span>
                    </div>
                </div>
                <div class="trace-step-expand">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                </div>
            </div>
            <div class="trace-step-detail" style="display: none;">
                ${detailHtml}
            </div>
        `;
    }
    return html;
}

/**
 * 获取步骤图标
 */
function getStepIcon(type) {
    if (type === 'run') {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-14 9V3z"/></svg>`;
    } else if (type === 'model') {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"/></svg>`;
    } else if (type === 'tool') {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`;
    }
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>`;
}

/**
 * 生成步骤详情
 */
function generateStepDetail(step) {
    const detail = step.detail || {};
    let gridHtml = '';
    let fullHtml = '';

    if (step.type === 'run') {
        gridHtml = `
            <div class="trace-detail-item">
                <span class="trace-detail-label">Token输入</span>
                <span class="trace-detail-value">${formatTokenCount(detail.tokens_in || 0)}</span>
            </div>
            <div class="trace-detail-item">
                <span class="trace-detail-label">Token输出</span>
                <span class="trace-detail-value">${formatTokenCount(detail.tokens_out || 0)}</span>
            </div>
            <div class="trace-detail-item">
                <span class="trace-detail-label">Token缓存</span>
                <span class="trace-detail-value">${formatTokenCount(detail.tokens_cache || 0)}</span>
            </div>
        `;
        if (detail.query) {
            fullHtml += `
                <div class="trace-detail-full">
                    <div class="trace-detail-full-label">用户查询</div>
                    <div class="trace-detail-full-content">${escapeHtml(detail.query)}</div>
                </div>
            `;
        }
        if (detail.reply_summary) {
            fullHtml += `
                <div class="trace-detail-full">
                    <div class="trace-detail-full-label">模型回复</div>
                    <div class="trace-detail-full-content">${escapeHtml(detail.reply_summary)}</div>
                </div>
            `;
        }
    } else if (step.type === 'model') {
        gridHtml = `
            <div class="trace-detail-item">
                <span class="trace-detail-label">TTFT</span>
                <span class="trace-detail-value">${formatDuration(detail.ttft_seconds || 0)}</span>
            </div>
            <div class="trace-detail-item">
                <span class="trace-detail-label">请求大小</span>
                <span class="trace-detail-value">${formatBytes(detail.bytes_request || 0)}</span>
            </div>
            <div class="trace-detail-item">
                <span class="trace-detail-label">响应大小</span>
                <span class="trace-detail-value">${formatBytes(detail.bytes_response || 0)}</span>
            </div>
            <div class="trace-detail-item">
                <span class="trace-detail-label">上下文查询</span>
                <span class="trace-detail-value">${detail.in_context_query_chars || 0} chars</span>
            </div>
        `;
    } else if (step.type === 'tool') {
        // 通用工具详情
        const toolFields = Object.entries(detail).filter(([k, v]) => v && k !== 'result_summary');
        gridHtml = toolFields.map(([key, value]) => {
            const labelMap = {
                'file': '文件路径',
                'command': '执行命令',
                'skill': '技能名称',
                'url': 'URL'
            };
            const label = labelMap[key] || key;
            let displayValue = String(value);
            if (displayValue.length > 60) displayValue = displayValue.substring(0, 60) + '...';
            return `
                <div class="trace-detail-item">
                    <span class="trace-detail-label">${label}</span>
                    <span class="trace-detail-value">${escapeHtml(displayValue)}</span>
                </div>
            `;
        }).join('');

        if (detail.result_summary) {
            let resultText = String(detail.result_summary);
            if (resultText.length > 500) resultText = resultText.substring(0, 500) + '...';
            fullHtml += `
                <div class="trace-detail-full">
                    <div class="trace-detail-full-label">执行结果</div>
                    <div class="trace-detail-full-content">${escapeHtml(resultText)}</div>
                </div>
            `;
        }
    }

    return `
        <div class="trace-detail-grid">
            ${gridHtml}
        </div>
        ${fullHtml}
    `;
}

/**
 * 展开/收起对话卡片
 */
function toggleTraceExpand(headerEl) {
    const card = headerEl.closest('.trace-card');
    const body = card.querySelector('.trace-card-body');
    const icon = headerEl.querySelector('.trace-expand-icon svg');
    const isExpanded = body.style.display !== 'none';
    body.style.display = isExpanded ? 'none' : 'block';
    icon.style.transform = isExpanded ? '' : 'rotate(180deg)';
}

/**
 * 展开/收起步骤详情
 */
function toggleStepDetail(stepEl) {
    const detail = stepEl.nextElementSibling;
    if (!detail || !detail.classList.contains('trace-step-detail')) return;
    const icon = stepEl.querySelector('.trace-step-expand svg');
    const isExpanded = detail.style.display !== 'none';
    detail.style.display = isExpanded ? 'none' : 'block';
    icon.style.transform = isExpanded ? '' : 'rotate(180deg)';
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

// ===================== 事件监听器 =====================

document.addEventListener('DOMContentLoaded', function() {
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
            autoRefreshInterval = setInterval(refreshData, 2000);
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
            initCharts();
            refreshData();
            autoRefreshInterval = setInterval(refreshData, 2000);
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