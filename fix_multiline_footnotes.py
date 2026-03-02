"""
fix_multiline_footnotes.py
--------------------------
يدمج كل حاشية متعددة الأسطر في سطر واحد
لمنع انكسار بلوك الحواشي في Markdown
"""
import re, sys, pathlib

def fix_file(text: str) -> str:
    lines = text.splitlines()
    result = []
    i = 0
    fn_def = re.compile(r'^\[\^\d+\]:')

    while i < len(lines):
        line = lines[i]
        if fn_def.match(line):
            # ابدأ تجميع الحاشية
            parts = [line.rstrip()]
            i += 1
            # أضف الأسطر التالية التي هي امتداد (غير فارغة وغير حاشية جديدة)
            while i < len(lines):
                nxt = lines[i]
                if nxt == '' or fn_def.match(nxt):
                    break
                # سطر امتداد — أدمجه
                parts.append(nxt.strip())
                i += 1
            # ادمج في سطر واحد
            result.append(' '.join(p for p in parts if p))
        else:
            result.append(line)
            i += 1

    return '\n'.join(result)


def main():
    if len(sys.argv) < 2:
        # عالج كل ملفات md في المجلد الحالي
        paths = list(pathlib.Path('.').glob('*.md'))
    else:
        paths = [pathlib.Path(p) for p in sys.argv[1:]]

    for path in paths:
        if path.name.lower() == 'readme.md':
            continue
        original = path.read_text(encoding='utf-8')
        fixed = fix_file(original)
        if fixed != original:
            path.write_text(fixed, encoding='utf-8')
            # احسب عدد الحواشي المدمجة
            merged = sum(
                1 for o, f in zip(original.splitlines(), fixed.splitlines())
                if o != f and re.match(r'^\[\^\d+\]:', f)
            )
            print(f"✅ {path.name}: أُصلح {merged} حاشية متعددة الأسطر")
        else:
            print(f"➖ {path.name}: لا تغيير")


if __name__ == '__main__':
    main()