/* ===========================================================================
   login.js — estados 1 (unauthenticated) y 2 (authenticating).
   
   Esta página NO carga app.js: antes del login no hay CSRF ni sesión, y el
   botón de salir no existe. El fetch se escribe aquí a mano por eso.
   =========================================================================== */
(function () {
  "use strict";

  const form = document.getElementById("form-login");
  const btn = document.getElementById("btn-entrar");
  const cajaError = document.getElementById("login-error");
  const campoUsuario = document.getElementById("username");
  const campoPass = document.getElementById("password");

  function mostrarError(msg) {
    cajaError.textContent = msg;
    cajaError.hidden = false;
  }

  function limpiarError() {
    cajaError.hidden = true;
    cajaError.textContent = "";
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    limpiarError();

    const usuario = campoUsuario.value.trim();
    const pass = campoPass.value;
    if (!usuario || !pass) {
      mostrarError("Escribe tu usuario y contraseña.");
      return;
    }

    // Estado 2: el formulario completo se bloquea, no solo el botón. Un doble
    // Enter durante la espera generaría dos intentos y acercaría el lockout.
    btn.disabled = true;
    campoUsuario.disabled = true;
    campoPass.disabled = true;
    const textoOriginal = btn.textContent;
    btn.textContent = "Entrando…";

    try {
      const r = await fetch("/api/v1/ui/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ username: usuario, password: pass })
      });

      let datos = null;
      try { datos = await r.json(); } catch (e) { /* sin cuerpo */ }

      if (r.ok) {
        // La contraseña nunca se conserva en memoria más de lo necesario.
        campoPass.value = "";
        window.location.href = (datos && datos.redirect) || "/ui/chat";
        return;
      }

      mostrarError((datos && datos.answer) || "No se pudo iniciar sesión.");

      // Tras un lockout el formulario queda inservible a propósito: reactivar
      // los campos invitaría a seguir intentando durante el bloqueo.
      if (r.status === 429) {
        btn.textContent = "Cuenta bloqueada";
        return;
      }
    } catch (e) {
      mostrarError("No hay conexión con el servidor. Revisa tu red e inténtalo otra vez.");
    }

    btn.disabled = false;
    campoUsuario.disabled = false;
    campoPass.disabled = false;
    btn.textContent = textoOriginal;
    campoPass.value = "";
    campoPass.focus();
  });
})();
