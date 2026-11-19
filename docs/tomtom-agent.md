# TomTom Agent — interactive maps in the SAS RAM UI

This agent gives a RAM agent live geospatial powers — geocoding, routing, traffic
incidents, POIs, isochrones — and renders the result as a **pretty, interactive,
SAS‑themed map** inside this custom UI.

## How it works

```
RAM agent  ──calls──►  TomTom MCP (remote, Streamable HTTP)
                          ├─ data tools: tomtom-geocode / -routing / -traffic / -poi-search / -reachable-range …
                          └─ tomtom-render-map  ──►  normalized map spec  { kind:"tomtom.map", markers, routes, incidents, areas, … }
                                                          │
RAM returns answer + toolCalls  ──►  this UI  ──►  MapCard (MapLibre GL) renders the spec
```

- RAM (and standard MCP clients) can only show text/JSON, which is why the agent
  emits a **spec** via `tomtom-render-map` instead of a picture. The custom UI
  picks the spec out of the tool‑call output (`extractMapSpec`) and draws a live
  map (`MapCard.jsx`) — the same idea as the SAS `render_chart` flow.
- The map is themed to match the UI (pearl/glass chrome, SAS‑blue routes & markers,
  glass popups), defaults to Dubai, and is bounded to the UAE.

## 1. Register the TomTom MCP in RAM

Self‑host the TomTom MCP (`tomtom-maps-mcp`, HTTP mode) and add it in RAM as a
**Remote MCP server**, transport **Streamable HTTP** — exactly like the SAS MCP:

- **URL:** `http://<tomtom-mcp-host>:<port>/mcp`
- **Auth:** API Key or None
- Server env: `TOMTOM_API_KEY=<key>`, and `MAPS=tomtom-orbis-maps` for the richer
  Orbis tool set (EV routing, search‑along‑route, area‑search, data‑viz) or leave
  default for standard TomTom Maps. `tomtom-render-map` is available on **both**.

## 2. Scope the agent to Dubai / UAE

Two layers (both already biased to the UAE):

1. **Server‑side** — `tomtom-render-map` defaults the map view to Dubai and bounds
   it to the UAE.
2. **Agent prompt** — add to the agent's system prompt so the data tools stay in
   region:

   > You are a mobility assistant for Dubai and the UAE. When calling TomTom
   > search/geocoding tools, restrict results to the UAE (`countrySet=ARE`) and bias
   > toward Dubai. After gathering coordinates/routes/incidents, **always call
   > `tomtom-render-map`** to show the result as an interactive map. Prefer it over
   > `tomtom-static-map` / `tomtom-dynamic-map`.

## 3. Configure the UI map

The map needs a TomTom key in the browser. It is read when the frontend is **built**:

| Where | How |
|---|---|
| `npm run dev` | copy `frontend/.env.example` to `frontend/.env.local` and set the values |
| `docker build` | `--build-arg VITE_TOMTOM_API_KEY=...` |
| Railway | add a service variable with the same name, then redeploy |

- `VITE_TOMTOM_API_KEY`: browser key for map and traffic tiles. It is visible in the page, so
  restrict it to your site's domain.
- `VITE_MAP_STYLE_URL` *(optional)*: a TomTom vector style for 3D buildings / full theming.
- `VITE_MAP_RASTER` *(optional)*: `true` forces the flat raster basemap.

Without a key the map card shows a short note instead of a map; the rest of the answer is
unaffected.

## 4. Try it without a live agent (mock mode)

Start the app in mock mode (`RAM_MOCK=true`, the default in `backend/.env.example`; see the
[README](../README.md#run-it-locally)) and ask anything with "route", "map" or "traffic" in it,
for example "route from Burj Khalifa to Dubai Marina". The UI renders the sample Dubai map
(route, markers, an incident, the traffic toggle). Set `VITE_TOMTOM_API_KEY` to see the basemap tiles.
