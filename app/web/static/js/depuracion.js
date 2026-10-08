/* ===========================================================================
   depuracion.js — vista de administrador (P5).
   
   Las tres cargas son independientes y se lanzan en paralelo: si las métricas
   fallan, el catálogo igual se muestra. Encadenarlas haría que un endpoint
   caído dejara la página entera vacía.
   =========================================================================== */
(function () {
  "use strict";
  const F = window.F;

  const salud = document.getElementById("salud");
  const capsBody = document.getElementById("caps-body");
  const metricas = document.getElementById("metricas");

  async function cargarSalud() {
    try {
      // /api/v1/ready y no /health: el segundo devuelve texto plano ("healthy")
      // y sólo prueba que el proceso vive. Aquí interesa el estado de BD y LLM.
      const d = await F.api("/api/v1/ready");
      salud.innerHTML = Object.keys(d).map(function (k) {
        const v = d[k];
        const texto = (typeof v === "object") ? JSON.stringify(v) : String(v);
        return "<dt>" + F.esc(k) + "</dt><dd>" + F.esc(texto) + "</dd>";
      }).join("");
    } catch (e) {
      salud.innerHTML = "<dd>No disponible: " + F.esc(e.message) + "</dd>";
    }
  }

  async function cargarCaps() {
    try {
      const d = await F.api("/api/v1/ui/capabilities");
      if (d.degradado) {
        capsBody.innerHTML = '<tr><td colspan="4">Catálogo no disponible.</td></tr>';
        return;
      }
      const items = d.items || [];
      capsBody.innerHTML = items.length
        ? items.map(function (c) {
            return "<tr>" +
              '<td class="mono">' + F.esc(c.id) + "</td>" +
              "<td>" + F.esc(c.nombre) + "</td>" +
              "<td>" + F.esc(c.riesgo) + "</td>" +
              "<td>" + F.esc(c.categoria) + "</td>" +
            "</tr>";
          }).join("")
        : '<tr><td colspan="4">Sin capacidades visibles.</td></tr>';
    } catch (e) {
      capsBody.innerHTML = '<tr><td colspan="4">Error: ' + F.esc(e.message) + "</td></tr>";
    }
  }

  async function cargarMetricas() {
    try {
      const r = await fetch("/api/v1/metrics", { credentials: "same-origin" });
      const texto = await r.text();
      // Se recorta: el objetivo es un vistazo, no volcar un dump enorme en el DOM.
      metricas.textContent = texto.length > 6000 ? texto.slice(0, 6000) + "\n…" : texto;
    } catch (e) {
      metricas.textContent = "No disponible: " + e.message;
    }
  }

  cargarSalud();
  cargarCaps();
  cargarMetricas();
})();
