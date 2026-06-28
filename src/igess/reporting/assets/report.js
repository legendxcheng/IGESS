(async function () {
  const inline = document.getElementById('igess-report-data');
  const report = inline ? JSON.parse(inline.textContent) : await fetchReport();
  document.querySelector('[data-scenario]').textContent = report.scenario.id;
})();

async function fetchReport() {
  const root = document.querySelector('[data-report-src]');
  const src = root ? root.dataset.reportSrc : 'report_data.json';
  const response = await fetch(src);
  return await response.json();
}
