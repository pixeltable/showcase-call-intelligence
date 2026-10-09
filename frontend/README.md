# Frontend

One React UI and one API client ([`src/api/client.ts`](src/api/client.ts)) for both backends. The Vite dev server proxies `/api` to the backend on `VITE_API_PORT`. See the repo [README](../README.md).

- Reference: `VITE_API_PORT=8001 VITE_DEV_PORT=5173 npm run dev`
- Pixeltable: `VITE_API_PORT=8000 VITE_DEV_PORT=5174 npm run dev`
