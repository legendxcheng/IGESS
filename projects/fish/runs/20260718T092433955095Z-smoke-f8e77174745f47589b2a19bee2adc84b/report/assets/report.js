async function bootstrapReport() {
  const report = await loadReport();
  renderOverview(report);
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
    scenario.textContent = report.scenario.id;
  }
  const container = document.querySelector('[data-overview-kpis]');
  if (!container) return;
  const overview = report.overview || {};
  const firstUnlock = overview.first_key_unlock;
  const worstPayback = overview.worst_payback;
  const profiles = overview.profiles || [];
  container.innerHTML = [
    kpiCard('Duration', numericMarkup(overview.duration_seconds, 's')),
    kpiCard('Profiles', `<span class="kpi-value">${escapeHtml(profiles.join(', ') || 'None')}</span>`),
    kpiCard('Purchases', numericMarkup(overview.purchase_count)),
    kpiCard(
      'First key unlock',
      firstUnlock ? numericMarkup(firstUnlock.time_seconds, 's') : '<span class="kpi-value">None</span>',
      firstUnlock ? identityMarkup(firstUnlock) : ''
    ),
    kpiCard('Prestige resets', numericMarkup(overview.prestige_reset_count)),
    kpiCard(
      'Worst payback',
      worstPayback ? numericMarkup(worstPayback.payback_seconds, 's') : '<span class="kpi-value">None</span>',
      worstPayback ? identityMarkup(worstPayback) : ''
    ),
    kpiCard(
      'Never reached',
      `<div class="kpi-pair"><div><span>Purchased</span>${numericMarkup(overview.never_purchased_count)}</div>` +
        `<div><span>Unlocked</span>${numericMarkup(overview.never_unlocked_count)}</div></div>`
    ),
    kpiCard('Warning categories', numericMarkup(overview.warning_category_count)),
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
  const exactTitle = exact ? ` title="Exact value: ${escapeHtml(exact)}"` : '';
  const exactDetails = exact
    ? `<details class="exact-value"><summary>Exact</summary><code>${escapeHtml(exact)}</code></details>`
    : '';
  return `<span class="kpi-value" data-exact-value="${escapeHtml(exact)}"${exactTitle}>` +
    `${escapeHtml(display)}${escapeHtml(suffix)}</span>${exactDetails}`;
}

function identityMarkup(row) {
  const identity = `${row.profile_id || ''} ${row.kind || ''}:${row.item_id || ''}`.trim();
  return identity ? `<p class="kpi-detail">${escapeHtml(identity)}</p>` : '';
}

function finalResourcesCard(finalResources) {
  const profiles = Object.entries(finalResources);
  if (!profiles.length) {
    return kpiCard('Final resources', '<span class="kpi-value">None</span>');
  }
  const displayRows = profiles.flatMap(([profileId, resources]) =>
    Object.entries(resources || {}).map(([resourceId, point]) =>
      `<li><strong>${escapeHtml(profileId)}</strong> · ${escapeHtml(resourceId)}: ${numericMarkup(point)}</li>`
    )
  );
  const exactRows = profiles.flatMap(([profileId, resources]) =>
    Object.entries(resources || {}).map(([resourceId, point]) =>
      `<li><strong>${escapeHtml(profileId)}</strong> · ${escapeHtml(resourceId)}: ` +
        `<code>${escapeHtml(point && point.exact_value != null ? point.exact_value : '')}</code></li>`
    )
  );
  return kpiCard(
    'Final resources',
    `<ul class="kpi-resources">${displayRows.join('')}</ul>`,
    `<details class="exact-values"><summary>Exact values</summary><ul>${exactRows.join('')}</ul></details>`
  );
}

function renderResourceControls(report) {
  const container = document.querySelector('[data-resource-controls]');
  if (!container) return;
  const ids = report.overview.resource_ids || [];
  if (!ids.length) {
    container.innerHTML = '<div class="empty">No resource data available.</div>';
    return;
  }
  container.innerHTML = ids.map((id, index) =>
    `<button type="button" data-resource="${escapeHtml(id)}" class="${index === 0 ? 'active' : ''}">${escapeHtml(id)}</button>`
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
  const option = lineOption(`Resource: ${resourceId || 'none'}`, rows, 'Resource');
  replaceChart('resource-chart', option);
}

function renderCpsChart(report) {
  const rows = report.series.total_cps || [];
  const option = lineOption('Total CPS', rows, 'CPS');
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
    name: kind,
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
          `<strong>${escapeHtml(event.kind)}</strong>`,
          `Profile: ${escapeHtml(event.profile_id)}`,
          `Time: ${numericTooltip(event.time, 's')}`,
          `Item: ${escapeHtml(event.item_id || '')}`,
        ].join('<br>');
      },
    },
    legend: { top: 0 },
    grid: { left: 90, right: 24, top: 48, bottom: 48 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: 'seconds' },
    yAxis: { type: 'category', data: profiles },
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
          `<strong>${escapeHtml(row.profile_id)} ${escapeHtml(row.kind)}:${escapeHtml(row.item_id)}</strong>`,
          `Payback: ${numericTooltip(row.payback_seconds, 's')}`,
          `Cost: ${numericTooltip(row.cost)}`,
          `Delta CPS: ${numericTooltip(row.delta_cps)}`,
          `Source: ${escapeHtml(row.source_ref || '')}`,
        ].join('<br>');
      },
    },
    grid: { left: 170, right: 24, top: 24, bottom: 40 },
    xAxis: { type: 'value', name: 'seconds' },
    yAxis: {
      type: 'category',
      data: rows.map(row => `${row.profile_id} ${row.kind}:${row.item_id}`),
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
          `${escapeHtml(param.seriesName)}: ${numericTooltip(row)}`,
          `Time: ${numericTooltip(row.time, 's')}`,
        ].join('<br>');
      }).join('<br>'),
    },
    legend: { top: 28 },
    grid: { left: 70, right: 24, top: 72, bottom: 54 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'value', name: 'seconds' },
    yAxis: { type: 'value', name: valueName },
    series: profiles.map(profile => ({
      name: profile,
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
    diagnosticBlock('Never purchased', invalid.never_purchased || []),
    diagnosticBlock('Never unlocked', invalid.never_unlocked || []),
    diagnosticBlock('Overpowered', (diagnostics.overpowered_content || []).map(row => row.item_id)),
    diagnosticHtmlBlock('Bottlenecks', Object.entries(bottleneckGapCounts).map(([profile, count]) =>
      `${escapeHtml(profile)}: ${numericTooltip(count)} gaps`
    )),
    diagnosticBlock('Infinite payback', infinitePaybacks.map(row => `${row.profile_id} ${row.kind}:${row.item_id}`)),
  ].join('');
}

function diagnosticBlock(title, values) {
  const body = values.length
    ? `<ul>${values.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ul>`
    : '<p>None</p>';
  return `<div class="metric"><strong>${escapeHtml(title)}</strong>${body}</div>`;
}

function diagnosticHtmlBlock(title, safeRows) {
  const body = safeRows.length
    ? `<ul>${safeRows.map(row => `<li>${row}</li>`).join('')}</ul>`
    : '<p>None</p>';
  return `<div class="metric"><strong>${escapeHtml(title)}</strong>${body}</div>`;
}

function renderEvidence(report) {
  const target = document.querySelector('[data-evidence]');
  if (!target) return;
  const evidence = report.evidence || {};
  const traces = evidence.traces || [];
  const refs = evidence.source_refs || [];
  if (!traces.length && !refs.length) {
    target.innerHTML = '<div class="empty">No trace evidence available.</div>';
    return;
  }
  const traceRows = traces.map(trace => [
    escapeHtml(trace.profile_id || ''),
    numericTooltip(trace.time, 's'),
    `${escapeHtml(trace.kind || '')}:${escapeHtml(trace.item_id || '')}`,
    `<code>${escapeHtml(trace.formula_trace || '')}</code>`,
  ].join(' '));
  const referenceRows = refs.map(ref => [
    escapeHtml(ref.profile_id || ''),
    `${escapeHtml(ref.kind || '')}:${escapeHtml(ref.item_id || '')}`,
    `<code>${escapeHtml(ref.source_ref || '')}</code>`,
  ].join(' '));
  target.innerHTML = [
    evidenceHtmlDetails('Formula traces', traceRows),
    evidenceHtmlDetails('Source references', referenceRows),
  ].join('');
}

function evidenceHtmlDetails(title, safeRows) {
  if (!safeRows.length) return '';
  return `<details open><summary>${escapeHtml(title)}</summary><ul>${safeRows
    .slice(0, 100)
    .map(row => `<li>${row}</li>`)
    .join('')}</ul></details>`;
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
  return `<span title="Exact value: ${escapeHtml(exact)}">${escapeHtml(display)}${escapeHtml(suffix)}</span>`;
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
    element.innerHTML = '<div class="empty">No data available.</div>';
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
