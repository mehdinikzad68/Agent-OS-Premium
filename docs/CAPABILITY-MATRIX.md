# Agent OS — Capability Matrix

> **قانون حقیقت در این سند:** هر ردیف فقط بر اساس شواهد محلی (کد یا اسناد
> داخلی) علامت می‌خورد. «Implemented» یعنی کد در مخزن WSL در HEAD
> `4783c9b` وجود دارد و یک مسیر قابل استناد دارد. «Verified-by-test» فقط
> زمانی زده می‌شود که یک تست در مخزن آن رفتار را پوشش دهد. «Planned» یعنی
> هدف اعلام‌شده ولی پیاده‌سازی نشده. هیچ‌بخشی از این سند بر اساس ادعای
> خارجی یا حافظهٔ جلسه پر نشده است. وضعیت مخزن و تاریخ این عکس‌برداری در
> [00-CURRENT-STATE](00-CURRENT-STATE.md) آمده است.

## ۱. مرجع و وضعیت‌ها

| نماد | معنی |
|---|---|
| ✅ Implemented + verified-by-test | در کد هست و تستی در مخزن آن را می‌پوشد |
| ◑ Implemented (بدون تست اختصاصی) | در کد هست؛ تست اختصاصی مستقیم پیدا نشد |
| ⚠ Partial | بخشی پیاده شده، بخشی صریحاً محدود یا ناقص |
| 📋 Planned | هدف اعلام‌شده، پیاده‌سازی نشده |

## ۲. سرویس کنترل (Python stdlib-only)

| قابلیت | وضعیت | شاهد |
|---|---|---|
| ذخیرهٔ SQLite در حالت WAL، `SCHEMA_VERSION = 4` | ✅ | `store.py:37`؛ migration از v۱ تا v۴ |
| Event log فقط-الحاقی (append-only) با dedup_key | ✅ | `store.py:625`، `record_event` |
| Missions / Jobs / Approvals / Projects | ✅ | `service.py`، `models.py` |
| مسیرهای HTTP توکن‌محور روی loopback | ✅ | `api.py`، `LOOPBACK_HOSTS` (`api.py:847`) |
| تأیید deny-by-default قبل از dispatch | ✅ | `policy.validate_dispatch()`، A1–A13 |
| امضای دسترسی دائمی (authority split) | ✅ | `Principal` در `models.py`؛ decide/reconcile فقط HUMAN |
| Workflow templates + executions | ◑ | `service.py:891`؛ `NodeActionType` در `models.py:339` |
| Graphics (آفریدن/رندر SVG/soft-delete) | ◑ | `service.py:1045`؛ `graphics.py` |
| Knowledge docs | ◑ | متد در service/store هست، **مسیر HTTP نیست** → خارج از API |
| Hermes در حالت planner متصل | 📋 | فقط ingestion از رویدادها هست، و آن هم observation-only |

## ۳. اجراگرها (Executor registry)

ثبت اجراگر تنها سطح dispatch است. **پیش‌فرض فقط `fake-executor` ثبت می‌شود**
(`cli.py:66`)؛ بقیه نیازمند پرچم صریح هستند:

| اجراگر | وضعیت | شرط فعال‌سازی |
|---|---|---|
| `fake-executor` | ✅ | پیش‌فرض؛ `--fake-behavior` رفتار را تنظیم می‌کند |
| `subprocess-executor` | ⚠ | `--enable-subprocess` **و** `--source-workspace` (در غیر این صورت exit ۲) |
| `container-executor` | ⚠ | `--enable-container`؛ تصویر پیش‌فرض `python:3.14-slim` (`cli.py:274`)، timeout پیش‌فرض ۱۲۰ (`cli.py:278`) |
| `hermes-executor` | ◑ | به‌عنوان adapter موجود است، ولی جزو رجیستری پیش‌فرض نیست |
| DSH / Antigravity | 📋 | متصل نیست |

## ۴. امنیت و حریم خصوصی

| قابلیت | وضعیت | شاهد/توضیح |
|---|---|---|
| توکن Bearer روی همهٔ `/api/*` | ✅ | `api.py::_authorize` |
| Shell عمومی بدون توکن (مرورگر نمی‌تواند هدر بفرستد) | ✅ | `api.py:768` (`/`، `/ui`، `/index.html`) |
| محدودیت به loopback-only | ✅ | `cli.py:52` (exit ۲)، `api.py:847` |
| سقف اندازهٔ بدنه → ۴۱۳ | ✅ | `MAX_BODY = 1_000_000` (`api.py:717`) |
| هدر `X-Content-Type-Options: nosniff` | ✅ | `api.py:731` و `api.py:821` |
| هدر `X-Frame-Options` | ❌ **ارسال نمی‌شود** | در docs/10 به‌اشتباه «DENY» نوشته شده بود (تصحیح شد) |
| بدون نشت جزئیات داخلی در خطاها | ✅ | `api.py:185–216`؛ خطای ۵۰۰ نهایی فقط کد می‌دهد |
| قرمزسازی (redaction) evidence | ✅ | `api.py::_job_evidence` (هم خواندن هم نوشتن) |
| منبع ingest باید در ریشه‌های مجاز باشد | ✅ | `assert_source_allowed` (`service.py:213`) → ۴۰۳ |
| Cryptographic attestation از سمت executor | 📋 | پیاده نشده |

**هشدار مهم برای داشبورد:** `/api/tools/discover` یک read امن نیست. این مسیر
`discovery.discover(...)` را اجرا می‌کند که **probe از باینری‌های allowlist‌شده**
انجام می‌دهد. هرچند `execution_granted: False` است و چیزی نصب نمی‌کند، در
pollingِ داشبورد نباید گفته شود «read-only». (جزئیات در docs/03.)

## ۵. رابط کاربری

| لایه | وضعیت | شاهد |
|---|---|---|
| داشبورد Canvas 2D تک‌فایلی (vanilla JS، RTL، آفلاین) | ✅ | working tree `web/index.html`؛ مطابق ADR-001 **مرجع رسمی** |
| پشتیبانی از کیبورد/دسترس‌پذیری | ◑ | مشخصات Phase 8 درخواست کرده، پوشش تست اختصاصی مستقیم پیدا نشد |
| داشبورد Three.js «Galaxy Command» | ⚠ | در HEAD وجود دارد ولی **آزمایشی و غیرمرجع** (ADR-001) |
| داشبورد React + TypeScript | 📋 | هدف محصول، پیاده نشده (docs/00 بخش ۷) |
| TypeScript/CDN به‌جز `three.min.js` | ❌ | پروژه آفلاین است؛ `docs/UI-Design/` untracked و خارج از ضمانت |

## ۶. تست‌ها

| قابلیت | وضعیت | شاهد |
|---|---|---|
| سوئیت تست مبتنی بر `unittest` | ✅ | `tests/` + `run_tests.py` (این چارچوب رسمی است) |
| شمارش استاتیکی توابع تست | ✅ | **643 test functions across 43 files** (شمارش `def test_`؛ `live_server.py` مستثنی) |
| نتیجهٔ اجرا در این فاز | — | **اجرا نشده**؛ بنابراین هیچ adعای «passed/all green» مجاز نیست |
| `pytest` به‌عنوان چارچوب رسمی | ❌ | نصب محلی دارد ولی مرجع نیست |
| e2e_verify (۱۱ گام) | ✅ | ابزار موجود است |
| check_ui (بررسی ساختار UI) | ✅ | ابزار موجود است |

## ۷. مستندسازی

| سند | وضعیت | نکته |
|---|---|---|
| `docs/00-CURRENT-STATE.md` | ✅ جدید | snapshot تاریخ‌دار وضعیت مخزن |
| `docs/01..04` | ✅ به‌روز | نصب/کاربرد/API/توسعه — با این فاز همسان شد |
| `docs/10` گزارش امنیتی | ✅ به‌روز | هدرها، چارچوب تست و شمارش تصحیح شد |
| `docs/09` + `docs/ui-2d-mission-control-design.md` | ⚠ | دو فایل **محتوای تکراری** هستند (هیچ تغییری نکرد) |
| `docs/hermes-integration-layer.md` | ⚠ | «Nothing in this document is implemented» — خارج از scope |
| `docs/phase6-design.md` | ⚠ | مرجع تاریخی |
| `AGENT-OS-HANDOFF.md` / `threat_model.md` / `CHANGELOG.md` | ❌ | **وجود ندارند**؛ فقط اشارهٔ تاریخی |
