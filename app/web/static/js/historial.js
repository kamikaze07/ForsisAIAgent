/* ===========================================================================
   historial.js — página de historial (§6.3). Paginación simple vía offset:
   no hay cursor porque el volumen esperado por usuario es de cientos, no de
   millones de hilos; un offset es más fácil de razonar y de depurar.
   =========================================================================== */
(function () {
  "use strict";
  const F = window.F;

  const estadoBox = document.getElementById("hist-estado");
  const tabla = document.getElementById("tabla-hist");
  const body = document.getElementById("hist-body");
  const selEmpresa = document.getElementById("f-empresa");
  const chkErrores = document.getElementById("f-errores");
  const chkTodos = document.getElementById("f-todos");
  const btnPrev = document.getElementById("btn-prev");
  const btnNext = document.getElementById("btn-next");
  const pagInfo = document.getElementById("pag-info");

  const LIMITE = 25;
  let offset = 0;

  function qs(params) {
    const u = new URLSearchParams();
    Object.keys(params).forEach(function (k) {
      if (params[k] !== "" && params[k] !== null && params[k] !== undefined) u.set(k, params[k]);
    });
    return u.toString();
  }

  async function cargar() {
    tabla.hidden = true;
    estadoBox.hidden = false;
    estadoBox.textContent = "Cargando…";

    const params = {
      limit: LIMITE,
      offset: offset,
      company: selEmpresa.value,
      only_errors: chkErrores.checked,
      scope: (chkTodos && chkTodos.checked) ? "all" : "mine"
    };

    try {
      const datos = await F.api("/api/v1/ui/sessions?" + qs(params));
      pintar(datos.items || []);
      btnPrev.disabled = offset === 0;
      btnNext.disabled = (datos.items || []).length < LIMITE;
      pagInfo.textContent = "Desde " + (offset + 1);
    } catch (e) {
      estadoBox.textContent = e.message || "No se pudo cargar el historial.";
    }
  }

  function pintar(items) {
    if (!items.length) {
      estadoBox.textContent = "No hay conversaciones que coincidan con los filtros.";
      estadoBox.hidden = false;
      tabla.hidden = true;
      return;
    }
    estadoBox.hidden = true;
    tabla.hidden = false;
    body.innerHTML = items.map(function (it) {
      return "<tr>" +
        '<td><a href="/ui/ejecucion/' + encodeURIComponent(it.session_id) + '">' +
          F.esc(it.titulo) + "</a></td>" +
        "<td>" + F.esc(it.company) + "</td>" +
        "<td>" + F.esc(it.mensajes) + "</td>" +
        "<td>" + F.pill(it.ultimo_status) + "</td>" +
        "<td>" + F.fecha(it.last_seen_at) + "</td>" +
      "</tr>";
    }).join("");
  }

  [selEmpresa, chkErrores, chkTodos].forEach(function (el) {
    if (!el) return;
    el.addEventListener("change", function () { offset = 0; cargar(); });
  });

  btnPrev.addEventListener("click", function () {
    offset = Math.max(0, offset - LIMITE);
    cargar();
  });
  btnNext.addEventListener("click", function () {
    offset += LIMITE;
    cargar();
  });

  cargar();
})();
