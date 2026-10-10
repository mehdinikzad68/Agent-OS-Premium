# گزارش ممیزی پروژه — Agent-OS Neural Command (React source)

| | |
|---|---|
| **تاریخ ممیزی** | ۲۰۲۶-۱۰-۱۰ (Asia/Tehran) |
| **محدوده** | `agent-os-neural-command-robot-React-source` (پروژهی واحد) |
| **روش** | Read-only: خواندن تمام فایلهای متنی، بررسی ایستای نسخهها/اسکریپتها، پوشش امنیتی؛ **بدون** اجرای build/test/install، **بدون** تغییر هیچ فایل پروژهای |
| **زبان گزارش** | فارسی (مسیرها، شناسههای کد و اصطلاحات فنی به شکل اصلی) |
| **وضعیت اصلاحات** | ✅ **فاز ۰ (ISS-01، ISS-02، ISS-03/16) در تاریخ ۲۰۲۶-۱۰-۱۰ اعمال و با ۱۷۰/۱۷۰ تست سبز تأیید شد** — جزئیات در [بخش ۷ — اصلاحات اعمالشده](#7-اصلاحات-اعمالشدهفاز-۰) |

> **⚠️ اعلان پوشش (بالای گزارش): پوشش کامل حاصل نشده است.**
> خارج از پوشش/خوانده‌نشده:
> - ۱۲ فایل PNG در `visual-baseline/` — **Unreadable** (مدلِ این نشست قابلیت ورودی تصویر ندارد؛ فقط ابعاد از هدر PNG خوانده شد)
> - ۳۰ فایل `woff2` در `public/fonts/` — **Unreadable (binary)**
> - `package-lock.json` — **Partially read** (خطوط ۱–۶۰ خطبه‌خط؛ بقیه با بررسی ساختاری/تطبیق نسخه)
> - `src/fonts.css` — **Partially read** (خطوط ۱–۸۰ خطبه‌خط؛ خطوط ۸۱–۴۰۹ خطبه‌خط خوانده نشد، اما هر ۴۵ بلوک `@font-face` به‌صورت ماشینی استخراج و بررسی شد)
> - `node_modules/` (~۷۴۴۷ فایل) — **Skipped** (vendored/generated، طبق دستور)
>
> **تغییرات فایل‌سیستم:** تنها فایلِ ایجادشده، همین گزارش (`AUDIT-REPORT.md`) است؛ هیچ فایل از پروژه تغییر داده، منتقل یا حذف نشد.

---

## فهرست

1. [خلاصهی مدیریتی](#0-خلاصهی-مدیریتی)
2. [خلاصهی پوشش](#1-خلاصهی-پوشش)
3. [فایل‌انباره (Inventory)](#2-فایل‌انباره-inventory)
4. [درک پروژه](#3-درک-پروژه)
5. [وضعیت بر پایهی ابعاد](#4-وضعیت-بر-پایهی-ابعاد)
6. [مشکلات و ریسک‌های اولویت‌بندی‌شده](#5-مشکلات-و-ریسکهای-اولویتبندیشده)
7. [پرسش‌های باز](#6-پرسش‌های-باز)

---

## 0. خلاصهی مدیریتی

وضعیت کلی: پروژه‌ای منسجم، تمیز و معماراً تفکیک‌شده (مدل خالص / آداپتر / رندر) با ۱۶۲ تست واحد و مستندسازی فنی خوب؛ اما لایهی React — که هیچ تستی آن را پوشش نمی‌دهد — دو باگ کارکردی جدی دارد.

1. **پوشش:** ۷۵ فایل کامل‌خوانده‌شده، ۲ فایل بخشی، ۴۲ فایل غیرقابل‌خواندن (باینری/تصویر)، ۱ مجموعه Skip شده (`node_modules`)، مجموع فایل‌های پروژه ۱۱۹.
2. **ریسک ۱ (High):** دو مسیرِ ذخیره‌سازی روی یک کلید legacy باعث **تکثیر نماییِ custom tools در هر reload** می‌شود [Inferred].
3. **ریسک ۲ (Medium):** بازیابی حافظهی مشترک در UI همیشه با خطای `no shared-memory provider configured` شکست می‌خورد [Observed].
4. **ریسک 3 (Medium):** اعتبارسنجی ضعیفِ import می‌تواند باعث crash کل اپ (`a.sub[lang]`) یا شمارش‌های NaN شود [Observed].

---

## 1. خلاصهی پوشش

| وضعیت | تعداد | توضیح |
|---|---|---|
| Fully read | ۷۵ | تمام فایل‌های متنی `src/`، `tests/`، `skills/`، `docs/`، ریشهی پروژه، `visual-baseline/README.md`، `.freebuff/project-id`، `public/fonts/.gitkeep` |
| Partially read | ۲ | `package-lock.json`، `src/fonts.css` (دلایل در بالا) |
| Unreadable | ۴۲ | ۱۲ تصویر PNG + ۳۰ فونت WOFF2 |
| Skipped | ۱ مجموعه (~۷۴۴۷ فایل) | `node_modules/` (vendored) |
| **مجموع فایل‌های پروژه (بدون node_modules)** | **۱۱۹** | |

---

## 2. فایل‌انباره (Inventory)

### 2.1 ریشه، پیکربندی، اسناد

| Path | Type | Size | Read status | Notes |
|---|---|---|---|---|
| `.gitignore` | config | 0.1 KB | Fully read | `node_modules/`، `dist/`، `.env*` |
| `README.md` | doc | 0.4 KB | Fully read | فقط ۱۸ خط؛ ادعای نادرست دربارهی Google Fonts (ISS-04) |
| `package.json` | config | 0.5 KB | Fully read | اسکریپت‌های `dev`/`build`/`preview`/`test` |
| `package-lock.json` | lock | 86.4 KB | Partially read | خطوط ۶۱–۲۶۴۶ خوانده نشد؛ ساختار (lockfileVersion 3، ۱۷۷ بسته) و تطابق نسخه‌ها بررسی شد |
| `index.html` | entry | 0.3 KB | Fully read | `lang="en"` هاردکد (ISS-13) |
| `vite.config.js` | config | 0.1 KB | Fully read | فقط پلاگین `react()` |
| `tailwind.config.js` | config | 0.6 KB | Fully read | content + تمِ فونت/radius |
| `postcss.config.js` | config | 0.1 KB | Fully read | `tailwindcss` + `autoprefixer` |
| `.freebuff/project-id` | data | ~0 KB | Fully read | یک UUID؛ غیرمحرمانه |
| `docs/adapter-contract.md` | doc | 6.2 KB | Fully read | قرارداد آداپتر (skill 08) |
| `visual-baseline/README.md` | doc | 2.2 KB | Fully read | ادعای ۱۶۲ تست و build (ISS-10) |
| `skills/README.md` | doc | 1.4 KB | Fully read | فهرست ۱۰ skill |
| `skills/00-global-guardrails.md` | doc | 1.8 KB | Fully read | دستورالعمل عاملِ کدنویسی (به‌عنوان داده رفتار شد) |
| `skills/01-source-inspection.md` | doc | 1.8 KB | Fully read | « |
| `skills/02-canvas-graph-model.md` | doc | 2.3 KB | Fully read | « |
| `skills/03-fiber-interaction.md` | doc | 2.8 KB | Fully read | « (ISS-14) |
| `skills/04-draft-apply-persistence.md` | doc | 2.7 KB | Fully read | « |
| `skills/05-shared-memory-mock.md` | doc | 2.2 KB | Fully read | « (ISS-02) |
| `skills/06-subagent-clusters-timeline.md` | doc | 3.0 KB | Fully read | « |
| `skills/07-dynamic-navigation-pages.md` | doc | 1.8 KB | Fully read | « |
| `skills/08-backend-adapter-contract.md` | doc | 2.5 KB | Fully read | « |
| `skills/09-visual-regression.md` | doc | 1.6 KB | Fully read | « |

### 2.2 `src/` (۴۰ فایل)

| Path | Type | Size | Read status | Notes |
|---|---|---|---|---|
| `src/main.jsx` | entry | 0.3 KB | Fully read | `createRoot` + `Suspense` |
| `src/App.jsx` | source | 33.4 KB | Fully read | ۹۸۱ خط؛ لایهی بدون تست (ISS-01/02/03/16) |
| `src/data.js` | source | 3.6 KB | Fully read | داده‌های دمو؛ hash ماسکشده در خط ۱۳۶ |
| `src/i18n.js` | source | 19.7 KB | Fully read | کاتالوگ EN/FA؛ کلیدهای بلااستفاده (ISS-08) |
| `src/index.css` | style | 5.8 KB | Fully read | `@import "./fonts.css"` در خط ۴ |
| `src/fonts.css` | style | 18.5 KB | Partially read | ۴۵ بلوک `@font-face` ماشینی بررسی شد |
| `src/adapter/mockAdapter.js` | source | 19.5 KB | Fully read | ۵۷۲ خط |
| `src/adapter/storage.js` | source | 10.5 KB | Fully read | اعتبارسنجی ورودی (ISS-03/16) |
| `src/adapter/memoryProvider.js` | source | 1.5 KB | Fully read | mock فقط‌خواندنی |
| `src/model/index.js` | source | 0.3 KB | Fully read | barrel |
| `src/model/registry.js` | source | 5.5 KB | Fully read | اعتبارسنج موجودیت‌ها |
| `src/model/connections.js` | source | 5.8 KB | Fully read | جدول `PORT_RULES` |
| `src/model/view.js` | source | 7.3 KB | Fully read | فقط چیدمان |
| `src/model/draft.js` | source | 6.3 KB | Fully read | تاریخچهی محدود ۱۰۰ |
| `src/model/memory.js` | source | 1.4 KB | Fully read | سیاست دسترسی |
| `src/model/runtime.js` | source | 16.7 KB | Fully read | ۵۱۵ خط، reducer خالص |
| `src/model/manifest.js` | source | 11.1 KB | Fully read | ناوبری/صفحات دادهمحور |
| `src/model/seed.js` | source | 16.4 KB | Fully read | ۵۱۷ خط |
| `src/components/Header.jsx` | source | 2.7 KB | Fully read | |
| `src/components/Sidebar.jsx` | source | 3.8 KB | Fully read | دکمهی Help بدون handler (ISS-07) |
| `src/components/Btn.jsx` | source | 0.4 KB | Fully read | |
| `src/components/Gate.jsx` | source | 7.8 KB | Fully read | hold-to-approve برای tier 3 |
| `src/components/StatusCard.jsx` | source | 9.4 KB | Fully read | `a.sub[lang]` بدون نگهبان (ISS-03) |
| `src/components/AddTool.jsx` | source | 5.3 KB | Fully read | تولید id (ISS-18) |
| `src/components/DraftBar.jsx` | source | 6.9 KB | Fully read | |
| `src/components/WorkspaceTools.jsx` | source | 7.0 KB | Fully read | preview قبل از import |
| `src/components/NavCustomizer.jsx` | source | 11.7 KB | Fully read | |
| `src/components/MemoryInspector.jsx` | source | 5.0 KB | Fully read | |
| `src/components/Timeline.jsx` | source | 9.7 KB | Fully read | |
| `src/components/ConnectionPicker.jsx` | source | 1.5 KB | Fully read | |
| `src/pages/PageRouter.jsx` | source | 3.2 KB | Fully read | |
| `src/pages/registry.js` | source | 0.6 KB | Fully read | |
| `src/pages/renderers.jsx` | source | 10.9 KB | Fully read | نگهبان `a.sub ?` (ناهمگون با StatusCard) |
| `src/pages/icons.js` | source | 1.1 KB | Fully read | |
| `src/scene/NeuralScene.jsx` | source | 40 KB | Fully read | ۱۱۵۴ خط، کامل |
| `src/scene/layout.js` | source | 7.2 KB | Fully read | |
| `src/scene/head.js` | source | 1.7 KB | Fully read | |
| `src/scene/backdrop.js` | source | 1.6 KB | Fully read | |
| `src/scene/colors.js` | source | 0.9 KB | Fully read | |
| `src/scene/random.js` | source | 0.4 KB | Fully read | `mulberry32` |

### 2.3 `tests/` (۱۳ فایل — همه Fully read)

| Path | Size | تعداد `test(` | Notes |
|---|---|---|---|
| `tests/adapter.test.js` | 20.8 KB | ۲۶ | قرارداد آداپتر + سیاست حافظه |
| `tests/clusters.test.js` | 6.0 KB | ۹ | خوشه‌ها/freshness |
| `tests/connections.test.js` | 6.1 KB | ۱۶ | سازگاری پورت، چرخه |
| `tests/contract.test.js` | 4.8 KB | ۵ | capabilityها + پویش URL در src |
| `tests/draft.test.js` | 6.5 KB | ۱۲ | draft/undo/redo |
| `tests/layout.test.js` | 3.7 KB | ۱۰ | هندسهی بِزیر |
| `tests/manifest.test.js` | 8.3 KB | ۱۸ | اعتبارسنجی manifest/صفحات |
| `tests/memory.test.js` | 2.0 KB | ۴ | سیاست دسترسی |
| `tests/registry.test.js` | 2.9 KB | ۱۱ | ریجستری |
| `tests/runtime.test.js` | 6.9 KB | ۱۳ | reducer رویداد |
| `tests/seed.test.js` | 8.2 KB | ۱۳ | سازگاری seed با مدل |
| `tests/storage.test.js` | 11.0 KB | ۱۵ | ذخیره‌سازی/import/export |
| `tests/view.test.js` | 3.3 KB | ۱۰ | مدل view |
| **مجموع** | | **۱۶۲** | شمارش ایستا؛ اجرای واقعی انجام نشد |

### 2.4 `visual-baseline/` (۱۳ فایل)

| Path | Type | Size | Read status | Notes |
|---|---|---|---|---|
| `visual-baseline/README.md` | doc | 2.2 KB | Fully read | روش capture و محدودیت‌ها |
| `before/01-fa-home-980x766-before.png` | image | 776.3 KB | Unreadable | 1225×958 (از هدر PNG) |
| `before/02-en-home-980x766-before.png` | image | 766.7 KB | Unreadable | 1225×958 |
| `before/03-fa-1440x900-before.png` | image | 1071.1 KB | Unreadable | 1800×1125 |
| `before/04-fa-390x844-before.png` | image | 172.3 KB | Unreadable | 488×1055 (برش) |
| `before/05-en-1440x900-before.png` | image | 1055.7 KB | Unreadable | 1800×1125 |
| `before/06-en-390x844-before.png` | image | 169.3 KB | Unreadable | 488×1055 (برش) |
| `after/01-fa-home-980x766-after.png` | image | 776.6 KB | Unreadable | 1225×958 |
| `after/02-en-home-980x766-after.png` | image | 780.0 KB | Unreadable | 1225×958 |
| `after/03-fa-1440x900-after.png` | image | 1071.8 KB | Unreadable | 1800×1125 |
| `after/04-fa-390x844-after.png` | image | 173.1 KB | Unreadable | 488×1055 (برش) |
| `after/05-en-1440x900-after.png` | image | 1052.9 KB | Unreadable | 1800×1125 |
| `after/06-en-390x844-after.png` | image | 170.5 KB | Unreadable | 488×1055 (برش) |

ابعاد PNG با ادعای `visual-baseline/README.md:23-28` (DPR برابر ۱٫۲۵، برش موبایل) سازگار است [Observed]؛ اما **محتوای بصری قابل‌تأیید نیست** [Unknown].

### 2.5 `public/fonts/` (۳۱ فایل)

| Path | Type | Read status | Notes |
|---|---|---|---|
| `public/fonts/.gitkeep` | data | Fully read | خالی (۰ بایت) |
| `public/fonts/5aU19_...SjQpf.woff2` ×2 (69.5 / 69.8 KB) | binary | Unreadable (binary) | |
| `public/fonts/5aU19_...RSjQpf.woff2` ×2 (9.3 KB هر کدام) | binary | Unreadable (binary) | |
| `public/fonts/5aU19_...ySjQ.woff2` ×2 (16.4 / 16.2 KB) | binary | Unreadable (binary) | |
| `public/fonts/5aU69_...Oz.woff2` ×3 (8.9 / 73.2 / 15.8 KB) | binary | Unreadable (binary) | |
| `public/fonts/cIflMap...bIl1*.woff2` ×4 | binary | Unreadable (binary) | Chakra Petch |
| `public/fonts/cIflMap...bJI91*.woff2` ×4 | binary | Unreadable (binary) | Chakra Petch |
| `public/fonts/cIflMap...bQI51*.woff2` ×4 | binary | Unreadable (binary) | Chakra Petch |
| `public/fonts/Dxxo8...*.woff2` ×3 (21.3 / 45.2 / 33.7 KB) | binary | Unreadable (binary) | Vazirmatn — هر فایل برای ۴ وزن مشترک (فونت متغیر) |
| `public/fonts/tDbv2o...*.woff2` ×6 (1.6 تا 30.7 KB) | binary | Unreadable (binary) | |

کنترل انجام‌شده [Observed]: هر ۳۰ URL ارجاع‌شده در `src/fonts.css` در `public/fonts/` موجود است؛ هر ۳۰ فایل حداقل یک‌بار استفاده شده (۴۵ ارجاع، ۳۰ فایل یکتا، ۰ مفقود، ۰ بلااستفاده).

### 2.6 Skip شده

| Path | Reason |
|---|---|
| `node_modules/` (~۷۴۴۷ فایل) | وابستگی‌های vendored/generated — طبق دستور Skip شد |
| `.git/` | **وجود ندارد** (`Test-Path .git` = False) — با `visual-baseline/README.md:3` همخوان است [Observed] |

هیچ `.env*`، `.github/`، `.gitlab-ci`، `.circleci`، ESLint/Prettier/tsconfig در سطح پروژه یافت نشد [Observed].

---

## 3. درک پروژه

### 3.1 ماهیت و هدف

- این یک بازسازیِ منبعِ Vite + React از یک artifact به نام «Agent-OS Neural Command» است: `README.md:3` — «Reconstructed Vite + React source for the Agent-OS Neural Command artifact» [Observed].
- رابط، یک داشبورد «مأموریت‌کنترل» فارسی/انگلیسی با یک هولوگرام Canvas 2D در مرکز، گره‌های عامل/ابزار، گِیت تأیید درخواست‌های حساس، خط‌زمانی اجراها و صفحات ناوبریِ داده‌محور است: `src/App.jsx:733-955`، `src/scene/NeuralScene.jsx` [Observed].
- داده‌ها و بکاند **MOCK/دمو** هستند و این موضوع در کد برچسب‌خورده: `src/adapter/mockAdapter.js:1-21`، برچسب `mock-tag` در `src/index.css:293-305`، `src/pages/PageRouter.jsx:91` [Observed].

### 3.2 اجزای اصلی و جریان داده

1. **ورود:** `index.html:10` ← `src/main.jsx:1-13` ← `src/App.jsx` (۹۸۱ خط، تمام state در همین کامپوننت) [Observed].
2. **لایهی مدلِ خالص** (بدون React/DOM/شبکه): `src/model/index.js:1-9`
   - `registry.js` — موجودیت‌ها + اعتبارسنج؛ کوآردیناتور با **نقش** (kind) پیدا می‌شود نه id (`registry.js:127-130`)
   - `connections.js` — جدول صریح سازگاری پورت (`PORT_RULES`، خطوط ۲۱–۲۶) و سیاست چرخه per-type (خط ۳۴)
   - `view.js` — فقط چیدمان؛ هرگز پیکربندی عملیاتی نیست (`view.js:1-7`)
   - `draft.js` — تغییرات عملیاتی + undo/redo با تاریخچهی محدود ۱۰۰ (`draft.js:11`)
   - `runtime.js` — reducer رویداد اجرا با dedupe و ردِ رویداد کهنه (`runtime.js:122-238`)
   - `manifest.js` — ناوبری/صفحات داده‌محور با allowlist (`manifest.js:12-42`)، بدون `eval`
3. **seed:** `src/model/seed.js:455-488` داده‌های `src/data.js` را به مدل تبدیل می‌کند (ریجستری، اتصالات، runtime با دو مأموریت mock، manifest، صفحات، حافظهی مشترک) [Observed].
4. **آداپتر:** `src/adapter/mockAdapter.js:347-571` — قرارداد چهار-حقیقتی (supported / authorized / available / configured)، نتایج تایپدار بهجای throw (`:56-59`)، اعمال ترتیبیِ per-op با `status: ok | partial | failed | noop` (`:325-334`) [Observed].
5. **پایدارسازی:** `src/adapter/storage.js:187-268` (خواندن/نوشتن با `schemaVersion` و اعتبارسنجی بخش‌به‌بخش) **به‌علاوه** یک مسیر مستقیم `localStorage` در `App.jsx:62-74` [Observed].
6. **رندر:** `NeuralScene.jsx` (Canvas 2D + overlay HTML؛ حلقهی انیمیشن روی ref، خطوط ۲۱۹–۶۲۰)، کامپوننت‌های `src/components/*`، و روتینگ صفحات `src/pages/PageRouter.jsx:25-74` [Observed].
7. **جریان تغییرات:** کاربر در حالت Edit ← `addChange` به draft ← `applyDraft` (`App.jsx:266-302`) ← نتایج per-op ← ذخیره‌ی debounced با ۳۰۰ms (`App.jsx:585-597`) [Observed].

### 3.3 فناوری و نسخه‌های واقعاً یافته‌شده

| جزء | نسخه‌ی اعلامی (`package.json:12-23`) | نسخه‌ی نصب‌شده در `node_modules` |
|---|---|---|
| react / react-dom | 18.3.1 | 18.3.1 [Observed] |
| lucide-react | 0.577.0 | 0.577.0 [Observed] |
| vite | 5.4.11 | 5.4.11 [Observed] |
| @vitejs/plugin-react | 4.3.4 | 4.3.4 [Observed] |
| tailwindcss | 3.4.18 | 3.4.18 [Observed] |
| postcss | 8.5.23 | 8.5.23 [Observed] |
| autoprefixer | 10.4.20 | 10.4.20 [Observed] |

- همهی وابستگی‌ها **پین‌شده** (بدون `^`) و با `package-lock.json` (lockfileVersion 3، ۱۷۷ بسته، ۱۷۷ `resolved` + ۱۷۷ `integrity`) سازگارند [Observed].
- زبان: JavaScript ESM (`"type": "module"`، `package.json:5`)؛ بدون TypeScript (فقط JSDoc در `registry.js:14-33`) [Observed].
- تست: `node --test` بومی (`package.json:10`) — بدون Jest/Vitest/jsdom [Observed].
- محیط مشاهدهشده (نهِ پروژه): Node v22.23.2، npm 10.9.8.

### 3.4 زیرپروژه‌ها و ارتباط آن‌ها

پروژه‌ای واحد است. `skills/` (۱۰ سند دستورالعمل برای عاملِ کدنویس)، `docs/` و `visual-baseline/` پوشه‌های همین پروژه‌اند و ارتباط‌شان با کد در خودِ فایل‌ها اثبات شده:

- ارجاع صریح به skillها در کد: `src/index.css:269-270` («skill 07»)، `src/App.jsx:51` («skill 07»)، `src/App.jsx:129-130` («skill 08») [Observed].
- ارجاع `visual-baseline/README.md:17` به `src/scene/NeuralScene.jsx:230` [Observed].

ارتباط با یک backend واقعی خارجی (`\\wsl.localhost\...\Agent-OS`) فقط در `docs/adapter-contract.md:113` توصیف شده و در این مخزن موجود نیست [Unknown].

---

## 4. وضعیت بر پایهی ابعاد

### 4.1 کامل بودن و پیشرفت

- **کامل و پیاده‌سازی‌شده** [Observed]: مدل‌ها، آداپتر mock، پایدارسازی، ناوبری داده‌محور، گیت تأیید، خوشه‌های زیرعامل، خط‌زمانی، import/export، RTL/FA، بازپخش مشاهده‌ای.
- **بدون هیچ نشانه‌ای از** `TODO|FIXME|XXX|HACK|stub` **در `src/`** [Observed] (پویش تنها `placeholder`های مربوط به inputها را یافت).
- **عناصر مرده/ناتمام** [Observed]:
  - دکمهی `Filter` بدون handler — `src/App.jsx:775`
  - دکمهی `Help` در Sidebar بدون handler — `src/components/Sidebar.jsx:92-98`
  - سه متدِ declareشده‌ی unsupported در آداپتر — `src/adapter/mockAdapter.js:562-570` (مستندشده در `docs/adapter-contract.md:141-145`)
- **کد بلااستفاده** [Observed]: importهای بلااستفاده در `src/App.jsx:8` (`setPosition`, `setFiberMidpoint`) و `src/App.jsx:34` (`SUN`)؛ کلیدهای بلااستفاده در `src/i18n.js:66-69, 83-85` (`evAdd`, `evRemove`, `core`, `signal`, `chooseType`, `invalidTarget`, `validTarget`).
- **فایل خالی:** فقط `public/fonts/.gitkeep` [Observed].

### 4.2 معماری و ساختار

- تفکیک لایه‌ها صریح و مستند است: مدل خالص بدون React (`src/model/index.js:1-2`)، آداپتر پشت یک interface (`src/adapter/storage.js:1-18`)، رندر بدون منطق backend (`src/scene/NeuralScene.jsx:1-14`) [Observed].
- قواعد دامنه به‌صورت جدول داده‌ای اعلام شده‌اند نه شرط‌های پراکنده: `src/model/connections.js:21-34`، `src/model/manifest.js:12-42` [Observed].
- انسجام خوب؛ بوتل‌های سالم (`src/model/index.js`)؛ تکرار معنادار اندک: منطق ذخیره‌سازی در دو جا (`src/App.jsx:62-74` و `src/adapter/storage.js`) — ریشه‌ی ISS-01 [Observed].
- **تناقض در سطح defensive بودن** [Observed]: `src/pages/renderers.jsx:43` از `a.sub ?` استفاده می‌کند، ولی `src/App.jsx:665` و `src/components/StatusCard.jsx:24` بدون نگهبان `a.sub[lang]` می‌خوانند.

### 4.3 کیفیت و صحت کد

**نکات مثبت** [Observed]:

- توابع خالص و بدون mutation با تست خلوص (`tests/adapter.test.js:93-95`، `tests/view.test.js:48-53`)
- خطاهای تایپدار بهجای `throw` (`src/adapter/mockAdapter.js:56-59`)
- مدیریت خرابِ داده‌ی ذخیره‌شده بدون crash (`src/adapter/storage.js:131-176`)
- نگهبان hookها: هیچ hookی بعد از early-return در `src/App.jsx:684` نیست

**مشکلات مشاهده/استنتاج‌شده:** بخش ۵.

**مدیریت خطا** [Observed]:

- `applyDraft` از `try/finally` بدون `catch` استفاده می‌کند (`src/App.jsx:271-301`)؛ طبق قرارداد آداپتر throw نمی‌کند، پس فقط در صورت نقض قرارداد، rejection سرکوب می‌شود — Low (ISS-17).
- listenerهای `keydown` بدون dependency array که هر رندر دوباره ثبت می‌شوند: `src/App.jsx:542-558`، `src/scene/NeuralScene.jsx:195-217` — Low (ISS-11).
- حلقهی انیمیشن `kinds` را از closureای با deps برابر `[size, head]` می‌خواند (`src/scene/NeuralScene.jsx:368` و `:620`) در حالی که بقیه‌ی ورودی‌ها از `live.current` تازه می‌شوند — امروز بی‌اثر است چون ابزارهای سفارشی همیشه `kind=tool` هستند — Low (ISS-12).

### 4.4 تست و اعتبارسنجی

- ۱۳ فایل تست، ۱۶۲ فراخوانی `test(`، همه روی ماژول‌های خالص (مدل/آداپتر/layout) [Observed]؛ پویش نشان داد **هیچ تستی import از `.jsx`/`react`/`components/` ندارد** [Observed].
- پوشش موضوعی خوب: قرارداد آداپتر، سیاست حافظه، reducer رویداد، اعتبارسنجی ورودی/manifest، پایدارسازی، هندسه [Observed].
- **وضعیت گذشته‌ی اجرا:** `visual-baseline/README.md:6-7` ادعا می‌کند «`npm test`: 162/162 passing at capture time» و «`npm run build`: 1779 modules, CSS 24.66 kB, JS ~315 kB» [Observed **به‌عنوان محتوای فایل**]. تعداد ۱۶۲ با شمارش ایستای این ممیزی تطابق دارد، اما **هیچ لاگ خروجی تست/build داخل پروژه نیست** و ممیزی نیز اجرا نکرده است؛ وضعیت فعلی تست‌ها/build **[Unknown]**.
- **بدون lint/format/CI** [Observed] — هیچ gate خودکار کیفیتی در پروژه نیست (ISS-15).

### 4.5 مستندسازی

**قوی** [Observed]:

- `docs/adapter-contract.md` (۱۴۷ خط: جدول متدها، taxonomy خطاها، قواعد adapter واقعی، گپ‌های شناخته‌شده)
- ۱۰ سند skill با acceptance criteria صریح
- `visual-baseline/README.md` با روش و محدودیت‌های صادقانه

**ضعیف/متناقض** [Observed]:

- `README.md:18` ادعا می‌کند «The original Google Fonts import is preserved in `src/index.css`»، در حالی که `src/index.css:1-4` می‌گوید importِ CDN با `./fonts.css` **جایگزین** شده و `tests/contract.test.js:96-100` نیز همین را تأیید می‌کند — تناقض صریح (ISS-04).
- `README.md` هیچ اشاره‌ای به MOCK بودنِ backend، تست‌ها (`npm test`)، `skills/`، `docs/` و `visual-baseline/` ندارد [Observed]؛ این با قاعده‌ی خودِ پروژه (`skills/00-global-guardrails.md:11`: «Label every simulated behavior as MOCK in ... the README») ناسازگار است (ISS-05).
- `visual-baseline/README.md:8` می‌گوید «39 source files under `src/`» در حالی که شمارش واقعی ۴۰ فایل است (۱۷ jsx + ۲۱ js + ۲ css) (ISS-10).

### 4.6 وابستگی‌ها و پیکربندی

- همهی وابستگی‌ها پین‌شده و با lock سازگار؛ نسخه‌های نصب‌شده = نسخه‌های اعلامی [Observed]. ناسازگاری‌ای میان `package.json` و `package-lock.json` دیده نشد [Observed].
- بدون فرضِ environment پنهان: بدون `.env`، بدون هیچ URL در کل `src/` (پویش `https?://` = صفر) که خودِ تست `tests/contract.test.js:101-117` نیز آن را اجرا می‌کند [Observed].
- بدون فیلد `engines` در `package.json` در حالی که `node --test` به Node ≥18 نیاز دارد — Low [Observed].
- پیکربندی Vite حداقلی است (`vite.config.js:1-6`)؛ فونت‌ها با مسیر مطلق `/fonts/...` در CSS ارجاع می‌شوند که به deploy در ریشه‌ی دامنه وابسته است — Low [Observed].

### 4.7 امنیت و مدیریت داده

- **هیچ secret واقعی یافت نشد** [Observed]: پویش `api_key|secret|password|token|PRIVATE KEY` در فایل‌های پروژه فقط به مستندات/تست‌ها/برچسب‌های UI برخورد (`docs/adapter-contract.md:97`، `tests/storage.test.js:119-126`، `src/i18n.js:26`). تنها مقدار credential-مانند، یک hash **نمایشیِ ماسکشده** در داده‌ی دموست: `src/data.js:136` (پیشوند `41c9`؛ در UI به‌صورت `••••••` رندر می‌شود — `src/components/Gate.jsx:116-126`)؛ واقعی نیست و افشا نمی‌شود.
- **بدون** `eval` / `new Function` / `innerHTML` / `dangerouslySetInnerHTML` / `document.write` **در `src/`** [Observed].
- **پویش متنِ راهنما:** جست‌وجوی `ignore previous instructions|disregard|you are now|act as if|system prompt` در فایل‌های پروژه هیچ نتیجه‌ای نداد (تنها کامنت‌های کامپایلر داخل `node_modules`) [Observed]. پوشه‌ی `skills/` ذاتاً سند دستورالعمل برای عاملِ کدنویسی است و به‌عنوان **داده** رفتار شد؛ هیچ دستورِ مخاطب‌به‌من در پروژه یافت نشد.
- داده‌ی حافظه فقط برچسب دارد و هرگز خوانده نمی‌شود: `src/model/seed.js:399-400` («Source references are data, never instructions») و پیاده‌سازی `src/adapter/memoryProvider.js:1-11` بدون دسترسی فایل‌سیستم [Observed].
- محدودیت‌ها صادقانه ثبت شده‌اند: `src/adapter/storage.js:10-18` (localStorage محلی است، نه persistence چندکاربره) و `src/App.jsx:581-584` [Observed].
- نکته‌ی داده [Observed]: `src/App.jsx` مستقیماً `localStorage` را می‌نویسد (`:62-74`) در حالی که کل لایه‌ی storage پشت یک interface است — نقضِ همان انتزاعی که `src/adapter/storage.js:1-8` وعده داده (ریشه‌ی ISS-01).

---

## 5. مشکلات و ریسک‌های اولویت‌بندی‌شده

| ID | Severity | Evidence | مکان (file: lines) | تأثر (یک خط) |
|---|---|---|---|---|
| ISS-01 | **High** | [Inferred] | `src/App.jsx:49, 62-74, 82, 172-174, 563-579` + `src/adapter/storage.js:25-27, 199-224` | دو نویسنده روی یک کلید legacy؛ custom tools در هر reload **تکثیر (به‌صورت نمایی)** می‌شوند. ✅ **رفع شد** |
| ISS-02 | Medium | [Observed] | `src/App.jsx:128` در برابر `src/adapter/mockAdapter.js:347-353, 390-395, 496-501` | بازیابی حافظه در UI همیشه `unsupported` برمی‌گرداند؛ پذیرش skill 05 در رابط کاربری شکست‌خورده است. ✅ **رفع شد** |
| ISS-03 | Medium | [Observed] | `src/adapter/storage.js:82-96` + `src/App.jsx:659-671` + `src/components/StatusCard.jsx:24` | importِ «معتبر» بدون `sub` باعث TypeError در رندر و سفیدشدن کل اپ می‌شود. ✅ **رفع شد** |
| ISS-16 | Medium | [Observed] | `src/adapter/storage.js:82-96` + `src/App.jsx:653-657` | `status` ناشناخته → `counts[...]++` برابر NaN و `STATUS_COLOR[status]` نامعتبر در UI. ✅ **رفع شد** |
| ISS-04 | Medium | [Observed] | `README.md:18` در برابر `src/index.css:1-4` و `tests/contract.test.js:96-100` | مستند با کد تناقض صریح دارد (فونت Google CDN). |
| ISS-05 | Medium | [Observed] | `README.md:1-18` در برابر `skills/00-global-guardrails.md:11` | README هیچ برچسب MOCK ندارد؛ خواننده ممکن است دمو را یکپارچه‌سازی واقعی بپندارد. |
| ISS-06 | Medium | [Inferred] | `package.json:10` + نبودِ هر import از `react`/`.jsx` در `tests/*` | هیچ تستی لایه‌ی React را پوشش نمی‌دهد؛ ISS-01/02/03 دقیقاً در همین لایه‌اند. |
| ISS-07 | Low | [Observed] | `src/App.jsx:775`، `src/components/Sidebar.jsx:92-98` | کنترل‌های مرده (Filter، Help) — UX گمراه‌کننده. |
| ISS-08 | Low | [Observed] | `src/App.jsx:8, 34`؛ `src/i18n.js:66-69, 83-85` | import و کلیدهای i18n بلااستفاده (کد مرده). |
| ISS-09 | Low | [Observed] | `src/App.jsx:644-651` | منطق وضعیت با شناسه‌ی هاردکد `wordpress` — نقضِ همان «هاردکد نکردن id» که `src/model/registry.js:127-130` رعایت می‌کند. |
| ISS-10 | Low | [Observed] | `visual-baseline/README.md:6-8` | «39 source files» در برابر ۴۰ فایل واقعی؛ ادعای build نیز بدون لاگ. |
| ISS-11 | Low | [Observed] | `src/App.jsx:542-558, 622-624`؛ `src/scene/NeuralScene.jsx:195-217` | listenerهای بدون deps (ثبت مجدد هر رندر) و dependency ناقص در effect بازپخش. |
| ISS-12 | Low | [Observed] | `src/scene/NeuralScene.jsx:368, 620` | `kinds` در حلقه‌ی رندر از closure کهنه خوانده می‌شود (الان بی‌اثر). |
| ISS-13 | Low | [Observed] | `index.html:2` در برابر `src/App.jsx:77` | `lang="en"` هاردکد با وجود پیش‌فرض فارسی — ناسازگاری دسترس‌پذیری در اولین رندر. |
| ISS-14 | Low | [Inferred] | `skills/03-fiber-interaction.md:40, 46` در برابر `src/scene/NeuralScene.jsx:195-217, 699-705, 1114-1122` | انحراف از مشخصات خودِ پروژه: Escape هنگام drag هندسه‌ی اعمال‌شده را بازگردانی نمی‌کند؛ Disconnect بدون تأیید است. |
| ISS-15 | Low | [Observed] | نبود `.eslintrc*`، `.github/`، `prettier*` در سطح پروژه | هیچ gate خودکار کیفیت/یکپارچگی وجود ندارد. |
| ISS-17 | Low | [Observed] | `src/App.jsx:271-301` | `try/finally` بدون `catch`؛ نقض قرارداد آداپتر به unhandled rejection تبدیل می‌شود. |
| ISS-18 | Low | [Observed] | `src/components/AddTool.jsx:22` در برابر `src/model/registry.js:12` | شناسه‌ی تولیدی برای ورودی‌های فقط-علامتی می‌تواند با `ID_PATTERN` ناسازگار شود (برای custom tools هیچ‌جا اعتبارسنجی نمی‌شود). |

### جزئیات سه مورد کلیدی

**ISS-01 — تکثیر ابزارهای سفارشی در هر reload** [Inferred]

دو مسیر روی **یک کلید** می‌نویسند: `src/App.jsx:49` (`agentos-neural-tools-v1`) و `src/adapter/storage.js:27` (`LEGACY_TOOLS_KEY`، همان مقدار). `useState` در `src/App.jsx:82` هنگام mount از کلید legacy می‌خواند، سپس effect در `src/App.jsx:172-174` همان را دوباره می‌نویسد، و effect بارگذاری در `src/App.jsx:563-579` ابزارهای سفارشی را از رکورد workspace **بدون dedupe** به همان لیست اضافه می‌کند (`setAgents((prev) => [...prev, ...loaded.customTools])`) — برخلاف `handleImport` که در `src/App.jsx:327-330` صراحتاً dedupe می‌کند. نتیجه‌ی استنتاجی: در نوبت دومِ اجرا ابزار ۲ بار، در نوبت سوم ۴ بار ظاهر می‌شود (شمارش‌های status در `src/App.jsx:653-657` و کلیدهای React تکراری در `src/scene/NeuralScene.jsx:864-874` آلوده می‌شوند).

> جهت رفع (فقط جهت، نه اعمال): یک منبعِ حقیقت واحد برای persistence؛ حذفِ نوشتن مستقیمِ localStorage از `App`، یا حذف کلید legacy پس از migration.

**ISS-02 — بازیابی حافظه همیشه شکست می‌خورد** [Observed]

`src/App.jsx:128` آداپتر را فقط با `registry` می‌سازد؛ `src/adapter/mockAdapter.js:347-353` پارامتر `memory` را نمی‌گیرد، پس `queryMemory` (`:496-501`) همیشه `{ type: "unsupported", message: "queryMemory: no shared-memory provider configured" }` برمی‌گرداند و `getCapabilities().capabilities.queryMemory.supported === false` (`:390-395`). تابع `retrieve()` در `src/App.jsx:360-409` این خطا را با `entry.status = "error"` نشان می‌دهد؛ بنابراین سناریوی پذیرش skill 05 («عامل دارای grant → بازیابی مجاز») در UI هرگز محقق نمی‌شود، در حالی که تست‌ها با `memory: seed.memory` (`tests/adapter.test.js:312-320`) سبزند.

> جهت رفع: پاس‌دادن `seed.memory` به `createMockAdapter`، یا gating کردن دکمه‌ی Retrieve بر اساس capability.

**ISS-03 — import می‌تواند کل اپ را crash کند** [Observed]

`validateCustomTools` (`src/adapter/storage.js:82-96`) فقط `id` و `name` را الزام می‌کند؛ `labelFor` در `src/App.jsx:659-671` و `src/components/StatusCard.jsx:24` بدون نگهبان `a.sub[lang]` می‌خوانند (این داده در `tests/storage.test.js:29` هم بدون `sub` ساخته می‌شود). `src/pages/renderers.jsx:43` اما نگهبان دارد — ناهمگونی در سطح defensive بودن.

> جهت رفع: تقویت اعتبارسنجی بخش `customTools`، یا نگهبان‌دار کردن رندر.

---

## 6. پرسش‌های باز

1. **[Unknown]** آیا نوشتنِ `src/App.jsx:70-74` روی کلید legacy عمداً برای backward-compat است یا باگ؟ فقط صاحب پروژه می‌تواند تأیید کند (ISS-01).
2. **[Unknown]** وضعیت فعلی `npm test` و `npm run build` — طبق قیدِ read-only اجرا نشد؛ تنها ادعای `visual-baseline/README.md:6-7` موجود است و لاگ خروجی در پروژه نیست.
3. **[Unknown]** تفاوت بصریِ مجموعه‌های `before/` و `after/` — به دلیل نبودِ قابلیت ورودی تصویر در این مدل قابل‌مشاهده نیست؛ فقط ابعاد PNG با مستند سازگار است.
4. **[Unknown]** پوشش ناقص دو فایل: `package-lock.json` (خطوط ۶۱–۲۶۴۶) و `src/fonts.css` (خطوط ۸۱–۴۰۹) — خواندن خط‌به‌خط ناتمام ماند؛ بررسی ساختاری/ماشینی انجام شد اما پوشش کامل نیست.
5. **[Unknown]** سرنوشت آداپترِ backend واقعی (`docs/adapter-contract.md:113-128`) — در این مخزن وجود ندارد؛ آیا در مخزن دیگری (WSL) هست؟ خارج از scope این پروژه.
6. **[Unknown]** عدم تطابق تعداد فایل‌ها (۳۹ ادعاشده در برابر ۴۰ واقعی): آیا فایلی پس از capture به `src/` افزوده شده؟
7. **پیشنهاد بررسی بعدی (در صورت مجوز):** اجرای `npm test` و `npm run build`، و یک سناریوی دستیِ reload با یک ابزار سفارشی برای تأیید تجربیِ ISS-01.

---

## خودکنترلی پیش از تحویل (مرحلهی ممیزی)

> **نکته:** این خودکنترلی مربوط به **مرحلهی ممیزی read-only** است. اعمال فاز۰ بعدها و با انتخاب صریح کاربر انجام شد — جزئیات در [بخش ۷ — اصلاحات اعمالشده](#7-اصلاحات-اعمالشدهفاز-۰).

- ✅ (الف) هر ادعا تنها **یک** برچسب دارد: `[Observed]` / `[Inferred]` / `[Unknown]`.
- ✅ (ب) هر `[Observed]` مسیر + بازه‌ی خط دارد.
- ✅ (ج) هیچ ادعایی از پوشش کامل با جدول فایل‌انباره در تناقض نیست (۷۵ کامل / ۲ بخشی / ۴۲ غیرقابل‌خواندن / ۱ مجموعه Skip).
- ✅ (د) هیچ مقدار secret افشا نشده (تنها پیشوند `41c9` از داده‌ی دمو).
- ✅ (هـ) هیچ فایل پروژه‌ای تغییر داده نشد؛ هیچ build/test/install اجرا نشد؛ تنها فایلِ ایجادشده، همین گزارش است. (اعمال فاز۰ بعدها و با انتخاب صریح کاربر انجام شد — بخش ۷.)

---

## ۷. اصلاحات اعمالشده (فاز ۰)

> **تاریخ اجرا:** ۲۰۲۶-۱۰-۱۰ — پس از انتخاب صریح کاربر برای شروع فاز۰.
> **تأیید:** `npm test` → **۱۷۰ تست، ۱۷۰ pass، ۰ fail** (۸ تست رگرسیون تازه).

### ۷٫۱ فایلهای تغییریافته

| فایل | تغییر |
|---|---|
| `src/App.jsx` | حذف `STORAGE_KEY` و `loadCustom`/`saveCustom`؛ اتصال `memory: seed.memory` به آداپتر؛ افزودن `memorySupported`؛ dedupe بر اساس id هنگام بارگذاری |
| `src/adapter/storage.js` | افزودن `normalizeCustomTool` و `AGENT_STATUSES`؛ نرمالسازی `sub`/`status`/`tok`/`load`/`seen` در مرز پایدارسازی |
| `src/components/StatusCard.jsx` | شاخه توضیحِ unsupported **قبل از** بررسی اتصال (capability first) |
| `src/i18n.js` | افزودن کلید `memoryUnsupported` در دو کاتالوگ `en` و `fa` |
| `tests/storage.test.js` | به‌روزرسانی assertionها به شکل نرمالشده + ۴ تست رگرسیون تازه |
| `tests/contract.test.js` | ۴ تست اسکنِ منبع تازه (ISS-01 / ISS-02) |

### ۷٫۲ رفع هر مشکل

**ISS-01 (High) — تکثیر نمایی custom tools** [رفع‌شده]
- ریشه: دو نویسنده روی یک کلید. حذف کاملِ نوشتنِ مستقیم از `App.jsx`؛ اکنون فقط `saveWorkspace` (debounced) می‌نویسد و فقط `loadWorkspace` می‌خواند.
- دفاع ثانویه: dedupe بر اساس id هنگام بارگذاری، تا اجرای مجدد effect (مثلاً StrictMode) هم نتواند تکثیر کند.
- گارد در برابر regresiion: دو تست اسکنِ منبع در `contract.test.js` — «`App.jsx` هرگز `localStorage` را مستقیم صدا نمی‌زند» و «کلید legacy فقط در `storage.js` زندگی می‌کند».

**ISS-02 (Medium) — بازیابی حافظه همیشه unsupported** [رفع‌شده]
- ریشه: `createMockAdapter` پارامتر `memory` را نمی‌گرفت. اکنون `memory: seed.memory` پاس می‌شود؛ جریان کامل skill-05 (dsh مجاز، seo ردشده) در UI کار می‌کند.
- gatingِ چهار-حقیقتی: `StatusCard` اکنون اگر provider قابلیت `queryMemory` را رد کند، به‌جای دکمه مرده، توضیح نشان می‌دهد (`memoryUnsupported`).
- گارد: تست اسکنِ منبع «آداپتر باید `memory: seed.memory` بگیرد» + «`StatusCard` باید `memory.supported === false` را رندر کند».

**ISS-03 / ISS-16 (Medium) — crash و NaN از import ناقص** [رفع‌شده]
- ریشه: `validateCustomTools` فقط `id`/`name` را چک می‌کرد. اکنون `normalizeCustomTool` در **مرز پایدارسازی** (تنها نقطه ورود داده) فیلدهای نمایشی را نرمال می‌کند:
  - `sub` → شیء `{en, fa}` با fallback به `name` (رفع TypeError روی `a.sub[lang]`)
  - `status` → فقط از `AGENT_STATUSES`، وگرنه `offline` (رفع `counts[...]++` برابر NaN)
  - `tok`/`load`/`seen` → مقادیر امن
- نرمالسازی **بیصدا** است (نمایش، نه پیکربندی)؛ فقط نبودِ `id`/`name` همچنان خطای گزارش‌شده است.
- گارد: ۴ تست تازه در `storage.test.js` — import بدون `sub`، `status` ناشناخته، حفظِ داده معتبر، و idempotency.

### ۷٫۳ چیزهایی که هنوز باز است

- ISS-04 تا ISS-18 باقیمانده (مستندات، تستِ لایه React، کدِ مرده، lint/CI) — فازهای P1/P2.
- **ISS-06 (شکاف تستِ لایه React)** عمداً در فاز۰ بسته نشد: گاردهای اسکنِ منبع جایگزینِ تستِ رفتاریِ کامپوننت نیستند و فقط تا زمانی که harness کامپوننت نداریم، بهترین دفاع ممکن‌اند.
