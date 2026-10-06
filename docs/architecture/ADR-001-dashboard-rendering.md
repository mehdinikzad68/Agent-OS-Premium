# ADR-001: Dashboard rendering — Canvas 2D is the official baseline

- **وضعیت:** پذیرفته‌شده (Accepted)
- **تاریخ:** ۲۰۲۶-۱۰-۰۶
- **تصمیم‌گیرنده:** مالک محصول (انسان)
- **جایگزینی می‌کند:** تداخل ضمنی بین مشخصات Phase 8 (Canvas 2D) و کامیت
  HEAD «feat: 3D Galaxy Command UI integration»

## زمینه

در HEAD `4783c9b` مخزن WSL (`/home/mehdi/workspace/Agent-OS`)،
`control-service/agent_os/web/index.html` نسخهٔ Three.js «Galaxy Command» است:
۱۴ اشارهٔ `THREE.`، یک اشارهٔ `WebGL`، و یک `<script src="three.min.js">`.
در همان حال، working treeِ همان فایل یک تغییر **نه‌کامیت‌شده** با حجم
+۲۰۰۴/−۸۳۰ خط است که نسخهٔ Canvas 2D «Neural Scene / Neural Command» را نگه
می‌دارد: هیچ اشارهٔ `THREE.`/`WebGL`/`<script src>` ندارد و دو فراخوانی واقعی
`getContext("2d")` (خط‌های 1285 و 1446) به‌علاوهٔ یک capability check بدون آرگومان
(`getContext` در خط 1876) در آن است.

دو سند طراحی هم وجود داشتند که با هم تضاد می‌گفتند: مشخصات Phase 8
(`docs/09-سند-طراحی-UI-2D-Mission-Control.md` و کپی بایت‌به‌بایتِ آن در
`docs/ui-2d-mission-control-design.md`) یک داشبورد «۱۰۰٪ مستقل از
3D/WebGL/Three.js، بدون وابستگی خارجی به CDN» را الزام می‌کرد، در حالی که
کامیت HEAD پروژه را به سمت Three.js می‌برد. مسالهٔ عملیاتی این بود که
هیچ‌کدام از دو لایه نمی‌توانستند «مرجع» باشند بدون اینکه دیگری پنهان یا
حذف شود.

## تصمیم

**خط پایهٔ رسمی و مرجع داشبورد Agent OS نسخهٔ Canvas 2D (2D «Neural
Command») است.** لایهٔ Three.js در HEAD **آزمایشی و غیرمرجع** تلقی می‌شود،
تا زمانی که یک ADR صریحِ جدید چیز دیگری اعلام کند.

این تصمیم در مورد **مستندسازی** است، نه در مورد کد. هیچ کد Three.js،
مسیریابی، دارایی (`three.min.js`) یا رابطی حذف یا تغییر نکرده‌ایم و نخواهیم
کرد. سه ویژگی کدنویسی این ADR به‌صورت صریح ممنوع است: حذف لایهٔ Three.js،
حذف مسیر `/three.min.js`، و اصلاح مسیر تکراریِ `/three.min.js` در
`api.py:771–776`. هر کدام نیاز به یک تغییر جداگانهٔ کد در آینده دارد.

## دلایل

1. **آفلاین‌بودن.** مشخصات Phase 8 صریحاً وابستگی به CDN را منع می‌کند.
   نسخهٔ Canvas 2D هیچ وابستگی خارجی ندارد؛ لایهٔ Three.js به
   `three.min.js` وابسته است (که خوشبختانه به‌صورت محلی bundled شده، ولی
   این وابستگی همچنان یک فایل و یک مسیر اضافی است).
2. **قانون محصول.** `agent-os-product-development-master-plan-EN.md:119`
   می‌نویسد: «The 3D layer is progressive enhancement and must never be the
   only path to an approval». یعنی ۳D هرگز تنها مسیر تأیید نمی‌تواند
   باشد، پس ۲D باید همیشه کار کند.
3. **تثبیت پنهان.** وقتی HEAD یک رابط است و working tree رابط دیگری را
   نگه می‌دارد، هر خواننده‌ای (انسان یا agent) نمی‌تواند بداند کدام مرجع
   است. این ADR مرجع را روشن می‌کند بدون اینکه چیزی را پاک کند.
4. **دسترس‌پذیری.** Canvas 2D با کیبورد و screen reader سینک‌تر است و
   نیاز به GPU/WebGL ندارد؛ Three.js روی سخت‌افزار یا مرورگرهای قدیمی
   ممکن است اصلاً باز نشود.

## عواقب

- **پشتیبان ۲D همیشه لازم است.** هر ویژگی جدید باید روی Canvas 2D کار
  کند، حتی اگر بعداً نسخهٔ ۳D هم بگیرد.
- **آفلاین‌بودن یک قانون واقعی است.** یک تغییر که حتی یک وابستگی CDN هم
  اضافه کند، این ADR را نقض می‌کند.
- **دسترس‌پذیری یک نیازمندی است، نه یک افزودنی.** مسیر تأیید باید با
  کیبورد کامل باشد.
- **نگاه و احساس حفظ می‌شود.** هر بازنویسی UI باید شباهت بصری مشخصات
  مرجع را حفظ کند.
- **حذف Three.js نیاز به تغییر کد جداگانه دارد.** این ADR چنین کاری
  انجام نمی‌دهد و مجوز آن را هم نمی‌دهد.
- **هیچ ضمانتی برای `docs/UI-Design/` نیست.** آن پوشه untracked است و
  محتوای HTML آن ممکن است به CDN وابسته باشد؛ نباید «آفلاین» یا
  «production» نامیده شود.

## با توجه به

- [00-CURRENT-STATE](../00-CURRENT-STATE.md) — شواهد دقیق working tree و HEAD
- [CAPABILITY-MATRIX](../CAPABILITY-MATRIX.md) — وضعیت رابط‌ها
- `docs/09-سند-طراحی-UI-2D-Mission-Control.md` و
  `docs/ui-2d-mission-control-design.md` (کپی بایت‌به‌بایت) — مشخصات Phase 8
- `agent-os-product-development-master-plan-EN.md:119` — قانون enhancement
