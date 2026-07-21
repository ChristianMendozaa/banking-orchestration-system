# Sistema de Orquestación

El despliegue local publica dos interfaces independientes desde la misma imagen de
frontend. Ambas utilizan el mismo backend y la misma base de datos.

| Interfaz | URL predeterminada | Contenido |
| --- | --- | --- |
| Kiosco | `http://localhost:3000` | Atención pública del kiosco |
| Personal | `http://localhost:3001` | Login, operación ejecutiva y panel gerencial |

Cada contenedor valida su modo con `APP_SURFACE` y rechaza con `404` tanto las páginas
como las familias API pertenecientes a la otra interfaz.

## Configuración

Si todavía no existen los archivos locales de entorno:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Reemplace en `backend/.env` todas las credenciales y secretos de ejemplo. Para cambiar
los puertos u orígenes públicos, configure en `.env`:

```dotenv
KIOSK_FRONTEND_PORT=3000
STAFF_FRONTEND_PORT=3001
KIOSK_FRONTEND_ORIGIN=http://localhost:3000
STAFF_FRONTEND_ORIGIN=http://localhost:3001
```

Los valores de origen deben coincidir con las URLs que utilizará el navegador, también
cuando se despliegue detrás de dominios o proxies reversos.

## Ejecución

```bash
docker compose up --build --remove-orphans
```

`--remove-orphans` retira contenedores de servicios antiguos, como el anterior
`frontend`, sin eliminar los volúmenes de PostgreSQL ni de conocimiento. El servicio
`frontend-kiosk` construye la imagen compartida y `frontend-staff` reutiliza exactamente
esa misma imagen.

Servicios principales:

- `frontend-kiosk`: interfaz exclusiva de kiosco.
- `frontend-staff`: interfaz de ejecutivos y gerencia.
- `backend`: API compartida en `http://localhost:8000`.
- `postgres`: PostgreSQL con pgvector.

Para comprobar el estado:

```bash
docker compose ps
curl -I http://localhost:3000/
curl -I http://localhost:3001/
```

La raíz del puerto 3000 redirige a `/kiosco`; la del puerto 3001 redirige a `/login`.
