# KERNEL-GAP — مقایسهٔ معماری Agent-OS با AIOS و نقشهٔ مسیر «سیستم‌عامل عامل‌ها»

**وضعیت سند:** تحلیل فاز ۰ (بدون کد جدید).
**نویسنده:** مهدی نیک‌زاد سمسکندی.
**تاریخ:** ۲۰۲۶-۱۰-۱۱.
**مبنا:** بازخوانی مستقیم کد Agent-OS در WSL و سورس کرنل AIOS از GitHub (در همین تاریخ).
**قاعده:** هر ادعای این سند باید به یک فایل مشخص ارجاع بدهد. هرچه سند یا کد نشان نداده باشد، «تأیید نشده» علامت خورده است.

---

## ۱. هدف این سند

پاسخ به یک پرسش مشخص:

> Agent-OS امروز یک **ارکستراتور** است یا یک **سیستم‌عامل عامل‌ها**؟ و برای رسیدن به دومی، دقیقاً چه کم دارد؟

برای پاسخ، دو کدبیس را رو‌به‌روی هم می‌گذاریم:

- **Agent-OS** (این ریپو) — `control-service/agent_os/`.
- **AIOS** — کرنل دانشگاه Rutgers (`agiresearch/AIOS`)، مقالهٔ arXiv:2403.16971، پذیرفته‌شده در COLM 2025.

---

## ۲. تعریف عملیاتی (تفاوت ارکستراتور و سیستم‌عامل)

تفاوت در **جای کنترل** است، نه در تعداد امکانات:

| بُعد | ارکستراتور | سیستم‌عامل عامل‌ها |
|---|---|---|
| جای تصمیم | عامل تصمیم می‌گیرد، ارکستراتور هماهنگ می‌کند | کرنل تصمیم می‌گیرد؛ عامل فقط درخواست می‌دهد |
| دسترسی به منبع | عامل آزاد است | فقط از مسیر syscall |
| زمان‌بندی | صف ساده یا هم‌زمانی | زمان‌بند واقعی (اولویت، batch، context switch) |
| جداسازی | ندارد | هر عامل فضای خودش |
| دور زدن | ممکن است | ناممکن (تنها مسیر) |

**معیار سنجش:** اگر عاملی بتواند بدون عبور از دروازهٔ مرکزی عمل کند، هنوز سیستم‌عامل نیست.

---

## ۳. وضعیت واقعی Agent-OS (خوانده‌شده از کد، ۲۰۲۶-۱۰-۱۱)

### ۳.۱ ساختار

مسیر کانونی: `/home/mehdi/workspace/Agent-OS` (طبق `docs/architecture/ADR-002-canonical-repository.md`).

```
control-service/agent_os/
  service.py        1138 خط   ← ماشین حالت قطعی، dispatch()
  store.py          1016 خط   ← SQLite، حقیقت عملیاتی
  api.py             888 خط   ← HTTP API
  graphics.py        527 خط
  models.py          411 خط   ← مدل‌های دامنه، encode_command
  logging_setup.py   342 خط   ← لاگ ساختاریافته + redact
  discovery.py       327 خط   ← کشف ابزار
  cli.py             300 خط
  paths.py            88 خط   ← canonicalize، is_within
  policy.py           69 خط   ← validate_dispatch (۱۰ بررسی)
  evidence.py         60 خط
  ─────────────────────────
  جمع:              5175 خط
```

تست‌ها: ۳۸ فایل در `control-service/tests/`.

### ۳.۲ آنچه واقعاً دارد

| قابلیت | شاهد در کد |
|---|---|
| دروازهٔ تأیید deny-before-dispatch | `policy.py::validate_dispatch` — ۱۰ بررسی، اولین شکست برنده |
| تأیید یک‌بارمصرف | `policy.py` — `approval_already_consumed` |
| قفل به hash مانیفست | `policy.py` — `manifest_changed_new_decision_required` |
| تطابق بایت‌به‌بایت فرمان | `policy.py` — بررسی ۸ (`command_not_in_scope`) |
| تفکیک اختیار | `models.py` — PLANNER پیشنهاد، HUMAN تأیید، WORKER اجرا |
| مدارک اجباری برای VERIFIED | `service.py` — `REQUIRED_EVIDENCE_KEYS = ("diff", "test_report")` |
| بازداری و پاک‌سازی مدارک | `service.py::_bounded_evidence` — redact قبل از truncate |
| فرمان به‌صورت argv ساختاریافته | `models.py::encode_command` — JSON کانونیک، `shell=False` |
| لاگ رویداد فقط-افزودنی | `service.py` + `store.py` |
| کشف ابزار با بررسی اجراپذیری | `discovery.py` |

### ۳.۳ آنچه ندارد

- رابط syscall یکنواخت برای انواع عمل (LLM، حافظه، ذخیره‌سازی، ابزار).
- صف درخواست و زمان‌بند.
- اندازه‌گیری و سهمیهٔ منابع per-agent.
- ثبت و کارخانهٔ عامل (agent registry / factory).
- جداسازی state بین عامل‌ها.

---

## ۴. الگوی کرنل AIOS (خوانده‌شده از سورس)

### ۴.۱ جریان پنج‌لایه

```
Agent → hooks/modules/agent.py (ThreadPoolExecutor + ProcessStore)
      → syscall/syscall.py::SyscallExecutor.execute_request()   [انتخاب بر پایهٔ isinstance]
      → hooks/stores/_global.py   [چهار صف سراسری]
      → scheduler/fifo_scheduler.py  [چهار thread پردازش]
      → Managers: LLMAdapter | MemoryManager | StorageManager | ToolManager
```

### ۴.۲ ماژول‌های کرنل

| ماژول | نقش | فایل کلیدی |
|---|---|---|
| `syscall/` | رابط فراخوان | `syscall.py` (36KB)، `factory.py`، `schema.py` |
| `scheduler/` | صف و توزیع | `base.py`، `fifo_scheduler.py`، `rr_scheduler.py` |
| `hooks/` | صف‌ها و ثبت فرآیند | `stores/_global.py`، `modules/agent.py` |
| `memory/` | مدیریت حافظه و متن | `manager.py`، `context_injector.py`، `write_barrier.py` |
| `storage/` | فایل‌سیستم معنایی | `filesystem/lsfs.py`، `vector_db.py` |
| `tool/` | ابزار و MCP | `manager.py`، `mcp_server.py` |
| `llm_core/` | مسیریابی مدل | `adapter.py`، `routing.py` (شامل برنامه‌ریزی خطی با `pulp`) |

### ۴.۳ جزئیات ساختاری

- `Syscall(Thread)` — خودِ فراخوان یک thread با `event.wait()`. فیلدها: `pid`, `aid`, `status`, `response`, `time_limit`, `priority`, `created/start/end_time`, `source`, `target`.
- `execute_request()` فقط `isinstance` و `action_type` را می‌سنجد؛ هیچ بررسی مجوزی ندارد.
- `FIFOScheduler` چهار thread دائمی دارد؛ LLM را با `batch_interval` (پیش‌فرض ۱ ثانیه) دسته می‌کند.
- `ToolManager.__init__` هنگام ساخت، `mcp_server.py` را به‌عنوان subprocess بالا می‌آورد.

### ۴.۴ شکاف کلیدی (تمایز Agent-OS)

> **در تمام پنج لایهٔ کرنل AIOS، حتی یک خط کد دربارهٔ اجازه، سیاست یا تأیید انسانی وجود ندارد.**

کرنل AIOS فرض می‌کند هر عاملی که syscall می‌زند مجاز است. هیچ‌جا سیاستی سنجیده نمی‌شود، تأییدی گرفته نمی‌شود، و ردی ثبت نمی‌شود.

**نتیجه:** AIOS یک کرنل **کارآمدی** است. Agent-OS یک کرنل **مجوز** است. هیچ‌کدام آن یکی را ندارد.

---

## ۵. جدول مقایسه (هر سلول با شاهد)

| مؤلفهٔ کرنل | AIOS | Agent-OS | شاهد Agent-OS |
|---|---|---|---|
| رابط syscall یکنواخت | ✅ | ❌ | ندارد؛ فقط `dispatch()` |
| صف درخواست | ✅ | ❌ | — |
| زمان‌بند | ✅ | ❌ | — |
| مدیریت حافظه/متن | ✅ | ⚠️ نیمه | Obsidian به‌عنوان حافظهٔ مشترک، بدون مدیریت |
| مدیریت ابزار | ✅ | ✅ | `discovery.py` + MCP |
| مسیریابی LLM | ✅ | ⚠️ خارجی | OmniRoute |
| کارخانهٔ عامل | ✅ | ❌ | — |
| **دروازهٔ سیاست اجباری** | ❌ | ✅ | `policy.py` |
| **تأیید یک‌بارمصرف + hash** | ❌ | ✅ | `policy.py` |
| **مدارک اجباری (VERIFIED)** | ❌ | ✅ | `service.py` |
| **بازداری/پاک‌سازی مدارک** | ❌ | ✅ | `service.py::_bounded_evidence` |
| **لاگ رویداد فقط-افزودنی** | ⚠️ لاگ ساده | ✅ | `store.py` |
| جداسازی state | ⚠️ نیمه (`virtual_env`) | ❌ | — |
| سهمیهٔ منابع per-agent | ❌ | ❌ | هیچ‌کس ندارد |

---

## ۶. تز تمایز

> **AIOS می‌داند کدام عامل کدام منبع را بگیرد. Agent-OS می‌داند کدام عمل مجاز است. سیستم‌عاملی که هر دو را داشته باشد، هنوز وجود ندارد.**

این ادعا **قابل اندازه‌گیری** است. هارنس ضداثبات پیشنهادی: پنج فرمانی که گیت تأیید Hermes با `approvals.mode=smart` آن‌ها را ALLOW می‌کند باید به کرنل Agent-OS داده شوند و همه باید block شوند:

1. `git push origin main`
2. `docker rm -f <container>`
3. `curl -X POST <url>`
4. `wsl -e bash -c "<cmd>"`
5. `sudo apt install <pkg>`

اگر یکی از این‌ها رد نشود، کرنل شکست خورده است.

**توجه:** این پنج فرمان از یک اندازه‌گیری پیشین روی گیت Hermes می‌آید. اعتبار خود آن اندازه‌گیری در این سند **تأیید نشده** و باید پیش از استناد در پست عمومی، دوباره اجرا شود.

---

## ۷. معماری هدف

```
Agents (Hermes | DSH | Claude Code | OpenCode)
   │
   ▼  syscall(agent_id, action, args)          ← فاز ۱ (ندارد)
SYSCALL INTERFACE
   │
   ▼
POLICY KERNEL (fail-closed, deny-by-default)   ← ✅ دارد؛ باید به همهٔ syscallها وصل شود
   │
   ▼
RESOURCE GOVERNOR (توکن/پول/زمان per-agent)    ← فاز ۳ (هیچ‌کس ندارد)
   │
   ▼
SCHEDULER (FIFO + اولویت)                      ← فاز ۴ (ندارد)
   │
   ▼
EVENT BUS + AUDIT (زنجیره‌ای، بازپخش‌پذیر)      ← ✅ دارد
   │
   ▼
SHARED MEMORY (Obsidian) + STATE               ← ⚠️ نیمه
```

---

## ۸. نقشهٔ راه فازبندی‌شده

هر فاز باید **کوچک، قابل آزمون، و تمام‌شدنی** باشد. هر مسیر جدید سرویس پیش از کامیت بعدی **تست دائمی** می‌خواهد (درس ثبت‌شدهٔ فاز ۲).

| فاز | عنوان | خروجی | وضعیت |
|---|---|---|---|
| **۰** | تثبیت مبنا | همین سند | در حال انجام |
| **۱** | Syscall Interface | `syscall()` به‌عنوان تنها دروازه + اتصال `validate_dispatch` + هارنس ضداثبات ۵ فرمان + تست دائمی | تأیید نشده |
| **۲** | Approval syscall | تأیید انسانی به‌عنوان syscall درجه‌یک + UI در داشبورد | تأیید نشده |
| **۳** | Resource Governor | اندازه‌گیری و سهمیهٔ منابع per-agent | تأیید نشده |
| **۴** | Scheduler | FIFO با اولویت (الگو از AIOS) | تأیید نشده |
| **۵** | Agent Registry + Factory | ثبت و کشف عامل (الگو از AIOS) | تأیید نشده |

**تصمیم مالک:** دامنهٔ نسخهٔ ۱ در این سند **ثبت نشده** و باید توسط مالک مشخص شود.

---

## ۹. الزامات پیش از عمومی‌کردن ریپو

موارد زیر در بررسی ۲۰۲۶-۱۰-۱۱ دیده شد و **پیش از عمومی‌کردن** باید حل شوند:

| # | مورد | وضعیت فعلی | اقدام لازم |
|---|---|---|---|
| ۱ | **فایل لایسنس** | وجود ندارد | افزودن `LICENSE` (انتخاب مالک) + اعلان حق نشر با نام مالک |
| ۲ | **اعلان مالکیت در سرآیند کد** | ندارد | افزودن سرآیند مالکیت به فایل‌های `agent_os/` |
| ۳ | **شاخهٔ فعال** | `feature/neural-command-dashboard` | تعیین شاخهٔ پیش‌فرض عمومی (`main`) |
| ۴ | **تغییرات تأییدنشده** | ۳ فایل `UI-Image/*` حذف‌شده + پوشهٔ `docs/UI-Design/...` ردیابی‌نشده | تعیین تکلیف پیش از انتشار |
| ۵ | **node_modules در docs** | پوشهٔ `docs/UI-Design/.../node_modules/` فیزیکی موجود است (در گیت ردیابی نمی‌شود) | بررسی `.gitignore` و پاک‌سازی فیزیکی در صورت نیاز |
| ۶ | **فایل‌های Zone.Identifier** | `public/fonts/.gitkeep:Zone.Identifier` موجود | بررسی قاعدهٔ موجود `*:Zone.Identifier` |
| ۷ | **اسناد راهبردی/نقشه‌راه** | `agent-os-*-master-*.md` در `.gitignore` توضیح داده شده که **عمداً ردیابی می‌شوند** | تصمیم مالک: انتشار عمومی یا حذف از ردیابی |
| ۸ | **دو remote** | `origin` = private، `publicrepo` = public (استفاده‌نشده) | تأیید استراتژی انتشار |

---

## ۱۰. آنچه این سند تأیید نمی‌کند

- اینکه `Agent-OS-Premium` امروز عمومی است یا خصوصی — **تأیید نشده** (فقط نام در `.gitignore` و remote دیده شد).
- اینکه گیت تأیید Hermes واقعاً آن پنج فرمان را ALLOW می‌کند — **در این جلسه اندازه‌گیری نشد**.
- تعداد دقیق تست‌ها و اینکه همه پاس می‌شوند — **در این جلسه اجرا نشد**؛ فقط ۳۸ فایل تست دیده شد.
- کیفیت یا کفایت هر یک از فازهای ۱ تا ۵ — **طراحی، نه پیاده‌سازی**.

---

## ۱۱. منابع

- AIOS: `https://github.com/agiresearch/AIOS` — بازخوانی مستقیم سورس ۲۰۲۶-۱۰-۱۱.
- مقالهٔ AIOS: `arXiv:2403.16971` — COLM 2025.
- Agent-OS: `/home/mehdi/workspace/Agent-OS` — بازخوانی مستقیم کد ۲۰۲۶-۱۰-۱۱.
- ADR-002 (ریپوی کانونی): `docs/architecture/ADR-002-canonical-repository.md`.
- ADR-001 (داشبورد): `docs/architecture/ADR-001-dashboard-rendering.md`.

---

*این سند تحلیل است، نه تعهد. هیچ بخشی از فازهای ۱ تا ۵ پیاده‌سازی نشده است.*
