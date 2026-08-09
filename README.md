# LABELOS

A label design & management studio. Design print labels with a live preview,
tune color / size / quantity, and manage a print queue — a small but complete
full-stack app built with the Next.js App Router.

## Tech stack

- **Next.js 15** (App Router) + **React 19** + **TypeScript**
- **Route Handlers** for the REST API (`/api/labels`, `/api/health`)
- File-backed JSON persistence (`.data/labels.json`) for local development
- Hand-crafted CSS design system (no UI framework dependency)

## Getting started

```bash
npm install
npm run dev
```

The app runs at [http://localhost:3000](http://localhost:3000) (bound to `0.0.0.0`).

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start the dev server on `0.0.0.0:3000` |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run lint` | Lint with `eslint-config-next` |
| `npm run typecheck` | Type-check with `tsc --noEmit` |

## API

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/labels` | List labels (newest first) |
| `POST` | `/api/labels` | Create a label (`name`, `text`, `color`, `size`, `quantity`) |
| `DELETE` | `/api/labels/:id` | Delete a label |

## Cloud Agent environment

This repo ships a `.cursor/environment.json` so Cursor Cloud Agents boot with
dependencies installed and the dev server running on port 3000.
