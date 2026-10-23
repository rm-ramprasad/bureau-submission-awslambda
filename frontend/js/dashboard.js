// Dashboard: request-stage KPIs, data KPIs, needs attention, bureaus, NBFC status, recent requests (period filter).
document.addEventListener("alpine:init", () => {
  Alpine.data("dashboard", () => ({
    board: null,
    period: F.param("period") || "month",
    periods: [{ value: "month", label: "This month" }, { value: "30d", label: "Last 30 days" },
              { value: "90d", label: "Last 90 days" }, { value: "all", label: "All time" }],

    init() { this.load(); },

    async load() {
      try {
        this.board = await Api.get("/dashboard", { period: this.period });
        this.period = this.board.period;
      } catch (e) { App.error(e); }
    },

    periodLabel() { return (this.periods.find((p) => p.value === this.period) || this.periods[0]).label; },
    tracker(stage) { return F.url("tracker.html", { stage, period: this.period }); },
    queueSlow() { return !!this.$store.app.health?.slow; },

    stageHint(st) {
      const oldest = st.count ? "oldest " + F.age(st.oldest_age) : null;
      return {
        AWAITING_EXCEPTIONS: oldest || "none waiting",
        IN_PROGRESS: oldest || "nothing running",
        VALIDATED: oldest || "none pending",
        COMPLETED: F.pct(this.board.completion_rate) + " completion rate",
        FAILED: st.count ? "retry or raise a new request" : "none",
        CANCELLED: "discarded or cancelled",
      }[st.value];
    },
  }));
});
