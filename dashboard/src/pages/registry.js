// Renderer registry (skill 07): renderer name → component.
// The manifest references NAMES only; this map is the single
// place a name becomes code. An allowlisted name missing here
// resolves to a safe error panel (resolveRenderer), never a crash.

import {
  CommandCanvasPage,
  ResourceDetailPage,
  ResourceTablePage,
  SchemaFormPage,
  TimelinePage,
  BackendLivePage,
} from "./renderers.jsx";

export const RENDERER_REGISTRY = {
  "resource-table": ResourceTablePage,
  "resource-detail": ResourceDetailPage,
  "schema-form": SchemaFormPage,
  timeline: TimelinePage,
  "command-canvas": CommandCanvasPage,
  "backend-live": BackendLivePage,
};
