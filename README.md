# TouchSpace AI

**Scan a Space. Feel the Layout. Explore with Confidence.**

TouchSpace AI turns real indoor spaces into 3D-printable tactile maps for blind and visually impaired people, and pairs them with a voice assistant that answers questions about the space. Built for Cal Hacks 13.0.

## Workflow

Scan Room (iPhone/iPad LiDAR + RoomPlan) → Export JSON → Upload → Process Geometry → Generate Tactile Map → Preview 3D → Download STL → Print

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | React + TypeScript + Vite web app |
| `backend/` | FastAPI service: RoomPlan import, floor-plan processing, STL generation, routing, voice Q&A |
| `ios-scanner/` | SwiftUI RoomPlan scanner app |
| `sample-data/` | Synthetic demo fixtures (not real venue scans) |
| `docs/` | Architecture and usage docs |

## Status

Work in progress. Setup instructions will be added as each part lands.
