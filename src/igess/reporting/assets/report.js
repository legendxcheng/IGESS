async function bootstrapReport() {
  const report = await loadReport();
  renderOverview(report);
  renderFishProgression(report);
  renderResourceControls(report);
  renderResourceChart(report, firstResource(report));
  renderCpsChart(report);
  renderEventChart(report);
  renderPaybackChart(report);
  renderDiagnostics(report);
  renderEvidence(report);
  window.addEventListener('resize', resizeCharts);
}

if (typeof document !== 'undefined') {
  bootstrapReport();
}

const charts = [];

async function loadReport() {
  const inline = document.getElementById('igess-report-data');
  if (inline) {
    return JSON.parse(inline.textContent);
  }
  const src = document.body.dataset.reportSrc || 'report_data.json';
  const response = await fetch(src);
  return await response.json();
}

function renderOverview(report) {
  const scenario = document.querySelector('[data-scenario]');
  if (scenario) {
    scenario.textContent = scenarioLabel(report.scenario.id);
  }
  const container = document.querySelector('[data-overview-kpis]');
  if (!container) return;
  const overview = report.overview || {};
  const firstUnlock = overview.first_key_unlock;
  const worstPayback = overview.worst_payback;
  const profiles = overview.profiles || [];
  container.innerHTML = [
    kpiCard('模拟时长', numericMarkup(overview.duration_seconds, '秒')),
    kpiCard(
      '玩家档案',
      `<span class="kpi-value">${escapeHtml(profiles.map(profileLabel).join('、') || '无')}</span>`
    ),
    kpiCard('购买次数', numericMarkup(overview.purchase_count)),
    kpiCard(
      '首次关键解锁',
      firstUnlock ? numericMarkup(firstUnlock.time_seconds, '秒') : '<span class="kpi-value">无</span>',
      firstUnlock ? identityMarkup(firstUnlock) : ''
    ),
    kpiCard('转生重置次数', numericMarkup(overview.prestige_reset_count)),
    kpiCard(
      '最长回本周期',
      worstPayback ? numericMarkup(worstPayback.payback_seconds, '秒') : '<span class="kpi-value">无</span>',
      worstPayback ? identityMarkup(worstPayback) : ''
    ),
    kpiCard(
      '未触达内容',
      `<div class="kpi-pair"><div><span>从未购买</span>${numericMarkup(overview.never_purchased_count)}</div>` +
        `<div><span>从未解锁</span>${numericMarkup(overview.never_unlocked_count)}</div></div>`
    ),
    kpiCard('预警类别数', numericMarkup(overview.warning_category_count)),
    finalResourcesCard(overview.final_resources || {}),
  ].join('');
}

function kpiCard(label, valueMarkup, detailMarkup = '') {
  return [
    '<article class="kpi-card" role="listitem">',
    `<h3>${escapeHtml(label)}</h3>`,
    valueMarkup,
    detailMarkup,
    '</article>',
  ].join('');
}

function numericMarkup(point, suffix = '') {
  if (!point || typeof point !== 'object') {
    return '<span class="kpi-value">—</span>';
  }
  const display = point.display_value == null || point.display_value === ''
    ? '—'
    : String(point.display_value);
  const exact = point.exact_value == null ? '' : String(point.exact_value);
  const exactTitle = exact ? ` title="精确值：${escapeHtml(exact)}"` : '';
  const exactDetails = exact
    ? `<details class="exact-value"><summary>精确值</summary><code>${escapeHtml(exact)}</code></details>`
    : '';
  return `<span class="kpi-value" data-exact-value="${escapeHtml(exact)}"${exactTitle}>` +
    `${escapeHtml(display)}${escapeHtml(suffix)}</span>${exactDetails}`;
}

function identityMarkup(row) {
  const identity = [
    profileLabel(row.profile_id || ''),
    `${contentKindLabel(row.kind || '')}：${itemIdentityLabel(row.item_id || '')}`,
  ].filter(Boolean).join(' · ');
  return identity ? `<p class="kpi-detail">${escapeHtml(identity)}</p>` : '';
}

function finalResourcesCard(finalResources) {
  const profiles = Object.entries(finalResources);
  if (!profiles.length) {
    return kpiCard('最终资源', '<span class="kpi-value">无</span>');
  }
  const displayRows = profiles.flatMap(([profileId, resources]) =>
    Object.entries(resources || {}).map(([resourceId, point]) =>
      `<li><strong>${escapeHtml(profileLabel(profileId))}</strong> · ${escapeHtml(resourceLabel(resourceId))}：${numericMarkup(point)}</li>`
    )
  );
  const exactRows = profiles.flatMap(([profileId, resources]) =>
    Object.entries(resources || {}).map(([resourceId, point]) =>
      `<li><strong>${escapeHtml(profileLabel(profileId))}</strong> · ${escapeHtml(resourceLabel(resourceId))}：` +
        `<code>${escapeHtml(point && point.exact_value != null ? point.exact_value : '')}</code></li>`
    )
  );
  return kpiCard(
    '最终资源',
    `<ul class="kpi-resources">${displayRows.join('')}</ul>`,
    `<details class="exact-values"><summary>精确值</summary><ul>${exactRows.join('')}</ul></details>`
  );
}

function renderFishProgression(report) {
  const fish = report.fish_progression || {};
  if (!fish.available) return;
  renderCoreProgression(fish.core || {}, fish.balance || {});
  renderPersistentProgression(fish.persistent || {});
}

function renderCoreProgression(core, balance = {}) {
  const section = document.querySelector('[data-fish-core-section]');
  const profiles = core.profiles || {};
  const entries = Object.entries(profiles);
  if (!entries.length) return;
  if (section) section.hidden = false;
  const target = document.querySelector('[data-fish-core-kpis]');
  if (target) {
    target.innerHTML = entries.map(([profileId, profile]) => {
      const summary = profile.summary || {};
      return [
        kpiCard(
          `${profileLabel(profileId)} · 摸鱼幸运值`,
          numericMarkup(summary.fish_luck_final),
          `<p class="kpi-detail">峰值 ${numericInline(summary.fish_luck_peak)}</p>`
        ),
        kpiCard(
          `${profileLabel(profileId)} · 垃圾幸运值`,
          numericMarkup(summary.trash_luck_final),
          `<p class="kpi-detail">峰值 ${numericInline(summary.trash_luck_peak)}</p>`
        ),
        kpiCard(
          `${profileLabel(profileId)} · 力量`,
          numericMarkup(summary.strength_final),
          `<p class="kpi-detail">峰值 ${numericInline(summary.strength_peak)}</p>`
        ),
        kpiCard(
          `${profileLabel(profileId)} · 幸运值最长停滞`,
          `<div class="kpi-pair"><div><span>摸鱼</span>${numericMarkup(summary.longest_fish_luck_stagnation_seconds, '秒')}</div>` +
            `<div><span>垃圾</span>${numericMarkup(summary.longest_trash_luck_stagnation_seconds, '秒')}</div></div>`
        ),
      ].join('');
    }).join('');
  }
  renderFishAcquisitionRateChart(balance.profiles || {});
  renderFishCumulativeOutputChart(balance.profiles || {});
  renderLuckProgressionChart(profiles);
}

function renderFishAcquisitionRateChart(profiles) {
  const series = [];
  Object.entries(profiles).forEach(([profileId, profile]) => {
    const rows = profile.rate_rows || [];
    [
      ['资源/秒', 'resource_per_second', '#16a34a'],
      ['金钱/秒', 'money_per_second', '#2563eb'],
    ].forEach(([label, field, color]) => {
      series.push({
        name: `${profileLabel(profileId)} · ${label}`,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        itemStyle: { color },
        data: fishEconomyLineData(rows, field, { positiveOnly: true }),
      });
    });
  });
  replaceChart('fish-acquisition-rate-chart', fishBalanceLineOption(
    '每秒获得的资源量与金钱量（5分钟窗口）',
    series,
    '每秒获得量 · 对数同轴',
    { logarithmic: true }
  ));
}

function renderFishCumulativeOutputChart(profiles) {
  const series = [];
  Object.entries(profiles).forEach(([profileId, profile]) => {
    const rows = profile.cumulative_rows || [];
    [
      ['累计金钱', 'money_acquired_cumulative', '#2563eb'],
      ['累计资源', 'resource_acquired_cumulative', '#16a34a'],
    ].forEach(([label, field, color]) => {
      series.push({
        name: `${profileLabel(profileId)} · ${label}`,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        itemStyle: { color },
        data: fishEconomyLineData(rows, field, { positiveOnly: true }),
      });
    });
  });
  replaceChart('fish-cumulative-output-chart', fishBalanceLineOption(
    '累计获得的金钱量与资源量',
    series,
    '累计毛产出 · 对数同轴',
    { logarithmic: true }
  ));
}

function fishEconomyLineData(rows, field, { positiveOnly = false } = {}) {
  return rows
    .filter(row => Number.isFinite(row[field] && row[field].chart_value))
    .map(row => ({
      value: [
        Number(row.active_time_seconds || 0),
        positiveOnly && row[field].chart_value <= 0
          ? null
          : row[field].chart_value,
      ],
      row,
      field,
    }));
}

function fishBalanceLineOption(title, series, yAxisName, { logarithmic = false } = {}) {
  const usable = series.filter(item =>
    item.data.some(datum => Number.isFinite(datum.value[1]))
  );
  if (!usable.length) return null;
  return {
    title: {
      text: title,
      subtext: logarithmic ? '同一纵轴比较数量级；仅显示大于 0 的窗口' : '',
      left: 'center',
      textStyle: { fontSize: 15 },
      subtextStyle: { fontSize: 11, color: '#64748b' },
    },
    tooltip: {
      trigger: 'axis',
      formatter: params => params.map(param => {
        const datum = param.data;
        const row = datum.row;
        return [
          `<strong>${escapeHtml(param.seriesName)}</strong>：${numericTooltip(row[datum.field])}`,
          `累计在线：${formatDurationClock(row.active_time_seconds)}（${numericTooltip(row.active_time, '秒')}）`,
        ].join('<br>');
      }).join('<br><br>'),
    },
    legend: { top: 48, type: 'scroll' },
    grid: { left: 92, right: 28, top: 98, bottom: 58 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: {
      type: 'value',
      name: '累计在线时间',
      axisLabel: { formatter: value => formatDurationCompact(value) },
    },
    yAxis: logarithmic
      ? { type: 'log', logBase: 10, name: yAxisName, minorSplitLine: { show: true } }
      : { type: 'value', name: yAxisName, scale: true },
    series: usable,
  };
}

function renderCoreStrengthChart(profiles) {
  const series = [];
  Object.entries(profiles).forEach(([profileId, profile]) => {
    const rows = profile.rows || [];
    [
      ['当前值', 'strength_current', 'solid'],
      ['历史峰值', 'strength_peak', 'dashed'],
    ].forEach(([label, field, lineType]) => {
      series.push({
        name: `${profileLabel(profileId)} · ${label}`,
        type: 'line',
        showSymbol: false,
        lineStyle: { type: lineType },
        data: progressionLineData(rows, field),
      });
    });
  });
  replaceChart('core-strength-chart', progressionLineOption(
    '力量当前值与历史峰值',
    series,
    '力量'
  ));
}

function renderLuckProgressionChart(profiles) {
  const series = [];
  Object.entries(profiles).forEach(([profileId, profile]) => {
    const rows = profile.rows || [];
    [
      ['摸鱼幸运值（当前）', 'fish_luck_current', 'solid'],
      ['摸鱼幸运值（峰值）', 'fish_luck_peak', 'dashed'],
      ['垃圾幸运值（当前）', 'trash_luck_current', 'solid'],
      ['垃圾幸运值（峰值）', 'trash_luck_peak', 'dashed'],
    ].forEach(([label, field, lineType]) => {
      series.push({
        name: `${profileLabel(profileId)} · ${label}`,
        type: 'line',
        showSymbol: false,
        lineStyle: { type: lineType },
        data: progressionLineData(rows, field),
      });
    });
  });
  replaceChart('luck-progression-chart', progressionLineOption(
    '摸鱼幸运值与垃圾幸运值变化曲线',
    series,
    '幸运值'
  ));
}

function progressionLineData(rows, field) {
  return rows
    .filter(row => Number.isFinite(row[field] && row[field].chart_value))
    .map(row => ({
      value: [
        Number(row.active_time_seconds || 0),
        row[field].chart_value,
      ],
      row,
      field,
    }));
}

function progressionLineOption(title, series, yAxisName) {
  const usable = series.filter(item => item.data.length);
  if (!usable.length) return null;
  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: params => params.map(param => {
        const datum = param.data;
        const row = datum.row;
        const marker = row.reset_or_milestone_marker
          ? `<br>标记：${escapeHtml(eventKindLabel(row.reset_or_milestone_marker))}`
          : '';
        return `${escapeHtml(param.seriesName)}：${numericTooltip(row[datum.field])}` +
          `<br>累计在线：${numericTooltip(row.active_time, '秒')}` +
          `<br>模拟时间：${numericTooltip(row.wall_time, '秒')}${marker}`;
      }).join('<br><br>'),
    },
    legend: { top: 28, type: 'scroll' },
    grid: { left: 80, right: 24, top: 76, bottom: 54 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: '累计在线时间（秒）' },
    yAxis: { type: 'value', name: yAxisName, scale: true },
    series: usable,
  };
}

function renderPersistentProgression(persistent) {
  const section = document.querySelector('[data-fish-persistent-section]');
  const profiles = persistent.profiles || {};
  const entries = Object.entries(profiles);
  if (!entries.length) return;
  if (section) section.hidden = false;
  const target = document.querySelector('[data-fish-persistent-kpis]');
  if (target) {
    target.innerHTML = entries.map(([profileId, profile]) => {
      const summary = profile.summary || {};
      return [
        kpiCard(
          `${profileLabel(profileId)} · 永久成长次数`,
          numericMarkup(summary.total_progression_count),
          `<p class="kpi-detail">每在线小时 ${numericInline(summary.events_per_active_hour)} 次</p>`
        ),
        kpiCard(
          `${profileLabel(profileId)} · 最长成长空窗`,
          `<div class="kpi-pair"><div><span>全部成长</span>${numericMarkup(summary.max_interval_seconds, '秒')}</div>` +
            `<div><span>系统成长</span>${numericMarkup(summary.system_progression_max_interval_seconds, '秒')}</div></div>`
        ),
        kpiCard(
          `${profileLabel(profileId)} · 尾部成长空窗`,
          numericMarkup(summary.tail_gap_seconds, '秒')
        ),
        kpiCard(
          `${profileLabel(profileId)} · 无成长在线时段`,
          `<div class="kpi-pair"><div><span>全部成长</span>${numericMarkup(summary.complete_online_sessions_without_progression)}</div>` +
            `<div><span>系统成长</span>${numericMarkup(summary.complete_online_sessions_without_system_progression)}</div></div>`,
          `<p class="kpi-detail">共 ${numericInline(summary.complete_online_sessions)} 个完整在线时段</p>`
        ),
      ].join('');
    }).join('');
  }
  renderDailyProgressionCharts(profiles);
  renderProgressionEventsTable(profiles);
}

function renderDailyProgressionCharts(profiles) {
  const target = document.querySelector('[data-daily-progression-charts]');
  if (!target) return;
  const entries = Object.entries(profiles).flatMap(([profileId, profile]) =>
    (profile.days || []).map(day => ({ profileId, day }))
  );
  if (!entries.length) {
    target.innerHTML = '<div class="empty">没有可展示的在线日。</div>';
    return;
  }
  const categories = [...new Set(entries.flatMap(({ day }) =>
    (day.rows || []).map(row => row.progression_category || 'other')
  ))].sort((left, right) => progressionCategoryRank(left) - progressionCategoryRank(right));
  const categoryLabels = categories.map(progressionCategoryLabel);
  target.innerHTML = entries.map(({ profileId, day }, index) => {
    const count = day.event_count && day.event_count.display_value != null
      ? day.event_count.display_value
      : (day.rows || []).length;
    return [
      '<article class="daily-chart-card">',
      `<h3>第 ${escapeHtml(day.day_index)} 天 · ${escapeHtml(profileLabel(profileId))} · ${escapeHtml(count)} 次有效成长</h3>`,
      `<div id="daily-progression-chart-${index}" class="chart daily-chart"></div>`,
      '</article>',
    ].join('');
  }).join('');
  entries.forEach(({ profileId, day }, index) => {
    const duration = day.duration_seconds && day.duration_seconds.chart_value;
    const rows = day.rows || [];
    const series = categories.map((category, categoryIndex) => ({
      name: progressionCategoryLabel(category),
      type: 'scatter',
      symbolSize: 12,
      itemStyle: { color: progressionCategoryColor(category) },
      data: rows
        .filter(row => (row.progression_category || 'other') === category)
        .map(row => ({
          value: [Number(row.day_active_time_seconds || 0), categoryIndex],
          row,
          profileId,
        })),
    })).filter(item => item.data.length);
    replaceChart(`daily-progression-chart-${index}`, {
      tooltip: {
        trigger: 'item',
        formatter: params => {
          const row = params.data.row;
          return [
            `<strong>${escapeHtml(progressionCategoryLabel(row.progression_category))}</strong>`,
            `当日在线：${formatDurationClock(row.day_active_time_seconds)}`,
            `累计在线：${formatDurationClock(row.active_time_seconds)}`,
            `事件：${escapeHtml(eventKindLabel(row.source_event_kind))} · ${escapeHtml(itemIdentityLabel(row.item_id))}`,
            `指标：${escapeHtml(metricLabel(row.metric_id))}`,
            `变化：${numericTooltip(row.metric_before)} → ${numericTooltip(row.metric_after)}`,
            `距上次有效成长：${numericTooltip(row.gap_from_previous_progression_seconds, '秒')}`,
          ].join('<br>');
        },
      },
      legend: { top: 0, type: 'scroll' },
      grid: { left: 118, right: 24, top: 42, bottom: 48 },
      xAxis: {
        type: 'value',
        name: '当日在线时间',
        min: 0,
        max: Number.isFinite(duration) && duration > 0 ? duration : undefined,
        axisLabel: { formatter: value => formatDurationCompact(value) },
      },
      yAxis: { type: 'category', data: categoryLabels },
      series,
    });
  });
}

function progressionCategoryLabel(category) {
  const labels = {
    best_hall_fish: '摸鱼厅最优鱼',
    barbell: '杠铃',
    fish_hall: '摸鱼厅容量',
    strength_rebirth: '力量转生',
    torpedo: '鱼雷 / 垃圾幸运值',
    trash_man_realm: '垃圾佬境界',
    trash_man_rebirth: '垃圾佬转生',
    permanent_unlock: '永久解锁',
    other: '其他',
  };
  return labels[category] || category || labels.other;
}

function progressionCategoryRank(category) {
  const order = [
    'best_hall_fish',
    'barbell',
    'fish_hall',
    'strength_rebirth',
    'torpedo',
    'trash_man_realm',
    'trash_man_rebirth',
    'permanent_unlock',
    'other',
  ];
  const index = order.indexOf(category);
  return index === -1 ? order.length : index;
}

function progressionCategoryColor(category) {
  const colors = {
    best_hall_fish: '#5470c6',
    barbell: '#91cc75',
    fish_hall: '#fac858',
    strength_rebirth: '#ee6666',
    torpedo: '#73c0de',
    trash_man_realm: '#3ba272',
    trash_man_rebirth: '#fc8452',
    permanent_unlock: '#9a60b4',
    other: '#6b7280',
  };
  return colors[category] || colors.other;
}

function renderProgressionDensityChart(profiles) {
  const series = [];
  Object.entries(profiles).forEach(([profileId, profile]) => {
    const density = profile.density_by_active_hour || [];
    const rows = profile.rows || [];
    series.push({
      name: `${profileLabel(profileId)} · 每小时事件数`,
      type: 'bar',
      yAxisIndex: 0,
      data: density
        .filter(row => Number.isFinite(row.event_count && row.event_count.chart_value))
        .map(row => ({
          value: [
            ((row.active_time_start_seconds.chart_value || 0) +
              (row.active_time_end_seconds.chart_value || 0)) / 2,
            row.event_count.chart_value,
          ],
          row,
          kind: 'density',
        })),
    });
    series.push({
      name: `${profileLabel(profileId)} · 事件变化幅度`,
      type: 'scatter',
      yAxisIndex: 1,
      symbolSize: 9,
      data: rows
        .filter(row => Number.isFinite(row.relative_delta && row.relative_delta.chart_value))
        .map(row => ({
          value: [
            Number(row.active_time_seconds || 0),
            row.relative_delta.chart_value * 100,
          ],
          row,
          kind: 'magnitude',
        })),
    });
  });
  if (!series.some(item => item.data.length)) {
    replaceChart('progression-density-chart', null);
    return;
  }
  replaceChart('progression-density-chart', {
    title: {
      text: '成长触发密度与标准化变化幅度',
      left: 'center',
      textStyle: { fontSize: 14 },
    },
    tooltip: {
      trigger: 'item',
      formatter: params => {
        const datum = params.data;
        const row = datum.row;
        if (datum.kind === 'density') {
          return [
            `<strong>${escapeHtml(params.seriesName)}</strong>`,
            `时间窗：${numericTooltip(row.active_time_start_seconds, '秒')}–${numericTooltip(row.active_time_end_seconds, '秒')}`,
            `事件数：${numericTooltip(row.event_count)}`,
            `平均变化幅度：${numericTooltip(row.average_relative_delta)}`,
          ].join('<br>');
        }
        return [
          `<strong>${escapeHtml(progressionCategoryLabel(row.progression_category))} · ${escapeHtml(itemIdentityLabel(row.item_id))}</strong>`,
          `累计在线：${numericTooltip(row.active_time, '秒')}`,
          `变化：${numericTooltip(row.metric_before)} → ${numericTooltip(row.metric_after)}`,
          `差值：${numericTooltip(row.metric_delta)}`,
          `标准化幅度：${numericTooltip(row.relative_delta)}`,
        ].join('<br>');
      },
    },
    legend: { top: 28, type: 'scroll' },
    grid: { left: 70, right: 80, top: 76, bottom: 54 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: '累计在线时间（秒）' },
    yAxis: [
      { type: 'value', name: '每在线小时事件数', minInterval: 1 },
      { type: 'value', name: '标准化变化幅度（%）', position: 'right' },
    ],
    series,
  });
}

function renderProgressionEventsTable(profiles) {
  const target = document.querySelector('[data-progression-events]');
  if (!target) return;
  const rows = Object.entries(profiles).flatMap(([profileId, profile]) =>
    (profile.rows || []).map(row => ({ ...row, profile_id: profileId }))
  );
  if (!rows.length) {
    target.innerHTML = '<div class="empty">没有发生永久成长事件。</div>';
    return;
  }
  const body = rows.slice(0, 500).map(row => [
    '<tr>',
    `<td>${escapeHtml(profileLabel(row.profile_id))}</td>`,
    `<td>${numericTooltip(row.active_time, '秒')}</td>`,
    `<td>${escapeHtml(progressionCategoryLabel(row.progression_category))}</td>`,
    `<td>${escapeHtml(eventKindLabel(row.source_event_kind))}<br><code>${escapeHtml(itemIdentityLabel(row.item_id))}</code></td>`,
    `<td>${numericTooltip(row.gap_from_previous_progression_seconds, '秒')}</td>`,
    `<td>${numericTooltip(row.metric_before)} → ${numericTooltip(row.metric_after)}</td>`,
    `<td>${numericTooltip(row.metric_delta)}</td>`,
    '</tr>',
  ].join('')).join('');
  const truncated = rows.length > 500
    ? `<p class="section-note">共 ${escapeHtml(rows.length)} 条事件，当前显示前 500 条；完整数据请查看 behavior_progression.csv。</p>`
    : '';
  target.innerHTML = [
    truncated,
    '<table class="data-table">',
    '<thead><tr><th>玩家档案</th><th>累计在线</th><th>类别</th><th>事件</th><th>间隔</th><th>变化前 → 变化后</th><th>差值</th></tr></thead>',
    `<tbody>${body}</tbody>`,
    '</table>',
  ].join('');
}

function numericInline(point, suffix = '') {
  if (!point || typeof point !== 'object') return '—';
  const display = point.display_value == null ? '—' : String(point.display_value);
  const exact = point.exact_value == null ? '' : String(point.exact_value);
  return `<span title="精确值：${escapeHtml(exact)}">${escapeHtml(display)}${escapeHtml(suffix)}</span>`;
}

function renderResourceControls(report) {
  const container = document.querySelector('[data-resource-controls]');
  if (!container) return;
  const ids = report.overview.resource_ids || [];
  if (!ids.length) {
    container.innerHTML = '<div class="empty">没有可展示的资源数据。</div>';
    return;
  }
  container.innerHTML = ids.map((id, index) =>
    `<button type="button" data-resource="${escapeHtml(id)}" class="${index === 0 ? 'active' : ''}">${escapeHtml(resourceLabel(id))}</button>`
  ).join('');
  container.querySelectorAll('[data-resource]').forEach(button => {
    button.addEventListener('click', () => {
      container.querySelectorAll('button').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      renderResourceChart(report, button.dataset.resource);
    });
  });
}

function renderResourceChart(report, resourceId) {
  const rows = (report.series.resources || []).filter(row => row.resource_id === resourceId);
  const option = lineOption(`资源：${resourceId ? resourceLabel(resourceId) : '无'}`, rows, '资源数量');
  replaceChart('resource-chart', option);
}

function renderCpsChart(report) {
  const rows = report.series.total_cps || [];
  const option = lineOption('总产出速率', rows, '每秒产出');
  replaceChart('cps-chart', option);
}

function renderEventChart(report) {
  const events = report.series.events || [];
  if (!events.length) {
    replaceChart('event-chart', null);
    return;
  }
  const profiles = report.scenario.profiles || [];
  const kinds = [...new Set(events.map(event => event.kind || 'event'))].sort();
  const series = kinds.map(kind => ({
    name: eventKindLabel(kind),
    type: 'scatter',
    symbolSize: 10,
    data: events
      .filter(event => (event.kind || 'event') === kind)
      .map(event => ({
        value: [Number(event.time_seconds || 0), profiles.indexOf(event.profile_id)],
        event,
      })),
  }));
  replaceChart('event-chart', {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        const event = params.data.event;
        return [
          `<strong>${escapeHtml(eventKindLabel(event.kind))}</strong>`,
          `玩家档案：${escapeHtml(profileLabel(event.profile_id))}`,
          `时间：${numericTooltip(event.time, '秒')}`,
          `内容项：${escapeHtml(itemIdentityLabel(event.item_id || ''))}`,
        ].join('<br>');
      },
    },
    legend: { top: 0 },
    grid: { left: 90, right: 24, top: 48, bottom: 48 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: '时间（秒）' },
    yAxis: { type: 'category', data: profiles.map(profileLabel) },
    series,
  });
}

function renderPaybackChart(report) {
  const rows = (report.diagnostics.payback || [])
    .filter(row => Number.isFinite(row.payback_seconds && row.payback_seconds.chart_value))
    .sort((a, b) => b.payback_seconds.chart_value - a.payback_seconds.chart_value)
    .slice(0, 25);
  if (!rows.length) {
    replaceChart('payback-chart', null);
    return;
  }
  replaceChart('payback-chart', {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        const row = params.data.row;
        return [
          `<strong>${escapeHtml(profileLabel(row.profile_id))} · ${escapeHtml(contentKindLabel(row.kind))}：${escapeHtml(itemIdentityLabel(row.item_id))}</strong>`,
          `回本周期：${numericTooltip(row.payback_seconds, '秒')}`,
          `成本：${numericTooltip(row.cost)}`,
          `每秒产出增量：${numericTooltip(row.delta_cps)}`,
          `数据来源：${escapeHtml(row.source_ref || '')}`,
        ].join('<br>');
      },
    },
    grid: { left: 170, right: 24, top: 24, bottom: 40 },
    xAxis: { type: 'value', name: '回本时间（秒）' },
    yAxis: {
      type: 'category',
      data: rows.map(row => `${profileLabel(row.profile_id)} ${contentKindLabel(row.kind)}：${itemIdentityLabel(row.item_id)}`),
      inverse: true,
    },
    series: [{
      type: 'bar',
      data: rows.map(row => ({ value: row.payback_seconds.chart_value, row })),
    }],
  });
}

function lineOption(title, rows, valueName) {
  const plottable = finiteRows(rows);
  if (!plottable.length) return null;
  const profiles = [...new Set(plottable.map(row => row.profile_id))].sort();
  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: params => params.map(param => {
        const row = param.data.row;
        return [
          `${escapeHtml(profileLabel(param.seriesName))}：${numericTooltip(row)}`,
          `时间：${numericTooltip(row.time, '秒')}`,
        ].join('<br>');
      }).join('<br>'),
    },
    legend: { top: 28 },
    grid: { left: 70, right: 24, top: 72, bottom: 54 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: '时间（秒）' },
    yAxis: { type: 'value', name: valueName },
    series: profiles.map(profile => ({
      name: profileLabel(profile),
      type: 'line',
      showSymbol: false,
      data: plottable
        .filter(row => row.profile_id === profile)
        .map(row => ({
          value: [Number(row.time_seconds || 0), row.chart_value],
          row,
        })),
    })),
  };
}

function renderDiagnostics(report) {
  const target = document.querySelector('[data-diagnostics]');
  if (!target) return;
  const diagnostics = report.diagnostics || {};
  const invalid = diagnostics.invalid_content || {};
  const bottleneckGapCounts = diagnostics.bottleneck_gap_counts || {};
  const infinitePaybacks = (diagnostics.payback || [])
    .filter(row => row.payback_seconds && row.payback_seconds.exact_value === 'Infinity')
    .slice(0, 10);
  target.innerHTML = [
    diagnosticBlock('从未购买', (invalid.never_purchased || []).map(itemIdentityLabel)),
    diagnosticBlock('从未解锁', (invalid.never_unlocked || []).map(itemIdentityLabel)),
    diagnosticBlock(
      '强度异常内容',
      (diagnostics.overpowered_content || []).map(row => itemIdentityLabel(row.item_id))
    ),
    diagnosticHtmlBlock('成长瓶颈', Object.entries(bottleneckGapCounts).map(([profile, count]) =>
      `${escapeHtml(profileLabel(profile))}：${numericTooltip(count)} 个空窗`
    )),
    diagnosticBlock(
      '无法回本',
      infinitePaybacks.map(row =>
        `${profileLabel(row.profile_id)} ${contentKindLabel(row.kind)}：${itemIdentityLabel(row.item_id)}`
      )
    ),
  ].join('');
}

function diagnosticBlock(title, values) {
  const body = values.length
    ? `<ul>${values.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ul>`
    : '<p>无</p>';
  return `<div class="metric"><strong>${escapeHtml(title)}</strong>${body}</div>`;
}

function diagnosticHtmlBlock(title, safeRows) {
  const body = safeRows.length
    ? `<ul>${safeRows.map(row => `<li>${row}</li>`).join('')}</ul>`
    : '<p>无</p>';
  return `<div class="metric"><strong>${escapeHtml(title)}</strong>${body}</div>`;
}

function renderEvidence(report) {
  const target = document.querySelector('[data-evidence]');
  if (!target) return;
  const evidence = report.evidence || {};
  const traces = evidence.traces || [];
  const refs = evidence.source_refs || [];
  if (!traces.length && !refs.length) {
    target.innerHTML = '<div class="empty">没有可展示的分析依据。</div>';
    return;
  }
  const traceRows = traces.map(trace => [
    escapeHtml(profileLabel(trace.profile_id || '')),
    numericTooltip(trace.time, '秒'),
    `${escapeHtml(eventKindLabel(trace.kind || ''))}：${escapeHtml(itemIdentityLabel(trace.item_id || ''))}`,
    `<code>${escapeHtml(trace.formula_trace || '')}</code>`,
  ].join(' '));
  const referenceRows = refs.map(ref => [
    escapeHtml(profileLabel(ref.profile_id || '')),
    `${escapeHtml(contentKindLabel(ref.kind || ''))}：${escapeHtml(itemIdentityLabel(ref.item_id || ''))}`,
    `<code>${escapeHtml(ref.source_ref || '')}</code>`,
  ].join(' '));
  target.innerHTML = [
    evidenceHtmlDetails('公式计算过程', traceRows),
    evidenceHtmlDetails('数据来源', referenceRows),
  ].join('');
}

function evidenceHtmlDetails(title, safeRows) {
  if (!safeRows.length) return '';
  return `<details open><summary>${escapeHtml(title)}</summary><ul>${safeRows
    .slice(0, 100)
    .map(row => `<li>${row}</li>`)
    .join('')}</ul></details>`;
}

function scenarioLabel(scenarioId) {
  const labels = {
    smoke: '冒烟验证',
    analytic_smoke: '解析式冒烟验证',
    day_1_progression: '首日成长',
    day_1_growth: '首日成长',
    week_1_growth: '首周成长',
    month_1_growth: '首月成长',
  };
  return labels[scenarioId] || scenarioId || '';
}

function profileLabel(profileId) {
  const labels = {
    default: '默认玩家',
    casual: '休闲玩家',
    explorer: '探索型玩家',
    optimizer: '效率型玩家',
    paid_20pct: '付费二成玩家',
  };
  return labels[profileId] || profileId || '';
}

function resourceLabel(resourceId) {
  const labels = {
    gold: '金币',
    money: '金钱',
    material: '材料',
    strength: '力量',
    shell: '贝壳',
    shells: '贝壳',
    prestige_point: '转生点',
    prestige_points: '转生点',
  };
  return labels[resourceId] || resourceId || '';
}

function contentKindLabel(kind) {
  const labels = {
    activity: '活动',
    generator: '生产器',
    upgrade: '升级',
    milestone: '里程碑',
    prestige: '转生',
  };
  return labels[kind] || eventKindLabel(kind);
}

function itemIdentityLabel(itemId) {
  const text = String(itemId || '');
  const match = text.match(/^([a-z][a-z0-9_]*):(.*)$/);
  if (!match) return text;
  const labels = {
    activity: '活动',
    generator: '生产器',
    upgrade: '升级',
    prestige: '转生',
    fish: '鱼',
    throw: '投掷',
    fish_hall: '摸鱼厅',
    fish_hall_upgrade: '摸鱼厅升级',
    barbell: '杠铃',
    torpedo: '鱼雷',
    strength_rebirth: '力量转生',
    trash_man_rebirth: '垃圾佬转生',
    trash_man_realm: '垃圾佬境界',
  };
  const prefix = labels[match[1]] || match[1];
  return `${prefix}：${match[2]}`;
}

function eventKindLabel(kind) {
  const labels = {
    event: '事件',
    buy_generator: '购买生产器',
    buy_upgrade: '购买升级',
    unlock_activity: '解锁活动',
    unlock_generator: '解锁生产器',
    unlock_upgrade: '解锁升级',
    prestige_reset: '转生重置',
    fish_engine_ready: '摸鱼模拟就绪',
    fish_throw_resolved: '摸鱼投掷结算',
    fish_upgraded: '鱼升级',
    fish_hall_upgraded: '摸鱼厅升级',
    fish_offline_settled: '离线收益结算',
    fish_session_online_started: '在线时段开始',
    fish_session_offline_started: '离线时段开始',
    fish_behavior_started: '摸鱼行为开始',
    fish_behavior_idle_completed: '摸鱼空闲行为完成',
    fish_system_unlocked: '系统永久解锁',
    fish_ability_unlocked: '能力永久解锁',
    fish_strategy_unlocked: '策略永久解锁',
    torpedo_purchased: '购买鱼雷',
    torpedo_upgraded: '鱼雷升级',
    barbell_synthesized: '合成杠铃',
    barbell_exercise_completed: '完成杠铃锻炼',
    strength_reborn: '力量转生',
    trash_man_reborn: '垃圾佬转生',
    trash_man_breakthrough_funded: '垃圾佬突破筹资完成',
    trash_man_realm_broken_through: '垃圾佬境界突破',
  };
  return labels[kind] || kind || '';
}

function metricLabel(metricId) {
  const labels = {
    fish_hall_cps: '摸鱼厅每秒产出',
    barbell_strength_per_second: '杠铃每秒力量',
    fish_hall_level: '摸鱼厅等级',
    material_output_multiplier: '材料产出倍率',
    fish_hall_output_multiplier: '摸鱼厅产出倍率',
    trash_luck: '垃圾幸运值',
    trash_man_realm_id: '垃圾佬境界',
    unlock_state: '解锁状态',
  };
  return labels[metricId] || metricId || '';
}

function firstResource(report) {
  return (report.overview.resource_ids || [])[0] || null;
}

function finiteRows(rows) {
  return rows.filter(row => Number.isFinite(row.chart_value));
}

function numericText(point) {
  return point && point.display_value != null ? String(point.display_value) : '';
}

function numericTooltip(point, suffix = '') {
  if (!point || typeof point !== 'object') return '';
  const display = numericText(point);
  const exact = point.exact_value == null ? '' : String(point.exact_value);
  return `<span title="精确值：${escapeHtml(exact)}">${escapeHtml(display)}${escapeHtml(suffix)}</span>`;
}

function formatDurationCompact(value) {
  const seconds = Math.max(0, Number(value) || 0);
  if (seconds >= 3600) {
    const hours = seconds / 3600;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}小时`;
  }
  if (seconds >= 60) return `${Math.round(seconds / 60)}分`;
  return `${Math.round(seconds)}秒`;
}

function formatDurationClock(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return [hours, minutes, seconds]
    .map(part => String(part).padStart(2, '0'))
    .join(':');
}

function replaceChart(id, option) {
  const element = document.getElementById(id);
  if (!element) return null;
  const existing = charts.find(item => item.id === id);
  if (existing) {
    existing.chart.dispose();
    charts.splice(charts.indexOf(existing), 1);
  }
  const chart = mountChart(id, option);
  return chart;
}

function mountChart(id, option) {
  const element = document.getElementById(id);
  if (!element) return null;
  if (!option || typeof echarts === 'undefined') {
    element.innerHTML = '<div class="empty">没有可展示的数据。</div>';
    return null;
  }
  const chart = echarts.init(element);
  chart.setOption(option);
  charts.push({ id, chart });
  return chart;
}

function resizeCharts() {
  charts.forEach(item => item.chart.resize());
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
