/* ===========================================================================
   app.js — utilidades compartidas por todas las páginas de la UI.
   
   Se carga en todas las vistas autenticadas. No es un framework: expone un
   objeto global `F` con lo que varias páginas repiten (fetch con CSRF,
   escape de HTML, formato de fechas) y nada más.

   El token CSRF se lee del <meta name="forsis-csrf"> que inyecta base.html, y
   no de window.__CSRF__: la CSP es script-src 'self' sin 'unsafe-inline', de
   modo que un script en linea que defina esa variable nunca se ejecuta y el
   header saldria vacio. Ademas la cookie de CSRF puede estar expirada en el
   navegador mientras el HTML cacheado conserva el token: por eso se acepta
   cualquiera de las dos mitades del doble envio, ya que el servidor exige que
   ambas coincidan con la sesion.
   =========================================================================== */
(function () {
  "use strict";

  /**
   * Token CSRF para las cabeceras mutantes.
   *
   * Prioridad: el <meta> del documento actual (si el HTML esta fresco) y, si
   * no, la cookie `forsis_csrf` (legible por JS a proposito). Se cachea el
   * valor porque leerlo en cada llamada es trabajo inutil.
   */
  let _csrf = null;
  function leerCsrf() {
    if (_csrf) return _csrf;
    const meta = document.querySelector('meta[name="forsis-csrf"]');
    if (meta && meta.content) {
      _csrf = meta.content;
      return _csrf;
    }
    const m = document.cookie.match(/(?:^|;\s*)forsis_csrf=([^;]+)/);
    if (m) {
      _csrf = decodeURIComponent(m[1]);
      return _csrf;
    }
    return "";
  }

  /**
   * fetch con las cabeceras que la API de la UI exige.
   *
   * El CSRF se envía en TODOS los métodos mutantes; el servidor lo rechaza si
   * falta. `credentials: same-origin` es explícito aunque sea el valor por
   * defecto en navegadores modernos: la cookie de sesión es el mecanismo de
   * autenticación y conviene que se vea en el código.
   */
  async function api(url, opciones) {
    const o = Object.assign({ method: "GET", credentials: "same-origin" }, opciones || {});
    o.headers = Object.assign({ "Accept": "application/json" }, o.headers || {});

    if (o.method !== "GET" && o.method !== "HEAD") {
      o.headers["Content-Type"] = "application/json";
      o.headers["X-Forsis-CSRF"] = leerCsrf();
    }
    if (o.cuerpo !== undefined) {
      o.body = JSON.stringify(o.cuerpo);
      delete o.cuerpo;
    }

    const r = await fetch(url, o);

    // Una sesión caída debe llevar al login, no producir un error silencioso
    // en cada página. 401 solo ocurre si la cookie expiró o fue revocada.
    if (r.status === 401) {
      window.location.href = "/ui/login?motivo=expirada";
      throw new Error("sesion_expirada");
    }

    let datos = null;
    try { datos = await r.json(); } catch (e) { /* respuesta sin cuerpo JSON */ }

    if (!r.ok) {
      const err = new Error((datos && datos.answer) || "Error " + r.status);
      err.status = r.status;
      err.payload = datos;
      err.codigo = datos && datos.error && datos.error.code;
      throw err;
    }
    return datos;
  }

  /**
   * Escapa texto para interpolarlo en HTML.
   *
   * Todo lo que viene de la base de datos pasa por aquí antes de tocar
   * innerHTML. Los nombres de usuario y los mensajes son datos que el usuario
   * controla; sin escape, un mensaje con <img onerror> sería XSS almacenado.
   */
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** Fecha ISO -> formato local corto. Cadena vacía si no hay dato. */
  function fecha(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleString("es-MX", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  }

  /** Duración en ms -> texto legible. */
  function duracion(ms) {
    if (ms === null || ms === undefined) return "—";
    if (ms < 1000) return ms + " ms";
    return (ms / 1000).toFixed(1) + " s";
  }

  function pill(estado) {
    const e = String(estado || "").toLowerCase();
    let clase = "pill-warn";
    if (e === "ok" || e === "success") clase = "pill-ok";
    else if (e === "error" || e === "denied" || e === "denegado") clase = "pill-error";
    return '<span class="pill ' + clase + '">' + esc(estado || "—") + "</span>";
  }

  // Cerrar sesión desde la barra superior, presente en toda vista autenticada.
  const btnSalir = document.getElementById("btn-logout");
  if (btnSalir) {
    btnSalir.addEventListener("click", async function () {
      btnSalir.disabled = true;
      try {
        await api("/api/v1/ui/logout", { method: "POST" });
      } catch (e) { /* salir siempre debe salir, incluso si la red falla */ }
      window.location.href = "/ui/login?motivo=salida";
    });
  }

  window.F = { api: api, esc: esc, fecha: fecha, duracion: duracion, pill: pill, csrf: leerCsrf };
})();
