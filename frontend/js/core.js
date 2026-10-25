// Shared by every page: sign-in (Cognito, authorization code + PKCE), API calls, the page shell (sidebar, top bar,
// NBFC selector), flash messages and formatting. Loaded before the page's own script and before Alpine.

const CFG = window.APP_CONFIG || { auth: "none" };

// ---------------------------------------------------------------- sign-in
const Auth = {
  manager: null,

  mgr() {
    if (!this.manager && CFG.auth === "cognito") {
      this.manager = new oidc.UserManager({
        authority: CFG.authority, client_id: CFG.clientId, response_type: "code", scope: "openid email profile",
        redirect_uri: location.origin + "/callback.html", loadUserInfo: false, automaticSilentRenew: false,
        userStore: new oidc.WebStorageStateStore({ store: window.sessionStorage }),   // gone when the tab closes
      });
    }
    return this.manager;
  },

  // The Cognito ID token for the API, or a redirect to the sign-in page (the promise then never resolves).
  async token() {
    if (CFG.auth !== "cognito") return null;
    const user = await this.mgr().getUser();
    if (user && !user.expired) return user.id_token;
    await this.signIn();
    return new Promise(() => {});
  },

  signIn() {
    return this.mgr().signinRedirect({ state: location.pathname + location.search });
  },

  async signOut() {
    try { await Api.post("/session/end"); } catch (e) { /* signing out anyway */ }
    if (CFG.auth !== "cognito") { location.href = "/"; return; }
    await this.mgr().removeUser();
    location.href = `${CFG.domain}/logout?client_id=${encodeURIComponent(CFG.clientId)}` +
                    `&logout_uri=${encodeURIComponent(location.origin + "/signed-out.html")}`;
  },
};

// ---------------------------------------------------------------- API
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

const Api = {
  async request(method, path, params = {}, body = null) {
    const query = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") query.append(k, v);
    const headers = { "Accept": "application/json" };
    const token = await Auth.token();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (body) headers["Content-Type"] = "application/json";
    const resp = await fetch(`/api${path}${query.toString() ? "?" + query : ""}`,
                             { method, headers, body: body ? JSON.stringify(body) : null });
    if (resp.status === 401 && CFG.auth === "cognito") { await Auth.signIn(); return new Promise(() => {}); }
    return resp;
  },

  async json(resp) {
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 403) App.denied(data.error);
    if (!resp.ok) throw new ApiError(data.error || `Request failed (${resp.status})`, resp.status);
    return data;
  },

  // GET with the selected NBFC (unless the page passes tenant itself)
  async get(path, params = {}) {
    return this.json(await this.request("GET", path, { tenant: App.store().tenant, ...params }));
  },

  async post(path, body = {}) {
    return this.json(await this.request("POST", path, {}, { tenant: App.store().tenant, ...body }));
  },

  // Downloads: the API answers with a short-lived link (S3), or streams the file (local development).
  async download(path, params = {}) {
    const resp = await this.request("GET", path, { tenant: App.store().tenant, ...params });
    if ((resp.headers.get("Content-Type") || "").includes("application/json")) {
      const data = await this.json(resp);
      window.location.href = data.url;
      return;
    }
    if (!resp.ok) throw new ApiError(`Download failed (${resp.status})`, resp.status);
    const name = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") || "")?.[1] || "download";
    const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await resp.blob()),
                                                               download: name });
    link.click();
    URL.revokeObjectURL(link.href);
  },
};

// ---------------------------------------------------------------- formatting
const F = {
  pad: (n) => String(n).padStart(2, "0"),
  dt(iso) {                                   // UTC from the API -> local "dd-mm-yyyy hh:mm"
    if (!iso) return "";
    const d = new Date(iso);
    return `${F.pad(d.getDate())}-${F.pad(d.getMonth() + 1)}-${d.getFullYear()} ${F.pad(d.getHours())}:${F.pad(d.getMinutes())}`;
  },
  d(iso) {                                    // "2026-09-30" -> "30-09-2026"
    if (!iso) return "";
    const [y, m, day] = iso.slice(0, 10).split("-");
    return `${day}-${m}-${y}`;
  },
  num: (n) => (n === null || n === undefined ? "" : Number(n).toLocaleString("en-IN")),
  pct: (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`),
  age(seconds) {
    if (seconds === null || seconds === undefined) return "";
    const minutes = Math.floor(seconds / 60), days = Math.floor(minutes / 1440), hours = Math.floor((minutes % 1440) / 60);
    return days ? `${days}d ${hours}h` : hours ? `${hours}h` : `${minutes}m`;
  },
  title: (s) => (s ? String(s).toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : ""),
  param: (name) => new URLSearchParams(location.search).get(name),
  url(path, params = {}) {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ""));
    return q.toString() ? `${path}?${q}` : path;
  },
};

// ---------------------------------------------------------------- app state, flash messages
const App = {
  store: () => Alpine.store("app"),

  flash(text, kind = "ok") {
    App.store().flashes = [{ text, kind, id: Math.random() }];      // the latest message replaces older ones
    window.scrollTo({ top: 0, behavior: "smooth" });
  },

  // A message shown on the next page (e.g. after creating a request and moving to its exceptions step)
  flashNext(text, kind = "ok") {
    try { sessionStorage.setItem("flash", JSON.stringify({ text, kind })); } catch (e) { /* not shown */ }
  },

  error(err) { App.flash(err.message || String(err), "error"); },

  go(path, message) {
    if (message) App.flashNext(message);
    location.href = path;
  },

  denied(message) {
    document.body.innerHTML = `<div class="center-page"><div class="login-box"><h1>No access</h1>
      <p>${(message || "Your account is not registered for Bureau Submission.").replace(/</g, "&lt;")}</p>
      <p><button onclick="Auth.signOut()">Sign out</button></p></div></div>`;
    throw new ApiError(message, 403);
  },

  // The deployment's NBFC (from /meta); the API applies it to every call whatever the page sends.
  tenantName() {
    const s = App.store();
    return s.meta?.tenants.find((t) => t.tenant_id === s.tenant)?.display_name || s.tenant;
  },
};

document.addEventListener("alpine:init", () => {
  try { localStorage.removeItem("tenant"); } catch (e) { /* none */ }     // left over from the NBFC selector
  Alpine.store("app", { tenant: "", meta: null, user: null, health: null, flashes: [] });
  try {
    const next = JSON.parse(sessionStorage.getItem("flash") || "null");
    sessionStorage.removeItem("flash");
    if (next) Alpine.store("app").flashes.push({ ...next, id: 0 });
  } catch (e) { /* none */ }
  Promise.all([Api.get("/me"), Api.get("/meta"), Api.get("/health")]).then(([me, meta, health]) => {
    const s = Alpine.store("app");
    Object.assign(s, { user: me, meta, health, tenant: meta.tenant || "" });
    if (sessionStorage.getItem("signed-in")) {      // right after the sign-in redirect: record the login once
      sessionStorage.removeItem("signed-in");
      Api.post("/session").catch(() => {});
    }
  }).catch((e) => { if (e.status !== 403) App.error(e); });
});

// ---------------------------------------------------------------- page shell
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  new: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
  exceptions: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
  tracker: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  files: '<ellipse cx="12" cy="5.5" rx="8" ry="2.5"/><path d="M4 5.5v13c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-13M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5"/>',
  audit: '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  admin: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

const NAV = [
  ["Main"], ["dashboard", "index.html", "Dashboard", "dashboard"], ["new", "new.html", "New request", "new"],
  ["exceptions", "exceptions.html", "Exceptions", "exceptions"],
  ["Reports"], ["tracker", "tracker.html", "Submission tracker", "tracker"], ["files", "files.html", "Files", "files"],
  ["audit", "audit.html", "Audit", "audit"],
  ["Admin"], ["rules", "rules.html", "Rules & policies", "admin"], ["admin", null, "NBFCs & bureaus", "admin"],
];

// Wraps the page's <main> in the sidebar and top bar. <body data-nav="tracker" data-crumb="...html...">
function renderShell() {
  const main = document.querySelector("main.content");
  if (!main) return;
  const active = document.body.dataset.nav;
  const nav = NAV.map(([key, href, label, ic]) => {
    if (!href && !label) return `<div class="nav-group">${key}</div>`;
    if (!href) return `<span class="nav-item soon" title="Coming in a later step">${icon(ic)}<span>${label}</span><em>soon</em></span>`;
    return `<a class="nav-item ${key === active ? "active" : ""}" href="${href}">${icon(ic)}<span>${label}</span></a>`;
  }).join("");
  const shell = document.createElement("div");
  shell.className = "shell";
  shell.setAttribute("x-data", "{}");
  shell.innerHTML = `
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark"><img src="logo.png" alt=""></span>
      <span><strong>Open Terrace Analytics</strong><small>Bureau Submission</small></span></div>
    <nav>${nav}</nav>
    <div class="sidebar-foot">
      <div class="worker" :class="$store.app.health && $store.app.health.slow ? 'down' : 'ok'"
           :title="$store.app.health && $store.app.health.oldest_pending_at ? 'Oldest waiting since ' + F.dt($store.app.health.oldest_pending_at) : ''">
        <span class="dot"></span>
        <span x-text="$store.app.health && $store.app.health.slow ? 'Runs waiting ' + F.age($store.app.health.waiting_seconds) : 'Processing normally'"></span>
      </div>
      <div class="user"><span class="avatar" x-text="($store.app.user?.display_name || '··').slice(0, 2).toUpperCase()"></span>
        <span><strong x-text="$store.app.user?.display_name"></strong><small x-text="$store.app.user?.email || 'Bureau reporting team'"></small></span></div>
      <div class="user-actions" x-show="CFG.auth === 'cognito'"><button class="linkish" @click="Auth.signOut()">Sign out</button></div>
    </div>
  </aside>
  <div class="main">
    <header class="topbar">
      <div class="crumbs"><a href="index.html">Bureau reporting</a> <span>/</span> ${document.body.dataset.crumb || ""}</div>
      <div class="tenant-picker" x-show="$store.app.tenant"><span class="muted">NBFC</span>
        <strong x-text="App.tenantName()"></strong></div>
      <a class="button" href="new.html">${icon("plus")} New request</a>
    </header>
  </div>`;
  main.replaceWith(shell);
  const flashes = document.createElement("template");
  flashes.innerHTML = `<template x-for="f in $store.app.flashes" :key="f.id">
      <div class="flash" :class="f.kind" x-text="f.text"></div></template>`;
  main.prepend(flashes.content);
  shell.querySelector(".main").append(main);
}

renderShell();
