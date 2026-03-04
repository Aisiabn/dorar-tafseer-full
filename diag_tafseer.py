"""
diag_tafseer.py
يجلب صفحة سورة واحدة ويطبع:
  ① ما الـ block المختار (tab-pane / body)
  ② عدد الـ articles وأحجامها
  ③ النص الموجود خارج الـ articles داخل الـ block
  ④ فحص داخل <section> خارج articles
"""

import requests
from bs4 import BeautifulSoup
import re, copy

BASE  = "https://dorar.net"
URL   = f"{BASE}/tafseer/2"
DELAY = 1.5

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 Chrome/109.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en-US;q=0.9",
        "Referer": BASE,
    })
    return s

def fetch(session, url):
    r = session.get(url, timeout=20)
    print(f"[{r.status_code}] {url}\n")
    return r.text if r.status_code == 200 else ""

def diag(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav","header","footer","script","style","form"]):
        tag.decompose()
    for pat in [
        re.compile(r"\bmodal\b"), re.compile(r"\breadMore\b"),
        re.compile(r"\bcard-personal\b"), re.compile(r"\bdefault-gradient\b"),
        re.compile(r"\bfooter-copyright\b"),
    ]:
        for t in soup.find_all(True, class_=pat):
            t.decompose()

    # ── اختيار block
    block = None
    card  = soup.find("div", class_="card-body")
    if card:
        for pane in card.find_all("div", class_="tab-pane"):
            cls = pane.get("class", [])
            if "active" in cls and (pane.find("article") or len(pane.get_text(strip=True)) > 200):
                block = pane
                break
        if not block:
            for pane in card.find_all("div", class_="tab-pane"):
                if pane.find("article"):
                    block = pane
                    break

    if not block:
        block = soup.find("body") or soup
        print("⚠ لم يُوجد tab-pane — استُخدم body كـ block\n")
    else:
        print(f"✔ block = {block.name}  classes={block.get('class')}\n")

    # ── عدد articles
    articles = block.find_all("article")
    print(f"── articles داخل block: {len(articles)}")
    for i, art in enumerate(articles, 1):
        txt = art.get_text(strip=True)
        print(f"   [{i}] {len(txt)} حرف  |  أول 80: {txt[:80]!r}")
    print()

    # ── النص خارج articles داخل block
    block_copy = copy.copy(block)
    for art in block_copy.find_all("article"):
        art.decompose()
    outside = block_copy.get_text(strip=True)
    print(f"── نص خارج articles (كامل block): {len(outside)} حرف")
    if outside:
        print(f"   أول 400: {outside[:400]!r}")
    print()

    # ── فحص داخل <section> خارج articles
    section = block.find("section")
    if section:
        sec_copy = copy.copy(section)
        for art in sec_copy.find_all("article"):
            art.decompose()
        outside_sec = sec_copy.get_text(strip=True)
        print(f"── نص داخل <section> خارج articles: {len(outside_sec)} حرف")
        if outside_sec:
            print(f"   أول 600:\n{outside_sec[:600]!r}")
    else:
        print("── لا يوجد <section> داخل block")

if __name__ == "__main__":
    s = make_session()
    html = fetch(s, URL)
    if html:
        diag(html)