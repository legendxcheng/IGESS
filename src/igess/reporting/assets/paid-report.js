(() => {
  "use strict";
  const { lanes, titles } = JSON.parse(document.getElementById("paid-data").textContent);
  const selector = document.getElementById("scenario");
  const charts = Object.fromEntries(Object.keys(titles).map((key, index) => [
    key, echarts.init(document.getElementById(`paid-chart-${index}`)),
  ]));

  function draw() {
    for (const [key, chart] of Object.entries(charts)) {
      chart.setOption({
        title: { text: titles[key], textStyle: { fontSize: 15 } },
        tooltip: {
          trigger: "axis",
          renderMode: "richText",
          formatter: points => points.map(point => `${point.seriesName}: ${point.data.raw}`).join("\n"),
        },
        legend: { top: 25 },
        grid: { top: 70, bottom: 30, left: 50, right: 20 },
        xAxis: { type: "value" },
        yAxis: { type: "value" },
        series: lanes.filter(lane => lane.scenario === selector.value).map(lane => ({
          name: lane.plan,
          type: "line",
          showSymbol: false,
          data: lane.curves.filter(point => point.values[key]).map(point => ({
            value: [point.x, point.values[key].y],
            raw: point.values[key].raw,
          })),
        })),
      }, true);
    }
  }
  selector.addEventListener("change", draw);
  window.addEventListener("resize", () => Object.values(charts).forEach(chart => chart.resize()));
  draw();
})();
