const DOGASSISTANT_VERSION = "0.3.1";
const DEFAULT_QUICK_ACTIONS = ["meal", "water", "pee", "poo", "walk"].map((action) => ({ action }));
const DEFAULT_TABS = ["overview", "timeline", "training"];
const LEGACY_QUICK_ACTIONS = ["meal", "treat", "weight", "pee", "poo", "medication", "walk", "past-walk", "note"].map((action) => ({ action }));
const LEGACY_TABS = ["overview", "timeline", "training", "records", "schedule", "documents"];
const ACTION_LABELS = {
  meal: "Meal", "quick-meal": "Quick meal", water: "Water", pee: "Pee", poo: "Poo", walk: "Walk",
  treat: "Treat", medication: "Medication", weight: "Weight", "past-walk": "Past walk", note: "Note",
};
const ACTION_ICONS = {
  meal: "🍽️", "quick-meal": "⚡🍽️", water: "🚰", pee: "💧", poo: "💩", walk: "🦮",
  treat: "🦴", medication: "💊", weight: "⚖️", "past-walk": "🕘", note: "📝",
};

const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

const relative = (value) => {
  if (!value) return "Not recorded";
  const then = new Date(value);
  const seconds = Math.round((then.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (abs < 90) return formatter.format(seconds, "second");
  if (abs < 5400) return formatter.format(Math.round(seconds / 60), "minute");
  if (abs < 129600) return formatter.format(Math.round(seconds / 3600), "hour");
  return formatter.format(Math.round(seconds / 86400), "day");
};

class DogAssistantCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "overview";
    this._dog = null;
    this._events = [];
    this._loading = false;
    this._error = null;
    this._savingAction = null;
    this._toast = null;
  }

  static getStubConfig(hass) {
    return { dog: "", quick_actions: DEFAULT_QUICK_ACTIONS.map((item) => ({ ...item })), tabs: [...DEFAULT_TABS] };
  }

  static getConfigElement() {
    return document.createElement("dogassistant-card-editor");
  }

  setConfig(config) {
    if (!config || config.dog === undefined) throw new Error("Select a Dog Assistant dog");
    const dogChanged = this._config?.dog && this._config.dog !== config.dog;
    if (dogChanged && this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
    const quickActions = Array.isArray(config.quick_actions) && config.quick_actions.length
      ? config.quick_actions.map((item) => typeof item === "string" ? { action: item } : item).filter((item) => ACTION_LABELS[item.action])
      : (config.quick_actions === undefined ? LEGACY_QUICK_ACTIONS : DEFAULT_QUICK_ACTIONS).map((item) => ({ ...item }));
    const tabs = Array.isArray(config.tabs) && config.tabs.length
      ? config.tabs
      : (config.tabs === undefined ? LEGACY_TABS : DEFAULT_TABS);
    this._config = { title: "", ...config, quick_actions: quickActions, tabs };
    if (this._hass) this._load();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) this._load();
    if (first) this._startClock();
  }

  getCardSize() { return 6; }

  async _load() {
    if (!this._config?.dog || this._loading) {
      this._render();
      return;
    }
    this._loading = true;
    this._error = null;
    this._render();
    try {
      [this._dog, this._eventsPage] = await Promise.all([
        this._hass.callWS({ type: "dogassistant/get_dog", dog_id: this._config.dog }),
        this._hass.callWS({ type: "dogassistant/list_events", dog_id: this._config.dog, limit: 200 }),
      ]);
      this._events = this._eventsPage.items;
      await this._preparePhoto();
      if (!this._unsubscribe) {
        this._unsubscribe = await this._hass.connection.subscribeMessage(
          () => this._refresh(),
          { type: "dogassistant/subscribe", dog_id: this._config.dog },
        );
      }
    } catch (error) {
      this._error = error?.message || String(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _refresh() {
    try {
      [this._dog, this._eventsPage] = await Promise.all([
        this._hass.callWS({ type: "dogassistant/get_dog", dog_id: this._config.dog }),
        this._hass.callWS({ type: "dogassistant/list_events", dog_id: this._config.dog, limit: 200 }),
      ]);
      this._events = this._eventsPage.items;
      await this._preparePhoto();
      this._render();
    } catch (error) {
      this._error = error?.message || String(error);
      this._render();
    }
  }

  disconnectedCallback() {
    if (this._unsubscribe) this._unsubscribe();
    this._unsubscribe = null;
    if (this._photoUrl) URL.revokeObjectURL(this._photoUrl);
    this._photoUrl = null;
    if (this._clock) clearInterval(this._clock);
    this._clock = null;
    if (this._toastTimer) clearTimeout(this._toastTimer);
  }

  connectedCallback() { this._startClock(); }

  _startClock() {
    if (this._clock) return;
    this._clock = setInterval(() => this._render(), 60000);
  }

  async _preparePhoto() {
    const documentId = this._dog?.profile?.photo_document_id;
    if (documentId === this._photoDocumentId) return;
    if (this._photoUrl) URL.revokeObjectURL(this._photoUrl);
    this._photoUrl = null;
    this._photoDocumentId = documentId;
    if (!documentId) return;
    try {
      const response = await this._fetchAuth(`/api/dogassistant/documents/${encodeURIComponent(documentId)}`);
      if (response.ok && response.headers.get("content-type")?.startsWith("image/")) {
        this._photoUrl = URL.createObjectURL(await response.blob());
      }
    } catch (_) { /* Fall back to the dog icon. */ }
  }

  _last(type) { return this._events.find((event) => event.type === type); }
  _activeWalk() { return this._events.find((event) => event.type === "walk" && !event.data?.ended_at); }
  _isAdmin() { return Boolean(this._hass?.user?.is_admin); }

  _localDateTime(value = new Date()) {
    const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  _walkDuration(event) {
    const started = new Date(event?.data?.started_at || event?.occurred_at);
    const ended = new Date(event?.data?.ended_at || Date.now());
    const seconds = Math.max(0, Math.round((ended.getTime() - started.getTime()) / 1000));
    if (!Number.isFinite(seconds)) return null;
    if (seconds < 60) return `${seconds} sec`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return minutes ? `${hours} hr ${minutes} min` : `${hours} hr`;
  }

  _walkSummary(event) {
    if (!event) return "Not recorded";
    if (!event.data?.ended_at) {
      return `${this._walkDuration(event)} so far · started ${relative(event.data?.started_at || event.occurred_at)}`;
    }
    return `${this._walkDuration(event)} · ${relative(event.data.ended_at)}`;
  }

  _quantity(amount, unit) {
    const displayUnit = Number(amount) === 1 && unit === "pieces" ? "piece" : unit;
    return `${amount} ${displayUnit || ""}`.trim();
  }

  _label(value) {
    const text = String(value || "").replaceAll("_", " ");
    return text ? text[0].toUpperCase() + text.slice(1) : text;
  }

  _style() {
    return `<style>
      :host{display:block;--da-accent:var(--primary-color,#03a9f4);--da-muted:var(--secondary-text-color,#777)}
      ha-card{overflow:hidden;padding-bottom:14px}
      .hero{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding:16px;background:linear-gradient(135deg,color-mix(in srgb,var(--da-accent) 18%,var(--card-background-color)),var(--card-background-color))}
      .avatar{width:62px;height:62px;border-radius:50%;background:color-mix(in srgb,var(--da-accent) 25%,var(--card-background-color));display:grid;place-items:center;font-size:32px;overflow:hidden;flex:0 0 auto}
      .avatar img{width:100%;height:100%;object-fit:cover}.hero-copy{min-width:0}.hero h2{margin:0;font-size:1.45rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.subtitle{color:var(--da-muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge{justify-self:end;white-space:nowrap;border-radius:999px;padding:7px 11px;background:var(--error-color,#db4437);color:white;font-size:.78rem;font-weight:700}.ok{background:var(--success-color,#43a047)}
      nav{display:flex;overflow:auto;border-bottom:1px solid var(--divider-color);padding:0 10px;scrollbar-width:none}nav::-webkit-scrollbar{display:none}nav button{background:none;border:0;color:var(--primary-text-color);padding:13px 11px;cursor:pointer;border-bottom:2px solid transparent}nav button.active{color:var(--da-accent);border-color:var(--da-accent)}
      main{padding:14px}.attention{border-left:4px solid var(--warning-color,#ffa600);background:color-mix(in srgb,var(--warning-color,#ffa600) 12%,transparent);padding:9px 12px;border-radius:6px;margin-bottom:12px}.attention strong{display:block}
      .today-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.today-item{border:1px solid var(--divider-color);border-radius:10px;padding:11px}.today-head{display:flex;justify-content:space-between;gap:8px}.today-label{font-weight:700}.today-count{font-size:.78rem;color:var(--da-muted)}.today-meta{font-size:.82rem;color:var(--da-muted);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .actions{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}.actions button,.primary,.secondary{border:0;border-radius:10px;padding:10px 6px;cursor:pointer;background:color-mix(in srgb,var(--da-accent) 15%,var(--card-background-color));color:var(--primary-text-color)}.actions button span{display:block;font-size:20px;margin-bottom:3px}.actions button:disabled{opacity:.55;cursor:wait}.walk-active{background:color-mix(in srgb,var(--error-color,#db4437) 18%,var(--card-background-color))!important}
      .list{display:flex;flex-direction:column;gap:8px}.item{border:1px solid var(--divider-color);border-radius:10px;padding:11px;display:flex;gap:10px;align-items:flex-start}.item .body{min-width:0;flex:1}.item strong{display:block}.meta{font-size:.82rem;color:var(--da-muted);margin-top:3px}.item button{border:0;background:none;color:var(--error-color);cursor:pointer}.empty{text-align:center;color:var(--da-muted);padding:24px 8px}
      .toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.toolbar h3{margin:0}.primary{background:var(--da-accent);color:var(--text-primary-color,#fff);padding:8px 12px}.secondary{border:1px solid var(--divider-color);background:transparent;padding:8px 12px}
      dialog{border:0;border-radius:12px;background:var(--card-background-color);color:var(--primary-text-color);box-shadow:0 8px 30px #0005;max-width:min(520px,calc(100vw - 32px));width:100%;padding:0}dialog::backdrop{background:#0008}.dialog-head{padding:16px 18px;border-bottom:1px solid var(--divider-color);font-weight:700}.form{padding:16px 18px;display:grid;grid-template-columns:1fr 1fr;gap:12px}.form label{font-size:.82rem;color:var(--da-muted)}.form input,.form select,.form textarea{box-sizing:border-box;width:100%;margin-top:4px;padding:9px;border:1px solid var(--divider-color);border-radius:7px;background:var(--card-background-color);color:var(--primary-text-color)}.form textarea{min-height:72px}.wide{grid-column:1/-1}.range-row{display:flex;align-items:center;gap:12px;margin-top:8px}.range-row input[type=range]{flex:1;margin:0;padding:0;border:0}.range-value{min-width:64px;text-align:right;color:var(--primary-text-color);font-weight:700}.time-range{margin-top:8px}.time-range input[type=range]{margin:0;padding:0;border:0}.range-caption{display:flex;justify-content:space-between;gap:12px;margin-top:5px}.range-caption .range-value{min-width:0;text-align:left}.range-local{color:var(--primary-text-color);font-weight:600;font-variant-numeric:tabular-nums}.dialog-actions{display:flex;justify-content:flex-end;gap:8px;padding:0 18px 16px}.error{padding:16px;color:var(--error-color)}.loading{padding:30px;text-align:center;color:var(--da-muted)}
      .form-label{font-size:.82rem;color:var(--da-muted)}.preset-grid{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-top:7px}.preset-grid button{border:1px solid var(--divider-color);border-radius:999px;padding:8px 11px;background:color-mix(in srgb,var(--da-accent) 10%,var(--card-background-color));color:var(--primary-text-color);cursor:pointer}.preset-grid button.selected{border-color:var(--da-accent);background:color-mix(in srgb,var(--da-accent) 22%,var(--card-background-color))}.preset-empty{color:var(--da-muted);font-size:.85rem}.preset-grid .add-preset{border-style:dashed;background:transparent}
      .profile{display:grid;grid-template-columns:auto 1fr;gap:7px 12px}.profile dt{color:var(--da-muted)}.profile dd{margin:0;white-space:pre-wrap}.section{margin-top:18px}.section h4{margin:0 0 8px}.document input{max-width:100%}
      .snackbar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:10;display:flex;align-items:center;gap:16px;max-width:calc(100% - 32px);padding:10px 14px;border-radius:9px;background:var(--primary-text-color,#222);color:var(--card-background-color,#fff);box-shadow:0 4px 18px #0005}.snackbar button{border:0;background:none;color:var(--da-accent);font-weight:700;cursor:pointer}
      @media(max-width:600px){.form{grid-template-columns:1fr}.wide{grid-column:auto}.hero{padding:14px}.today-grid{grid-template-columns:1fr 1fr}}
    </style>`;
  }

  _render() {
    if (!this.shadowRoot) return;
    if (!this._config?.dog) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="empty">Edit this card and select a dog.</div></ha-card>`;
      return;
    }
    if (this._loading && !this._dog) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="loading">Loading Dog Assistant…</div></ha-card>`;
      return;
    }
    if (this._error || !this._dog) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="error">${esc(this._error || "Dog not found")}</div></ha-card>`;
      return;
    }
    const profile = this._dog.profile || {};
    const attention = this._dog.attention || [];
    const photo = this._photoUrl;
    const allowedTabs = this._isAdmin()
      ? ["overview", "timeline", "training", "records", "schedule", "documents"]
      : ["overview", "timeline", "training"];
    const tabs = this._config.tabs.filter((tab) => allowedTabs.includes(tab));
    if (!tabs.length) tabs.push("overview");
    if (!tabs.includes(this._tab)) this._tab = "overview";
    this.shadowRoot.innerHTML = `${this._style()}<ha-card>
      <div class="hero"><div class="avatar">${photo ? `<img src="${photo}" alt="">` : "🐕"}</div><div class="hero-copy"><h2>${esc(this._config.title || this._dog.name)}</h2><div class="subtitle">${esc([profile.breed, profile.sex].filter(Boolean).join(" · ") || "Dog Assistant")}</div></div><div class="badge ${attention.length ? "" : "ok"}">${attention.length ? `${attention.length} ${attention.length === 1 ? "alert" : "alerts"}` : "All good"}</div></div>
      <nav>${tabs.map((tab) => `<button data-tab="${tab}" class="${this._tab === tab ? "active" : ""}">${tab[0].toUpperCase() + tab.slice(1)}</button>`).join("")}</nav>
      <main>${this[`_${this._tab}Html`]()}</main>
      <dialog id="editor"></dialog>
      ${this._toast ? `<div class="snackbar"><span>${esc(this._toast.message)}</span><button data-undo-event="${esc(this._toast.eventId)}">Undo</button></div>` : ""}
    </ha-card>`;
    this.shadowRoot.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => { this._tab = button.dataset.tab; this._render(); }));
    this.shadowRoot.querySelector("[data-undo-event]")?.addEventListener("click", (event) => this._undoEvent(event.currentTarget.dataset.undoEvent));
    this._bindTabActions();
  }

  _overviewHtml() {
    const attention = this._dog.attention || [];
    const walk = this._activeWalk();
    const actionButtons = this._config.quick_actions.map((definition) => {
      const action = definition.action;
      const active = action === "walk" && walk;
      const label = active ? "End walk" : ACTION_LABELS[action];
      const icon = active ? "⏹️" : ACTION_ICONS[action];
      return `<button data-action="${esc(action)}" ${definition.food_id ? `data-food-id="${esc(definition.food_id)}"` : ""} class="${active ? "walk-active" : ""}" ${this._savingAction ? "disabled" : ""}><span>${icon}</span>${esc(label)}</button>`;
    }).join("");
    return `${attention.map((item) => `<div class="attention"><strong>${esc(item.name || item.kind)}</strong>${esc(item.severity)}${item.at || item.scheduled_for ? ` · ${relative(item.at || item.scheduled_for)}` : ""}</div>`).join("")}
      <div class="today-grid">
        ${this._todayItem("Meal", "meal", "🍽️")}
        ${this._todayItem("Water", "water", "🚰")}
        ${this._todayItem("Pee", "toilet", "💧", "urine")}
        ${this._todayItem("Poo", "toilet", "💩", "stool")}
        ${this._todayItem("Walk", "walk", "🦮")}
      </div>
      <div class="actions">${actionButtons}</div>`;
  }

  _todayEvents(type, toiletKind = null) {
    const today = this._dayKey(new Date());
    return this._events.filter((event) => event.type === type
      && this._dayKey(new Date(event.occurred_at)) === today
      && (!toiletKind || event.data?.kind === toiletKind || event.data?.kind === "both"));
  }

  _dayKey(value) {
    const parts = new Intl.DateTimeFormat("en", {
      timeZone: this._hass?.config?.time_zone,
      year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(value);
    return ["year", "month", "day"].map((type) => parts.find((part) => part.type === type)?.value).join("-");
  }

  _todayItem(label, type, icon, toiletKind = null) {
    const events = this._todayEvents(type, toiletKind);
    const latest = events[0];
    const activeWalk = type === "walk" ? this._activeWalk() : null;
    const displayEvent = activeWalk || latest;
    const time = displayEvent
      ? new Date(displayEvent.occurred_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: this._hass?.config?.time_zone })
      : null;
    const meta = activeWalk
      ? `In progress · ${time}${activeWalk.caregiver ? ` · ${activeWalk.caregiver}` : ""}`
      : latest
      ? `${new Date(latest.occurred_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: this._hass?.config?.time_zone })}${latest.caregiver ? ` · ${latest.caregiver}` : ""}`
      : "Nothing logged today";
    return `<div class="today-item"><div class="today-head"><span class="today-label">${icon} ${label}</span><span class="today-count">${events.length} today</span></div><div class="today-meta">${esc(meta)}</div></div>`;
  }

  _timelineHtml() {
    if (!this._events.length) return `<div class="empty">No care events yet.</div>`;
    return `<div class="list">${this._events.map((event) => `<div class="item"><div>${this._eventIcon(event.type, event)}</div><div class="body"><strong>${esc(this._eventTitle(event))}</strong><div class="meta">${new Date(event.occurred_at).toLocaleString()}${event.caregiver ? ` · ${esc(event.caregiver)}` : ""}</div>${event.notes ? `<div>${esc(event.notes)}</div>` : ""}</div>${this._isAdmin() ? `<button data-delete-event="${esc(event.id)}" title="Delete">✕</button>` : ""}</div>`).join("")}</div>`;
  }

  _eventIcon(type, event) {
    if (type === "toilet") return event?.data?.kind === "urine" ? "💧" : "💩";
    return ({ meal: "🍽️", water: "🚰", treat: "🦴", walk: "🦮", medication: "💊", weight: "⚖️", note: "📝" })[type] || "•";
  }
  _eventTitle(event) {
    const data = event.data || {};
    if (event.type === "meal") return [data.meal_type, data.food, data.amount && `${data.amount} ${data.unit || ""}`].filter(Boolean).join(" · ") || "Meal";
    if (event.type === "water") return "Water refreshed";
    if (event.type === "treat") return [data.treat, data.amount && this._quantity(data.amount, data.unit)].filter(Boolean).join(" · ") || "Treat";
    if (event.type === "walk") return data.ended_at ? `${this._label(data.activity || "Walk")} · ${this._walkDuration(event)}` : `${this._label(data.activity || "Walk")} in progress`;
    if (event.type === "toilet") return `${({ urine: "Pee", stool: "Poo", both: "Pee & poo" })[data.kind] || "Toilet"}${data.condition ? ` · ${this._label(data.condition)}` : ""}`;
    if (event.type === "medication") return `${this._label(data.status || "given")} · ${this._dog.medications.find((m) => m.id === data.medication_id)?.name || "Medication"}`;
    if (event.type === "weight") return `${data.weight_kg} kg`;
    if (event.type === "note") return `${this._label(data.category || "General")}: ${data.text || "Note"}`;
    return event.type;
  }

  _recordsHtml() {
    const p = this._dog.profile || {};
    const fields = [["Birth date", p.birth_date], ["Adoption date", p.adoption_date], ["Breed", p.breed], ["Sex", p.sex], ["Neutered", p.neutered], ["Colour / markings", p.colour], ["Target weight", p.target_weight_kg && `${p.target_weight_kg} kg`], ["Diet", p.diet], ["Allergies", p.allergies], ["Conditions", p.conditions], ["Vet", p.vet], ["Emergency contact", p.emergency_contact], ["Microchip", p.microchip], ["Registry", p.microchip_registry], ["Licence", p.registration], ["Insurance", p.insurance_provider], ["Policy", p.insurance_policy]].filter(([, value]) => value !== undefined && value !== "");
    return `<div class="toolbar"><h3>Profile and records</h3>${this._isAdmin() ? `<button class="primary" data-action="profile">Edit</button>` : ""}</div>${fields.length ? `<dl class="profile">${fields.map(([label, value]) => `<dt>${label}</dt><dd>${esc(value)}</dd>`).join("")}</dl>` : `<div class="empty">Add identity, health, vet, and insurance details.</div>`}
      ${this._recordSection("Food portions", "foods")}${this._recordSection("Treat portions", "treats")}${this._recordSection("Vaccinations", "vaccinations")}`;
  }

  _scheduleHtml() {
    return `${this._recordSection("Medications", "medications")}${this._recordSection("Appointments", "appointments")}`;
  }

  _trainingHtml() {
    return this._recordSection("Training commands", "commands");
  }

  _recordSection(title, kind) {
    const records = this._dog[kind] || [];
    return `<div class="section"><div class="toolbar"><h4>${title}</h4>${this._isAdmin() ? `<button class="secondary" data-add-record="${kind}">Add</button>` : ""}</div><div class="list">${records.length ? records.map((record) => `<div class="item"><div class="body"><strong>${esc(record.command || record.name || record.title || title.slice(0, -1))}</strong><div class="meta">${esc(this._recordSummary(kind, record))}</div></div>${this._isAdmin() ? `<button data-delete-record="${kind}:${esc(record.id)}" title="Delete">✕</button>` : ""}</div>`).join("") : `<div class="empty">No ${title.toLowerCase()} yet.</div>`}</div></div>`;
  }

  _recordSummary(kind, record) {
    if (kind === "commands") return [record.meaning, record.notes].filter(Boolean).join(" · ");
    if (kind === "foods") return `${record.portion_grams} g per meal`;
    if (kind === "treats") return this._quantity(record.amount, record.unit || "pieces");
    if (kind === "medications") return [record.dose && `${record.dose} ${record.unit || ""}`, record.schedule?.times?.join(", "), record.instructions].filter(Boolean).join(" · ");
    if (kind === "vaccinations") return [record.administered_at && `Given ${record.administered_at}`, record.due_at && `Due ${record.due_at}`, record.provider].filter(Boolean).join(" · ");
    return [record.start && new Date(record.start).toLocaleString(), record.location].filter(Boolean).join(" · ");
  }

  _documentsHtml() {
    const documents = this._dog.documents || [];
    return `<div class="toolbar"><h3>Documents</h3>${this._isAdmin() ? `<button class="primary" data-action="upload">Upload</button>` : ""}</div><div class="list">${documents.length ? documents.map((document) => `<div class="item"><div>📎</div><div class="body"><strong>${esc(document.label)}</strong><div class="meta">${esc(this._label(document.category))} · ${(document.size / 1024).toFixed(1)} KB</div></div><button data-open-document="${esc(document.id)}" title="Open">↗</button>${this._isAdmin() ? `<button data-delete-document="${esc(document.id)}" title="Delete">✕</button>` : ""}</div>`).join("") : `<div class="empty">No documents uploaded.</div>`}</div>${this._isAdmin() ? `<div class="section"><button class="secondary" data-action="export">Export this dog</button></div>` : ""}`;
  }

  _bindTabActions() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((el) => el.addEventListener("click", () => this._action(el.dataset.action, el)));
    this.shadowRoot.querySelectorAll("[data-delete-event]").forEach((el) => el.addEventListener("click", () => this._deleteEvent(el.dataset.deleteEvent)));
    this.shadowRoot.querySelectorAll("[data-add-record]").forEach((el) => el.addEventListener("click", () => this._recordDialog(el.dataset.addRecord)));
    this.shadowRoot.querySelectorAll("[data-delete-record]").forEach((el) => el.addEventListener("click", () => { const [kind, id] = el.dataset.deleteRecord.split(":"); this._deleteRecord(kind, id); }));
    this.shadowRoot.querySelectorAll("[data-open-document]").forEach((el) => el.addEventListener("click", () => this._openDocument(el.dataset.openDocument)));
    this.shadowRoot.querySelectorAll("[data-delete-document]").forEach((el) => el.addEventListener("click", () => this._deleteDocument(el.dataset.deleteDocument)));
  }

  async _action(action, element = null) {
    if (action === "quick-meal") {
      return this._logRoutine("meal", element?.dataset.foodId);
    }
    if (["water", "pee", "poo"].includes(action)) {
      return this._logRoutine(action);
    }
    if (action === "walk") {
      const service = this._activeWalk() ? "end_walk" : "start_walk";
      await this._call(service, {});
      return;
    }
    if (action === "past-walk") return this._walkDialog();
    if (action === "meal") return this._careDialog("meal", null, element?.dataset.foodId);
    if (action === "profile") return this._profileDialog();
    if (action === "upload") return this._uploadDialog();
    if (action === "export") return this._download(`/api/dogassistant/export?dog_id=${encodeURIComponent(this._dog.id)}`, "dogassistant-export.zip");
    this._careDialog(action);
  }

  async _logRoutine(action, foodId = null) {
    if (this._savingAction) return;
    this._savingAction = action;
    this._render();
    try {
      const event = await this._hass.callWS({
        type: "dogassistant/log_routine_event",
        dog_id: this._dog.id,
        action,
        ...(foodId ? { food_id: foodId } : {}),
      });
      this._toast = { eventId: event.id, message: `${ACTION_LABELS[action]} logged` };
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this._toast = null; this._render(); }, 8000);
    } catch (error) {
      this._showError(error);
    } finally {
      this._savingAction = null;
      this._render();
    }
  }

  async _undoEvent(eventId) {
    try {
      await this._hass.callWS({ type: "dogassistant/undo_event", event_id: eventId });
      this._toast = null;
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this._render();
    } catch (error) { this._showError(error); }
  }

  async _call(service, data) {
    try {
      await this._hass.callService("dogassistant", service, { dog_id: this._dog.id, ...data });
    } catch (error) { this._showError(error); }
  }

  _dialog(title, body, submit) {
    const dialog = this.shadowRoot.querySelector("#editor");
    dialog.innerHTML = `<form method="dialog"><div class="dialog-head">${esc(title)}</div><div class="form">${body}</div><div class="dialog-actions"><button type="button" data-dialog-cancel class="secondary">Cancel</button><button type="submit" class="primary">Save</button></div></form>`;
    const form = dialog.querySelector("form");
    dialog.querySelector("[data-dialog-cancel]").addEventListener("click", () => dialog.close());
    dialog.querySelectorAll("[data-range-output]").forEach((input) => {
      const output = dialog.querySelector(`#${input.dataset.rangeOutput}`);
      const timeOutput = input.dataset.timeOutput ? dialog.querySelector(`#${input.dataset.timeOutput}`) : null;
      const update = () => {
        const value = Number(input.value);
        if (input.dataset.rangeKind === "ago") {
          if (value === 0) output.textContent = "Now";
          else if (value < 60) output.textContent = `${value} min ago`;
          else {
            const hours = Math.floor(value / 60);
            const minutes = value % 60;
            output.textContent = `${hours} hr${minutes ? ` ${minutes} min` : ""} ago`;
          }
          if (timeOutput) {
            const localTime = new Date(Date.now() - value * 60 * 1000);
            timeOutput.textContent = localTime.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
          }
        } else if (input.dataset.rangeKind === "duration") {
          const hours = Math.floor(value / 60);
          const minutes = value % 60;
          output.textContent = hours ? `${hours} hr${minutes ? ` ${minutes} min` : ""}` : `${minutes} min`;
        } else output.textContent = `${input.value} ${input.dataset.rangeUnit || ""}`.trim();
      };
      input.addEventListener("input", update);
      update();
    });
    dialog.querySelectorAll("[data-food-preset]").forEach((button) => {
      button.addEventListener("click", () => {
        dialog.querySelectorAll("[data-food-preset]").forEach((item) => item.classList.toggle("selected", item === button));
        dialog.querySelector('[name="food"]').value = button.dataset.foodPreset;
        const amount = dialog.querySelector('[name="amount"]');
        amount.value = button.dataset.foodAmount;
        amount.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
    dialog.querySelector("[data-add-food-from-meal]")?.addEventListener("click", () => {
      dialog.close();
      this._recordDialog("foods");
    });
    dialog.querySelectorAll("[data-treat-preset]").forEach((button) => {
      button.addEventListener("click", () => {
        dialog.querySelectorAll("[data-treat-preset]").forEach((item) => item.classList.toggle("selected", item === button));
        dialog.querySelector('[name="treat"]').value = button.dataset.treatPreset;
        dialog.querySelector('[name="amount"]').value = button.dataset.treatAmount;
        dialog.querySelector('[name="unit"]').value = button.dataset.treatUnit;
      });
    });
    dialog.querySelector("[data-add-treat-from-log]")?.addEventListener("click", () => {
      dialog.close();
      this._recordDialog("treats");
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await submit(new FormData(form)); dialog.close(); } catch (error) { this._showError(error); }
    });
    dialog.showModal();
  }

  _careDialog(kind, toiletKind = null, selectedFoodId = null) {
    const common = `<label class="wide">Notes<textarea name="notes"></textarea></label>`;
    const when = (label = "When") => `<label class="wide">${label}<div class="time-range"><input name="minutes_ago" type="range" min="0" max="1440" step="15" value="0" data-range-kind="ago" data-range-output="entry-time" data-time-output="entry-local-time"><div class="range-caption"><output id="entry-time" class="range-value">Now</output><span id="entry-local-time" class="range-local"></span></div></div></label>`;
    const toiletConditions = toiletKind === "urine"
      ? `<option value="normal">Normal</option><option value="frequent">Frequent</option><option value="dark">Dark</option><option value="blood">Blood</option><option value="difficulty">Difficulty</option><option value="accident">Accident</option>`
      : `<option value="normal">Normal</option><option value="soft">Soft</option><option value="diarrhoea">Diarrhoea</option><option value="constipated">Constipated</option><option value="blood">Blood</option><option value="mucus">Mucus</option>`;
    const foodPresets = (this._dog.foods || []).map((food) => `<button type="button" data-food-preset="${esc(food.name)}" data-food-amount="${Number(food.portion_grams)}" class="${food.id === selectedFoodId ? "selected" : ""}">${esc(food.name)} · ${Number(food.portion_grams)} g</button>`).join("");
    const foodPicker = `<div class="wide"><div class="form-label">Food portions</div><div class="preset-grid">${foodPresets || `<span class="preset-empty">No saved portions</span>`}<button type="button" class="add-preset" data-add-food-from-meal>＋ Add portion</button></div></div>`;
    const treatPresets = (this._dog.treats || []).map((treat) => `<button type="button" data-treat-preset="${esc(treat.name)}" data-treat-amount="${Number(treat.amount)}" data-treat-unit="${esc(treat.unit || "pieces")}">${esc(treat.name)} · ${esc(this._quantity(Number(treat.amount), treat.unit || "pieces"))}</button>`).join("");
    const treatPicker = `<div class="wide"><div class="form-label">Treat portions</div><div class="preset-grid">${treatPresets || `<span class="preset-empty">No saved treats</span>`}<button type="button" class="add-preset" data-add-treat-from-log>＋ Add treat</button></div></div>`;
    const definitions = {
      meal: ["Log meal", `${when("Meal time")}${foodPicker}<label>Food name <span>(optional)</span><input name="food" placeholder="e.g. usual kibble"></label><label class="wide">Amount<div class="range-row"><input name="amount" type="range" min="0" max="1000" step="10" value="200" data-range-unit="g" data-range-output="meal-amount"><output id="meal-amount" class="range-value">200 g</output></div></label>${common}`],
      treat: ["Log treat", `${when("Treat time")}${treatPicker}<label>Treat name <span>(optional)</span><input name="treat" placeholder="e.g. dental chew"></label><label>Amount<input name="amount" type="number" inputmode="decimal" min="0" step="1" value="1"></label><label>Unit<select name="unit"><option value="pieces">Pieces</option><option value="g">Grams (g)</option></select></label>${common}`],
      toilet: [toiletKind === "urine" ? "Log pee" : "Log poo", `${when()}<input type="hidden" name="kind" value="${toiletKind || "stool"}"><label>Condition<select name="condition">${toiletConditions}</select></label>${common}`],
      weight: ["Log weight", `${when()}<label>Weight<input required name="weight" type="number" min="0" step="0.01"></label><label>Unit<select name="unit"><option value="kg">Kilograms (kg)</option><option value="lb">Pounds (lb)</option><option value="g">Grams (g)</option></select></label>${common}`],
      note: ["Add note", `${when()}<label>Category<select name="category"><option value="general">General</option><option value="health">Health</option><option value="behaviour">Behaviour</option><option value="diet">Diet</option><option value="training">Training</option><option value="incident">Incident</option></select></label><label class="wide">Note<textarea required name="text"></textarea></label>`],
      medication: ["Record medication", `${when("Given at")}<label>Medication<select required name="medication_id">${this._dog.medications.map((med) => `<option value="${esc(med.id)}">${esc(med.name)}</option>`).join("")}</select></label><label>Status<select name="status"><option value="given">Given</option><option value="skipped">Skipped</option><option value="refused">Refused</option></select></label><label>Dose<input name="dose" type="number" step="0.01"></label><label>Unit<input name="unit"></label>${common}`],
    };
    const [title, body] = definitions[kind];
    this._dialog(title, body, async (form) => {
      const data = Object.fromEntries([...form.entries()].filter(([, value]) => value !== ""));
      const minutesAgo = Number(data.minutes_ago || 0);
      delete data.minutes_ago;
      data.occurred_at = new Date(Date.now() - minutesAgo * 60 * 1000).toISOString();
      if (data.amount) data.amount = Number(data.amount);
      if (kind === "meal") data.unit = "g";
      if (data.weight) data.weight = Number(data.weight);
      if (data.dose) data.dose = Number(data.dose);
      await this._call(({ meal: "log_meal", treat: "log_treat", toilet: "log_toilet", weight: "log_weight", note: "add_note", medication: "record_medication" })[kind], data);
    });
    if (kind === "meal" && selectedFoodId) {
      const food = (this._dog.foods || []).find((item) => item.id === selectedFoodId);
      const dialog = this.shadowRoot.querySelector("#editor");
      if (food && dialog) {
        dialog.querySelector('[name="food"]').value = food.name;
        const amount = dialog.querySelector('[name="amount"]');
        amount.value = food.portion_grams;
        amount.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
  }

  _walkDialog() {
    this._dialog("Log past walk", `<label class="wide">Ended<div class="time-range"><input name="ended_minutes_ago" type="range" min="0" max="1440" step="15" value="0" data-range-kind="ago" data-range-output="walk-ended" data-time-output="walk-ended-local"><div class="range-caption"><output id="walk-ended" class="range-value">Now</output><span id="walk-ended-local" class="range-local"></span></div></div></label><label class="wide">Duration<div class="range-row"><input name="duration_minutes" type="range" min="5" max="480" step="5" value="30" data-range-kind="duration" data-range-output="walk-duration"><output id="walk-duration" class="range-value">30 min</output></div></label><label>Activity<select name="activity"><option value="walk">Walk</option><option value="run">Run</option><option value="hike">Hike</option><option value="play">Play</option><option value="training">Training</option></select></label><label>Distance <span>(optional)</span><input name="distance" type="number" min="0" step="0.01"></label><label>Distance unit<select name="distance_unit"><option value="km">Kilometres (km)</option><option value="mi">Miles (mi)</option><option value="m">Metres (m)</option></select></label><label class="wide">Notes<textarea name="notes"></textarea></label>`, async (form) => {
      const data = Object.fromEntries([...form.entries()].filter(([, value]) => value !== ""));
      const ended = new Date(Date.now() - Number(data.ended_minutes_ago) * 60 * 1000);
      const started = new Date(ended.getTime() - Number(data.duration_minutes) * 60 * 1000);
      delete data.ended_minutes_ago;
      delete data.duration_minutes;
      data.started_at = started.toISOString();
      data.ended_at = ended.toISOString();
      data.occurred_at = data.ended_at;
      if (data.distance) data.distance = Number(data.distance);
      await this._call("log_walk", data);
    });
  }

  _profileDialog() {
    const p = this._dog.profile || {};
    const input = (name, label, type = "text", wide = false) => `<label class="${wide ? "wide" : ""}">${label}<input name="${name}" type="${type}" value="${esc(p[name] || "")}"></label>`;
    const area = (name, label) => `<label class="wide">${label}<textarea name="${name}">${esc(p[name] || "")}</textarea></label>`;
    this._dialog("Edit profile", `${input("name", "Name", "text")} ${input("birth_date", "Birth date", "date")} ${input("adoption_date", "Adoption date", "date")} ${input("breed", "Breed")} ${input("sex", "Sex")} ${input("neutered", "Neutered / spayed")} ${input("colour", "Colour / markings")} ${input("target_weight_kg", "Target weight (kg)", "number")} ${area("diet", "Diet and feeding instructions")} ${area("allergies", "Allergies")} ${area("conditions", "Conditions")} ${input("vet", "Primary vet", "text", true)} ${input("emergency_contact", "Emergency contact", "text", true)} ${input("microchip", "Microchip number")} ${input("microchip_registry", "Microchip registry")} ${input("registration", "Licence / registration")} ${input("registration_expiry", "Registration expiry", "date")} ${input("insurance_provider", "Insurance provider")} ${input("insurance_policy", "Policy number")} ${input("insurance_renewal", "Insurance renewal", "date")}`, async (form) => {
      const values = Object.fromEntries(form.entries());
      const name = values.name; delete values.name;
      const profile = { ...p };
      Object.entries(values).forEach(([key, value]) => { if (value === "") delete profile[key]; else profile[key] = key === "target_weight_kg" ? Number(value) : value; });
      await this._hass.callWS({ type: "dogassistant/update_profile", dog_id: this._dog.id, name, profile });
    });
  }

  _recordDialog(kind) {
    let title; let body;
    if (kind === "commands") {
      title = "Add training command";
      body = `<label>Word or command<input required name="command" placeholder="e.g. Place"></label><label class="wide">What it means<textarea required name="meaning" placeholder="e.g. Go to your bed and stay there until released"></textarea></label><label class="wide">Notes <span>(optional)</span><textarea name="notes" placeholder="Hand signal, release word, or training tips"></textarea></label>`;
    } else if (kind === "foods") {
      title = "Add food portion";
      body = `<label>Food name<input required name="name" placeholder="e.g. usual kibble"></label><label>Portion (g)<input required name="portion_grams" type="number" inputmode="decimal" min="1" max="1000" step="1"></label>`;
    } else if (kind === "treats") {
      title = "Add treat portion";
      body = `<label>Treat name<input required name="name" placeholder="e.g. dental chew"></label><label>Amount<input required name="amount" type="number" inputmode="decimal" min="0" max="1000" step="1" value="1"></label><label>Unit<select name="unit"><option value="pieces">Pieces</option><option value="g">Grams (g)</option></select></label>`;
    } else if (kind === "medications") {
      title = "Add medication";
      body = `<label>Name<input required name="name"></label><label>Dose<input name="dose" type="number" step="0.01"></label><label>Unit<input name="unit"></label><label>Times<input name="times" placeholder="08:00, 20:00"></label><label class="wide">Instructions<textarea name="instructions"></textarea></label><label><input name="as_needed" type="checkbox"> As needed</label>`;
    } else if (kind === "vaccinations") {
      title = "Add vaccination";
      body = `<label>Name<input required name="name"></label><label>Administered<input name="administered_at" type="date"></label><label>Next due<input name="due_at" type="date"></label><label>Provider<input name="provider"></label><label>Batch / lot<input name="batch"></label><label class="wide">Notes<textarea name="notes"></textarea></label>`;
    } else {
      title = "Add appointment";
      body = `<label>Title<input required name="title"></label><label>Type<input name="appointment_type" placeholder="Vet, grooming…"></label><label>Start<input required name="start" type="datetime-local"></label><label>End<input name="end" type="datetime-local"></label><label class="wide">Location<input name="location"></label><label class="wide">Notes<textarea name="notes"></textarea></label>`;
    }
    this._dialog(title, body, async (form) => {
      const raw = Object.fromEntries(form.entries());
      const record = Object.fromEntries(Object.entries(raw).filter(([, value]) => value !== ""));
      if (record.portion_grams) record.portion_grams = Number(record.portion_grams);
      if (kind === "treats" && record.amount) record.amount = Number(record.amount);
      if (record.dose) record.dose = Number(record.dose);
      if (kind === "medications") {
        record.active = true; record.as_needed = form.get("as_needed") === "on";
        record.schedule = { times: (record.times || "").split(",").map((value) => value.trim()).filter(Boolean), weekdays: [0, 1, 2, 3, 4, 5, 6] };
        delete record.times;
      }
      if (kind === "appointments") {
        record.start = new Date(record.start).toISOString();
        if (record.end) record.end = new Date(record.end).toISOString();
      }
      await this._hass.callWS({ type: "dogassistant/upsert_record", dog_id: this._dog.id, kind, record });
    });
  }

  _uploadDialog() {
    this._dialog("Upload document", `<label>Label<input required name="label"></label><label>Category<select name="category"><option value="medical">Medical</option><option value="vaccination">Vaccination</option><option value="insurance">Insurance</option><option value="registration">Registration</option><option value="other">Other</option><option value="profile_photo">Profile photo</option></select></label><label class="wide">PDF or image (10 MiB maximum)<input required name="file" type="file" accept="application/pdf,image/jpeg,image/png,image/webp"></label>`, async (form) => {
      if (form.get("category") === "profile_photo" && !form.get("file")?.type?.startsWith("image/")) {
        throw new Error("A profile photo must be a JPEG, PNG, or WebP image");
      }
      form.append("dog_id", this._dog.id);
      const response = await this._fetchAuth("/api/dogassistant/documents", { method: "POST", body: form });
      if (!response.ok) throw new Error(await response.text());
      const document = await response.json();
      if (form.get("category") === "profile_photo") {
        await this._hass.callWS({ type: "dogassistant/update_profile", dog_id: this._dog.id, profile: { ...this._dog.profile, photo_document_id: document.id } });
      }
    });
  }

  async _deleteEvent(id) {
    if (!confirm("Delete this care event?")) return;
    await this._hass.callWS({ type: "dogassistant/delete_event", event_id: id });
  }
  async _deleteRecord(kind, id) {
    if (!confirm("Delete this record?")) return;
    await this._hass.callWS({ type: "dogassistant/delete_record", dog_id: this._dog.id, kind, record_id: id });
  }
  async _deleteDocument(id) {
    if (!confirm("Permanently delete this document?")) return;
    const response = await this._fetchAuth(`/api/dogassistant/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!response.ok) this._showError(new Error(await response.text()));
  }
  async _openDocument(id) {
    const metadata = (this._dog.documents || []).find((document) => document.id === id);
    await this._download(
      `/api/dogassistant/documents/${encodeURIComponent(id)}`,
      metadata?.original_name,
    );
  }
  async _download(url, filename) {
    const response = await this._fetchAuth(url);
    if (!response.ok) return this._showError(new Error(await response.text()));
    const blob = await response.blob();
    const header = response.headers.get("Content-Disposition") || "";
    const encodedName = header.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const plainName = header.match(/filename="([^"]+)"/i)?.[1];
    let downloadName = filename || (encodedName && decodeURIComponent(encodedName)) || plainName || "download";
    if (!downloadName.includes(".")) {
      const extension = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
      }[blob.type];
      if (extension) downloadName += extension;
    }
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = blobUrl; link.download = downloadName; link.click();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
  }
  _fetchAuth(url, options = {}) {
    const token = this._hass.auth?.data?.access_token;
    return fetch(url, { ...options, headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  }
  _showError(error) {
    this._hass.callService("persistent_notification", "create", { title: "Dog Assistant", message: error?.message || String(error) });
  }
}

class DogAssistantCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); }
  setConfig(config) { this._config = config; if (this._hass) this._load(); else this._render(); }
  set hass(hass) { this._hass = hass; this._load(); }
  async _load() {
    if (!this._hass) return;
    try {
      this._dogs = await this._hass.callWS({ type: "dogassistant/list_dogs" });
      this._dog = this._config?.dog
        ? await this._hass.callWS({ type: "dogassistant/get_dog", dog_id: this._config.dog })
        : null;
    } catch (_) { this._dogs = []; this._dog = null; }
    this._render();
  }
  _actions() {
    const configured = this._config?.quick_actions;
    return (Array.isArray(configured) && configured.length
      ? configured
      : (configured === undefined ? LEGACY_QUICK_ACTIONS : DEFAULT_QUICK_ACTIONS))
      .map((item) => typeof item === "string" ? { action: item } : { ...item })
      .filter((item) => ACTION_LABELS[item.action]);
  }
  _emit(changes) {
    this._config = { ...this._config, ...changes };
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    this._render();
  }
  _render() {
    if (!this.shadowRoot || !this._config) return;
    const actions = this._actions();
    const selected = new Set(actions.map((item) => item.action));
    const available = Object.keys(ACTION_LABELS).filter((action) => !selected.has(action));
    const tabs = new Set(Array.isArray(this._config.tabs) && this._config.tabs.length
      ? this._config.tabs
      : (this._config.tabs === undefined ? LEGACY_TABS : DEFAULT_TABS));
    const quickMeal = actions.find((item) => item.action === "quick-meal");
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;padding:12px}.row{margin-bottom:16px}label,.heading{display:block;margin-bottom:5px;font-weight:600}select,input[type=text]{box-sizing:border-box;width:100%;padding:9px;border:1px solid var(--divider-color);border-radius:7px;background:var(--card-background-color);color:var(--primary-text-color)}
      .action-row{display:grid;grid-template-columns:1fr auto auto auto;align-items:center;gap:5px;padding:6px 0;border-bottom:1px solid var(--divider-color)}button{border:1px solid var(--divider-color);border-radius:7px;padding:6px 9px;background:transparent;color:var(--primary-text-color);cursor:pointer}.add{display:flex;gap:6px;margin-top:8px}.add select{flex:1}.checks{display:grid;grid-template-columns:1fr 1fr;gap:8px}.checks label{font-weight:400}.hint{font-size:.82rem;color:var(--secondary-text-color);margin-top:5px}
    </style>
    <div class="row"><label for="dog">Dog</label><select id="dog"><option value="">Select a dog</option>${(this._dogs || []).map((dog) => `<option value="${esc(dog.id)}" ${dog.id === this._config.dog ? "selected" : ""}>${esc(dog.name)}</option>`).join("")}</select></div>
    <div class="row"><label for="title">Optional card title</label><input id="title" type="text" value="${esc(this._config.title || "")}"></div>
    <div class="row"><span class="heading">Quick actions</span>${actions.map((item, index) => `<div class="action-row"><span>${ACTION_ICONS[item.action]} ${esc(ACTION_LABELS[item.action])}</span><button data-move="${index}:-1" title="Move up" ${index === 0 ? "disabled" : ""}>↑</button><button data-move="${index}:1" title="Move down" ${index === actions.length - 1 ? "disabled" : ""}>↓</button><button data-remove="${index}" title="Remove">✕</button></div>`).join("")}<div class="add"><select id="add-action"><option value="">Add an action…</option>${available.map((action) => `<option value="${action}">${esc(ACTION_LABELS[action])}</option>`).join("")}</select><button id="add-action-button">Add</button></div></div>
    ${quickMeal ? `<div class="row"><label for="meal-food">Quick meal portion</label><select id="meal-food"><option value="">Generic meal</option>${(this._dog?.foods || []).map((food) => `<option value="${esc(food.id)}" ${food.id === quickMeal.food_id ? "selected" : ""}>${esc(food.name)} · ${Number(food.portion_grams)} g</option>`).join("")}</select><div class="hint">The standard Meal action always opens the detailed form. Saved food portions are managed in Records.</div></div>` : ""}
    <div class="row"><span class="heading">Visible tabs</span><div class="checks">${["overview", "timeline", "training", "records", "schedule", "documents"].map((tab) => `<label><input type="checkbox" data-tab-option="${tab}" ${tabs.has(tab) ? "checked" : ""}> ${tab[0].toUpperCase() + tab.slice(1)}</label>`).join("")}</div></div>`;
    this.shadowRoot.querySelector("#dog").addEventListener("change", async (event) => {
      this._emit({ dog: event.target.value });
      await this._load();
    });
    this.shadowRoot.querySelector("#title").addEventListener("change", (event) => this._emit({ title: event.target.value }));
    this.shadowRoot.querySelectorAll("[data-move]").forEach((button) => button.addEventListener("click", () => {
      const [index, direction] = button.dataset.move.split(":").map(Number);
      const reordered = this._actions();
      const [item] = reordered.splice(index, 1);
      reordered.splice(index + direction, 0, item);
      this._emit({ quick_actions: reordered });
    }));
    this.shadowRoot.querySelectorAll("[data-remove]").forEach((button) => button.addEventListener("click", () => {
      const updated = this._actions(); updated.splice(Number(button.dataset.remove), 1);
      this._emit({ quick_actions: updated });
    }));
    this.shadowRoot.querySelector("#add-action-button").addEventListener("click", () => {
      const action = this.shadowRoot.querySelector("#add-action").value;
      if (action) this._emit({ quick_actions: [...this._actions(), { action }] });
    });
    this.shadowRoot.querySelector("#meal-food")?.addEventListener("change", (event) => {
      const updated = this._actions().map((item) => item.action === "quick-meal"
        ? { action: "quick-meal", ...(event.target.value ? { food_id: event.target.value } : {}) }
        : item);
      this._emit({ quick_actions: updated });
    });
    this.shadowRoot.querySelectorAll("[data-tab-option]").forEach((checkbox) => checkbox.addEventListener("change", () => {
      const updated = [...this.shadowRoot.querySelectorAll("[data-tab-option]:checked")].map((item) => item.dataset.tabOption);
      this._emit({ tabs: updated.length ? updated : ["overview"] });
    }));
  }
}

if (!customElements.get("dogassistant-card")) customElements.define("dogassistant-card", DogAssistantCard);
if (!customElements.get("dogassistant-card-editor")) customElements.define("dogassistant-card-editor", DogAssistantCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "dogassistant-card")) {
  window.customCards.push({ type: "dogassistant-card", name: "Dog Assistant", description: "One-tap daily dog care with optional health records", preview: true });
}
console.info(`%c DOGASSISTANT-CARD %c ${DOGASSISTANT_VERSION} `, "color:white;background:#4f7d53;font-weight:700", "color:#4f7d53;background:#edf5ed");
