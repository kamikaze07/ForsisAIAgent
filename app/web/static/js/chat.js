/* ===========================================================================
   chat.js — la vista principal. Implementa los 9 estados de channels.md §2.8.
   
     1 unauthenticated      -> no ocurre aquí (la página redirige antes)
     2 authenticating       -> login.js
     3 idle                 -> compositor activo, sin progreso
     4 waiting_llm          -> "Pensando…"
     5 executing_tool       -> "Consultando <herramienta>…"
     6 rendering            -> se pinta la respuesta
     7 degraded             -> respuesta con aviso ámbar
     8 error                -> 502/504/otros, con reintento cuando aplica
     9 awaiting_confirmation-> diálogo modal L2/L3
   
   El estado vive en una sola variable (`estado`) y una sola función lo aplica
   al DOM (`aplicarEstado`). Repartir `disabled = true` por los manejadores es
   exactamente cómo se consiguen botones que se quedan bloqueados para siempre.
   =========================================================================== */
(function () {
  "use strict";

  const F = window.F;

  const transcripcion = document.getElementById("transcripcion");
  const estadoVacio = document.getElementById("estado-vacio");
  const form = document.getElementById("form-chat");
  const campo = document.getElementById("mensaje");
  const btnEnviar = document.getElementById("btn-enviar");
  const btnNuevo = document.getElementById("btn-nuevo");
  const selEmpresa = document.getElementById("sel-empresa");
  const hiloId = document.getElementById("hilo-id");
  const progreso = document.getElementById("progreso");
  const progresoTexto = document.getElementById("progreso-texto");
  const bitacora = document.getElementById("bitacora");
  const btnCancelar = document.getElementById("btn-cancelar");
  const avisoNoMapeado = document.getElementById("aviso-no-mapeado");
  const dlg = document.getElementById("dlg-confirmar");

  const CLAVE_EMPRESA = "forsis_ui_empresa";

  let estado = "idle";
  let sessionId = null;
  let peticion = null;      // AbortController del turno en vuelo
  let yo = null;            // datos de /me

  // --------------------------------------------------------------- estados

  function aplicarEstado(nuevo, detalle) {
    estado = nuevo;
    const ocupado = (nuevo === "waiting_llm" || nuevo === "executing_tool");

    btnEnviar.disabled = ocupado;
    campo.disabled = ocupado;
    // La empresa no se puede cambiar con un turno en vuelo: la respuesta
    // llegaría etiquetada con una empresa distinta de la consultada.
    selEmpresa.disabled = ocupado || !!sessionId;
    progreso.hidden = !ocupado;
    transcripcion.setAttribute("aria-busy", ocupado ? "true" : "false");

    if (nuevo === "waiting_llm") progresoTexto.textContent = "Pensando…";
    else if (nuevo === "executing_tool") {
      progresoTexto.textContent = detalle
        ? "Consultando " + detalle + "…"
        : "Consultando los sistemas…";
    }
    if (!ocupado) campo.focus();
  }

  // --------------------------------------------------------------- pintado

  function quitarEstadoVacio() {
    if (estadoVacio && estadoVacio.parentNode) estadoVacio.remove();
  }

  function alFinal() {
    transcripcion.scrollTop = transcripcion.scrollHeight;
  }

  function pintarUsuario(texto) {
    quitarEstadoVacio();
    const div = document.createElement("div");
    div.className = "turno turno-user";
    div.innerHTML = '<div class="burbuja">' + F.esc(texto) + "</div>";
    transcripcion.appendChild(div);
    alFinal();
  }

  /**
   * Pinta la respuesta del agente.
   *
   * `datos.answer` se inserta como texto escapado, nunca como HTML: el texto
   * viene de un LLM y de la base de datos, y ninguno de los dos es una fuente
   * de confianza para marcado.
   */
  function pintarAgente(datos) {
    quitarEstadoVacio();
    const div = document.createElement("div");
    const clases = ["turno", "turno-agent"];
    if (datos.status === "error") clases.push("es-error");
    if (datos.status === "degraded") clases.push("es-degradado");
    div.className = clases.join(" ");

    let html = '<div class="burbuja">' + F.esc(datos.answer || "(sin respuesta)") + "</div>";

    // Estado 7: el aviso de degradación va dentro del turno, no en una barra
    // global, para que quede registrado junto a la respuesta afectada.
    if (datos.status === "degraded") {
      html += '<p class="fuente">Respuesta parcial: algunos sistemas no respondieron.</p>';
    }

    if (datos.data && datos.data.rows && datos.data.rows.length) {
      html += tablaDatos(datos.data);
    }

    // Componentes estructurados (cards/tablas) que compone el backend. Van
    // después del texto porque el texto es el resumen y esto es el detalle.
    (datos.components || []).forEach(function (c) {
      html += componente(c);
    });

    // §3.4 citación de fuente: toda cifra debe poder rastrearse.
    const trace = datos.trace || {};
    const ejecs = trace.tool_executions || [];
    if (ejecs.length) {
      const partes = ejecs.map(function (e) {
        return F.esc(e.tool) + (e.rows !== null && e.rows !== undefined ? " (" + e.rows + " filas)" : "");
      });
      html += '<p class="fuente"><span>Fuente: ' + partes.join(" · ") + "</span>";
      if (datos.session_id) {
        html += '<a href="/ui/ejecucion/' + encodeURIComponent(datos.session_id) + '">Ver traza</a>';
      }
      html += "</p>";
    }

    div.innerHTML = html;
    transcripcion.appendChild(div);
    alFinal();
  }

  function tablaDatos(data) {
    const filas = data.rows || [];
    if (!filas.length) return "";
    const cols = data.columns || Object.keys(filas[0]);
    let h = '<div class="tabla-datos"><table class="tabla"><thead><tr>';
    cols.forEach(function (c) { h += "<th scope=\"col\">" + F.esc(c) + "</th>"; });
    h += "</tr></thead><tbody>";
    filas.forEach(function (f) {
      h += "<tr>";
      cols.forEach(function (c) { h += "<td>" + F.esc(f[c]) + "</td>"; });
      h += "</tr>";
    });
    h += "</tbody></table></div>";
    return h;
  }

  /**
   * Renderiza un `UIComponent` del backend. Dos formas:
   *   type="table" -> columns[{key,label,align}] + rows[{key: valor}]
   *   type="card"  -> fields[{label,value}]
   * Todo valor pasa por F.esc: viene de la BD y del LLM.
   */
  function componente(c) {
    if (!c || !c.type) return "";

    if (c.type === "table" && (c.rows || []).length) {
      const cols = c.columns || [];
      let h = '<div class="componente comp-tabla">';
      if (c.title) h += '<p class="comp-titulo">' + F.esc(c.title) + "</p>";
      h += '<div class="tabla-datos"><table class="tabla"><thead><tr>';
      cols.forEach(function (col) {
        const cls = col.align === "right" ? ' class="num"' : "";
        h += '<th scope="col"' + cls + ">" + F.esc(col.label) + "</th>";
      });
      h += "</tr></thead><tbody>";
      c.rows.forEach(function (f) {
        h += "<tr>";
        cols.forEach(function (col) {
          const cls = col.align === "right" ? ' class="num"' : "";
          h += "<td" + cls + ">" + F.esc(f[col.key]) + "</td>";
        });
        h += "</tr>";
      });
      h += "</tbody></table></div>";
      if (c.caption) h += '<p class="comp-nota">' + F.esc(c.caption) + "</p>";
      return h + "</div>";
    }

    if ((c.fields || []).length) {
      let h = '<div class="componente comp-card">';
      if (c.title) h += '<p class="comp-titulo">' + F.esc(c.title) + "</p>";
      h += '<dl class="comp-campos">';
      c.fields.forEach(function (f) {
        h += "<dt>" + F.esc(f.label) + "</dt><dd>" + F.esc(f.value) + "</dd>";
      });
      h += "</dl>";
      if (c.caption) h += '<p class="comp-nota">' + F.esc(c.caption) + "</p>";
      return h + "</div>";
    }

    return "";
  }

  function pintarError(mensaje, reintentable, textoOriginal) {
    quitarEstadoVacio();
    const div = document.createElement("div");
    div.className = "turno turno-agent es-error";
    let html = '<div class="burbuja">' + F.esc(mensaje) + "</div>";
    div.innerHTML = html;

    // El reintento solo se ofrece cuando el servidor lo marca como reintentable
    // (502/504). Ofrecerlo en un 403 solo produciría otro 403.
    if (reintentable && textoOriginal) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "link";
      b.textContent = "Reintentar";
      b.addEventListener("click", function () {
        div.remove();
        enviar(textoOriginal, true);
      });
      div.appendChild(b);
    }
    transcripcion.appendChild(div);
    alFinal();
  }

  // --------------------------------------------------------------- envío

  /**
   * Ejecuta el turno contra el endpoint SSE y va mostrando las etapas.
   *
   * Si el navegador o el servidor no soportan el stream (respuesta sin
   * `text/event-stream`), cae al endpoint síncrono: el turno nunca depende de
   * que el SSE funcione.
   */
  async function turnoStream(texto, signal) {
    const cuerpo = {
      message: texto,
      company: selEmpresa.value,
      session_id: sessionId
    };

    const r = await fetch("/api/v1/ui/chat/stream", {
      method: "POST",
      signal: signal,
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Forsis-CSRF": F.csrf(),
        "Idempotency-Key": crypto.randomUUID()
      },
      body: JSON.stringify(cuerpo)
    });

    if (r.status === 401) throw new Error("sesion_expirada");

    const tipo = r.headers.get("content-type") || "";
    if (!r.ok || !tipo.includes("text/event-stream") || !r.body) {
      // Degradación: endpoint síncrono de siempre.
      return await F.api("/api/v1/ui/chat", {
        method: "POST",
        signal: signal,
        headers: { "Idempotency-Key": crypto.randomUUID() },
        cuerpo: cuerpo
      });
    }

    const lector = r.body.getReader();
    const dec = new TextDecoder();
    let buffer = "";
    let resultado = null;
    let errorEvt = null;

    while (true) {
      const { done, value } = await lector.read();
      if (done) break;
      buffer += dec.decode(value, { stream: true });

      // Los eventos SSE se separan por línea en blanco.
      let corte;
      while ((corte = buffer.indexOf("\n\n")) !== -1) {
        const bruto = buffer.slice(0, corte);
        buffer = buffer.slice(corte + 2);

        let evento = "message";
        let datos = "";
        bruto.split("\n").forEach(function (linea) {
          if (linea.startsWith("event:")) evento = linea.slice(6).trim();
          else if (linea.startsWith("data:")) datos += linea.slice(5).trim();
        });
        if (!datos) continue;

        let payload;
        try { payload = JSON.parse(datos); } catch (e) { continue; }

        if (evento === "stage") {
          aplicarEtapa(payload);
        } else if (evento === "result") {
          resultado = payload;
        } else if (evento === "error") {
          errorEvt = payload;
        }
      }
    }

    if (errorEvt) {
      const err = new Error(errorEvt.answer || "Error del agente");
      err.payload = errorEvt;
      throw err;
    }
    if (!resultado) throw new Error("El servidor cerró la conexión sin responder.");
    return resultado;
  }

  /**
   * Muestra la etapa actual y la acumula en la bitácora del turno, para que el
   * usuario vea qué se hizo y no solo un "Pensando…" opaco.
   */
  function aplicarEtapa(evt) {
    const texto = evt.text || "Procesando…";
    if (evt.stage === "executing_tool") aplicarEstado("executing_tool", null);
    progresoTexto.textContent = texto;
    anotarPaso(texto);
  }

  function anotarPaso(texto) {
    if (!bitacora) return;
    const li = document.createElement("li");
    li.textContent = texto;
    bitacora.appendChild(li);
    bitacora.hidden = false;
    alFinal();
  }

  function limpiarBitacora() {
    if (!bitacora) return;
    bitacora.innerHTML = "";
    bitacora.hidden = true;
  }

  async function enviar(texto, esReintento) {
    if (!texto.trim()) return;
    if (estado === "waiting_llm" || estado === "executing_tool") return;

    if (!esReintento) pintarUsuario(texto);
    limpiarBitacora();
    aplicarEstado("waiting_llm");

    peticion = new AbortController();
    // 504 del lado del cliente: si nginx tarda más que su propio timeout, el
    // usuario ve un mensaje claro en vez de una espera indefinida.
    const reloj = setTimeout(function () { peticion.abort("timeout"); }, 125000);

    try {
      const datos = await turnoStream(texto, peticion.signal);

      if (datos.session_id && !sessionId) {
        sessionId = datos.session_id;
        hiloId.textContent = "hilo " + sessionId.slice(0, 12);
      }

      // Estado 9: el agente pide confirmación antes de una acción L2/L3.
      if (datos.status === "awaiting_confirmation" || datos.requires_confirmation) {
        aplicarEstado("idle");
        pedirConfirmacion(datos, texto);
        return;
      }

      aplicarEstado("rendering");
      pintarAgente(datos);
      aplicarEstado("idle");
    } catch (e) {
      aplicarEstado("idle");

      if (e.message === "sesion_expirada") return;  // app.js ya redirige

      if (e.name === "AbortError") {
        if (peticion && peticion.signal.reason === "timeout") {
          pintarError("La consulta tardó demasiado y se canceló. Puedes reintentarla.",
                      true, texto);
        } else {
          pintarError("Consulta cancelada.", false, null);
        }
        return;
      }

      const reintentable = !!(e.payload && e.payload.error && e.payload.error.retryable) ||
                           e.status === 502 || e.status === 504;
      pintarError(e.message || "Ocurrió un error inesperado.", reintentable, texto);
    } finally {
      clearTimeout(reloj);
      peticion = null;
    }
  }

  // --------------------------------------------------------------- estado 9

  function pedirConfirmacion(datos, textoOriginal) {
    const c = datos.confirmation || {};
    document.getElementById("dlg-titulo").textContent = c.title || "Confirmar acción";
    document.getElementById("dlg-resumen").textContent =
      c.summary || datos.answer || "¿Confirmas esta acción?";

    const ul = document.getElementById("dlg-detalles");
    ul.innerHTML = "";
    (c.details || []).forEach(function (d) {
      const li = document.createElement("li");
      li.textContent = typeof d === "string" ? d : JSON.stringify(d);
      ul.appendChild(li);
    });

    if (typeof dlg.showModal === "function") {
      dlg.showModal();
    }

    dlg.addEventListener("close", function alCerrar() {
      dlg.removeEventListener("close", alCerrar);
      if (dlg.returnValue === "confirm") {
        // El token de confirmación vuelve tal cual: la UI no lo interpreta ni
        // lo reconstruye, solo lo devuelve para que el servidor lo valide.
        enviarConfirmacion(c.token || datos.confirmation_token, textoOriginal);
      } else {
        pintarAgente({ answer: "Acción cancelada. No se modificó nada.", status: "ok" });
      }
    });
  }

  async function enviarConfirmacion(token, textoOriginal) {
    if (!token) {
      pintarError("No se pudo confirmar la acción: falta el token de confirmación.", false, null);
      return;
    }
    aplicarEstado("waiting_llm");
    try {
      const datos = await F.api("/api/v1/ui/chat", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        cuerpo: {
          message: textoOriginal,
          company: selEmpresa.value,
          session_id: sessionId,
          inputs: { confirmation_token: token, confirmed: true }
        }
      });
      aplicarEstado("idle");
      pintarAgente(datos);
    } catch (e) {
      aplicarEstado("idle");
      if (e.message !== "sesion_expirada") {
        pintarError(e.message || "No se pudo ejecutar la acción confirmada.", false, null);
      }
    }
  }

  // --------------------------------------------------------------- eventos

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    const t = campo.value;
    campo.value = "";
    enviar(t, false);
  });

  // Enter envía, Shift+Enter salta línea: convención establecida en mensajería.
  campo.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });

  btnCancelar.addEventListener("click", function () {
    if (peticion) peticion.abort("usuario");
  });

  btnNuevo.addEventListener("click", function () {
    if (estado === "waiting_llm" || estado === "executing_tool") return;
    sessionId = null;
    hiloId.textContent = "";
    transcripcion.innerHTML = "";
    if (estadoVacio) transcripcion.appendChild(estadoVacio);
    aplicarEstado("idle");
  });

  transcripcion.addEventListener("click", function (ev) {
    const sug = ev.target.closest(".sug");
    if (sug) enviar(sug.textContent, false);
  });

  // La empresa elegida se recuerda: cambiarla en cada sesión sería una fuente
  // de consultas accidentales contra la empresa equivocada.
  selEmpresa.addEventListener("change", function () {
    try { localStorage.setItem(CLAVE_EMPRESA, selEmpresa.value); } catch (e) {}
  });

  // --------------------------------------------------------------- arranque

  (async function init() {
    try {
      const guardada = localStorage.getItem(CLAVE_EMPRESA);
      if (guardada) selEmpresa.value = guardada;
    } catch (e) {}

    try {
      yo = await F.api("/api/v1/ui/me");
      if (!yo.mapped) {
        avisoNoMapeado.textContent =
          "Tu cuenta no está vinculada a un usuario de los sistemas Forsis. " +
          "Las consultas de datos serán denegadas hasta que un administrador la vincule.";
        avisoNoMapeado.hidden = false;
      }
    } catch (e) { /* /me no es crítico para escribir el primer mensaje */ }

    aplicarEstado("idle");
  })();
})();
