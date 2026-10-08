/* ===========================================================================
   cuenta.js — cambio de contraseña (§6.11).
   
   La comparación de las dos copias se hace en el cliente solo como cortesía:
   el servidor vuelve a validar longitud y la contraseña actual. Validación de
   cliente es ayuda, nunca control.
   =========================================================================== */
(function () {
  "use strict";
  const F = window.F;

  const form = document.getElementById("form-pass");
  const actual = document.getElementById("actual");
  const nueva = document.getElementById("nueva");
  const nueva2 = document.getElementById("nueva2");
  const msg = document.getElementById("pass-msg");
  const btn = document.getElementById("btn-pass");

  function aviso(texto, esError) {
    msg.textContent = texto;
    msg.className = esError ? "error" : "aviso";
    msg.hidden = false;
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    msg.hidden = true;

    if (nueva.value !== nueva2.value) {
      aviso("Las dos contraseñas nuevas no coinciden.", true);
      nueva2.focus();
      return;
    }
    if (nueva.value.length < 12) {
      aviso("La contraseña nueva debe tener al menos 12 caracteres.", true);
      return;
    }

    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Actualizando…";

    try {
      const d = await F.api("/api/v1/ui/password", {
        method: "POST",
        cuerpo: { actual: actual.value, nueva: nueva.value }
      });
      aviso(d.answer || "Contraseña actualizada.", false);
      form.reset();
    } catch (e) {
      if (e.message !== "sesion_expirada") {
        aviso(e.message || "No se pudo actualizar la contraseña.", true);
      }
    } finally {
      // Las contraseñas se limpian del DOM en cualquier desenlace.
      actual.value = ""; nueva.value = ""; nueva2.value = "";
      btn.disabled = false;
      btn.textContent = original;
    }
  });
})();
