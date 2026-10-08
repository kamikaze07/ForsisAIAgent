# Sprint 5 — Identidad desde `trafico-system`

> Estado: **aprobado por el usuario** (diseño), pendiente de aprobación de implementación.
> Decisión de arranque: "una sola contraseña para toda la empresa; las credenciales del
> agente son las mismas que las de `trafico-system`; si el usuario ya tiene sesión en
> tráfico, no debe tener que escribirla otra vez."

---

## 1. Por qué este sprint

El Sprint 4 dejó la UI operativa pero con identidad propia:

- `agent_ui_users` tiene `password_hash` argon2id sembrado a mano (3 cuentas de prueba).
- `traf_username` / `liq_nombre_usu` vienen vacíos, así que toda consulta de negocio cae en
  `ROL_NO_MAPEADO` (`web-ui-design.md` §B-U8) y el usuario ve el aviso
  "Tu cuenta no está vinculada a un usuario de los sistemas Forsis".

`web-ui-design.md` §2.1 justify el login propio ("identidad **I2 — Login propio del
agente**", cuyo papel es *vincular* al humano con las cuentas de servicio y **no** ser
credencial para los ERP). Ese diseño es correcto y **se mantiene**: el agente conserva su
propia sesión, sus propias cookies y su propio control de acceso a la UI.

Lo que este sprint cambia es **de dónde sale la credencial**: no una credencial nueva del
agente, sino la del usuario en tráfico. La identidad I2 sigue siendo del agente; la
*autenticación* pasa a ser delegada.

---

## 2. Decisión: verificación en vivo, sin hashes locales

### 2.1 Qué se descartó y por qué

| Opción | Por qué no |
|---|---|
| **A. Credencial argon2id propia + auto-relleno del mapeo** | No cumple el requisito. El usuario seguiría necesitando una contraseña *del agente*, distinta de la de tráfico. Es la contradicción central de este sprint. |
| **1. SSO por token emitido por tráfico** | Técnicas la opción correcta a futuro, pero exige **modificar `trafico-system`**, que sigue bajo la restricción "sólo lectura". No hay nada que delegar todavía. Se documenta como deuda técnica (§7). |
| **C. Sembrar los 36 usuarios una vez** | Se desincroniza solo. `role`, `access_forsis` y `deactivated_at` cambian en tráfico y el agente no se entera. |

### 2.2 Lo que se hace

El login del agente verifica **contra `trafico.usuarios`**, en vivo, por el canal de
solo lectura que ya existe desde el Sprint 2 (`readonly_pool`, destino `trafico`).

```
usuario + contraseña
   └─> SELECT sobre trafico.usuarios  (columnas explícitas, nunca SELECT *)
         ├─ no hay fila / access_forsis=0 / deactivated_at -> error genérico
         ├─ verificación por password_algorithm (argon2id | md5_legacy | bcrypt)
         └─> JIT en agent_ui_users: crea o refresca el mapeo
               └─> sesión propia del agente (forsis_agent_ui_session)
```

**El hash de tráfico no se persiste nunca.** Se lee, se verifica y se descarta. En el
agente no queda copia de ningún hash de producción.

Esto **no abre ninguna brecha de permisos**: `forsis_agent_ro` ya tiene `SELECT` sobre
`trafico.usuarios` desde el Sprint 2, y ya podía leer esos hashes antes de este sprint.
Lo que se hace es usar un permiso que ya existía, no conceder uno nuevo.

### 2.3 Restricción de columnas

`sql_guard` filtra **verbos**, no columnas. Por eso la consulta de identidad proyecta
columnas explícitas y nunca `SELECT *`: el resto de `usuarios` (`session_version`,
`last_login_at`, `created_by`) no tiene nada que ver con autenticar a alguien.

---

## 3. Esquema verificado en vivo

Leído con `information_schema` desde el contenedor del agente, 2026-10-05:

| Columna | Tipo | Null | Default | Uso en este sprint |
|---|---|---|---|---|
| `id` | bigint unsigned | NO | — | — |
| `username` | varchar(50) | NO | — | **Login** |
| `password_hash` | varchar(255) | NO | — | **Verificación, no persistido** |
| `password_algorithm` | enum('md5_legacy','argon2id','bcrypt') | NO | `'md5_legacy'` | **Selecciona el verificador** |
| `access_forsis` | tinyint(1) | NO | `1` | **Gate** |
| `access_sicret` | tinyint(1) | NO | `1` | No se usa (kill-switch de SICRET escritorio) |
| `role` | varchar(50) | NO | — | **Derivación de rol de UI** |
| `role_id` | int unsigned | SÍ | `NULL` | **No se usa**: NULL en 35/36 |
| `employee_id` | int unsigned | SÍ | `NULL` | No se usa en este sprint (ver §6) |
| `email` | varchar(120) | SÍ | `NULL` | — |
| `session_version` | int unsigned | NO | `1` | No se usa (cubre la sesión PHP, no la nuestra) |
| `created_by` / `created_at` / `updated_at` | — | NO | — | — |
| `deactivated_at` | datetime | SÍ | `NULL` | **Gate** |
| `last_login_at` | datetime | SÍ | `NULL` | — |

**36 filas, todas con `access_forsis = 1`.** Reparto de algoritmos: 22 `md5_legacy`,
14 `argon2id`. Ningún `bcrypt` en uso, pero se soporta.

---

## 4. Roles: `SUPER USUARIO` es el admin

Distribución real de `role` entre los 36 usuarios con `access_forsis = 1`:

| Rol de tráfico | N | Rol en la UI |
|---|---|---|
| **SUPER USUARIO** | 8 | **`admin`** |
| TRÁFICO | 11 | `validador` |
| ADMINISTRADOR (= QHSE) | 4 | `validador` |
| FACTURACIÓN | 4 | `validador` |
| CUENTAS POR PAGAR | 3 | `validador` |
| LIQUIDACIONES | 2 | `validador` |
| RESETEOS | 2 | `validador` |
| SUPERVISOR DE CUENTAS POR PAGAR | 1 | `validador` |
| RECURSOS HUMANOS | 1 | `validador` |

**Sólo `SUPER USUARIO` es `admin`.** `ADMINISTRADOR` es el rol real de QHSE — administra
Unidades, no Guías — y tráfico lo tiene explícitamente excluido de operar Guías desde antes
del cambio que abrió Guías a Facturación y QHSE (`AuthorizationService.php:96-102`).
`AuthorizationService::esSuperUsuario()` (línea 34-37) lo confirma como el único privileged
de ese tipo, y está en `PRIVILEGIOS_PERMITIDOS` (línea 8).

Los 8 `SUPER USUARIO` activos: `CESAR01`, `DIRECCION`, `GERARDO`, `JOSUE`, `KOFUZ01`,
`SUSANA`, `usuarioadmin1`, `VICTORIANO`.

### 4.1 El mapa vive en configuración

La traducción rol-de-tráfico → rol-de-UI se declara en `.env`, no en Python: si tráfico
añade un rol, se ajusta el entorno y no se toca código.

```
UI_ADMIN_ROLES=SUPER USUARIO
```

Sólo se implementan los dos valores que `agent_ui_users.role` admite (`admin`,
`validador`). Cualquier rol no listado cae en `validador` — **fail closed**.

### 4.2 `agent_ui_users.role` y `trafico.usuarios.role` son escalas distintas

- `agent_ui_users.role` → gobierna la **UI**: quién ve `/ui/depuracion`, quién ve datos de
  otros usuarios.
- `trafico.usuarios.role` → gobierna los **datos de tráfico**: qué consultas tiene sentido
  responderle.

No se acoplan más allá de la traducción de arriba. Acoplarlas fully sería un error: un
`SUPER USUARIO` de tráfico no debería por definición tener la depuración del agente, y un
`admin` de la UI no debería por definición poder ver guías.

---

## 5. Cambios

### 5.1 Migración 07 — `agent_ui_users` sin credencial local

- `password_hash` → **NULL** (ya no se verifica localmente).
- Los 3 registros existentes quedan con `password_hash = NULL`.

`role`, `is_active`, `failed_attempts`, `locked_until`, `agent_roles`,
`write_allowlisted`, `traf_username`, `liq_nombre_usu` se conservan intactos. El control de
lockout y el de rol de UI siguen siendo locales, que es lo correcto: son política del
agente, no de tráfico.

### 5.2 Nuevo módulo `app/web/identity.py`

- `verificar_credenciales(username, password) → IdentityResult`
  - SELECT con columnas explícitas (§3).
  - Gate: fila existe ∧ `access_forsis = 1` ∧ `deactivated_at IS NULL`.
  - Verificación según `password_algorithm`; **cualquier valor fuera del enum falla cerrado**.
  - Mensaje de error **genérico** en todos los fallos: *"Usuario o contraseña incorrectos."*
    Nunca *"ese usuario no existe"* — anti-enumeración, igual que tráfico
    (`AuthenticationService.php:48`).
- `derivar_rol_ui(role_trafico) → {admin, validador}` según §4.1.
- **Nunca** escribe `password_hash` de tráfico.

### 5.3 `app/web/auth.py`

`login()` deja de verificar localmente y delega en `identity.py`. Sesiones, cookies,
lockout y `resolve_session()` **sin cambios**. La자는 suplementary validaciones de
`agent_ui_users` (rol, `is_active`) se mantienen.

### 5.4 Plantillas

`cuenta.html` y `chat.js` siguen usando `mapped = traf_username or liq_nombre_usu`. Como el
mapeo se resuelve en cada login, el aviso amarillo deja de aparecer para toda cuenta que
autoprovisione.

---

## 6. Fuera de alcance (y por qué)

**Departamento por usuario.** Se puede derivar por
`trafico.usuarios.employee_id → sicrePR.empleados.clave_depa → departamentos`, pero
`sicrePR.empleados` contiene NSS, RFC, domicilio, fecha de nacimiento y salarios
(`salarioimss`, `salarioReal`). No se toca en este sprint. Va al Sprint 6 con un
requirement propio de minimización de datos.

**Matriz rol-de-tráfico → capacidades del agente.** `web-ui-design.md` no la define.
Problema real que queda abierto: tráfico excluye a `ADMINISTRADOR` (QHSE) de operar Guías,
así que el agente no debería responderle consultas de Guías — si lo hace, se convierte en
un camino para saltarse un control que tráfico ya aplica. Se registra como riesgo (§7) y
se resuelve en el Sprint 6, no se inventa aquí.

**Autenticación contra `liquidaciones-system`.** Fuera de alcance; su riesgo es mayor
(77 usuarios con contraseña vacía, `permissions.md` §5 D-1).

---

## 7. Riesgos asumidos

1. **`trafico-db` caído ⇒ nadie puede iniciar sesión en la UI.** Dependencia nueva y real.
   Aceptada: tráfico es el sistema crítico de la empresa de todos modos, y amortiguarla
   exigiría cachear hashes — justo lo que este diseño evita.
2. **Hashes de producción legibles por el canal RO.** Permiso preexistente del Sprint 2,
   no una brecha nueva. Se asume explícitamente.
3. **22 de 36 usuarios siguen en `md5_legacy` (MD5 sin sal).** El agente **no puede**
   disparar la migración perezosa a argon2id que tráfico hace en login, porque escribir en
   tráfico está prohibido. No es responsabilidad de este sprint y no se "arregla" aquí;
   se reporta al equipo de tráfico.
4. **El agente depende de la Dupla de los permisos de tráfico.** Si tráfico endurece el
   grant sobre `usuarios`, el login deja de funcionar. Riesgo de acoplamiento.
5. **`role` es texto libre** copiado de `priv` legacy, con riesgo de drift documentado en
   `schema_usuarios.sql:22`. `role_id` está NULL en 35/36, así que el RBAC de
   `roles`/`permisos` es documentación, no autoridad — no se usa como fuente de verdad.

## 8. Deuda técnica registrada

**SSO con token emitido por tráfico** (`trafico.usuarios_integraciones` existe, 0 filas).
Es la solución correcta: el usuario se autentica una vez y no hay segunda contraseña ni
lectura de hashes por parte del agente. Requiere un endpoint de token firmado en tráfico, lo
que exige levantar la restricción de "sólo lectura". Cuando se levante, este sprint es lo
que se reemplaza — por eso el diseño isolate la verificación en `identity.py`, un solo
módulo, en vez de dispersarla en `auth.py`.

---

## 9. Verificación

Suite `verify-sprint5.sh`, siguiendo el patrón de los sprints anteriores:

- Migración aplicada y `password_hash` NULL en las 3 filas.
- `SUPER USUARIO` → `admin`; los otros 8 roles → `validador`.
- Login correcto contra tráfico → 200 + cookie + mapeo poblado.
- Contraseña incorrecta → error genérico (no revela existencia del usuario).
- Usuario inexistente → **exactamente el mismo** error y el mismo código.
- `access_forsis = 0` → denegado.
- `deactivated_at` no nulo → denegado.
- `password_algorithm` con valor inesperado → **fail cerrado**.
- Ningún `password_hash` de tráfico escrito en `agent_ui_users`.
- El aviso de "no vinculado" desaparece tras el login.
- Regresión: las 4 suites previas siguen pasando.