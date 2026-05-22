/**
 * OpenClaw 控制台前端逻辑
 * 提供实时监控和数据展示功能
 */

// 全局变量
let responseTimeChart = null;
let timeDistributionChart = null;
let autoRefreshInterval = null;

// 分页状态
let currentPage = 1;
let pageSize = 10;  // 默认每页10条
let allMetrics = [];  // 存储所有metrics数据

// Chart.js 默认配置
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
Chart.defaults.color = '#4E5969';

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

/**
 * 切换到上一页
 */
function goToPrevPage() {
    if (currentPage > 1) {
        currentPage--;
        updateTable(allMetrics);
    }
}

/**
 * 切换到下一页
 */
function goToNextPage() {
    const totalPages = Math.ceil(allMetrics.length / pageSize);
    if (currentPage < totalPages) {
        currentPage++;
        updateTable(allMetrics);
    }
}

/**
 * 改变每页显示数量
 */
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

/**
 * 关闭模态框
 */
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

/**
 * 切换侧边栏收起/展开 (桌面端)
 */
function toggleSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
}

/**
 * 侧边栏导航
 */
document.addEventListener('DOMContentLoaded', function() {
    // 侧边栏导航点击事件
    const sidebarItems = document.querySelectorAll('.sidebar-nav-item');
    sidebarItems.forEach(item => {
        item.addEventListener('click', function() {
            // 移除所有active状态
            sidebarItems.forEach(i => i.classList.remove('active'));
            // 添加当前active状态
            this.classList.add('active');

            // 同步顶部导航
            syncNavigation('sidebar', this);

            // 移动端点击后关闭侧边栏
            if (window.innerWidth <= 768) {
                toggleSidebar();
            }
        });
    });

    // 顶部导航点击事件
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach((item, index) => {
        item.addEventListener('click', function() {
            // 移除所有active状态
            navItems.forEach(i => i.classList.remove('active'));
            // 添加当前active状态
            this.classList.add('active');

            // 同步侧边栏导航
            syncNavigation('header', this);
        });
    });
});

/**
 * 同步导航状态
 */
function syncNavigation(source, element) {
    const index = Array.from(element.parentElement.children).indexOf(element);

    if (source === 'sidebar') {
        // 更新顶部导航
        const navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(item => item.classList.remove('active'));
        if (navItems[index]) {
            navItems[index].classList.add('active');
        }
    } else {
        // 更新侧边栏导航
        const sidebarItems = document.querySelectorAll('.sidebar-nav-item');
        sidebarItems.forEach(item => item.classList.remove('active'));
        if (sidebarItems[index]) {
            sidebarItems[index].classList.add('active');
        }
    }
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
            const result = await response.json();
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

/**
 * 隐藏错误横幅
 */
function hideErrorBanner() {
    const errorBanner = document.getElementById('errorBanner');
    if (errorBanner) {
        errorBanner.style.display = 'none';
    }
}

// 事件监听器设置
document.addEventListener('DOMContentLoaded', function() {
    // 自动刷新开关
    const toggle = document.getElementById('autoRefreshToggle');
    toggle.addEventListener('click', function() {
        this.classList.toggle('active');
        if (this.classList.contains('active')) {
            autoRefreshInterval = setInterval(refreshData, 2000);
        } else {
            clearInterval(autoRefreshInterval);
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

            // 每5秒尝试重新连接
            setTimeout(() => {
                window.location.reload();
            }, 5000);
        }
    });
});