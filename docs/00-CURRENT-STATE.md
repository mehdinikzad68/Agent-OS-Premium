# Agent OS — Current State (snapshot)

> **نقش این سند:** این تنها نقطه‌ای است که وضعیت **در لحظهٔ** مخزن را ثبت می‌کند:
> شاخه، HEAD، تغییرات working tree، نسخهٔ schema و وضعیت رابط کاربری. هر چیزی که
> در این سند «snapshot» نامیده شده، تاریخ دارد و نباید به جای حقیقت دائمی پروژه
> خوانده شود. سایر اسناد به این فایل ارجاع می‌دهند تا تاریخ را تکرار نکنند.

## ۱. مخزن رسمی (canonical)

| مورد | مقدار |
|---|---|
| مسیر رسمی | `/home/mehdi/workspace/Agent-OS` (WSL2, Ubuntu-26.04) |
| شاخه | `main` |
| HEAD | `4783c9b54f13ca869160eb3b7c0c8924f62e8db1` — «feat: 3D Galaxy Command UI integration» |
| جلوتر از `origin/main` | ۶ کامیت (عکس‌برداری ۲۰۲۶-۱۰-۰۶؛ این عدد یک snapshot است، نه حقیقت ثابت) |
| working tree | کثیف (جزئیات در بخش ۲) |

کپی `D:\DEV-Studio\Programming\Agent-OS` روی ویندوز **غیررسمی و قدیمی** است و
هیچ کامیت مشترکی با مخزن WSL ندارد. هیچ agent یا توسعه‌دهنده‌ای نباید در آن
مسیر کار کند؛ علت و جزئیات در
[ADR-002](architecture/ADR-002-canonical-repository.md) آمده است.

## ۲. وضعیت working tree (عکس‌برداری ۲۰۲۶-۱۰-۰۶)

`git status --porcelain` روی HEAD بالا این موارد را نشان می‌دهد:

| حالت | مسیر | توضیح |
|---|---|---|
| ` D` | `UI-Image/UI-Theme-RTL.jpg` | در working tree حذف شده، ولی هنوز در index/HEAD |
| ` D` | `UI-Image/UI-Theme.jpg` | همان |
| ` D` | `UI-Image/موجوه_مهم_طراحی_رابط_کاربری.mp4` | همان |
| ` M` | `control-service/agent_os/web/index.html` | تغییر **نه‌کامیت‌شده** با حجم تقریبی +۲۰۰۴/−۸۳۰ خط |
| `??` | `docs/UI-Design/` | پوشهٔ جدید و **untracked** |

دو نکتهٔ مهم که باید در سایر اسناد هم صریح نوشته شوند:

- **تغییرات رابط کاربری کامیت نشده‌اند.** چیزی که امروز در working treeِ
  `web/index.html` دیده می‌شود، نسخهٔ Canvas 2D است (بخش ۳)، ولی این وضعیت
  «انتشار‌یافته» یا «کامیت‌شده» نیست؛ فقط تاریخ ۲۰۲۶-۱۰-۰۶ را دارد.
- **`docs/UI-Design/` علاوه بر untracked بودن، از نظر وابستگی هم استثناست:**
  محتوای HTML این پوشه ممکن است به منابع خارجی (CDN) وابسته باشد، بنابراین
  نباید آن را «آفلاین» یا «production» نامید. قانون آفلاین‌بودن فقط به رابط
  Canvas 2D در working tree اشاره دارد.

## ۳. رابط کاربری: دو لایه، دو وضعیت

| لایه | آنچه در مخزن است | وضعیت رسمی |
|---|---|---|
| **Canvas 2D — «Neural Command»** | working treeِ `web/index.html` (uncommitted) | **مرجع رسمی داشبورد** (مطابق ADR-001) |
| **Three.js — «Galaxy Command»** | HEAD (`4783c9b`) | **آزمایشی؛ غیرمرجع در HEAD** |

شواهد خوانده‌شده از مخزن: نسخهٔ HEAD ۱۴ اشارهٔ `THREE.`، یک اشارهٔ `WebGL` و یک
تگ `<script src>` (بارگذاری `three.min.js`) دارد، در حالی که نسخهٔ working tree
هیچ‌کدام را ندارد و دو فراخوانی واقعی `getContext("2d")` (به‌علاوهٔ یک
capability check بدون آرگومان: `getContext` در یک بررسی) دارد. یعنی UI در working tree
دقیقاً مشخصات Phase 8 را برآورده می‌کند: «۱۰۰٪ مستقل از 3D/WebGL/Three.js، بدون
وابستگی خارجی به CDN».

حکم رسمی در [ADR-001](architecture/ADR-001-dashboard-rendering.md): خط پایهٔ
رسمی همان Canvas 2D است؛ لایهٔ Three.js تا زمانی که ADR جدیدی صادر نشود،
آزمایشی می‌ماند. **هیچ کد Three.js، مسیر، دارایی یا رابطی حذف یا تغییر
نکرده‌ایم** — فقط وضعیتش مستند شده است.

## ۴. حقیقت‌های کد (بدون بازتفسیر)

- **نسخه:** `0.2.0` (`api.py::_status`).
- **زبان/وابستگی:** فقط Python standard library؛ `dependencies = []`،
  `requires-python >= 3.11`، classifiers برای ۳.۱۱ و ۳.۱۴.
- **Schema:** `SCHEMA_VERSION = 4` (`store.py:37`).
- **اجراگر پیش‌فرض:** فقط `fake-executor` (`cli.py:66`).
  `subprocess-executor` نیاز به `--enable-subprocess` **و** `--source-workspace`
  دارد (در غیر این صورت exit ۲)، و `container-executor` نیاز به
  `--enable-container` دارد با تصویر پیش‌فرض `python:3.14-slim` (`cli.py:274`)
  و timeout پیش‌فرض ۱۲۰ ثانیه.
- **میزبان‌های حلقه‌ای:** `127.0.0.1` از طریق `LOOPBACK_HOSTS` (`api.py:847`)؛
  `serve()` هاست غیرحلقه‌ای را رد می‌کند و `cli.py:52` با exit ۲ خارج می‌شود.
- **اندازهٔ بدنه:** `MAX_BODY = 1_000_000` (`api.py:717`) → ۴۱۳.
- **هدرهای پاسخ:** `Content-Type: application/json; charset=utf-8`،
  `Content-Length`، `X-Content-Type-Options: nosniff` (`api.py:729–731`).
  **`X-Frame-Options` ارسال نمی‌شود** (در docs/10 تصحیح شد).

## ۵. شمارش تست: حقیقت مجاز

تنها عبارت مجاز برای تعداد تست در این پروژه:

> **Static inventory: 643 test functions across 43 files** (شمارش مستقل `def
> test_`؛ یک فایل `live_server.py` مستثنی شده است).

این یک **شمارش استاتیکی از توابع تست** است، نه یک نتیجهٔ اجرا. ادعای
«۶۴۳/۶۴۳ passed» یا «all green» **ممنوع** است، مگر اینکه یک اجرای واقعی در این
فاز انجام شده باشد — و نشده است. اگر از اجرای سوئیت صحبت می‌کنید، فقط از
دستور رسمی استفاده کنید: `python3 run_tests.py` یا
`python3 -B -m unittest discover -s tests -t .`.

**چارچوب رسمی: `unittest`.** `pytest` ممکن است روی این ماشین نصب باشد، ولی
مرجع نیست و نباید به عنوان چارچوب پروژه معرفی شود.

## ۶. اسنادی که به چیزی اشاره می‌کنند که وجود ندارد

این فایل‌ها در اسناد قدیمی به‌عنوان «موجود» معرفی شده بودند ولی **وجود
ندارند**؛ فقط باید به‌عنوان «ارجاع‌شده ولی ناموجود / اشارهٔ تاریخی» برخورد شوند:

| اشاره | وضعیت |
|---|---|
| `AGENT-OS-HANDOFF.md` | وجود ندارد. قبلاً در `api.py:3` و `.agent-ai/memory/MEMORY.md` ارجاع شده بود. |
| `threat_model.md` | وجود ندارد. docs/10 آن را به‌عنوان پایگاه ارزیابی معرفی کرده است. |
| `control-service/CHANGELOG.md` | وجود ندارد. |
| `run_real_kanban_task.py` | وجود ندارد. |

## ۷. موارد «Planned» (طرح‌شده، نه پیاده‌شده)

- **داشبورد React + TypeScript:** هدف محصول در
  `agent-os-product-development-master-plan-EN.md:122`، ولی پیاده‌سازی نشده.
  رابط فعلی تک‌فایلی HTML + vanilla JS است.
- **اندپوینت‌های Knowledge (`/api/knowledge*`):** لایهٔ service و store متد دارند
  (`service.create_knowledge_doc`، `store.update_knowledge_doc`)، ولی **هیچ مسیر
  HTTP‌ای وجود ندارد**؛ نباید به‌عنوان بخشی از API معرفی شوند.
- **اجراگرهای واقعی:** Hermes به‌عنوان planner متصل نیست (تنها ingestion از
  رویدادهای ثبت‌شدهٔ او وجود دارد، و آن هم observation-only است). DSH و
  Antigravity متصل نیستند.
