// One request (batch): rows and statuses, snapshots and findings summary, adjustments, generate files, downloads.
// Refreshes every 5 s while a row is pending or running.
document.addEventListener("alpine:init", () => {
  Alpine.data("batchPage", () => ({
    id: F.param("id"),
    b: null,
    busy: false,
    chosen: {},          // request_id -> bureaus ticked for generation
    confirm: {},         // request_id -> adjustments confirmed
    timer: null,

    init() { this.load(); },

    async load() {
      clearTimeout(this.timer);
      try {
        this.b = await Api.get(`/batches/${encodeURIComponent(this.id)}`);
        for (const g of this.b.generate_from) if (!(g.request_id in this.chosen)) this.chosen[g.request_id] = [...g.bureaus];
        if (this.b.active) this.timer = setTimeout(() => this.load(), 5000);
      } catch (e) { App.error(e); }
    },

    adjusted(g) { return this.b.snapshots.find((s) => s.snapshot.snapshot_id === g.snapshot_id).adjusted; },

    async run(fn) {
      this.busy = true;
      try { return await fn(); } catch (e) { App.error(e); return null; } finally { this.busy = false; }
    },

    async submit() {
      const data = await this.run(() => Api.post(`/batches/${encodeURIComponent(this.id)}/submit`));
      if (data) { App.flash(data.message); this.load(); }
    },

    async rowAction(r, action) {
      if (this.busy) return;
      await this.run(async () => {                                 // buttons stay disabled until the page is reloaded
        const data = await Api.post(`/requests/${r.request_id}/${action}`);
        App.flash(data.message);
        await this.load();
      });
    },

    async generate(g) {
      const data = await this.run(() => Api.post(`/batches/${encodeURIComponent(this.id)}/generate`, {
        request_id: g.request_id, bureau_codes: this.chosen[g.request_id], confirm_adjustments: !!this.confirm[g.request_id],
      }));
      if (data) App.go(`batch.html?id=${encodeURIComponent(data.batch_id)}`, data.message);
    },

    download(r, kind) { return this.run(() => Api.download(`/requests/${r.request_id}/${kind}`)); },
    csv(snapshotId) { return this.run(() => Api.download(`/snapshots/${snapshotId}/findings.csv`)); },
  }));
});
