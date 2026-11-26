/*
 * Mapbox helpers. Loaded only on pages that need a map and only when a
 * Mapbox token is configured. Elements opt in with data attributes:
 *   data-map-picker  : draggable pin that writes to #id_latitude / #id_longitude
 *   data-map-view    : read-only map with one pin (data-lat, data-lng)
 */
(function () {
  "use strict";
  const STYLE = "mapbox://styles/mapbox/light-v11";

  function pinElement() {
    // Mapbox positions the outer element with a transform, so the styled pin is a child.
    const el = document.createElement("div");
    el.setAttribute("aria-hidden", "true");
    const pin = document.createElement("span");
    pin.className = "map-pin block";
    el.appendChild(pin);
    return el;
  }

  function initPicker(el) {
    const latInput = document.getElementById("id_latitude");
    const lngInput = document.getElementById("id_longitude");
    const hasValue = latInput.value && lngInput.value;
    // Default view: the African continent.
    const center = hasValue ? [parseFloat(lngInput.value), parseFloat(latInput.value)] : [20, 2];
    const map = new mapboxgl.Map({ container: el, style: STYLE, center, zoom: hasValue ? 14 : 2.4, cooperativeGestures: true });
    el.mapInstance = map; // handy for debugging and browser tests
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }));
    const marker = new mapboxgl.Marker({ element: pinElement(), draggable: true, anchor: "bottom" });

    function write(lngLat) {
      latInput.value = lngLat.lat.toFixed(6);
      lngInput.value = lngLat.lng.toFixed(6);
      latInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function place(lngLat) {
      marker.setLngLat(lngLat).addTo(map);
      write(marker.getLngLat());
    }
    if (hasValue) marker.setLngLat(center).addTo(map);
    marker.on("dragend", () => write(marker.getLngLat()));
    map.on("click", (e) => place(e.lngLat));
    // Typing coordinates moves the pin.
    [latInput, lngInput].forEach((input) =>
      input.addEventListener("input", () => {
        const lat = parseFloat(latInput.value), lng = parseFloat(lngInput.value);
        if (Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
          marker.setLngLat([lng, lat]).addTo(map);
          map.easeTo({ center: [lng, lat] });
        }
      })
    );
  }

  function initView(el) {
    const lngLat = [parseFloat(el.dataset.lng), parseFloat(el.dataset.lat)];
    const map = new mapboxgl.Map({ container: el, style: STYLE, center: lngLat, zoom: 13.5, cooperativeGestures: true });
    el.mapInstance = map;
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }));
    new mapboxgl.Marker({ element: pinElement(), anchor: "bottom" }).setLngLat(lngLat).addTo(map);
  }

  document.addEventListener("DOMContentLoaded", function () {
    const tokenEl = document.querySelector("[data-mapbox-token]");
    if (!tokenEl || typeof mapboxgl === "undefined") return;
    mapboxgl.accessToken = tokenEl.dataset.mapboxToken;
    document.querySelectorAll("[data-map-picker]").forEach(initPicker);
    document.querySelectorAll("[data-map-view]").forEach(initView);
  });
})();
