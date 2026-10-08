# Inventario de Recursos del Servidor — Forsis

**Fecha:** 2026-10-03 12:17 CST
**Host:** Debian GNU/Linux 12 (bookworm), kernel 6.1.0-39-amd64

---

## 1. CPU

```bash
nproc; lscpu
```

| Métrica | Valor |
|---|---|
| vCPU totales | **16** |
| Sockets | 1 |
| Nodo NUMA 0 | CPUs 0-15 |
| Escalado de frecuencia | 92% |
| Load average (1/5/15 min) | **2.42 / 2.87 / 2.97** |
| Carga relativa | **~18% de 16 núcleos** |

### Consumidores principales de CPU (docker stats, instantánea)

| Contenedor | CPU% |
|---|---|
| trafico-correo-pases-cron | **163.50%** (≈1.6 núcleos sostenidos) |
| omniroute | **65.87%** |
| nextcloud-app | 21.71% |
| onlyoffice | 2.49% |
| immich_server | 2.61% |
| trafico-db | 1.27% |
| Resto | < 1% cada uno |

**Margen disponible:** ~13 núcleos efectivos. Hay holgura amplia, pero los
picos de `trafico-correo-pases-cron` y Omniroute son los vecinos ruidosos a
considerar. El agente debería limitarse a **2 vCPU** para no competir.

---

## 2. Memoria RAM

```bash
free -h; free -m
```

| Métrica | GiB | MiB |
|---|---|---|
| Total | 30 Gi | 31472 |
| Usado | 15 Gi | 15761 |
| Libre | 755 Mi | 646 |
| Compartido | 432 Mi | 433 |
| Búfer/caché | 15 Gi | 15969 |
| **Disponible** | **15 Gi** | **15710** |
| Swap total | 16 Gi | 17360 |
| **Swap usado** | **5.7 Gi** | **5864** |
| Swap libre | 11 Gi | 11496 |

### Interpretación

- **15.7 GB realmente disponibles** (el "libre" de 646 MB es engañoso: 16 GB
  están en caché de página, reclamables por el kernel bajo demanda).
- **Alerta: 5.7 GB de swap en uso (34%).** El sistema ya ha tenido que paginar
  a disco en algún momento de estos 7 días de uptime. Indica presión de
  memoria real, no solo caché. Cualquier contenedor nuevo sin límite agrava
  esto y puede provocar paginación de las bases de datos de producción.

### Consumidores principales de RAM

| Contenedor | Uso | % del host | Límite |
|---|---|---|---|
| omniroute | 1.263 GiB | 4.11% | sin límite |
| mailcow-clamd | 1.047 GiB | 3.41% | sin límite |
| onlyoffice | 617.9 MiB | 1.96% | sin límite |
| immich_server | 472.4 MiB | 1.50% | sin límite |
| trafico-correo-pases-cron | 358.7 MiB | 1.14% | sin límite |
| liquidaciones-php | 334.8 MiB | 1.06% | sin límite |
| nextcloud-app | 331.9 MiB | 1.05% | sin límite |
| forsis-chat (Mattermost) | 301.8 MiB | 0.96% | sin límite |
| trafico-db | 264.6 MiB | 0.84% | sin límite |
| mailcow-ofelia | 244.1 MiB | 0.78% | sin límite |
| trafico-php | 223.1 MiB | 0.71% | sin límite |
| orion-grafana | 197.5 MiB | 0.63% | sin límite |
| nextcloud-db | 193.8 MiB | 0.62% | sin límite |
| openwa-api | 157.6 MiB | 7.69% | **2 GiB** ← único con límite |

**Hallazgo:** de 77 contenedores en ejecución, **solo `openwa-api` declara un
límite de memoria**. Es la práctica a corregir y el estándar que el agente IA
debe adoptar desde el día uno.

**Presupuesto recomendado para forsis-ai-agent:** 2 GB total para todo el
stack (app ~1 GB, BD ~512 MB, nginx ~64 MB), con límites duros declarados.

---

## 3. Almacenamiento

```bash
df -h
```

| Sistema de ficheros | Tamaño | Usados | Disponible | Uso% | Montado en |
|---|---|---|---|---|---|
| **/dev/nvme0n1p2** | **1.8 T** | 489 G | **1.3 T** | **29%** | **/** |
| /dev/sda1 | 5.5 T | 1.7 T | **3.8 T** | 30% | /mnt/63537E674CF73DC0 |
| /dev/nvme0n1p1 | 511 M | 5.9 M | 506 M | 2% | /boot/efi |
| /dev/sdd1 | 7.0 G | 2.8 G | 4.2 G | 40% | /tmp/batboot |
| udev | 16 G | 0 | 16 G | 0% | /dev |
| tmpfs | 3.1 G | 12 M | 3.1 G | 1% | /run |
| tmpfs | 16 G | 1.5 M | 16 G | 1% | /dev/shm |
| tmpfs | 3.1 G | 120 K | 3.1 G | 1% | /run/user/1000 |

### Notas

- **Raíz en NVMe con 1.3 TB libres** — abundante y rápido. Es donde vive
  `/var/lib/docker` y donde irán los volúmenes del agente.
- `/mnt/63537E674CF73DC0` (HDD de 5.5 TB, 3.8 TB libres) alberga datos de
  Nextcloud; liquidaciones monta desde ahí la carpeta
  `nextcloud_data/data/luis01/files/Reseteo de Unidades` en RO. **Es
  almacenamiento masivo, no apto para la BD del agente** (latencia de disco
  mecánico), pero sí para adjuntos/documentos si el agente los necesita.
- `/tmp/batboot` es una unidad externa pequeña, irrelevante.

### Consumo de Docker

```bash
docker system df
```

| Tipo | Total | Activos | Tamaño | Reclamable |
|---|---|---|---|---|
| Imágenes | 73 | 68 | **34.45 GB** | **9.819 GB (28%)** |
| Contenedores | 78 | 77 | 2.017 GB | 0 B |
| Volúmenes locales | 40 | 33 | 5.999 GB | 217.1 MB (3%) |
| Build cache | 278 | 0 | 523.9 MB | **523.9 MB (100%)** |
| **Total** | | | **~43 GB** | **~10.5 GB** |

**Recuperable sin riesgo:** ~10.5 GB vía `docker image prune` +
`docker builder prune`. No es urgente (hay 1.3 TB), pero conviene antes de
construir una imagen nueva de 1.5 GB.

---

## 4. Puertos en uso

```bash
ss -ltnp
```

### 4.1 Puertos publicados por Docker (0.0.0.0 / [::])

| Puerto | Servicio | Contenedor |
|---|---|---|
| 81 | Almacén web | almacen-nginx |
| 110 | POP3 | mailcow-dovecot |
| 143 | IMAP | mailcow-dovecot |
| 443 | HTTPS (host) | — |
| 445 / 139 | SMB | Samba (host) |
| 465 | SMTPS | mailcow-postfix |
| 587 | Submission | mailcow-postfix |
| 993 | IMAPS | mailcow-dovecot |
| 995 | POP3S | mailcow-dovecot |
| 2283 | Immich | immich_server |
| 3306 | MySQL | almacen-db / host |
| 3307 | MariaDB | sicret-pruebas-db |
| 3310 | MariaDB | **trafico-db** |
| 3311 | MariaDB | **atlas-db** |
| 4190 | ManageSieve | mailcow-dovecot |
| 7070 | — | servicio host |
| 8000 | **uvicorn (PID 1203, fuera de Docker)** | ⚠️ colisión con prototipo |
| 8080 | — | servicio host |
| 8081 | phpMyAdmin almacén | almacen-phpmyadmin |
| 8082 | OnlyOffice HTTP | onlyoffice |
| 8086 | mailcow UI | mailcow-nginx |
| 8090 | Nextcloud | nextcloud-app |
| **8095** | **trafico-system HTTPS** | trafico-nginx |
| **8096** | **liquidaciones-system HTTPS** | liquidaciones-nginx |
| **8097** | **ATLAS HTTP** | atlas-nginx |
| **8098** | **ATLAS WebSocket** | atlas-websocket |
| 8443 | OnlyOffice HTTPS | onlyoffice |
| 8444 | mailcow HTTPS | mailcow-nginx |
| 8445 | — | servicio host |
| 8500 | Recovery Dashboard HTTPS | forsis-dashboard-nginx |
| 8501 | Recovery Dashboard HTTP | forsis-dashboard-nginx |
| 18080 | Orion web | orion-nginx |
| 20129 / 20130 | **Omniroute API** | omniroute |
| 20132 | Omniroute Live WS | omniroute |
| 21115-21119 | RustDesk | hbbs / hbbr |
| **25080** | **Mattermost** | forsis-chat |
| 53000 | Grafana | orion-grafana |
| 55432 | TimescaleDB | orion-db |
| 5173 | node (PID 3355, host) | dev server Vite |
| 22 | SSH | sshd |

### 4.2 Puertos solo en loopback (127.0.0.1)

| Puerto | Servicio |
|---|---|
| 25 | SMTP local |
| 631 | CUPS |
| 5432 | PostgreSQL host |
| 6060 | mercurio (PID 39104) |
| 7654 | mailcow redis |
| 13306 | mailcow mysql |
| 19991 | mailcow dovecot stats |
| 20128 | Omniroute dashboard |
| 34021 | VS Code server |

### 4.3 Puertos LIBRES recomendados para el agente

Verificado contra `ss -ltnp`, **ninguno de estos está en uso**:

| Puerto | Propuesta de uso |
|---|---|
| **8099** | **HTTPS público del agente (nginx → 443 interno)** — contiguo a la serie 8095-8098 de los sistemas Forsis, coherente con la convención |
| 8092 / 8093 / 8094 | Reserva en la misma serie (WebSocket del agente, etc.) |
| 8100 | Reserva adicional |
| 3312 | Reserva si se decidiera publicar la BD del agente (**no recomendado**) |

> **Prohibidos:** 8000 (uvicorn host), 5433 (reclamado por el prototipo, mejor
> no publicar BD en absoluto), 8080/8081/8082/8086/8090/8095-8098/8443-8445.

---

## 5. Veredicto de capacidad

| Recurso | Disponible | Necesidad estimada del agente | Holgura |
|---|---|---|---|
| CPU | ~13 núcleos libres | 2 vCPU | ✅ Amplia |
| RAM | 15.7 GB | 2 GB (stack completo) | ✅ Suficiente (vigilar swap) |
| Disco (/) | 1.3 TB en NVMe | ~5 GB imagen + ~10 GB datos/año | ✅ Amplia |
| Puertos | 8099 y serie 809x libres | 1 puerto HTTPS | ✅ |
| Redes | ai-network + patrón external | 2 adhesiones de red | ✅ |

**Conclusión: el servidor puede alojar `forsis-ai-agent` sin ampliación de
hardware.** La única restricción real es la **presión de memoria** (5.7 GB de
swap ya en uso), que obliga a declarar límites duros de recursos en el
contenedor nuevo — algo que hoy ningún otro stack hace y que es el principal
riesgo operativo del host.
