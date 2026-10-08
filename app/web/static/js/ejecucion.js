/* ===========================================================================
   ejecucion.js — visor de traza de un hilo (§6.4, criterio A13).
   
   El session_id se lee de la URL, no de una variable inyectada en la plantilla:
   así el enlace es compartible y recargar la página funciona. Un 404 aquí
   significa "no existe o no es tuyo" (A-6) y se muestra sin distinguir, que es
   justamente el punto.
   =========================================================================== */
(function () {
  "use strict";
  const F = window.F;

  const estadoBox = document.getElementById("ejec-estado");
  const cuerpo = document.getElementById("ejec-cuerpo");
  const turnos = document.getElementById("turnos");
  const toolsBody = document.getElementById("tools-body");
  const sinTools = document.getElementById("sin-tools");

  const partes = window.location.pathname.split("/");
  const sessionId = decodeURIComponent(partes[partes.length - 1] || "");

  async function cargar() {
    if (!sessionId) {
      estadoBox.textContent = "Falta el identificador de la conversación.";
      return;
    }
    try {
      const d = await F.api("/api/v1/ui/sessions/" + encodeURIComponent(sessionId));

      turnos.innerHTML = (d.turns || []).map(function (t) {
        const quien = t.role === "user" ? "Usuario" : "Agente";
        let h = "<li><strong>" + quien + "</strong>";
        if (t.status) h += " " + F.pill(t.status);
        h += '<br><span class="mono">' + F.fecha(t.created_at) + "</span>";
        h += "<div>" + F.esc(t.content) + "</div>";
        if (t.trace_id) h += '<div class="mono">trace ' + F.esc(t.trace_id) + "</div>";
        return h + "</li>";
      }).join("");

      const tools = d.tool_executions || [];
      if (tools.length) {
        toolsBody.innerHTML = tools.map(function (t) {
          return "<tr>" +
            "<td>" + F.esc(t.tool) + "</td>" +
            "<td>" + F.esc(t.risk_class) + "</td>" +
            "<td>" + F.pill(t.status) + "</td>" +
            "<td>" + (t.rows === null || t.rows === undefined ? "—" : F.esc(t.rows)) + "</td>" +
            "<td>" + F.duracion(t.ms) + "</td>" +
          "</tr>";
        }).join("");
      } else {
        sinTools.hidden = false;
      }

      estadoBox.hidden = true;
      cuerpo.hidden = false;
    } catch (e) {
      estadoBox.textContent = e.message || "No se pudo cargar la traza.";
      estadoBox.className = "error";
    }
  }

  cargar();
})();
