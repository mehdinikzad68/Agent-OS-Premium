// Static demo data (minified names in bundle: Bc, Ec, Nc, Oc, Uc).
// Values copied verbatim from the bundle.

export { T } from "./i18n.js";
export { STATUS_COLOR, SUN, MAG, PALETTE } from "./scene/colors.js";

// Bc
export const AGENTS = [
  {
    id: "hermes",
    name: "Hermes",
    sub: {
      en: "Orchestrator core",
      fa: "هسته‌ی هماهنگ‌کننده",
    },
    status: "running",
    tok: "41.2k",
    load: 72,
    seen: "17:46:02",
  },
  {
    id: "dsh",
    name: "DSH",
    sub: {
      en: "Code agent",
      fa: "عامل کدنویسی",
    },
    status: "running",
    tok: "18.9k",
    load: 64,
    seen: "17:46:01",
    cmd: "REFACTOR MODULE",
    icon: "code",
  },
  {
    id: "docker",
    name: "Docker",
    sub: {
      en: "Workspace runtime",
      fa: "محیط اجرای کار",
    },
    status: "running",
    tok: "2.1k",
    load: 38,
    seen: "17:46:02",
    cmd: "BUILD WORKSPACE",
    icon: "box",
  },
  {
    id: "seo",
    name: "SEO",
    sub: {
      en: "Content optimizer",
      fa: "بهینه‌ساز محتوا",
    },
    status: "awaiting",
    tok: "7.4k",
    load: 21,
    seen: "17:45:51",
    cmd: "PUBLISH META ×38",
    icon: "search",
  },
  {
    id: "wordpress",
    name: "WordPress",
    sub: {
      en: "Site deployer",
      fa: "استقرار سایت",
    },
    status: "awaiting",
    tok: "3.3k",
    load: 15,
    seen: "17:45:58",
    cmd: "ROTATE DB CREDENTIAL",
    icon: "db",
  },
  {
    id: "antigravity",
    name: "Antigravity",
    sub: {
      en: "IDE bridge",
      fa: "پل محیط توسعه",
    },
    status: "offline",
    tok: "0",
    load: 0,
    seen: "16:58:40",
    cmd: "LINK IDE BRIDGE",
    icon: "rocket",
  },
];

// Ec
export const LINKS = [
  {
    from: "hermes",
    to: "dsh",
  },
  {
    from: "hermes",
    to: "antigravity",
  },
  {
    from: "hermes",
    to: "docker",
  },
  {
    from: "hermes",
    to: "seo",
  },
  {
    from: "hermes",
    to: "wordpress",
  },
  {
    from: "docker",
    to: "wordpress",
  },
];

// Nc. Diff rows: [" ", text] context, ["+", text] added, ["-", text] removed,
// ["s", before, redactedHash, after] secret line (rendered as "-" with the value masked).
export const APPROVALS = [
  {
    id: "AG-3107",
    tier: 3,
    agent: "wordpress",
    by: "dsh-agent",
    target: "wp-bioscentiran/wp-config.php",
    title: {
      en: "Rotate production DB credential",
      fa: "چرخش رمز پایگاه‌داده‌ی تولید",
    },
    diff: [
      [" ", "<?php  // wp-config.php"],
      ["s", "define( 'DB_PASSWORD', '", "sha256:41c9…e2a7", "' );"],
      ["+", "define( 'DB_PASSWORD', vault( 'wp/db_pass@v8' ) );"],
      [" ", "define( 'DB_HOST', 'db.internal:3306' );"],
      [" ", "define( 'WP_CACHE', true );"],
    ],
  },
  {
    id: "AG-3109",
    tier: 2,
    agent: "seo",
    by: "seo-content",
    target: "wp-bioscentiran/sitemap + meta",
    title: {
      en: "Publish rewritten meta for 38 pages",
      fa: "انتشار متای بازنویسی‌شده برای ۳۸ صفحه",
    },
    diff: [
      [" ", "<!-- /products/lab-reagents -->"],
      ["-", "<title>Products | Bioscent</title>"],
      ["+", "<title>Lab Reagents & Kits | Bioscent Iran</title>"],
      ["+", "<meta name=\"description\" content=\"ISO-certified reagents…\">"],
      [" ", "<link rel=\"canonical\" href=\"/products/lab-reagents\">"],
    ],
  },
];

// Oc
export const HISTORY = [
  {
    t: "17:31",
    kind: "code",
    agent: "dsh",
    ev: {
      en: "Code change",
      fa: "تغییر کد",
    },
    ref: "dsh-agent",
  },
  {
    t: "17:34",
    kind: "box",
    agent: "docker",
    ev: {
      en: "Container build",
      fa: "ساخت کانتینر",
    },
    ref: "docker-workspace",
  },
  {
    t: "17:37",
    kind: "db",
    agent: "wordpress",
    ev: {
      en: "Plugin install",
      fa: "نصب افزونه",
    },
    ref: "wp-bioscentiran",
  },
  {
    t: "17:39",
    kind: "gate",
    agent: "seo",
    ev: {
      en: "Approval request",
      fa: "درخواست تأیید",
    },
    ref: "seo-content",
  },
  {
    t: "17:41",
    kind: "code",
    agent: "dsh",
    ev: {
      en: "Code change",
      fa: "تغییر کد",
    },
    ref: "dsh-agent",
  },
  {
    t: "17:43",
    kind: "rocket",
    agent: "antigravity",
    ev: {
      en: "Session dropped",
      fa: "قطع نشست",
    },
    ref: "antigravity-ide",
    bad: true,
  },
  {
    t: "17:46",
    kind: "pulse",
    agent: "hermes",
    ev: {
      en: "Heartbeat",
      fa: "ضربان",
    },
    ref: "hermes-core",
  },
];

// Uc
export const cmdFor = (a) => {
  const cmd = `CMD: ${a.cmd || "SYNC " + a.name.toUpperCase()}`;
  const state = { awaiting: "HOLD @ GATE", offline: "NO CARRIER", complete: "ACK" }[a.status];
  return [cmd, state];
};
