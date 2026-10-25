// Dashboard: one submission type at a time (?type=, record counts of types do not add up), request-stage KPIs, data
// KPIs, needs attention, bureaus, NBFC status, recent requests (period filter). The type switch shows how many
// items need attention in each type, so another type's problems stay visible.
const RECORD_UNIT = { CONSUMER: "account × holder", COMMERCIAL: "facility × borrower" };

document.addEventListener("alpine:init", () => {
  Alpine.data("dashboard", () => ({
    board: null,
    type: F.param("type") || "",
    period: F.param("period") || "month",
    periods: [{ value: "month", label: "This month" }, { value: "30d", label: "Last 30 days" },
              { value: "90d", label: "Last 90 days" }, { value: "all", label: "All time" }],

    init() { this.load(); },

    async load() {
      try {
        this.board = await Api.get("/dashboard", { period: this.period, type: this.type });
        this.period = this.board.period;
        this.type = this.board.type;
        history.replaceState(null, "", F.url("index.html", { type: this.type, period: this.period }));
      } catch (e) { App.error(e); }
    },

    periodLabel() { return (this.periods.find((p) => p.value === this.period) || this.periods[0]).label; },
    typeLabel() { return F.title(this.type); },
    tracker(stage) { return F.url("tracker.html", { stage, period: this.period, type: this.type }); },
    queueSlow() { return !!this.$store.app.health?.slow; },
    commercial() { return this.type === "COMMERCIAL"; },
    recordUnit() { return RECORD_UNIT[this.type] || "record"; },

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
