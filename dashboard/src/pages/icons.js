// Icon identifier → component map for declarative navigation.
//
// Manifests store icon NAMES from the allowlist (data only);
// this module is the only place that turns a name into a
// component. Unknown names (a manifest from a future version)
// fall back to a neutral glyph — the entry still renders and
// stays usable, never a crash.

import {
  Activity,
  Box,
  Bot,
  Brain,
  CircleQuestionMark,
  Code,
  Cpu,
  Database,
  FileText,
  Globe,
  History,
  House,
  Layers,
  Network,
  Plus,
  Rocket,
  Search,
  Settings,
  Shield,
  Wrench,
} from "lucide-react";

export const ICON_MAP = {
  home: House,
  rocket: Rocket,
  network: Network,
  bot: Bot,
  cpu: Cpu,
  wrench: Wrench,
  history: History,
  "file-text": FileText,
  settings: Settings,
  help: CircleQuestionMark,
  shield: Shield,
  memory: Brain,
  activity: Activity,
  layers: Layers,
  globe: Globe,
  database: Database,
  code: Code,
  box: Box,
  search: Search,
  plus: Plus,
};

/** Resolve an icon name; unknown names get a neutral fallback. */
export function iconFor(name) {
  return ICON_MAP[name] || CircleQuestionMark;
}
