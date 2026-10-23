// Findings of one snapshot (?snapshot=<id>[&rule_id=]): summary, filters, paging, CSV, and Exclude / Override into a
// new draft request for the same NBFC, date and type.
document.addEventListener("alpine:init", () => {
  Alpine.data("findingsPage", () => ({
    snapshot: F.param("snapshot"),
    data: null,
    flt: { rule_id: F.param("rule_id") || "", outcome: "", account_key: "", party_key: "" },
    page: 1,
    busy: false,

    init() { this.load(); },

    async load() {
      try {
        this.data = await Api.get(`/snapshots/${encodeURIComponent(this.snapshot)}/findings`, { ...this.flt, page: this.page });
      } catch (e) { App.error(e); }
    },

    ruleIds() { return [...new Set(this.data.summary.map((s) => s.rule_id))]; },
    canAdjust() { return this.data.snapshot.status === "VALIDATED"; },

    async run(fn) {
      this.busy = true;
      try { return await fn(); } catch (e) { App.error(e); return null; } finally { this.busy = false; }
    },

    async exclude(f) {
      const data = await this.run(() => Api.post(`/snapshots/${this.snapshot}/exclude`, { account_key: f.account_key }));
      if (data) App.flash(data.message);
    },

    async override(f) {
      const field = this.data.overridable.includes(f.field) ? f.field : null;
      const data = await this.run(() => Api.post(`/snapshots/${this.snapshot}/override`, { account_key: f.account_key, field }));
      if (data) location.href = F.url("exceptions.html", { batch: data.batch_id, type: data.type, account: data.account,
                                                          field: data.field });
    },

    csv() { return this.run(() => Api.download(`/snapshots/${this.snapshot}/findings.csv`, this.flt)); },
  }));
});
