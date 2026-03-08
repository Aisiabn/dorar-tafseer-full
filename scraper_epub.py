import requests
from bs4 import BeautifulSoup
import re, time, os, traceback
from ebooklib import epub

BASE      = "https://dorar.net"
INDEX     = "https://dorar.net/tafseer"
DELAY     = 1.0
OUT_DIR   = "dorar_tafseer_epub"
EPUB_FILE = os.path.join(OUT_DIR, "موسوعة_التفسير.epub")

TEST_SURAHS = None if os.environ.get("TEST_SURAHS") == "None" else (
    int(os.environ["TEST_SURAHS"]) if os.environ.get("TEST_SURAHS") else None
)

_TIP_RE     = re.compile(r'\x01(\d+)\x01')
_font_cache: dict[int, bytes] = {}


ARABIC_CSS = """
@charset "UTF-8";

body {
    direction: rtl;
    text-align: justify;
    font-family: "Amiri", "Scheherazade New", "Traditional Arabic", "Arabic Typesetting",
                 "Dubai", "Segoe UI", "Arial Unicode MS", serif;
    font-size: 1em;
    line-height: 2.0;
    margin: 1.2em 1.8em;
    color: #1a1a1a;
}

h1 { font-size: 1em; text-align: right; border-bottom: 2px solid #444; padding-bottom: 0.3em; margin-top: 1em; font-weight: bold; }
h2 { font-size: 1em; text-align: right; color: #2c2c2c; margin-top: 1.5em; font-weight: bold; }
h3 { font-size: 1em; text-align: right; color: #3a3a3a; margin-top: 1em; font-weight: bold; }
h4 { font-size: 1em; text-align: right; color: #555;    margin-top: 0.8em; font-weight: bold; }

p { margin: 0.6em 0; }

.source { color: #777; font-size: 0.85em; margin-bottom: 1em; text-align: right; }
.section-title { font-weight: bold; color: #333; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }

.quran {
    font-family: "Amiri Quran", "KFGQPC Uthmanic Script HAFS", "Scheherazade New",
                 "Traditional Arabic", serif;
    color: #1a4a1a;
}

.qpage-block {
    text-align: justify;
    direction: rtl;
    margin: 1em 0;
    padding: 0.5em;
    background: #f7f4ef;
    border-right: 3px solid #6a8a3a;
}

sup.fn-ref { font-size: 0.72em; line-height: 0; vertical-align: super; }
sup.fn-ref a { color: #0055aa; text-decoration: none; border-bottom: 1px dotted #0055aa; }

.footnotes {
    margin-top: 2.5em;
    border-top: 2px solid #bbb;
    padding-top: 1em;
    font-size: 0.83em;
    color: #444;
    text-align: right;
}
.footnotes h3 { font-size: 1em; color: #555; margin-bottom: 0.8em; }
.footnote-item { margin: 0.5em 0; padding-right: 0.3em; border-right: 2px solid #ddd; }
.footnote-back { color: #0055aa; text-decoration: none; font-size: 0.85em; margin-right: 0.4em; }
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
# خطوط QCF
# ══════════════════════════════════════════════

def fetch_qcf_font(session, page_num):
    if page_num in _font_cache:
        return _font_cache[page_num]
    url = f"{BASE}/fonts/QCF_P{page_num}.TTF"
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            _font_cache[page_num] = r.content
            print(f"  [FONT] خط الصفحة {page_num}")
            return r.content
    except Exception as e:
        print(f"  [FONT ERR] {url} — {e}")
    return None

def build_qcf_css(font_pages: set) -> str:
    lines = []
    for pnum in sorted(font_pages):
        lines.append(
            f'@font-face {{\n'
            f'  font-family: "QCF_P{pnum}";\n'
            f'  src: url("../fonts/QCF_P{pnum}.ttf") format("truetype");\n'
            f'}}\n'
            f'.qcf-pg{pnum} {{\n'
            f'  font-family: "QCF_P{pnum}", "Amiri Quran", serif;\n'
            f'  font-size: 1em;\n'
            f'  line-height: 2.2;\n'
            f'}}'
        )
    return "\n\n".join(lines)


# ══════════════════════════════════════════════
# استخراج المحتوى
# ══════════════════════════════════════════════

def convert_inner_soup(soup_tag):
    for inner in soup_tag.find_all("span", class_="aaya"):
        inner.replace_with(f"﴿{inner.get_text(strip=True)}﴾")
    for inner in soup_tag.find_all("span", class_="hadith"):
        inner.replace_with(inner.get_text(strip=True))
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

def extract_quran_block(html):
    soup  = BeautifulSoup(html, "html.parser")
    qpage = soup.find("div", id="qpage")
    if not qpage:
        return "", set()
    font_pages = set()
    for span in qpage.find_all("span"):
        sid = span.get("id", "")
        m   = re.match(r"pg(\d+)$", sid)
        if m:
            pnum = int(m.group(1))
            font_pages.add(pnum)
            span["class"] = f"qcf-pg{pnum}"
            del span["id"]
    qpage["class"] = "qpage-block"
    for attr in ("style", "id"):
        if attr in qpage.attrs:
            del qpage[attr]
    return str(qpage), font_pages

def extract_content(html):
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
    footnotes = []

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
            span.replace_with(span.get_text(strip=True))
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
            return (f'<sup class="fn-ref">'
                    f'<a id="fnref{gid}" href="#fn{gid}">[{gid}]</a>'
                    f'</sup>')

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
# بناء HTML صفحة واحدة
# ══════════════════════════════════════════════

def build_page_html(title, source_url, parsed):
    parts = [
        f'<h1>{title}</h1>',
        f'<p class="source">{source_url}</p>',
        '<hr/>',
    ]

    quran_block = parsed.get("quran_block", "")
    if quran_block:
        parts.append(quran_block)
        parts.append('<hr/>')

    text_html = parsed.get("text_html", "")
    footnotes = parsed.get("footnotes", [])

    if text_html:
        parts.append(text_html)

    if footnotes:
        parts.append('<div class="footnotes"><h3>الحواشي</h3>')
        for (fid, body) in footnotes:
            parts.append(
                f'<p class="footnote-item" id="fn{fid}">'
                f'<strong>[{fid}]</strong> {body}'
                f'<a class="footnote-back" href="#fnref{fid}" title="رجوع">↩</a>'
                f'</p>'
            )
        parts.append('</div>')

    return "\n".join(parts)

def wrap_xhtml(title, body_html, extra_css=""):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ar" dir="rtl">'
        '<head>'
        f'<title>{title}</title>'
        '<meta charset="utf-8"/>'
        '<link rel="stylesheet" href="../style/main.css" type="text/css"/>'
        + extra_css +
        '</head>'
        f'<body>{body_html}</body>'
        '</html>'
    ).encode("utf-8")


# ══════════════════════════════════════════════
# حفظ EPUB
# ══════════════════════════════════════════════

def save_epub(book_data, session):
    os.makedirs(OUT_DIR, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier("dorar-tafseer-001")
    book.set_title("موسوعة التفسير")
    book.set_language("ar")
    book.add_author("موسوعة الدرر السنية")
    book.set_direction("rtl")

    css = epub.EpubItem(
        uid="style", file_name="style/main.css",
        media_type="text/css", content=ARABIC_CSS.encode("utf-8"),
    )
    book.add_item(css)

    # ── خطوط QCF
    all_font_pages: set = set()
    for entry in book_data:
        all_font_pages |= entry.get("font_pages", set())

    for pnum in sorted(all_font_pages):
        font_bytes = fetch_qcf_font(session, pnum)
        if font_bytes:
            book.add_item(epub.EpubItem(
                uid        = f"font_qcf_{pnum}",
                file_name  = f"fonts/QCF_P{pnum}.ttf",
                media_type = "font/truetype",
                content    = font_bytes,
            ))

    qcf_css = None
    if all_font_pages:
        qcf_css = epub.EpubItem(
            uid="style_qcf", file_name="style/qcf.css",
            media_type="text/css",
            content=build_qcf_css(all_font_pages).encode("utf-8"),
        )
        book.add_item(qcf_css)

    extra_css_link = '<link rel="stylesheet" href="../style/qcf.css" type="text/css"/>' if qcf_css else ""

    spine = ["nav"]
    toc   = []

    for entry in book_data:
        snum     = entry["surah_num"]
        stitle   = entry["surah_title"]
        surl     = entry["surah_url"]
        intro    = entry["intro"]
        sections = entry["sections"]

        surah_items = []

        # صفحة التعريف
        intro_html = build_page_html(f"{stitle} — تعريف السورة", surl, intro)
        intro_item = epub.EpubHtml(
            title=f"{stitle} — تعريف",
            file_name=f"s{snum:03d}_intro.xhtml",
            lang="ar", direction="rtl",
        )
        intro_item.content = wrap_xhtml(f"{stitle} — تعريف", intro_html, extra_css_link)
        intro_item.add_item(css)
        if qcf_css:
            intro_item.add_item(qcf_css)
        book.add_item(intro_item)
        spine.append(intro_item)
        surah_items.append(intro_item)

        # صفحة لكل مقطع
        for i, sec in enumerate(sections, 1):
            sec_html = build_page_html(sec["title"], sec["url"], sec)
            item     = epub.EpubHtml(
                title=sec["title"],
                file_name=f"s{snum:03d}_sec{i:03d}.xhtml",
                lang="ar", direction="rtl",
            )
            item.content = wrap_xhtml(sec["title"], sec_html, extra_css_link)
            item.add_item(css)
            if qcf_css:
                item.add_item(qcf_css)
            book.add_item(item)
            spine.append(item)
            surah_items.append(item)

        sub_links = [epub.Link(p.file_name, p.title, p.file_name) for p in surah_items]
        toc.append((epub.Section(stitle, href=f"s{snum:03d}_intro.xhtml"), sub_links))

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

            intro                = extract_content(html_surah)
            intro["quran_block"] = ""
            first_url            = get_first_section_link(html_surah, snum)
            print(f"  تعريف: {len(intro['text_html'])} حرف")

            sections        = []
            all_font_pages  = set()
            next_url        = first_url
            visited         = set()
            sec_idx         = 1

            while next_url and next_url not in visited:
                visited.add(next_url)
                html_sec = get_page(session, next_url, referer=surl)
                time.sleep(DELAY)
                if not html_sec:
                    break
                title           = get_page_title(html_sec)
                parsed          = extract_content(html_sec)
                qblock, fpages  = extract_quran_block(html_sec)
                parsed["quran_block"] = qblock
                all_font_pages |= fpages
                print(f"    [{sec_idx}] {title[:50]}  →  {len(parsed['text_html'])} حرف"
                      + (f"  [{len(fpages)} خط]" if fpages else ""))
                sections.append({"url": next_url, "title": title, **parsed})
                next_url = get_next_link(html_sec)
                sec_idx += 1

            print(f"  → {len(sections)} مقطع  |  {len(all_font_pages)} خط QCF")

            book_data.append({
                "surah_num"  : snum,
                "surah_title": stitle,
                "surah_url"  : surl,
                "intro"      : intro,
                "sections"   : sections,
                "font_pages" : all_font_pages,
            })

        print("\n④ بناء EPUB...")
        save_epub(book_data, session)
        print("\n✔ اكتمل.")

    except SystemExit as e:
        print(e)
    except Exception:
        traceback.print_exc()