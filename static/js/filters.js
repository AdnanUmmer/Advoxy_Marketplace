/*
 * Live labels for filter dropdown buttons ("2+ beds · 1+ baths", "$1,000 – $3,000").
 * Used on the home hero and the search filter bar. Translated words come from
 * data-* attributes on the form (data-l-beds, data-l-baths, data-l-from, ...).
 */
document.addEventListener("alpine:init", () => {
  Alpine.data("filterLabels", () => {
    // The form element. Captured once: inside nested dropdowns `this.$el` is the inner element.
    let root = null;
    return {
    tick: 0,
    init() {
      root = this.$el;
      const bump = () => this.tick++;
      root.addEventListener("change", bump);
      root.addEventListener("input", bump);
    },
    t(key) { return (root && root.dataset[key]) || ""; },
    vals(name) {
      this.tick; // re-evaluate when any field changes
      if (!root) return [];
      return [...root.querySelectorAll(`[name="${name}"]`)]
        .filter((i) => (i.type === "checkbox" || i.type === "radio" ? i.checked : true))
        .map((i) => i.value)
        .filter(Boolean);
    },
    typeLabel() {
      const v = this.vals("type");
      if (!v.length) return "";
      const names = v.map((x) => root.querySelector(`[name="type"][value="${x}"]`).dataset.label);
      return names.length > 2 ? names.length + " " + this.t("lTypes") : names.join(", ");
    },
    bedsLabel() {
      const b = this.vals("beds")[0], ba = this.vals("baths")[0], parts = [];
      if (b) parts.push(b + "+ " + this.t("lBeds"));
      if (ba) parts.push(ba + "+ " + this.t("lBaths"));
      return parts.join(" · ");
    },
    priceLabel() {
      const lo = this.vals("price_min")[0], hi = this.vals("price_max")[0];
      const f = (n) => this.t("lSym") + Number(n).toLocaleString();
      if (lo && hi) return f(lo) + " – " + f(hi);
      if (lo) return this.t("lFrom") + " " + f(lo);
      if (hi) return this.t("lUpTo") + " " + f(hi);
      return "";
    },
    };
  });
});
