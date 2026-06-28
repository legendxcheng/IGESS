(async function () {
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
})();

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
          `Time: ${escapeHtml(event.time_seconds)}s`,
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
  const rows = finiteRows(report.diagnostics.payback || [])
    .sort((a, b) => b.chart_value - a.chart_value)
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
          `Payback: ${escapeHtml(row.display_value)}s`,
          `Cost: ${escapeHtml(row.cost || '')}`,
          `Delta CPS: ${escapeHtml(row.delta_cps || '')}`,
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
      data: rows.map(row => ({ value: row.chart_value, row })),
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
        return `${escapeHtml(param.seriesName)}: ${escapeHtml(row.display_value)}`;
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
  const bottlenecks = diagnostics.bottlenecks || {};
  const infinitePaybacks = (diagnostics.payback || [])
    .filter(row => row.chart_value === null)
    .slice(0, 10);
  target.innerHTML = [
    diagnosticBlock('Never purchased', invalid.never_purchased || []),
    diagnosticBlock('Never unlocked', invalid.never_unlocked || []),
    diagnosticBlock('Overpowered', (diagnostics.overpowered_content || []).map(row => row.item_id)),
    diagnosticBlock('Bottlenecks', Object.entries(bottlenecks).map(([profile, gaps]) => `${profile}: ${gaps.length} gaps`)),
    diagnosticBlock('Infinite payback', infinitePaybacks.map(row => `${row.profile_id} ${row.kind}:${row.item_id}`)),
  ].join('');
}

function diagnosticBlock(title, values) {
  const body = values.length
    ? `<ul>${values.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ul>`
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
  target.innerHTML = [
    evidenceDetails('Formula traces', traces.map(trace =>
      `${trace.profile_id || ''} ${trace.time_seconds || ''} ${trace.kind || ''}:${trace.item_id || ''} ${trace.formula_trace || ''}`
    )),
    evidenceDetails('Source references', refs.map(ref =>
      `${ref.profile_id || ''} ${ref.kind || ''}:${ref.item_id || ''} ${ref.source_ref || ''}`
    )),
  ].join('');
}

function evidenceDetails(title, rows) {
  if (!rows.length) return '';
  return `<details open><summary>${escapeHtml(title)}</summary><ul>${rows
    .slice(0, 100)
    .map(row => `<li><code>${escapeHtml(row)}</code></li>`)
    .join('')}</ul></details>`;
}

function firstResource(report) {
  return (report.overview.resource_ids || [])[0] || null;
}

function finiteRows(rows) {
  return rows.filter(row => Number.isFinite(row.chart_value));
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
