# النشر على Vercel

1. ارفع المجلد إلى GitHub ثم Import في Vercel، أو من الطرفية: `npm i -g vercel && vercel --prod`
2. المتغيرات (Settings → Environment Variables)، كلها اختيارية:
   - `API_KEY`: يحمي نقاط `/info` و`/link` و`/stream` (الواجهة العامة `/web/*` لا تحتاجه)
   - `COOKIES_B64`: كوكيز يوتيوب (base64 أو Netscape أو JSON) — حد Vercel لمجموع المتغيرات 64KB
   - `PROXY`: بروكسي سكني إن حجب يوتيوب عناوين Vercel
3. القيود الخاصة بـ Vercel: أقصى مدة للطلب 300 ثانية (تنزيل أطول يُستأنف بـ Range)،
   وسيرفر PO Token غير متاح (معطّل تلقائيا)، والعدّادات والكاش داخل الذاكرة لكل نسخة دالة.
4. حجم الحزمة بعد التثبيت ≈ 130MB (yt-dlp + ffmpeg). لتفعيل حل تحدي n عبر node أضف `nodejs-wheel-binaries`
   إلى requirements.txt (يضيف ≈ 200MB؛ يلزم حد حزمة 500MB)، والكود يكتشفه تلقائيا.
