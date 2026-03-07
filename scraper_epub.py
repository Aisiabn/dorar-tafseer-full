import requests
from bs4 import BeautifulSoup
import re, time, os, traceback
from ebooklib import epub

BASE    = "https://dorar.net"
INDEX   = "https://dorar.net/tafseer"
DELAY   = 1.0
OUT_DIR = "dorar_tafseer_epub"
EPUB_FILE = os.path.join(OUT_DIR, "موسوعة_التفسير.epub")

TEST_SURAHS = None if os.environ.get("TEST_SURAHS") == "None" else (
    int(os.environ["TEST_SURAHS"]) if os.environ.get("TEST_SURAHS") else None
)

_TIP_RE = re.compile(r'\x01(\d+)\x01')

ARABIC_CSS = """
@charset "UTF-8";

body {
    direction: rtl;
    text-align: right;
    font-family: "Amiri", "Traditional Arabic", "Arial", serif;
    font-size: 1em;
    line-height: 1.8;
    margin: 1em 1.5em;
    color: #1a1a1a;
}

h1 { font-size: 1.6em; border-bottom: 2px solid #444; padding-bottom: 0.3em; margin-top: 1em; }
h2 { font-size: 1.3em; color: #2c2c2c; margin-top: 1.5em; }
h3 { font-size: 1.1em; color: #3a3a3a; margin-top: 1em; }
h4 { font-size: 1em; color: #555; margin-top: 0.8em; }

.source { color: #777; font-size: 0.85em; margin-bottom: 1em; }
.intro-section { background: #f9f7f2; padding: 0.5em 1em; border-right: 3px solid #999; margin: 1em 0; }
.section-title { font-weight: bold; color: #333; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }

/* آيات قرآنية */
.quran { font-family: "Amiri Quran", "Traditional Arabic", serif; color: #1a4a1a; }

/* حواشي */
.footnote-ref { font-size: 0.75em; vertical-align: super; color: #0055aa; text-decoration: none; }
.footnotes { margin-top: 2em; border-top: 1px solid #ccc; padding-top: 1em; font-size: 0.85em; color: #444; }
.footnote { margin: 0.4em 0; }
.footnote-back { color: #0055aa; text-decoration: none; font-size: 0.8em; }
"""


# ══════════════════════════════════════════════
# Session
# ══════════════════════════════════════════════

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent"               : "Mozilla/5.0 (Windows NT 6.1; WOW64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/109.0.0.0 Safari/537.36",
        "Accept"                   : "text/html,application/xhtml+xml,*/*;q=0.8",
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


# ══════════════════════════════════════════════
# روابط وتنقل
# ══════════════════════════════════════════════

SURAH_RE   = re.compile(r"^/tafseer/(\d+)$")
SECTION_RE = re.compile(r"^/tafseer/(\d+)/(\d+)$")

def get_surah_links(html):
    soup  = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
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
    soup  = BeautifulSoup(html, "html.parser")
    cands = []
    for a in soup.find_all("a", href=SECTION_RE):
        m = SECTION_RE.match(a["href"])
        if m and int(m.group(1)) == surah_num:
            cands.append((int(m.group(2)), BASE + a["href"]))
    if cands:
        cands.sort()
        return cands[0][1]
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
        return og["content"].split(" - ", 1)[-1].strip()
    t = soup.find("title")
    if t:
        return t.get_text().split(" - ")[-1].strip()
    return ""


# ══════════════════════════════════════════════
# استخراج المحتوى
# ══════════════════════════════════════════════

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
    """يُعيد {"text_html": str, "footnotes": [(id, text)]}"""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()
    for pat in [
        re.compile(r"\bmodal\b"), re.compile(r"\balert-dorar\b"),
        re.compile(r"\btitle-manhag\b"), re.compile(r"\bdefault-gradient\b"),
        re.compile(r"\bfooter-copyright\b"), re.compile(r"\bcard-personal\b"),
    ]:
        for tag in soup.find_all(True, class_=pat):
            tag.decompose()

    block = None
    card  = soup.find("div", class_="card-body")
    if card:
        for pane in card.find_all("div", class_="tab-pane"):
            if "active" not in pane.get("class", []):
                continue
            if pane.find("article") or len(pane.get_text(strip=True)) > 200:
                block = pane
                break
        if not block:
            for pane in card.find_all("div", class_="tab-pane"):
                if pane.find("article"):
                    block = pane
                    break

    if not block:
        block = soup.find("body") or soup

    articles = block.find_all("article")
    if not articles:
        articles = soup.find_all("article") or [block]

    all_html  = []
    footnotes = []   # [(global_id, text), ...]

    for art in articles:
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

        for span in art.find_all("span", class_="aaya"):
            span.replace_with(f'<span class="quran">﴿{span.get_text(strip=True)}﴾</span>')
        for span in art.find_all("span", class_="sora"):
            span.replace_with(f" {span.get_text(strip=True)} ")
        for span in art.find_all("span", class_="hadith"):
            span.replace_with(f"«{span.get_text(strip=True)}»")
        for span in art.find_all("span", class_="title-2"):
            span.replace_with(f'<h4>{span.get_text(strip=True)}</h4>')
        for span in art.find_all("span", class_="title-1"):
            span.replace_with(f'<h4 class="section-title">{span.get_text(strip=True)}</h4>')
        for a in art.find_all("a"):
            if re.search(r"السابق|التالي|الصفحة|المراجع|اعتماد", a.get_text()):
                a.decompose()
        for i in range(1, 7):
            for h in art.find_all(f"h{i}"):
                h.replace_with(f'<h{min(i+2,6)}>{h.get_text(strip=True)}</h{min(i+2,6)}>')

        for p in art.find_all("p"):
            p.insert_before("\n\n")
            p.insert_after("\n\n")

        text = art.get_text(separator="\n", strip=False)

        def replace_marker(m, _tips=tips_map, _fns=footnotes):
            tid  = int(m.group(1))
            body = _tips.get(tid, '')
            gid  = len(_fns) + 1
            _fns.append((gid, body))
            return (f'<a class="footnote-ref" id="fnref{gid}" '
                    f'href="#fn{gid}">[{gid}]</a>')

        text = _TIP_RE.sub(replace_marker, text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'(?<!\n)\n(?![\n])', ' ', text)
        text = re.sub(r'\n{2,}', '</p>\n<p>', text).strip()
        text = f"<p>{text}</p>" if text else ""

        if text:
            all_html.append(text)

    return {
        "text_html": "\n".join(all_html),
        "footnotes": footnotes,
    }


# ══════════════════════════════════════════════
# بناء HTML فصل السورة
# ══════════════════════════════════════════════

def build_chapter_html(surah_title, surah_num, intro, sections):
    """يبني HTML كاملاً لفصل السورة."""
    parts = []
    all_footnotes = []  # (gid, text) مُعاد ترقيمه

    fn_offset = [0]

    def shift_fns(text_html, footnotes):
        """يُعيد ترقيم الحواشي ضمن block واحد."""
        shifted = []
        mapping = {}
        for (gid, body) in footnotes:
            new_id = fn_offset[0] + 1
            fn_offset[0] += 1
            mapping[gid] = new_id
            shifted.append((new_id, body))
            all_footnotes.append((new_id, body))

        def fix_ref(m):
            old = int(re.search(r'id="fnref(\d+)"', m.group(0)).group(1))
            new = mapping.get(old, old)
            return (f'<a class="footnote-ref" id="fnref{new}" '
                    f'href="#fn{new}">[{new}]</a>')

        text_html = re.sub(
            r'<a class="footnote-ref"[^>]+>\[\d+\]</a>',
            fix_ref, text_html
        )
        return text_html, shifted

    # ── رأس الصفحة
    parts.append(f'<h1>{surah_title}</h1>')
    parts.append(f'<p class="source">المصدر: {BASE}/tafseer/{surah_num}</p>')
    parts.append('<hr/>')

    # ── تعريف السورة
    if intro.get("text_html"):
        parts.append('<div class="intro-section">')
        parts.append('<h2>تعريف السورة</h2>')
        html, _ = shift_fns(intro["text_html"], intro.get("footnotes", []))
        parts.append(html)
        parts.append('</div>')
        parts.append('<hr/>')

    # ── مقاطع التفسير
    for sec in sections:
        parts.append(f'<h2>{sec["title"]}</h2>')
        parts.append(f'<p class="source">{sec["url"]}</p>')
        if sec.get("text_html"):
            html, _ = shift_fns(sec["text_html"], sec.get("footnotes", []))
            parts.append(html)
        parts.append('<hr/>')

    # ── الحواشي
    if all_footnotes:
        parts.append('<div class="footnotes">')
        parts.append('<h3>الحواشي</h3>')
        for (fid, body) in all_footnotes:
            parts.append(
                f'<p class="footnote" id="fn{fid}">'
                f'[{fid}] {body} '
                f'<a class="footnote-back" href="#fnref{fid}">↩</a>'
                f'</p>'
            )
        parts.append('</div>')

    return "\n".join(parts)


# ══════════════════════════════════════════════
# حفظ EPUB
# ══════════════════════════════════════════════

def save_epub(book_data):
    """
    book_data: [{"surah_title", "surah_num", "chapter_html", "sections_titles": [...]}]
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier("dorar-tafseer-001")
    book.set_title("موسوعة التفسير")
    book.set_language("ar")
    book.add_author("موسوعة الدرر السنية")
    book.set_direction("rtl")

    # CSS
    css = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=ARABIC_CSS.encode("utf-8"),
    )
    book.add_item(css)

    spine   = ["nav"]
    toc     = []

    for entry in book_data:
        snum   = entry["surah_num"]
        stitle = entry["surah_title"]
        chtml  = entry["chapter_html"]
        secs   = entry["sections_titles"]

        fname = f"surah_{snum:03d}.xhtml"
        chap  = epub.EpubHtml(
            title    = stitle,
            file_name= fname,
            lang     = "ar",
            direction= "rtl",
        )
        chap.content = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<!DOCTYPE html>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ar" dir="rtl">'
            '<head>'
            f'<title>{stitle}</title>'
            '<meta charset="utf-8"/>'
            '<link rel="stylesheet" href="../style/main.css" type="text/css"/>'
            '</head>'
            f'<body>{chtml}</body>'
            '</html>'
        ).encode("utf-8")
        chap.add_item(css)
        book.add_item(chap)
        spine.append(chap)

        # TOC: السورة كعنوان رئيسي، مقاطعها كعناوين فرعية
        sub_links = [
            epub.Link(f"{fname}#sec_{i}", t, f"surah{snum}_sec{i}")
            for i, t in enumerate(secs)
        ]
        if sub_links:
            toc.append((epub.Section(stitle, href=fname), sub_links))
        else:
            toc.append(epub.Link(fname, stitle, f"surah{snum}"))

    book.toc   = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(EPUB_FILE, book)
    print(f"\n✔ EPUB محفوظ: {EPUB_FILE}")


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

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

        book_data = []

        for surah in surah_links:
            snum   = surah["num"]
            stitle = surah["title"]
            surl   = surah["url"]

            print(f"\n{'='*50}")
            print(f"[{snum}] {stitle}")

            html_surah = get_page(session, surl, referer=INDEX)
            time.sleep(DELAY)
            if not html_surah:
                continue

            intro     = extract_content(html_surah)
            first_url = get_first_section_link(html_surah, snum)
            print(f"  تعريف: {len(intro['text_html'])} حرف")

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
                print(f"    [{sec_idx}] {title[:50]}  →  {len(parsed['text_html'])} حرف")
                sections.append({"url": next_url, "title": title, **parsed})
                next_url = get_next_link(html_sec)
                sec_idx += 1

            print(f"  → {len(sections)} مقطع")

            chapter_html = build_chapter_html(stitle, snum, intro, sections)
            book_data.append({
                "surah_num"      : snum,
                "surah_title"    : stitle,
                "chapter_html"   : chapter_html,
                "sections_titles": [s["title"] for s in sections],
            })

        print("\n④ بناء EPUB...")
        save_epub(book_data)
        print("\n✔ اكتمل.")

    except SystemExit as e:
        print(e)
    except Exception:
        traceback.print_exc()