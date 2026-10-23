// Submission tracker: all runs (filters, paging), or requests by stage (?stage=&period=, from the dashboard).
document.addEventListener("alpine:init", () => {
  Alpine.data("tracker", () => ({
    view: F.param("stage") || F.param("period") ? "requests" : "runs",
    stage: F.param("stage") || "",
    period: F.param("period") || "month",
    flt: { status: "", mode: "", bureau: "", from: "", to: "" },
    page: 1,
    runs: null,
    requests: null,

    init() { this.load(); },

    filtered() { return Object.values(this.flt).some(Boolean); },
    stageLabel() { return (this.$store.app.meta?.stages || []).find((s) => s.value === this.stage)?.label || ""; },

    showRuns() { this.view = "runs"; history.replaceState(null, "", "tracker.html"); this.load(); },
    showRequests() { this.view = "requests"; this.period = this.period || "all"; this.load(); },

    async load() {
      try {
        if (this.view === "runs") {
          this.runs = await Api.get("/batches", { ...this.flt, page: this.page });
        } else {
          history.replaceState(null, "", F.url("tracker.html", { stage: this.stage, period: this.period }));
          this.requests = (await Api.get("/batches", { stage: this.stage, period: this.period })).requests;
        }
      } catch (e) { App.error(e); }
    },
  }));
});
