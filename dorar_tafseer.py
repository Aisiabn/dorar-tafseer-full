"""
diag_footnotes.py
-----------------
يكشف الحاشية المسببة للاندماج بعد رقم 297
"""
import re, sys

path = sys.argv[1] if len(sys.argv) > 1 else "006_سُورةُ_الأنعامِ.md"
text = open(path, encoding="utf-8").read()

# استخرج كل تعريفات الحواشي مع موضعها وأول سطر بعدها
def_pattern = re.compile(r'^\[\^(\d+)\]:(.+)', re.MULTILINE)
matches = list(def_pattern.finditer(text))

print(f"إجمالي تعريفات الحواشي: {len(matches)}\n")

# ابحث عن الحاشية التي يتبعها سطر مُندَج (يبدأ بمسافة)
continuation = re.compile(r'^\s+\S')  # سطر يبدأ بمسافة ثم محتوى

problem_count = 0
for i, m in enumerate(matches):
    num = m.group(1)
    # الموضع في النص مباشرة بعد هذا التعريف
    end = m.end()
    # السطر التالي
    rest = text[end:]
    next_line_match = re.match(r'\n(.+)', rest)
    if next_line_match:
        next_line = next_line_match.group(1)
        # هل السطر التالي ليس تعريف حاشية جديدة وليس فارغاً؟
        if next_line.strip() and not next_line.startswith('[^'):
            # هذا سطر امتداد — عادي
            pass
    
    # الأهم: هل هذه الحاشية نفسها تبدأ بمسافة؟
    # (بمعنى هل [^N]: جاء بعد indent؟)
    line_start = text.rfind('\n', 0, m.start()) + 1
    prefix = text[line_start:m.start()]
    if prefix.strip() == '' and prefix != '':
        print(f"⚠️  حاشية [^{num}] (السطر ~{text[:m.start()].count(chr(10))+1}) تبدأ بمسافة: {repr(prefix)}")
        problem_count += 1

print()

# طريقة أخرى: احسب الفجوات في تسلسل الأرقام
nums = [int(m.group(1)) for m in matches]
print("أول 10 أرقام حواشي:", nums[:10])
print("آخر 10 أرقام:", nums[-10:])
print(f"\nإجمالي المشاكل الأولية: {problem_count}")

# اطبع الحاشية رقم 295-300 للفحص البصري
print("\n--- محتوى الحواشي 295-302 ---")
for m in matches:
    n = int(m.group(1))
    if 295 <= n <= 302:
        line_no = text[:m.start()].count('\n') + 1
        print(f"[^{n}] (سطر {line_no}): {repr(m.group(0)[:80])}")