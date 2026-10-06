# Agent OS — API Documentation

> **منبع حقیقت این سند:** کد `control-service/agent_os/api.py` در مخزن رسمی
> (`/home/mehdi/workspace/Agent-OS`) در HEAD `4783c9b`. هر مسیری که در این سند
> آمده، واقعاً در کد وجود دارد؛ مسیرهایی که وجود ندارند، حذف شده‌اند یا
> صریحاً «Planned» علامت خورده‌اند. وضعیت مخزن و تاریخ این عکس‌برداری در
> [00-CURRENT-STATE](00-CURRENT-STATE.md) آمده است.

## Base URL

```
http://127.0.0.1:8470
```

سرویس فقط روی loopback گوش می‌دهد (`LOOPBACK_HOSTS` در `api.py:847`). اجرا
با هاست غیرحلقه‌ای در `cli.py:52` رد می‌شود و با exit code ۲ خارج می‌شود.

## Authentication

تمام اندپوینت‌های `/api/*` به توکن Bearer نیاز دارند. فقط shell رابط کاربری
(`/`، `/ui`، `/index.html`) بدون احراز هویت سرو می‌شود، چون یک مرورگر که به
آدرس loopback می‌رود نمی‌تواند هدر `Authorization` بفرستد. shell هیچ رازی
> در خود ندارد.

```
Authorization: Bearer <token>
```

توکن از طریق `python3 -m agent_os.cli token` ساخته می‌شود.

## Response Format

همهٔ پاسخ‌ها JSON هستند. **کالکشن‌ها در یک آبجکت پیچیده می‌شوند، نه آرایهٔ
بدون پوشش** (مثلاً `{"missions": [...]}`، نه `[...]`).

خطاها این ساختار را دارند:

```json
{
  "error": {
    "code": "dispatch_refused",
    "message": "approval_expired"
  }
}
```

خطاهای ۵۰۰ هرگز جزئیات داخلی نشت نمی‌کنند؛ فقط کد `internal` را برمی‌گردانند.

## Status Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created (POST که یک منبع جدید می‌سازد) |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (wrong principal, source not allowed) |
| 404 | Not found (یا آیدی ناقص در مسیر) |
| 405 | Method not allowed (متد روی این مسیر پشتیبانی نمی‌شود) |
| 409 | Conflict (duplicate, dispatch refused) |
| 413 | Payload too large (>1MB؛ `MAX_BODY` در `api.py:717`) |
| 500 | Internal error (بدون نشت جزئیات) |

**هدرهای پاسخ:** `Content-Type`، `Content-Length`، و
`X-Content-Type-Options: nosniff` (`api.py:731`). توجه: `X-Frame-Options`
ارسال **نمی‌شود**.

**روش‌های مجاز روی هر مسیر:** اگر متدی روی مسیر پشتیبانی نشود، ۴۰۵
برمی‌گردد.

---

## Status

### GET /api/status

وضعیت سرور. **Read-only.** نشان می‌دهد کدام اجراگرها در رجیستری هستند.

**Auth:** Bearer.

**Response:**
```json
{
  "name": "agent-os",
  "version": "0.2.0",
  "executors": ["fake-executor"],
  "db_path": "/home/mehdi/.local/share/agent-os/mission-control.db"
}
```

> توجه: به‌طور پیش‌فرض فقط `fake-executor` در رجیستری ثبت می‌شود
> (`cli.py:66`). `subprocess-executor` و `container-executor` فقط با پرچم‌های
> صریح اضافه می‌شوند (جدول اجراگرها در [CAPABILITY-MATRIX](CAPABILITY-MATRIX.md)).

---

## Missions

### GET /api/missions

فهرست همهٔ ماموریت‌ها. **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "missions": [
    {
      "id": "m_abc123",
      "title": "Refactor auth",
      "state": "active",
      "created_at": "2026-10-04T12:00:00+00:00"
    }
  ]
}
```

### POST /api/missions

ساخت یک ماموریت. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{"title": "Refactor auth"}
```

**Response (201):** `Mission` (همان شکل ردیف بالا).

### GET /api/missions/{id}

گرفتن یک ماموریت. **Read-only.**

**Auth:** Bearer. **Response:** `Mission` — ۴۰۴ `not_found` اگر آیدی ناموجود
یا ناقص باشد.

### POST /api/missions/{id}/activate

فعال کردن یک ماموریت. **Mutating.**

**Auth:** Bearer. **Response (200):** `Mission`.

---

## Jobs

### GET /api/jobs

فهرست همهٔ job‌ها. **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "jobs": [
    {
      "id": "j_abc123",
      "mission_id": "m_abc123",
      "title": "Run tests",
      "proposed_by": "planner",
      "executor": "subprocess-executor",
      "workspace_paths": ["/home/mehdi/workspace/myproject"],
      "actions": ["run_tests"],
      "state": "awaiting_approval",
      "attempt_no": 0,
      "manifest_hash": "sha256:abc123...",
      "command": ["python", "-m", "unittest", "discover"],
      "created_at": "2026-10-04T12:00:00+00:00",
      "updated_at": "2026-10-04T12:00:00+00:00"
    }
  ]
}
```

### POST /api/jobs

پیشنهاد یک job. **Mutating.** (این مسیر جایگزین مسیر قدیمی
`POST /api/missions/{mission_id}/jobs` است که وجود نداشت.)

**Auth:** Bearer. **Body:**
```json
{
  "mission_id": "m_abc123",
  "title": "Run tests",
  "executor": "subprocess-executor",
  "workspace_paths": ["/home/mehdi/workspace/myproject"],
  "actions": ["run_tests"],
  "command": ["python", "-m", "unittest", "discover"]
}
```

فیلدهای اجباری: `mission_id`، `title`، `executor`، `workspace_paths`،
`actions`. `command` اختیاری است و **باید یک لیست غیرخالی از رشته‌ها
(argv)** باشد؛ در غیر این صورت ۴۰۰ `command_not_a_list`. `proposed_by`
اختیاری (پیش‌فرض `planner`).

**Response (201):** `Job`.

### GET /api/jobs/{id}

گرفتن یک job. **Read-only.**

**Auth:** Bearer. **Response:** `Job` — ۴۰۴ `not_found` اگر ناموجود.

### GET /api/jobs/{id}/evidence

آخرین evidence ثبت‌شدهٔ یک job، که از event log خوانده می‌شود (دائمی در
راه‌اندازی مجدد). **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "job_id": "j_abc123",
  "state": "completed_verified",
  "evidence": {
    "diff": "...",
    "test_report": "...",
    "exit_code": 0
  },
  "event_seq": 42,
  "ts": "2026-10-04T12:05:00+00:00",
  "kind": "job_completed_verified"
}
```

اگر evidence‌ای نباشد: `{"job_id": ..., "state": ..., "evidence": null,
"note": "no persisted evidence for this job"}`. مقادیر متنی evidence
**قرمزسازی (redact)** می‌شوند تا رازها نشت نکنند.

### POST /api/jobs/{id}/dispatch

اجرای یک job تأییدشده. **Mutating.** سرور approval را **قبل** از اجرای
executor اعتبارسنجی می‌کند.

**Auth:** Bearer. **Body:** ندارد.

**Response (200):**
```json
{
  "receipt": {
    "job_id": "j_abc123",
    "attempt": 1,
    "final_state": "completed_verified",
    "duplicated": false
  },
  "job": { "id": "j_abc123", "title": "Run tests", "state": "completed_verified", "...": "..." }
}
```

`job` شکل کامل `Job` را دارد (مثل `GET /api/jobs` در بالا)، یا `null` اگر
دیگر یافت نشود.

**Response (409):** `dispatch_refused` (مثلاً `approval_expired`،
`unknown_executor`).

### POST /api/jobs/{id}/reconcile

تطبیق وضعیت یک job قطع‌شده — فقط انسان. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{"final_state": "completed_verified", "note": "Manually verified"}
```

هر دو فیلد اجباری‌اند. `final_state` باید یکی از مقادیر مجاز `JobState`
باشد (`completed_verified`، `completed_unverified`، `failed`،
`interrupted_unknown` و غیره)؛ در غیر این صورت ۴۰۰.

**Response (200):** `Job`.

---

## Approvals

### GET /api/approvals

فهرست همهٔ approval‌ها. **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "approvals": [
    {
      "id": "a_abc123",
      "job_id": "j_abc123",
      "decision": "granted",
      "scope": {
        "executor": "subprocess-executor",
        "workspace_paths": ["/home/mehdi/workspace/myproject"],
        "actions": ["run_tests"],
        "command": ["python", "-m", "unittest", "discover"],
        "action": "run_tests"
      },
      "requested_at": "2026-10-04T12:00:00+00:00",
      "decided_at": "2026-10-04T12:01:00+00:00",
      "decided_by": "human",
      "expires_at": "2026-10-04T18:00:00+00:00",
      "manifest_hash": "sha256:abc123...",
      "consumed_at": null
    }
  ]
}
```

### POST /api/approvals

درخواست تأیید انسان برای یک job. **Mutating.** (این مسور جایگزین مسیر
قدیمی `POST /api/jobs/{id}/request-approval` است که وجود نداشت.)

**Auth:** Bearer. **Body:**
```json
{
  "job_id": "j_abc123",
  "expires_at": "2026-10-04T18:00:00+00:00",
  "scope": {
    "executor": "subprocess-executor",
    "workspace_paths": ["/home/mehdi/workspace/myproject"],
    "actions": ["run_tests"]
  },
  "action": "run_tests"
}
```

تنها `job_id` اجباری است. نکات مهم:

- **`scope.command` در بدنهٔ درخواست عمداً نادیده گرفته می‌شود.** scope یک
  کران است که فراخوان می‌تواند پیشنهاد کند، ولی command خودِ عملیات است و
  باید از job بیاید. اگر فراخوان `scope.command` بفرستد، یک رویداد
  `approval.scope_command_ignored` در event log و لاگ ثبت می‌شود تا هیچ
  کلاینتি فکر نکند کار کرده است.
- `expires_at` اختیاری است. اگر timezone نداشته باشد، UTC فرض می‌شود.
- `action` اختیاری است و approval را به یک عمل خاص می‌بندد؛ اگر نیاید، به
  اولین actionِ job بسته می‌شود.

**Response (201):** `Approval`.

### POST /api/approvals/{id}/decide

تصمیم دربارهٔ یک approval — فقط انسان. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{"decision": "granted"}
```

`decision` باید یکی از `requested`، `granted`، `denied` باشد. **فیلد
`principal` از سمت سرور به `HUMAN` قفل شده است** و ارسال آن در بدنه بی‌اثر
است؛ این یک تصمیم عمدی امنیتی است تا نتواند جعل شود.

**Response (200):** `Approval`.

---

## Projects

### GET /api/projects

فهرست پروژه‌های ثبت‌شده. **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "projects": [
    {
      "id": "p_abc123",
      "name": "myproject",
      "environment": "wsl",
      "root": "/home/mehdi/workspace/myproject",
      "canonical_root": "/home/mehdi/workspace/myproject",
      "is_symlink": false,
      "read_only": false,
      "created_at": "2026-10-04T12:00:00+00:00"
    }
  ]
}
```

### POST /api/projects

ثبت ریشهٔ یک پروژه. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{"name": "myproject", "environment": "wsl", "root": "/home/mehdi/workspace/myproject"}
```

هر سه فیلد اجباری‌اند. پروژهٔ تکراری → ۴۰۹ `conflict`.

**Response (201):** `Project`.

### DELETE /api/projects/{id}

فراموشی یک پروژه. **Mutating.** یک رویداد `project_removed` در event log
ثبت می‌کند.

**Auth:** Bearer. **Response (200):**
```json
{"removed": true}
```

اگر آیدی ناموجود باشد → ۴۰۴ `not_found`.

---

## Executors

### GET /api/executors

فهرست اجراگرهای ثبت‌شده. **Read-only.** فقط کلیدهای رجیستری را برمی‌گرداند،
نه artifact‌ها را.

**Auth:** Bearer. **Response:**
```json
{"executors": ["fake-executor"]}
```

> **پیش‌فرض فقط `fake-executor` است** (`cli.py:66`). برای
> `subprocess-executor` به `--enable-subprocess` **و** `--source-workspace`
> نیاز است (در غیر این صورت exit ۲)، و برای `container-executor` به
> `--enable-container` (تصویر پیش‌فرض `python:3.14-slim`، timeout ۱۲۰).

---

## Tools

### GET /api/tools/discover

کشف ابزارها. ⚠ **این یک read امن نیست.**

**Auth:** Bearer. **Body:** ندارد.

**Response (200):**
```json
{
  "tools": [
    {
      "id": "t_abc123",
      "name": "python3",
      "environment": "wsl",
      "path": "/usr/bin/python3",
      "version": "3.14.4",
      "confidence": "exact"
    }
  ],
  "execution_granted": false
}
```

> **هشدار:** این مسیر `discovery.discover(...)` را اجرا می‌کند که **probe از
> باینری‌های allowlist‌شده** انجام می‌دهد. هرچند چیزی نصب نمی‌کند و
> `execution_granted: false` است و هیچ grant‌ای ایجاد نمی‌شود، این اندپوینت
> نباید در pollingِ داشبورد به‌عنوان «read-only» معرفی شود. روی
> environment‌های پشتیبانی‌نشده → ۴۰۰ `environment_unsupported`.
>
> **نتیجهٔ discovery ثبت نمی‌شود:** کشف هیچ چیزی را در registry یا store
> نمی‌نویسد. درخواست discovery صرفاً گزارش می‌دهد؛ ثبت یک ابزار نیاز به
> `POST /api/tools/registry` (mutating) دارد.

### POST /api/tools/discover

همان کشف، با بدنهٔ تنظیمات اختیاری. همان هشدار بالا اعمال می‌شود — این
هم یک read امن نیست و نتیجه‌اش ثبت نمی‌شود.

**Auth:** Bearer. **Body (اختیاری، شکل کلی):**
```json
{ "environment": "wsl", "names": ["python3"] }
```
`environment` پشتیبانی‌نشده → ۴۰۰ `environment_unsupported`. **Response (200):**
همان `GET`.

### GET /api/tools/registry

فهرست ابزارهای ثبت‌شده (بررسی‌شده توسط مالک). **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "tools": [
    {
      "id": "t_abc123",
      "name": "python3",
      "environment": "wsl",
      "path": "/usr/bin/python3",
      "version": "3.14.4",
      "confidence": "exact"
    }
  ]
}
```

### POST /api/tools/registry

ثبت یک ابزار بررسی‌شده. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{
  "name": "python3",
  "environment": "wsl",
  "path": "/usr/bin/python3",
  "version": "3.14.4",
  "confidence": "not_probed"
}
```

فقط `name` و `environment` اجباری‌اند.

**Response (201):** `Tool`.

### DELETE /api/tools/registry/{id}

حذف یک ابزار از رجیستری. **Mutating.**

**Auth:** Bearer. **Response (200):**
```json
{"removed": true}
```

---

## Workflows

### GET /api/workflows

فهرست workflow template‌ها. **Read-only.**

**Auth:** Bearer. **Response:** `{"workflows": [WorkflowTemplate...]}`.

### GET /api/workflows/{id}

گرفتن یک template با node‌هایش. **Read-only.**

**Auth:** Bearer. **Response:** `WorkflowTemplate` (شامل `nodes`) — ۴۰۴ اگر
ناموجود.

### POST /api/workflows

ساخت یک workflow template. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{
  "title": "CI Pipeline",
  "description": "Lint, test, build",
  "inputs_schema": {},
  "default_executor": "subprocess-executor",
  "nodes": [
    {"id": "lint", "action_type": "execute_job", "depends_on": []},
    {"id": "review", "action_type": "human_approval", "depends_on": ["lint"]},
    {"id": "test", "action_type": "execute_job", "depends_on": ["review"]}
  ]
}
```

فقط `title` اجباری است. **`action_type` باید یکی از این مقادیر باشد**
(`NodeActionType` در `models.py:339`): `execute_job`، `human_approval`،
`conditional_branch`. مقادیر قدیمی مثل `lint` یا `run_tests` دیگر مجاز
نیستند و ۴۰۰ برمی‌گردانند. هر node باید `id` و `action_type` داشته باشد.

**Response (201):** `WorkflowTemplate` با `nodes`.

### POST /api/workflows/{id}/execute

اجرای یک workflow template. **Mutating.** یک mission جدید می‌سازد و آن را
فعال می‌کند، سپس node‌های بدون وابستگی را به‌صورت job proposal پخش
می‌کند. node‌های `human_approval` و `conditional_branch` به job تبدیل
نمی‌شوند.

**Auth:** Bearer. **Body:**
```json
{"inputs": {}}
```

`inputs` باید یک object باشد. `{{inputs.xxx}}` در command‌های node جایگزین
می‌شود.

**Response (200):** `WorkflowExecution`.

### GET /api/workflow-executions

فهرست اجرای workflow‌ها. **Read-only.**

**Auth:** Bearer. **Response:** `{"executions": [WorkflowExecution...]}`.

### GET /api/workflow-executions/{id}

گرفتن یک اجرا. **Read-only.**

**Auth:** Bearer. **Response:** `WorkflowExecution` — ۴۰۴ اگر ناموجود.

---

## Graphics

### GET /api/graphics

فهرست graphic‌ها. **Read-only.**

**Auth:** Bearer. **Response:** `{"graphics": [Graphic...]}`.

### GET /api/graphics/{id}

گرفتن یک graphic. **Read-only.** ۴۰۴ اگر ناموجود.

**Auth:** Bearer. **Response:** `Graphic`.

### POST /api/graphics

ساخت یک graphic. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{
  "title": "Workflow DAG",
  "kind": "diagram",
  "config": {"nodes": [], "edges": []}
}
```

`title` و `kind` اجباری‌اند. **`kind` باید یکی از این باشد** (`GraphicKind`
در `graphics.py:35`): `shape_2d`، `shape_3d`، `chart`، `diagram`. `config`
اختیاری است ولی باید یک object باشد.

**Response (201):** `Graphic`.

### POST /api/graphics/import

وارد کردن تنظیمات یک graphic از یک bundle. **Mutating.**

**Auth:** Bearer. **Body:** bundle خروجیِ `export`. **Response (201):**
`Graphic`.

### POST /api/graphics/{id}/render

رندر یک graphic به SVG. **Read-only** (هیچ state‌ای را تغییر نمی‌دهد).

**Auth:** Bearer. **Response (200):**
```json
{"svg": "<svg>...</svg>"}
```

رندر یک graphic حذف‌شده → ۴۰۰. graphic ناموجود → ۴۰۴.

### POST /api/graphics/{id}/export

خروجی گرفتن تنظیمات یک graphic. **Read-only.**

**Auth:** Bearer. **Response (200):** bundle قابل import.

### POST /api/graphics/{id}/update

به‌روزرسانی config یک graphic. **Mutating.**

**Auth:** Bearer. **Body:**
```json
{"config": {"nodes": []}}
```

`config` باید یک object باشد. **Response (200):** `Graphic` کاملِ به‌روزشده.
ناموجود → ۴۰۴.

### DELETE /api/graphics/{id}

حذف نرم (soft delete) یک graphic. **Mutating.**

**Auth:** Bearer. **Response (200):**
```json
{"deleted": "gfx_abc123"}
```

ناموجود → ۴۰۴.

---

## Events

### GET /api/events

فهرست همهٔ رویدادها — audit log فقط-الحاقی. **Read-only.**

**Auth:** Bearer. **Response:**
```json
{
  "events": [
    {
      "seq": 1,
      "ts": "2026-10-04T12:00:00+00:00",
      "kind": "job_dispatched",
      "payload": {"job_id": "j_abc123"},
      "dedup_key": null
    }
  ]
}
```

رویدادها به ترتیب `seq` برمی‌گردند. هیچ query param‌ای برای صفحه‌بندی وجود
ندارد.

### GET /api/events/external

فهرست رویدادهای خارجی ثبت‌شده (مثلاً از Hermes). **Read-only.** فقط
رویدادهایی با `kind == "external.tool_call"` را برمی‌گرداند، از جدید به قدیم.

**Auth:** Bearer. **Response:** `{"events": [Event...]}`.

> این رویدادها observation-only هستند: چیزهایی که یک runtime دیگر قبلاً
> ثبت کرده. هرگز نباید به‌عنوان چیزی که جلوگیری شد یا intercept شد،
> تفسیر شوند.

### POST /api/events/ingest

خواندن فعالیت واقعی از یک منبع خارجی به داخل event log. **Mutating** (نه
read-only): رویدادهای جدید به event log اضافه می‌کند.

**Auth:** Bearer. **Body:**
```json
{
  "source": "/home/mehdi/.hermes/events.sqlite",
  "cursor": 0,
  "limit": 500
}
```

`source` اجباری است و **باید داخل ریشه‌های مجاز باشد**؛ در غیر این صورت
۴۰۳ (`assert_source_allowed`). `cursor` و `limit` اختیاری‌اند (پیش‌فرض ۰ و
۵۰۰). dedup_key از id ردیف خودِ منبع ساخته می‌شود، تا خواندن مجدد یک
no-op باشد.

**Response (200):**
```json
{
  "status": "ok",
  "reason": null,
  "added": 12,
  "cursor": 12,
  "skipped": 0,
  "source": {"path": "/home/mehdi/.hermes/events.sqlite"}
}
```

سه حالت متمایز داریم که UI نباید آن‌ها را یکی کند: `status: "ok"` (رویداد
اضافه شد یا چیزی جدید نبود) و `status: "unavailable"` (منبع اصلاً خوانده
نمی‌شود؛ `added: 0` به معنای «هیچ چیزی جدید نبود» نیست).

هر رویداد واردشده `observed_only: true` دارد — این رفتار ثبت‌شده است، نه
یک action جلوگیری‌شده.

---

## Knowledge — Planned (بدون مسیر HTTP)

> **این مسیرها وجود ندارند.** لایهٔ service و store متد‌هایی دارند
> (`service.create_knowledge_doc`، `store.update_knowledge_doc`)، ولی **هیچ
> مسیر HTTP‌ای روی آن‌ها نقشه‌برداری نشده است.** این‌ها باید «Planned»
> تلقی شوند، نه بخشی از API. مسیرهای قدیمی `GET /api/knowledge`،
> `POST /api/knowledge` و `PUT /api/knowledge/{id}` که در نسخه‌های قدیمی
> این سند بودند، حذف شدند چون در کد نبودند.
