import requests
from bs4 import BeautifulSoup
import re
import time
import os
import traceback


BASE    = "https://dorar.net"
INDEX   = "https://dorar.net/tafseer"
DELAY   = 1.0
OUT_DIR = "dorar_tafseer"

TEST_SURAHS = None if os.environ.get("TEST_SURAHS") == "None" else (
    int(os.environ["TEST_SURAHS"]) if os.environ.get("TEST_SURAHS") else None
)

_TIP_RE = re.compile(r'\x01(\d+)\x01')


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent"               : "Mozilla/5.0 (Windows NT 6.1; WOW64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/109.0.0.0 Safari/537.36",
        "Accept"                   : "text/html,application/xhtml+xml,application/xml;"
                                     "q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language"          : "ar,en-US;q=0.9,en;q=0.8",
        "Connection"               : "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def get_page(session, url, referer=INDEX):
    session.headers["Referer"] = referer
    try:
        r = session.get(url, timeout=20)
        print(f"  [{r.status_code}] {url}")
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print(f"  [ERR] {url} — {e}")
        return ""


SURAH_RE   = re.compile(r"^/tafseer/(\d+)$")
SECTION_RE = re.compile(r"^/tafseer/(\d+)/(\d+)$")


def get_surah_links(html):
    soup  = BeautifulSoup(html, "html.parser")
    links = []
    seen  = set()
    for card in soup.find_all("div", class_="card-personal"):
        a = card.find("a", href=SURAH_RE)
        if not a:
            continue
        href  = a["href"]
        title = a.get_text(strip=True)
        if href in seen or not title:
            continue
        seen.add(href)
        num = int(SURAH_RE.match(href).group(1))
        links.append({"url": BASE + href, "title": title, "num": num})
    links.sort(key=lambda x: x["num"])
    return links


def get_first_section_link(html, surah_num):
    soup       = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=SECTION_RE):
        m = SECTION_RE.match(a["href"])
        if m and int(m.group(1)) == surah_num:
            candidates.append((int(m.group(2)), BASE + a["href"]))
    if candidates:
        candidates.sort()
        return candidates[0][1]
    for a in soup.find_all("a", href=SECTION_RE):
        if "التالي" in a.get_text():
            return BASE + a["href"]
    return None


def get_next_link(html):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=SECTION_RE):
        if "التالي" in a.get_text():
            return BASE + a["href"]
    return None


def get_page_title(html):
    soup = BeautifulSoup(html, "html.parser")
    og   = soup.find("meta", property="og:title")
    if og and og.get("content"):
        parts = og["content"].split(" - ", 1)
        return parts[-1].strip()
    t = soup.find("title")
    if t:
        parts = t.get_text().split(" - ")
        return parts[-1].strip()
    return ""


def convert_inner_soup(soup_tag):
    for inner in soup_tag.find_all("span", class_="aaya"):
        inner.replace_with(f"﴿{inner.get_text(strip=True)}﴾")
    for inner in soup_tag.find_all("span", class_="hadith"):
        inner.replace_with(f"«{inner.get_text(strip=True)}»")
    for inner in soup_tag.find_all("span", class_="sora"):
        t = inner.get_text(strip=True)
        if t:
            inner.replace_with(f" {t} ")


def get_tip_text(tip):
    _marker = re.compile(r'\x01\d+\x01')
    for attr in ("data-original-title", "title", "data-content", "data-tippy-content"):
        val = tip.get(attr, "").strip()
        if val:
            inner_soup = BeautifulSoup(val, "html.parser")
            convert_inner_soup(inner_soup)
            result = re.sub(r'\s+', ' ', inner_soup.get_text()).strip()
            return _marker.sub('', result).strip()
    convert_inner_soup(tip)
    result = re.sub(r'\s+', ' ', tip.get_text(strip=True)).strip()
    return _marker.sub('', result).strip()


def extract_content(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()
    for pat in [
        re.compile(r"\bmodal\b"),
        re.compile(r"\breadMore\b"),
        re.compile(r"\balert-dorar\b"),
        re.compile(r"\btitle-manhag\b"),
        re.compile(r"\bdefault-gradient\b"),
        re.compile(r"\bfooter-copyright\b"),
        re.compile(r"\bcard-personal\b"),
    ]:
        for tag in soup.find_all(True, class_=pat):
            tag.decompose()

    block = None
    card  = soup.find("div", class_="card-body")
    if card:
        # ① الـ pane الـ active مع محتوى فعلي
        for pane in card.find_all("div", class_="tab-pane"):
            if "active" not in pane.get("class", []):
                continue
            if pane.find("article") or len(pane.get_text(strip=True)) > 200:
                block = pane
                break

        # ② fallback: أي pane يحتوي <article> بغض النظر عن active
        if not block:
            for pane in card.find_all("div", class_="tab-pane"):
                if pane.find("article"):
                    block = pane
                    break

        # ③ fallback أخير: أطول pane نصاً
        if not block:
            best, best_len = None, 0
            for pane in card.find_all("div", class_="tab-pane"):
                t = len(pane.get_text(strip=True))
                if t > best_len:
                    best_len, best = t, pane
            if best_len > 200:
                block = best

    if not block:
        block = soup.find("body") or soup

    # DEBUG — احذفه بعد التشخيص
    raw_preview = block.get_text(strip=True)[:300]
    print(f"  [DEBUG block] {raw_preview}")

    articles  = block.find_all("article") or [block]
    all_text  = []
    footnotes = []

    for art in articles:

        # ── 1. استخرج الحواشي أولاً
        tips_map    = {}
        tip_counter = [1]
        for tip in reversed(list(art.find_all("span", class_="tip"))):
            tip_text = get_tip_text(tip)
            if tip_text:
                tips_map[tip_counter[0]] = tip_text
                tip.replace_with(f"\x01{tip_counter[0]}\x01")
                tip_counter[0] += 1
            else:
                tip.decompose()

        # ── 2. بقية التحويلات
        for span in art.find_all("span", class_="aaya"):
            span.replace_with(f"﴿{span.get_text(strip=True)}﴾")
        for span in art.find_all("span", class_="sora"):
            span.replace_with(f" {span.get_text(strip=True)} ")
        for span in art.find_all("span", class_="hadith"):
            span.replace_with(f"«{span.get_text(strip=True)}»")
        for span in art.find_all("span", class_="title-2"):
            span.replace_with(f"\n#### {span.get_text(strip=True)}\n")
        for span in art.find_all("span", class_="title-1"):
            span.replace_with(f"\n##### {span.get_text(strip=True)}\n")

        for a in art.find_all("a"):
            if re.search(r"السابق|التالي|الصفحة|المراجع|اعتماد", a.get_text()):
                a.decompose()

        for i in range(1, 7):
            for h in art.find_all(f"h{i}"):
                h.replace_with(f"\n{'#' * (i + 2)} {h.get_text(strip=True)}\n")

        for br in art.find_all("br"):
            br.replace_with("\n")

        for p in art.find_all("p"):
            p.insert_before("\n\n")
            p.insert_after("\n\n")

        # ── 3. استخرج النص واستبدل العلامات بـ [^N]
        text     = art.get_text(separator="\n", strip=False)
        local_fn = [len(footnotes) + 1]

        def replace_marker(m, _tips=tips_map, _fns=footnotes, _ctr=local_fn):
            tid  = int(m.group(1))
            body = _tips.get(tid, '')
            _fns.append(f"[^{_ctr[0]}]: {body}")
            ref  = f" [^{_ctr[0]}]"
            _ctr[0] += 1
            return ref

        text = _TIP_RE.sub(replace_marker, text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'(?<!\n)\n(?![\n#>﴿«\d])', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        if text:
            all_text.append(text)

    clean = re.sub(r'\n{3,}', '\n\n', "\n\n".join(all_text)).strip()
    return {"text": clean, "footnotes": footnotes}


def fix_multiline_footnotes(text):
    lines  = text.splitlines()
    result = []
    fn_def = re.compile(r'^\[\^\d+\]:')
    i = 0
    while i < len(lines):
        line = lines[i]
        if fn_def.match(line):
            parts = [line.rstrip()]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt == '' or fn_def.match(nxt):
                    break
                parts.append(nxt.strip())
                i += 1
            result.append(' '.join(p for p in parts if p))
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)


def renum(text, fns, global_fn_ref):
    if not fns:
        return text, []

    local_map = {}
    for fn in fns:
        m = re.match(r'\[\^(\d+)\]:', fn)
        if m and m.group(1) not in local_map:
            local_map[m.group(1)] = global_fn_ref[0]
            global_fn_ref[0] += 1

    for loc in local_map:
        text = re.sub(
            rf'(?<!\d)\[\^{re.escape(loc)}\](?!\d)',
            f'\x02{loc}\x02',
            text
        )
    for loc, gbl in local_map.items():
        text = text.replace(f'\x02{loc}\x02', f'[^{gbl}]')

    new_fns = []
    for fn in fns:
        m = re.match(r'\[\^(\d+)\]:(.*)', fn, re.DOTALL)
        if m:
            loc = m.group(1)
            gbl = local_map.get(loc)
            if gbl is not None:
                new_fns.append(f"[^{gbl}]:{m.group(2)}")
    return text, new_fns


def save_markdown(surah_title, surah_num, intro, sections):
    safe     = re.sub(r'[^\w\u0600-\u06FF]', '_', surah_title)[:40]
    filename = f"{surah_num:03d}_{safe}.md"
    filepath = os.path.join(OUT_DIR, filename)

    lines = [
        f"# {surah_title}\n\n",
        f"> المصدر: {BASE}/tafseer/{surah_num}\n\n",
        "---\n\n",
    ]

    all_footnotes = []
    global_fn_ref = [1]

    if intro.get("text"):
        lines.append("## تعريف السورة\n\n")
        text, fns = renum(intro["text"], intro.get("footnotes", []), global_fn_ref)
        lines.append(f"{text}\n\n")
        all_footnotes.extend(fns)
        lines.append("---\n\n")

    for sec in sections:
        lines.append(f"## {sec['title']}\n\n")
        lines.append(f"> {sec['url']}\n\n")
        if sec.get("text"):
            text, fns = renum(sec["text"], sec.get("footnotes", []), global_fn_ref)
            lines.append(f"{text}\n\n")
            all_footnotes.extend(fns)
        lines.append("---\n\n")

    if all_footnotes:
        lines.append("\n")
        for fn in all_footnotes:
            lines.append(f"{fn}\n")

    content = fix_multiline_footnotes("".join(lines))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    total = len(intro.get("text", "")) + sum(len(s.get("text", "")) for s in sections)
    print(f"    ✔ {filepath}  |  {len(sections)} مقطع  |  ~{total//1024} KB  |  {len(all_footnotes)} حاشية")
    return filepath


if __name__ == "__main__":
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        session = make_session()

        print("① تهيئة الجلسة...")
        get_page(session, INDEX, referer=BASE)
        time.sleep(1.5)

        print("\n② جلب الصفحة الرئيسية...")
        html_main = get_page(session, INDEX, referer=BASE)
        time.sleep(2)
        if not html_main:
            raise SystemExit("فشل جلب الصفحة الرئيسية")

        surah_links = get_surah_links(html_main)
        print(f"\n③ {len(surah_links)} سورة\n")

        if TEST_SURAHS:
            surah_links = surah_links[:TEST_SURAHS]
            print(f"   وضع الاختبار: أول {TEST_SURAHS} سور فقط\n")

        for surah in surah_links:
            snum   = surah["num"]
            stitle = surah["title"]
            surl   = surah["url"]

            safe     = re.sub(r'[^\w\u0600-\u06FF]', '_', stitle)[:40]
            filepath = os.path.join(OUT_DIR, f"{snum:03d}_{safe}.md")
            if os.path.exists(filepath):
                print(f"  ← موجود، تخطي: {filepath}")
                continue

            print(f"\n{'='*50}")
            print(f"[{snum}] {stitle}")

            html_surah = get_page(session, surl, referer=INDEX)
            time.sleep(DELAY)
            if not html_surah:
                continue

            intro     = extract_content(html_surah)
            first_url = get_first_section_link(html_surah, snum)
            print(f"  تعريف: {len(intro['text'])} حرف")

            sections = []
            next_url = first_url
            visited  = set()
            sec_idx  = 1

            while next_url and next_url not in visited:
                visited.add(next_url)
                html_sec = get_page(session, next_url, referer=surl)
                time.sleep(DELAY)
                if not html_sec:
                    break
                title  = get_page_title(html_sec)
                parsed = extract_content(html_sec)
                print(f"    [{sec_idx}] {title[:50]}  →  {len(parsed['text'])} حرف")
                sections.append({"url": next_url, "title": title, **parsed})
                next_url = get_next_link(html_sec)
                sec_idx += 1

            print(f"  → {len(sections)} مقطع مكتمل")
            save_markdown(stitle, snum, intro, sections)

        print("\n✔ اكتمل.")

    except SystemExit as e:
        print(e)
    except Exception:
        traceback.print_exc()