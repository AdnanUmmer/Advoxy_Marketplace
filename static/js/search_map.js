/*
 * Search page map (Mapbox GL JS + Mapbox GL Draw).
 * - Price-bubble pins for the current results; clicking one opens a preview card.
 * - Hovering a result card highlights its pin.
 * - "Search this area" filters to the visible map bounds; the draw tool filters to a drawn polygon.
 * - The distance filter measures from the map centre.
 * Pins come from <script id="map-pins"> in the results partial and refresh after every HTMX swap.
 */
(function () {
  "use strict";

  const STYLE = "mapbox://styles/mapbox/light-v11";
  const AFRICA = [[-20, -36], [55, 38]];
  let map, draw, markers = new Map(), popup, userMoved = false, programmaticMove = false;

  const $ = (sel) => document.querySelector(sel);
  const form = () => $("#search-form");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function readJSON(id) {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  function submit() {
    htmx.trigger(form(), "submit");
  }

  function setArea(ring) {
    $("#id_area").value = ring ? ring.map((p) => p[0].toFixed(5) + "," + p[1].toFixed(5)).join(";") : "";
  }

  function previewHTML(p) {
    const facts = [p.beds ? p.beds + " bd" : "", p.baths ? p.baths + " ba" : ""].filter(Boolean).join(" · ");
    return (
      '<a href="' + esc(p.url) + '" class="block w-[220px] text-ink no-underline">' +
      (p.photo ? '<img src="' + esc(p.photo) + '" alt="" class="h-[120px] w-full rounded-t-[10px] object-cover">' : "") +
      '<div class="p-3"><div class="font-display text-lg leading-tight">' + esc(p.price) + (p.rent ? ' <span class="text-xs text-muted">/ mo</span>' : "") + "</div>" +
      '<div class="mt-0.5 text-sm font-medium leading-snug">' + esc(p.title) + "</div>" +
      (facts ? '<div class="mt-1 text-xs text-muted">' + esc(facts) + "</div>" : "") + "</div></a>"
    );
  }

  function renderPins(fit) {
    const pins = readJSON("map-pins") || [];
    markers.forEach((m) => m.remove());
    markers.clear();
    if (popup) popup.remove();
    const bounds = new mapboxgl.LngLatBounds();
    pins.forEach((p) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "price-pin" + (p.featured ? " is-featured" : "");
      el.textContent = p.price;
      el.setAttribute("aria-label", p.title + ", " + p.price);
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        popup = new mapboxgl.Popup({ offset: 18, closeButton: true, maxWidth: "240px", className: "pin-popup" })
          .setLngLat([p.lng, p.lat]).setHTML(previewHTML(p)).addTo(map);
      });
      const marker = new mapboxgl.Marker({ element: el, anchor: "bottom" }).setLngLat([p.lng, p.lat]).addTo(map);
      markers.set(String(p.id), marker);
      bounds.extend([p.lng, p.lat]);
    });
    if (fit && pins.length) {
      programmaticMove = true;
      map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
    }
  }

  function wireCardHover() {
    document.querySelectorAll("#results [data-listing-id]").forEach((card) => {
      const id = card.dataset.listingId;
      card.addEventListener("mouseenter", () => markers.get(id)?.getElement().classList.add("is-active"));
      card.addEventListener("mouseleave", () => markers.get(id)?.getElement().classList.remove("is-active"));
    });
  }

  function init(el) {
    map = new mapboxgl.Map({ container: el, style: STYLE, bounds: AFRICA, cooperativeGestures: false });
    el.mapInstance = map; // handy for debugging and browser tests
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");

    draw = new MapboxDraw({ displayControlsDefault: false, controls: { polygon: true, trash: true } });
    map.addControl(draw, "top-left");

    // Restore a drawn area from the URL.
    const area = $("#id_area").value;
    map.on("load", () => {
      if (area) {
        const ring = area.split(";").map((p) => p.split(",").map(Number));
        ring.push(ring[0]);
        draw.add({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } });
      }
      renderPins(true);
      wireCardHover();
    });

    const onDraw = () => {
      const shapes = draw.getAll().features.filter((f) => f.geometry.type === "Polygon");
      const last = shapes[shapes.length - 1];
      if (shapes.length > 1) shapes.slice(0, -1).forEach((f) => draw.delete(f.id));
      setArea(last ? last.geometry.coordinates[0].slice(0, -1) : null);
      $("#id_near").value = "";
      submit();
    };
    map.on("draw.create", onDraw);
    map.on("draw.update", onDraw);
    map.on("draw.delete", onDraw);

    // "Search this area" after the user pans or zooms.
    const areaBtn = $("#search-area-btn");
    map.on("moveend", () => {
      if (programmaticMove) { programmaticMove = false; return; }
      userMoved = true;
      areaBtn.hidden = false;
    });
    areaBtn.addEventListener("click", () => {
      const b = map.getBounds();
      draw.deleteAll();
      setArea([[b.getWest(), b.getSouth()], [b.getEast(), b.getSouth()], [b.getEast(), b.getNorth()], [b.getWest(), b.getNorth()]]);
      areaBtn.hidden = true;
      submit();
    });

    // Distance filter measures from the map centre.
    $("#id_radius").addEventListener("change", (e) => {
      const c = map.getCenter();
      $("#id_near").value = e.target.value ? c.lat.toFixed(5) + "," + c.lng.toFixed(5) : "";
    }, true);

    document.body.addEventListener("htmx:afterSwap", (e) => {
      if (e.detail.target.id !== "results") return;
      renderPins(!userMoved && !$("#id_area").value);
      wireCardHover();
      areaBtn.hidden = true;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const tokenEl = document.querySelector("[data-mapbox-token]");
    const el = document.getElementById("search-map");
    if (!tokenEl || !el || typeof mapboxgl === "undefined") return;
    mapboxgl.accessToken = tokenEl.dataset.mapboxToken;
    init(el);
    // Clearing the area also clears the drawing.
    document.body.addEventListener("click", (e) => { if (e.target.closest("[data-clear-area]")) draw && draw.deleteAll(); });
  });
})();
