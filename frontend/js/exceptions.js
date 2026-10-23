// Exceptions: the drafts waiting for exceptions, or one request's step 2 (?batch=<id>[&type=&account=&field=]).
const KINDS = { EXCLUDE_ACCOUNT: "Exclude loan", EXCLUDE_CUSTOMER: "Exclude customer", OVERRIDE: "Override" };
const STATUS = {
  WILL_APPLY: ["Will apply", "b-DRAFT"], WAITING: ["Waiting for validation", "b-PENDING"],
  APPLIED: ["Applied", "b-SUCCEEDED"], NOT_FOUND: ["Not found", "b-WARN"], REMOVED: ["Removed", "b-CANCELLED"],
};

document.addEventListener("alpine:init", () => {
  Alpine.data("exceptionsPage", () => ({
    batchId: F.param("batch"),
    type: F.param("type"),
    drafts: null,
    page: null,
    history: false,
    busy: false,
    ex: { kind: "account", keys: "", reason: "" },
    ov: { account_number: F.param("account") || "", field: F.param("field") || "days_past_due", value: "", reason: "" },

    init() {
      this.load().then(() => { if (this.ov.account_number) this.$nextTick(() => this.$refs.value?.focus()); });
    },

    async load() {
      try {
        if (!this.batchId) {
          this.drafts = (await Api.get("/exceptions")).drafts;
          return;
        }
        this.page = await Api.get(`/batches/${encodeURIComponent(this.batchId)}/exceptions`,
                                  { type: this.type, history: this.history ? 1 : "" });
        this.type = this.page.row.submission_type;
      } catch (e) { App.error(e); }
    },

    async act(path, body = {}, leaving = false) {
      this.busy = true;
      try {
        const data = await Api.post(`/batches/${encodeURIComponent(this.batchId)}${path}`, { type: this.type, ...body });
        if (leaving) return data;
        App.flash(data.message);
        await this.load();
        return data;
      } catch (e) {
        App.error(e);
        return null;
      } finally {
        this.busy = false;
      }
    },

    async exclude() {
      if (await this.act("/exceptions/exclude", this.ex)) this.ex = { ...this.ex, keys: "", reason: "" };
    },

    async override() {
      if (await this.act("/exceptions/override", this.ov)) this.ov = { ...this.ov, account_number: "", value: "", reason: "" };
    },

    remove(a) { return this.act(`/exceptions/${a.adjustment_id}/remove`); },

    async submit() {
      const data = await this.act("/submit", {}, true);
      if (data) App.go(`batch.html?id=${encodeURIComponent(this.batchId)}`, data.message);
    },

    async discard() {
      if (!confirm("Discard this draft request? Its exceptions stay in the history.")) return;
      const data = await this.act("/discard", {}, true);
      if (data) App.go("exceptions.html", data.message);
    },
  }));
});
