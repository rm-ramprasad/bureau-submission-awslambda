// New request: always a validation, created as a draft; then straight to its exceptions step.
document.addEventListener("alpine:init", () => {
  Alpine.data("newRequest", () => ({
    form: { tenant_id: "", as_of_date: "", reporting_cycle: "ME", submission_types: ["CONSUMER"] },
    busy: false,

    init() {
      this.form.tenant_id = this.$store.app.tenant;
      const defaults = (meta) => { if (meta && !this.form.as_of_date) this.form.as_of_date = meta.default_as_of; };
      defaults(this.$store.app.meta);
      this.$watch("$store.app.meta", defaults);
    },

    async create() {
      this.busy = true;
      try {
        const data = await Api.post("/requests", this.form);
        if (this.form.tenant_id !== this.$store.app.tenant) App.setTenant(this.form.tenant_id);   // follow its NBFC
        App.go(`exceptions.html?batch=${encodeURIComponent(data.batch_id)}`, data.message);
      } catch (e) {
        App.error(e);
      } finally {
        this.busy = false;
      }
    },
  }));
});
