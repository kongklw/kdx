#!/usr/bin/env python3
"""
婴儿喂养看护知识爬虫
爬取官方网站的婴儿喂养看护相关数据，整理成RAG知识库文档
"""

import os
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Selenium not installed, skipping Selenium-based crawlers")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'rag', 'baby_feeding')
os.makedirs(OUTPUT_DIR, exist_ok=True)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

INFANT_TOPICS = {
    '喂养营养': {
        'keywords': ['喂养', '辅食', '营养', '母乳', '配方奶', '膳食', '饮食', '断奶'],
        'age_range': ['0-6个月', '6-12个月', '1-3岁'],
    },
    '生长发育': {
        'keywords': ['发育', '里程碑', '身高', '体重', '头围', '运动', '语言', '认知'],
        'age_range': ['0-1岁', '1-3岁', '3-6岁'],
    },
    '疫苗接种': {
        'keywords': ['疫苗', '接种', '免疫', '预防', '乙肝', '卡介苗', '脊灰', '百白破'],
        'age_range': ['0-6个月', '6-12个月', '1-3岁'],
    },
    '睡眠作息': {
        'keywords': ['睡眠', '作息', '入睡', '夜醒', '午睡', '生物钟', '睡眠训练'],
        'age_range': ['0-6个月', '6-12个月', '1-3岁'],
    },
    '口腔护理': {
        'keywords': ['口腔', '牙齿', '刷牙', '龋齿', '长牙', '口腔卫生'],
        'age_range': ['0-6个月', '6-12个月', '1-3岁'],
    },
    '皮肤护理': {
        'keywords': ['皮肤', '湿疹', '尿布疹', '痱子', '护肤', '保湿', '过敏'],
        'age_range': ['0-6个月', '6-12个月', '1-3岁'],
    },
    '急救安全': {
        'keywords': ['急救', '安全', '窒息', '烫伤', '溺水', '外伤', '防护'],
        'age_range': ['0-3岁'],
    },
    '常见疾病': {
        'keywords': ['疾病', '感冒', '发烧', '腹泻', '便秘', '肺炎', '哮喘'],
        'age_range': ['0-3岁'],
    },
    '心理健康': {
        'keywords': ['心理', '情绪', '焦虑', '社交', '性格', '行为', '心理发展'],
        'age_range': ['0-3岁'],
    },
    '早期教育': {
        'keywords': ['早教', '教育', '学习', '游戏', '认知', '阅读', '玩具'],
        'age_range': ['0-1岁', '1-3岁'],
    },
    '视力听力': {
        'keywords': ['视力', '听力', '眼睛', '耳朵', '弱视', '近视', '听力筛查'],
        'age_range': ['0-3岁'],
    },
    '如厕训练': {
        'keywords': ['如厕', '大小便', '训练', '尿布', '马桶'],
        'age_range': ['1-3岁'],
    },
}

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Linux"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    })
    return session

def get_selenium_driver():
    if not SELENIUM_AVAILABLE:
        return None
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument(f'user-agent={random.choice(USER_AGENTS)}')
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        return driver
    except Exception as e:
        print(f"Selenium driver init failed: {e}")
        return None

def save_markdown(title, content, source_url, category):
    if not content or len(content.strip()) < 100:
        print(f"内容太短，跳过: {title}")
        return None
    
    category_dir = os.path.join(OUTPUT_DIR, category)
    os.makedirs(category_dir, exist_ok=True)
    
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
    safe_title = re.sub(r'\s+', '_', safe_title)[:100]
    filename = f"{safe_title}.md"
    filepath = os.path.join(category_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\n")
        f.write(f"**来源**: [{source_url}]({source_url})\n\n")
        f.write("---\n\n")
        f.write(content)
    
    print(f"已保存: {filepath}")
    return filepath

def extract_content(soup):
    selectors = [
        'div.article',
        'div.TRS_Editor',
        'div.detail-content',
        'div.content',
        'div#zoom',
        'div.main-content',
        'div.page-content',
        'div.sf-detail-body',
        'div.article-content',
        'div.news-detail',
        'div.text-content',
        'div.body-content',
        'div.content-body',
        'div.container',
        'article',
        'main',
        'div[class*="content"]',
        'div[class*="article"]',
        'div.erjiRight',
        'div.contentArea',
        'div.post-content',
        'div.entry-content',
        'div.body',
        'div.main',
        'div.inner',
        'div.wrapper',
        'div.content_wrapper',
        'div.content-main',
        'div.maincontent',
        'div.page-body',
        'div.content-body',
        'div.article-body',
        'div.story-content',
        'div.news-content',
        'div.text',
    ]
    
    for selector in selectors:
        content_div = soup.select_one(selector)
        if content_div:
            content = content_div.get_text('\n', strip=True)
            if len(content.strip()) > 100:
                return content
    
    body = soup.find('body')
    if body:
        content = body.get_text('\n', strip=True)
        if len(content.strip()) > 100:
            return content
    
    return None

def extract_title(soup, url):
    selectors = [
        'h1',
        'title',
        'div.title',
        'span.title',
        'h2',
        'h1.entry-title',
        'h1.post-title',
        'div.article-title',
        'span.article-title',
        'div.news-title',
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            title = element.get_text(strip=True)
            if title and len(title) > 5:
                return title
    
    parsed = urlparse(url)
    return parsed.path.split('/')[-1].replace('.html', '').replace('.shtml', '')

def crawl_nhc_articles(session):
    urls = [
        'https://www.nhc.gov.cn/fys/c100078/202502/19903ff647694f3a85ed6fe332380b34.shtml',
        'https://www.nhc.gov.cn/rkjcyjtfzs/c100147/202201/a7d3fc17153f410ea97270814a3e662f.shtml',
        'https://www.gov.cn/zhengce/zhengceku/2020-08/01/content_5531915.htm',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = extract_title(soup, url)
            content = extract_content(soup)
            
            if content:
                content = re.sub(r'\n{3,}', '\n\n', content)
                save_markdown(title, content, url, '国家卫生健康委')
            else:
                print(f"无法提取内容: {url}")
            
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            print(f"爬取失败 {url}: {e}")

def crawl_unicef_china(session):
    urls = [
        'https://www.unicef.cn/zh-hans/what-we-do/child-health/nutrition',
        'https://www.unicef.cn/zh-hans/what-we-do/early-childhood-development',
        'https://www.unicef.cn/zh-hans/what-we-do/child-health',
        'https://www.unicef.cn/zh-hans/what-we-do/water-sanitation-hygiene',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = extract_title(soup, url)
            content = extract_content(soup)
            
            if content:
                content = re.sub(r'\n{3,}', '\n\n', content)
                save_markdown(title, content, url, 'UNICEF中国')
            else:
                print(f"无法提取内容: {url}")
            
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            print(f"爬取失败 {url}: {e}")

def crawl_who(session):
    urls = [
        'https://www.who.int/news-room/fact-sheets/detail/infant-and-young-child-feeding',
        'https://www.who.int/health-topics/breastfeeding',
        'https://www.who.int/news-room/fact-sheets/detail/child-development',
        'https://www.who.int/health-topics/vaccination',
        'https://www.who.int/news-room/fact-sheets/detail/child-mental-health',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = extract_title(soup, url)
            content = extract_content(soup)
            
            if content:
                content = re.sub(r'\n{3,}', '\n\n', content)
                save_markdown(title, content, url, 'WHO')
            else:
                print(f"无法提取内容: {url}")
            
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            print(f"爬取失败 {url}: {e}")

def crawl_cdc(session):
    base_url = 'https://www.chinacdc.cn'
    crawl_paths = [
        './tzgg/',
        './gzdt/zxzb/',
        './gzdt/zsdw/',
        './jkts/',
        './kxyj/kjjz/',
    ]
    
    for path in crawl_paths:
        full_url = urljoin(base_url, path)
        try:
            response = session.get(full_url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text().strip()
                keywords = ['疫苗', '免疫', '儿童', '接种', '婴幼儿', '喂养', '营养', '健康']
                if any(kw in text for kw in keywords) and href.endswith('.html'):
                    if href.startswith('http'):
                        article_url = href
                    else:
                        article_url = urljoin(base_url, href)
                    try:
                        article_response = session.get(article_url, timeout=30)
                        article_response.encoding = 'utf-8'
                        article_soup = BeautifulSoup(article_response.text, 'html.parser')
                        
                        title = extract_title(article_soup, article_url)
                        content = extract_content(article_soup)
                        
                        if content:
                            content = re.sub(r'\n{3,}', '\n\n', content)
                            save_markdown(title, content, article_url, '中国疾控中心')
                        
                        time.sleep(random.uniform(1, 3))
                    except Exception as e:
                        print(f"爬取文章失败 {article_url}: {e}")
            
        except Exception as e:
            print(f"爬取页面失败 {full_url}: {e}")
    
    crawl_cdc_vaccine(session)

def crawl_cdc_vaccine(session):
    vaccine_urls = [
        'https://www.chinacdc.cn/jkyj/mygh02/ymkyfjb/',
        'https://www.chinacdc.cn/jkyj/mygh02/',
    ]
    
    for url in vaccine_urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            erji_right = soup.find('div', class_='erjiRight')
            if erji_right:
                links = erji_right.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    text = link.get_text().strip()
                    if text and len(text) > 1:
                        article_url = urljoin(url, href)
                        if not article_url.endswith('/'):
                            article_url += '/'
                        try:
                            article_response = session.get(article_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            content_div = article_soup.find('div', class_='erjiRight')
                            if content_div:
                                content = content_div.get_text('\n', strip=True)
                                title = text
                                if content and len(content) > 100:
                                    content = re.sub(r'\n{3,}', '\n\n', content)
                                    save_markdown(title, content, article_url, '中国疾控中心')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取疫苗文章失败 {article_url}: {e}")
            
        except Exception as e:
            print(f"爬取疫苗页面失败 {url}: {e}")

def crawl_mohfw(session):
    urls = [
        'https://www.nhc.gov.cn/fys/c100078/list.shtml',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['婴幼儿', '喂养', '辅食', '营养', '发育', '疫苗']
                if any(kw in text for kw in keywords):
                    full_url = urljoin(url, href)
                    try:
                        article_response = session.get(full_url, timeout=30)
                        article_response.encoding = 'utf-8'
                        article_soup = BeautifulSoup(article_response.text, 'html.parser')
                        
                        title = extract_title(article_soup, full_url)
                        content = extract_content(article_soup)
                        
                        if content:
                            content = re.sub(r'\n{3,}', '\n\n', content)
                            save_markdown(title, content, full_url, '妇幼健康')
                        
                        time.sleep(random.uniform(1, 3))
                    except Exception as e:
                        print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_cmha(session):
    base_url = 'http://www.cmha.org.cn'
    search_keywords = ['辅食', '喂养', '育儿', '疫苗', '护理', '营养', '睡眠', '发育']
    
    for keyword in search_keywords:
        try:
            search_url = f'{base_url}/search.html'
            response = session.post(search_url, data={'keyword': keyword}, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text().strip()
                if text and len(text) > 5 and href.endswith('.html'):
                    full_url = urljoin(base_url, href)
                    if 'cmha.org.cn' in full_url:
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '中国妇幼保健协会')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"搜索失败 {keyword}: {e}")

def crawl_cns(session):
    urls = [
        'https://www.cnsoc.org/',
        'https://www.cnsoc.org/news/',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['婴幼儿', '儿童', '营养', '喂养', '膳食', '辅食']
                if any(kw in text for kw in keywords) and ('http' in href or href.startswith('/')):
                    full_url = urljoin(url, href)
                    if 'cnsoc.org' in full_url:
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '中国营养学会')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_nhc_more(session):
    urls = [
        'https://www.nhc.gov.cn/fys/index.shtml',
        'https://www.nhc.gov.cn/wjw/index.shtml',
        'https://www.nhc.gov.cn/kpzx/index.shtml',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['婴幼儿', '儿童', '育儿', '喂养', '保健', '疫苗', '发育', '睡眠', '护理']
                if any(kw in text for kw in keywords):
                    full_url = urljoin(url, href)
                    if full_url.endswith('.shtml') or full_url.endswith('.html'):
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '国家卫生健康委')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_health_cn(session):
    urls = [
        'https://www.health-china.com/',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['育儿', '儿童', '营养', '保健', '疫苗', '睡眠', '发育']
                if any(kw in text for kw in keywords) and ('http' in href or href.startswith('/')):
                    full_url = urljoin(url, href)
                    if full_url.endswith('.html') or full_url.endswith('.shtml'):
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '健康中国')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_aap(session):
    urls = [
        'https://www.healthychildren.org/English/ages-stages/Pages/default.aspx',
        'https://www.healthychildren.org/English/feeding-nutrition/Pages/default.aspx',
        'https://www.healthychildren.org/English/safety-prevention/Pages/default.aspx',
        'https://www.healthychildren.org/English/development/Pages/default.aspx',
        'https://www.healthychildren.org/English/health-issues/conditions/Pages/default.aspx',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                if href.startswith('/') and 'healthychildren.org' not in href:
                    full_url = urljoin(url, href)
                    if full_url.endswith('.aspx') and 'healthychildren.org' in full_url:
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '美国儿科学会')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_cdc_gov(session):
    urls = [
        'https://www.cdc.gov/children/',
        'https://www.cdc.gov/vaccines/parents/index.html',
        'https://www.cdc.gov/nutrition/index.html',
        'https://www.cdc.gov/childdevelopment/',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['baby', 'child', 'infant', 'toddler', 'vaccine', 'nutrition', 'development']
                if any(kw.lower() in text.lower() for kw in keywords):
                    if href.startswith('/'):
                        full_url = 'https://www.cdc.gov' + href
                    elif 'cdc.gov' in href:
                        full_url = href
                    else:
                        continue
                    if not full_url.endswith(('.pdf', '.doc', '.xls')):
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '美国CDC')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_nhs_uk(session):
    urls = [
        'https://www.nhs.uk/conditions/baby/',
        'https://www.nhs.uk/conditions/vaccinations/',
        'https://www.nhs.uk/conditions/child-health/',
        'https://www.nhs.uk/start-for-life/baby/',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['baby', 'child', 'infant', 'vaccine', 'feeding', 'development', 'sleep']
                if any(kw.lower() in text.lower() for kw in keywords):
                    if href.startswith('/'):
                        full_url = 'https://www.nhs.uk' + href
                    elif 'nhs.uk' in href:
                        full_url = href
                    else:
                        continue
                    if not full_url.endswith(('.pdf', '.doc', '.xls')):
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, '英国NHS')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_mayo_clinic(session):
    urls = [
        'https://www.mayoclinic.org/healthy-lifestyle/infant-and-toddler-health',
        'https://www.mayoclinic.org/healthy-lifestyle/childrens-health',
        'https://www.mayoclinic.org/diseases-conditions/childhood-diseases',
    ]
    
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text()
                keywords = ['baby', 'child', 'infant', 'toddler', 'vaccine', 'nutrition', 'development']
                if any(kw.lower() in text.lower() for kw in keywords):
                    if href.startswith('/'):
                        full_url = 'https://www.mayoclinic.org' + href
                    elif 'mayoclinic.org' in href:
                        full_url = href
                    else:
                        continue
                    if not full_url.endswith(('.pdf', '.doc', '.xls')):
                        try:
                            article_response = session.get(full_url, timeout=30)
                            article_response.encoding = 'utf-8'
                            article_soup = BeautifulSoup(article_response.text, 'html.parser')
                            
                            title = extract_title(article_soup, full_url)
                            content = extract_content(article_soup)
                            
                            if content:
                                content = re.sub(r'\n{3,}', '\n\n', content)
                                save_markdown(title, content, full_url, 'Mayo Clinic')
                            
                            time.sleep(random.uniform(1, 3))
                        except Exception as e:
                            print(f"爬取文章失败 {full_url}: {e}")
            
        except Exception as e:
            print(f"爬取列表失败 {url}: {e}")

def crawl_selenium_search(driver, keywords, max_pages=3):
    if not driver:
        return
    
    search_url = 'https://www.bing.com/search'
    
    for keyword in keywords:
        try:
            current_url = f'{search_url}?q={keyword}&first=1'
            driver.get(current_url)
            time.sleep(3)
            
            for page in range(max_pages):
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                results = soup.find_all('li', class_='b_algo')
                
                for result in results:
                    link = result.find('a', href=True)
                    if link:
                        url = link['href']
                        title = link.get_text()
                        if url and 'http' in url and not url.endswith(('.pdf', '.doc', '.xls')):
                            try:
                                session = get_session()
                                response = session.get(url, timeout=30)
                                response.encoding = 'utf-8'
                                article_soup = BeautifulSoup(response.text, 'html.parser')
                                
                                article_title = extract_title(article_soup, url)
                                content = extract_content(article_soup)
                                
                                if content:
                                    content = re.sub(r'\n{3,}', '\n\n', content)
                                    save_markdown(article_title, content, url, '搜索结果')
                                
                                time.sleep(random.uniform(1, 2))
                            except Exception as e:
                                print(f"爬取搜索结果失败 {url}: {e}")
                
                next_page = soup.find('a', class_='sb_pagN')
                if next_page and page < max_pages - 1:
                    next_url = next_page['href']
                    driver.get(f'https://www.bing.com{next_url}')
                    time.sleep(3)
                else:
                    break
            
        except Exception as e:
            print(f"Selenium搜索失败 {keyword}: {e}")

def crawl_selenium_cmha(driver):
    if not driver:
        return
    
    try:
        base_url = 'http://www.cmha.org.cn/search.html'
        driver.get(base_url)
        time.sleep(3)
        
        search_keywords = ['辅食', '喂养', '育儿', '疫苗', '护理', '营养', '睡眠', '发育']
        
        for keyword in search_keywords:
            try:
                search_input = driver.find_element(By.NAME, 'keyword')
                search_input.clear()
                search_input.send_keys(keyword)
                
                search_button = driver.find_element(By.XPATH, '//input[@type="submit"]')
                search_button.click()
                time.sleep(3)
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                links = soup.find_all('a', href=True)
                
                for link in links:
                    href = link['href']
                    text = link.get_text().strip()
                    if text and len(text) > 5 and href.endswith('.html'):
                        full_url = urljoin(base_url, href)
                        if 'cmha.org.cn' in full_url:
                            try:
                                session = get_session()
                                response = session.get(full_url, timeout=30)
                                response.encoding = 'utf-8'
                                article_soup = BeautifulSoup(response.text, 'html.parser')
                                
                                title = extract_title(article_soup, full_url)
                                content = extract_content(article_soup)
                                
                                if content:
                                    content = re.sub(r'\n{3,}', '\n\n', content)
                                    save_markdown(title, content, full_url, '中国妇幼保健协会')
                                
                                time.sleep(random.uniform(1, 2))
                            except Exception as e:
                                print(f"爬取文章失败 {full_url}: {e}")
                
                driver.get(base_url)
                time.sleep(2)
                
            except Exception as e:
                print(f"搜索失败 {keyword}: {e}")
        
    except Exception as e:
        print(f"Selenium爬取CMHA失败: {e}")

def add_local_knowledge():
    knowledge_base = [
        {
            'title': '婴儿喂养看护知识汇总',
            'content': '''
## 一、母乳喂养

### 1. 纯母乳喂养（0-6个月）
- 母乳是婴儿最理想的天然食物，含有丰富的营养素、免疫活性物质和水分
- 0-6个月婴儿提倡纯母乳喂养，不需要添加水和其他食物
- 按需哺乳，每日8-10次以上
- 婴儿从出生开始，应当在医生指导下每天补充维生素D 400-800国际单位

### 2. 母乳喂养的好处
- 降低婴儿患感冒、腹泻、肺炎等疾病的风险
- 减少成年后肥胖、糖尿病和心脑血管疾病等慢性病的发生
- 促进大脑发育，增进亲子关系
- 减少母亲产后出血、乳腺癌、卵巢癌的发生风险

## 二、辅食添加（6个月起）

### 1. 辅食添加原则
- 从6月龄开始添加辅食，首选富含铁的泥糊状食物
- 每次只引入1种新食物，观察是否出现呕吐、腹泻、皮疹等不良反应
- 逐渐调整辅食质地，从稠粥、肉泥等泥糊状食物逐渐过渡到半固体或固体食物
- 1岁以内婴儿辅食应当保持原味，不加盐、糖和调味品

### 2. 辅食种类
- 谷薯类：大米、小米、燕麦、土豆、红薯等
- 动物性食物：鱼、禽、肉及内脏、蛋类
- 蔬菜类：菠菜、西兰花、胡萝卜、南瓜等
- 水果类：苹果、香蕉、梨、蓝莓等

## 三、合理膳食（1-3岁）

### 1. 饮食搭配
- 每日三餐两点，主副食并重
- 食物搭配均衡，包括谷薯类、肉类、蛋类、豆类、乳及乳制品、蔬菜水果等
- 同类食物可轮流选用，做到膳食多样化

### 2. 饮食习惯培养
- 规律进餐，每次正餐控制在30分钟内
- 鼓励幼儿自主进食
- 少盐少糖，避免食用腌制品、熏肉、含糖饮料等高盐高糖食物
- 整粒花生、坚果、果冻等食物易引起窒息，应当避免食用

## 四、常见健康问题

### 1. 腹泻
- 母乳喂养的婴儿发生腹泻，不需要禁食，可以继续母乳喂养
- 及时补充体液，避免发生脱水
- 注意饮食卫生，餐具要消毒

### 2. 便秘
- 增加膳食纤维摄入，多吃蔬菜水果
- 保证充足饮水
- 培养规律排便习惯

### 3. 发热
- 密切监测体温变化
- 适当减少衣物，保持室内通风
- 鼓励多喝水
- 体温超过38.5℃可在医生指导下使用退烧药

## 五、生长发育监测

### 1. 定期体检
- 满月、3、6、8、12、18、24、30、36月龄时进行健康检查
- 监测体重、身长、头围等生长指标
- 进行发育评估

### 2. 生长异常处理
- 发现体重增长缓慢或停滞，及时咨询医生
- 关注身高增长情况，每年增长少于5厘米需就医
- 注意观察婴幼儿的运动、语言、社交能力发展

## 六、安全看护

### 1. 睡眠安全
- 婴儿应当仰卧睡觉
- 避免婴儿睡眠环境中有松软的物品
- 与父母同室不同床

### 2. 出行安全
- 使用安全座椅
- 避免将婴儿单独留在车内
- 注意防晒和保暖

### 3. 居家安全
- 药品、清洁剂等危险物品要放在婴幼儿接触不到的地方
- 插座要使用防护盖
- 楼梯、阳台要设置防护栏
''',
            'source': '综合整理自国家卫生健康委、WHO、UNICEF等官方资料',
        },
        {
            'title': '儿童生长发育指南',
            'content': '''
## 一、0-1岁婴儿发育里程碑

### 1. 运动发育
- 2个月：抬头
- 4个月：翻身
- 6个月：独坐
- 8个月：爬行
- 10个月：扶站
- 12个月：独走

### 2. 语言发育
- 3个月：咿呀发音
- 6个月：发出辅音
- 9个月：理解简单指令
- 12个月：说出第一个有意义的词

### 3. 社交发育
- 2个月：微笑回应
- 4个月：认人
- 6个月：怕生
- 9个月：挥手再见
- 12个月：模仿动作

## 二、1-3岁幼儿发育里程碑

### 1. 运动发育
- 18个月：跑、爬楼梯
- 2岁：双脚跳、踢球
- 3岁：骑三轮车、单脚站

### 2. 语言发育
- 18个月：说10-20个词
- 2岁：说简单句子
- 3岁：说完整句子，能讲简单故事

### 3. 认知发育
- 18个月：用杯喝水、翻书
- 2岁：堆积木、指出身体部位
- 3岁：认识颜色、数数1-10

## 三、生长发育评估

### 1. 生长曲线
- 定期绘制体重、身长、头围生长曲线
- 曲线偏离正常范围需及时咨询医生
- 关注生长速度而非单次测量值

### 2. 发育筛查
- 定期进行发育筛查
- 发现异常及时干预
- 早期干预对发育迟缓儿童至关重要

## 四、促进生长发育

### 1. 营养支持
- 保证充足的蛋白质、钙、铁、锌摄入
- 多晒太阳促进维生素D合成
- 避免挑食偏食

### 2. 运动锻炼
- 鼓励多户外活动
- 提供安全的运动环境
- 避免过度保护

### 3. 早期教育
- 多与孩子交流互动
- 提供适龄玩具和图书
- 培养好奇心和探索欲
''',
            'source': '综合整理自国家卫生健康委、中国妇幼保健协会资料',
        },
        {
            'title': '儿童疫苗接种指南',
            'content': '''
## 一、国家免疫规划疫苗

### 1. 乙肝疫苗
- 接种时间：出生后24小时内、1个月、6个月
- 预防疾病：乙型肝炎
- 接种部位：上臂三角肌

### 2. 卡介苗
- 接种时间：出生后24小时内
- 预防疾病：结核病
- 接种部位：上臂外侧

### 3. 脊灰疫苗
- 接种时间：2个月、3个月、4个月、4岁
- 预防疾病：脊髓灰质炎
- 接种方式：口服或注射

### 4. 百白破疫苗
- 接种时间：3个月、4个月、5个月、18-24个月
- 预防疾病：百日咳、白喉、破伤风
- 接种部位：上臂三角肌

### 5. 麻腮风疫苗
- 接种时间：8个月、18-24个月
- 预防疾病：麻疹、流行性腮腺炎、风疹
- 接种部位：上臂三角肌

### 6. 乙脑疫苗
- 接种时间：8个月、2周岁
- 预防疾病：流行性乙型脑炎
- 接种部位：上臂三角肌

### 7. 流脑疫苗
- 接种时间：6-18个月、3周岁、6周岁
- 预防疾病：流行性脑脊髓膜炎
- 接种部位：上臂三角肌

## 二、非免疫规划疫苗

### 1. 手足口病疫苗
- 接种时间：6月龄-5岁
- 预防疾病：手足口病
- 建议优先接种

### 2. 水痘疫苗
- 接种时间：12月龄以上
- 预防疾病：水痘
- 建议接种

### 3. 流感疫苗
- 接种时间：每年流感季前
- 预防疾病：流行性感冒
- 建议每年接种

### 4. 轮状病毒疫苗
- 接种时间：2月龄-3岁
- 预防疾病：轮状病毒肠炎
- 建议接种

### 5. 肺炎疫苗
- 接种时间：根据年龄选择
- 预防疾病：肺炎球菌感染
- 建议接种

## 三、疫苗接种注意事项

### 1. 接种前准备
- 带好接种本和身份证
- 告知医生孩子健康状况
- 避免空腹接种

### 2. 接种后观察
- 接种后留观30分钟
- 24小时内避免洗澡
- 观察有无不良反应

### 3. 不良反应处理
- 轻微发热、红肿：一般1-2天自行缓解
- 严重不良反应：立即就医
- 记录不良反应并报告接种单位

## 四、常见问题解答

### 1. 疫苗安全吗？
- 疫苗经过严格的安全性和有效性试验
- 不良反应发生率极低
- 接种疫苗的益处远大于风险

### 2. 可以推迟接种吗？
- 建议按时接种
- 特殊情况可推迟，但需尽快补种
- 推迟期间孩子可能缺乏保护

### 3. 接种后多久产生抗体？
- 不同疫苗产生抗体时间不同
- 一般接种后2-4周产生抗体
- 完成全程接种后保护效果最佳
''',
            'source': '综合整理自国家卫生健康委、中国疾控中心资料',
        },
        {
            'title': '儿童早期发展与教育指南',
            'content': '''
## 一、早期发展的重要性

### 1. 大脑发育关键期
- 0-3岁是大脑发育的黄金时期
- 出生时大脑重量约350克，3岁时约1000克
- 丰富的环境刺激促进神经元连接

### 2. 早期教育的意义
- 促进认知、语言、社交、情感全面发展
- 为未来学习打下基础
- 培养良好的行为习惯

## 二、0-1岁早期教育

### 1. 感官刺激
- 提供色彩丰富的环境
- 播放轻柔的音乐
- 进行触觉游戏

### 2. 语言交流
- 从出生开始就与婴儿说话
- 描述日常活动
- 读绘本、唱儿歌

### 3. 运动发展
- 帮助婴儿做抚触和被动操
- 提供安全的活动空间
- 鼓励翻身、爬行

## 三、1-3岁早期教育

### 1. 语言发展
- 扩展词汇量
- 鼓励表达需求
- 阅读绘本，培养阅读兴趣

### 2. 认知发展
- 认识颜色、形状、大小
- 数数和简单的数学概念
- 拼图、积木等益智游戏

### 3. 社交发展
- 与同龄儿童互动
- 学习分享和轮流
- 培养同理心

### 4. 独立性培养
- 自己吃饭、穿衣
- 自己如厕
- 整理玩具

## 四、家长角色

### 1. 陪伴的重要性
- 高质量的亲子陪伴
- 减少电子产品使用时间
- 建立安全的情感依恋

### 2. 积极的教育方式
- 多鼓励，少批评
- 尊重孩子的个性和兴趣
- 以身作则，树立榜样

### 3. 创造学习环境
- 提供适龄的图书和玩具
- 户外活动，接触大自然
- 参观博物馆、动物园等

## 五、常见误区

### 1. 过度早教
- 不要过早进行知识性学习
- 避免给孩子过多压力
- 以游戏和体验为主

### 2. 依赖电子产品
- 2岁以下不建议使用电子产品
- 2岁以上限制使用时间
- 家长陪同观看并互动

### 3. 包办代替
- 鼓励孩子自己尝试
- 允许孩子犯错
- 培养独立解决问题的能力
''',
            'source': '综合整理自国家卫生健康委、中国学前教育研究会资料',
        },
        {
            'title': '儿童常见疾病护理指南',
            'content': '''
## 一、呼吸系统疾病

### 1. 感冒
- 症状：流涕、打喷嚏、咳嗽、发热
- 护理：多喝水、多休息、保持室内通风
- 治疗：对症处理，必要时就医

### 2. 肺炎
- 症状：发热、咳嗽、呼吸急促、喘息
- 护理：保持呼吸道通畅、定时拍背
- 治疗：及时就医，遵医嘱用药

### 3. 哮喘
- 症状：喘息、咳嗽、胸闷、呼吸困难
- 护理：避免过敏原、规律用药
- 治疗：长期管理，定期复查

## 二、消化系统疾病

### 1. 腹泻
- 症状：大便次数增多、性状改变
- 护理：预防脱水、注意饮食卫生
- 治疗：补充水分和电解质，必要时就医

### 2. 便秘
- 症状：大便干结、排便困难
- 护理：增加膳食纤维、多喝水、培养规律排便
- 治疗：必要时使用开塞露，就医排查原因

### 3. 消化不良
- 症状：腹胀、腹痛、食欲不振、呕吐
- 护理：清淡饮食、少食多餐
- 治疗：遵医嘱使用助消化药物

## 三、皮肤疾病

### 1. 湿疹
- 症状：皮肤发红、瘙痒、干燥、脱屑
- 护理：保持皮肤湿润、避免刺激
- 治疗：遵医嘱使用外用药膏

### 2. 荨麻疹
- 症状：皮肤出现风团、瘙痒
- 护理：避免搔抓、查找过敏原
- 治疗：遵医嘱使用抗过敏药物

### 3. 痱子
- 症状：皮肤出现小红疹、瘙痒
- 护理：保持皮肤清洁干燥、穿宽松衣物
- 治疗：使用痱子粉或炉甘石洗剂

## 四、其他常见问题

### 1. 发热
- 护理：监测体温、适当减少衣物、多喝水
- 用药：体温超过38.5℃可使用退烧药
- 就医指征：持续高热、精神萎靡、抽搐等

### 2. 呕吐
- 护理：保持呼吸道通畅、少量多次补水
- 就医指征：频繁呕吐、呕吐物带血、脱水等

### 3. 意外伤害
- 预防：加强看护、消除安全隐患
- 处理：轻微擦伤消毒即可，严重伤害立即就医

## 五、就医指南

### 1. 何时需要就医
- 症状持续不见好转
- 出现异常症状
- 家长无法判断病情

### 2. 就医前准备
- 记录症状和时间
- 准备好既往病史资料
- 带好医保卡和就诊卡

### 3. 遵医嘱治疗
- 按时服药
- 定期复查
- 不要自行停药或换药
''',
            'source': '综合整理自国家卫生健康委、中国疾控中心资料',
        },
        {
            'title': '儿童心理健康指南',
            'content': '''
## 一、儿童心理健康的重要性

### 1. 心理健康对发展的影响
- 影响认知发展和学习能力
- 影响社交关系和人际关系
- 影响情绪调节和应对能力

### 2. 早期干预的重要性
- 儿童心理问题早期干预效果好
- 预防成年后心理问题的发生
- 促进全面健康发展

## 二、常见心理问题

### 1. 分离焦虑
- 表现：不愿离开父母、哭闹、拒绝上学
- 原因：安全感不足、环境变化
- 应对：逐步适应、建立信任

### 2. 注意力不集中
- 表现：容易分心、难以专注
- 原因：年龄特点、环境因素、生理因素
- 应对：提供安静环境、培养兴趣、适当运动

### 3. 情绪问题
- 表现：易怒、焦虑、抑郁、情绪波动
- 原因：家庭环境、压力、遗传因素
- 应对：情绪疏导、心理支持、专业帮助

### 4. 行为问题
- 表现：攻击性、逆反、说谎、偷窃
- 原因：模仿、寻求关注、缺乏规则意识
- 应对：建立规则、正面引导、行为矫正

## 三、促进心理健康

### 1. 建立安全的家庭环境
- 温暖和谐的家庭氛围
- 父母的关爱和支持
- 稳定的生活环境

### 2. 培养良好的心理素质
- 培养自信心和自尊心
- 学会情绪管理
- 培养抗压能力

### 3. 促进社交能力
- 鼓励与同龄人交往
- 学会分享和合作
- 培养同理心

### 4. 家长教育方式
- 民主平等的沟通
- 积极正面的引导
- 避免过度保护和溺爱

## 四、心理问题识别

### 1. 观察行为变化
- 突然的行为改变
- 持续的情绪低落
- 社交退缩

### 2. 关注学习情况
- 学习成绩明显下降
- 注意力不集中
- 不愿上学

### 3. 倾听孩子的心声
- 创造沟通的机会
- 认真倾听
- 给予理解和支持

## 五、寻求专业帮助

### 1. 何时需要专业帮助
- 问题持续超过2周
- 影响正常生活和学习
- 出现自伤或伤人行为

### 2. 专业资源
- 儿童心理医生
- 心理咨询师
- 学校心理辅导老师

### 3. 家长的态度
- 正视问题，不要回避
- 积极配合专业治疗
- 给予孩子更多关爱和支持
''',
            'source': '综合整理自国家卫生健康委、中国心理学会资料',
        },
        {
            'title': '儿童睡眠与作息指南',
            'content': '''
## 一、新生儿睡眠（0-3个月）

### 1. 睡眠特点
- 每日睡眠14-17小时
- 不分昼夜，每次2-4小时
- 夜间醒来多次吃奶

### 2. 睡眠环境
- 保持安静、光线柔和
- 温度适宜（22-26℃）
- 使用安全的婴儿床

### 3. 建立昼夜节律
- 白天多互动，夜晚保持安静
- 固定睡前程序：洗澡、抚触、喂奶、讲故事

## 二、婴儿睡眠（3-12个月）

### 1. 睡眠特点
- 每日睡眠12-15小时
- 夜间睡眠逐渐延长
- 白天2-3次小睡

### 2. 睡眠训练
- 6个月后可开始睡眠训练
- 建立固定的入睡时间
- 培养自主入睡能力

### 3. 常见问题
- 夜醒频繁：检查是否饥饿、尿布湿或身体不适
- 入睡困难：建立睡前程序，避免过度兴奋
- 昼夜颠倒：白天多晒太阳，减少白天睡眠时间

## 三、幼儿睡眠（1-3岁）

### 1. 睡眠特点
- 每日睡眠11-14小时
- 夜间睡眠10-12小时
- 白天1次午睡（1-2小时）

### 2. 作息规律
- 固定上床和起床时间
- 睡前避免电子产品
- 创造舒适的睡眠环境

### 3. 常见问题
- 不愿上床：建立睡前仪式，给予安全感
- 夜间醒来：避免立即回应，培养自我安抚能力
- 午睡过长或过晚：调整午睡时间

## 四、睡眠安全

### 1. 睡姿安全
- 婴儿应仰卧睡觉
- 避免俯卧或侧卧
- 使用坚实平坦的床垫

### 2. 睡眠环境安全
- 移除婴儿床内的松软物品
- 避免过热，穿宽松透气的睡衣
- 与父母同室不同床

### 3. 避免睡眠干扰
- 避免夜间频繁喂奶（6个月后）
- 减少夜间换尿布次数
- 保持规律作息

## 五、家长注意事项

### 1. 耐心引导
- 每个孩子的睡眠模式不同
- 不要急于求成
- 保持一致的睡眠策略

### 2. 自我照顾
- 家长也要保证充足睡眠
- 寻求家人支持
- 必要时寻求专业帮助
''',
            'source': '综合整理自国家卫生健康委、美国儿科学会资料',
        },
        {
            'title': '儿童口腔护理指南',
            'content': '''
## 一、0-6个月口腔护理

### 1. 口腔清洁
- 每次喂奶后用干净纱布清洁口腔
- 从出生开始清洁牙龈
- 避免含奶瓶睡觉

### 2. 牙齿萌出
- 第一颗牙通常在6个月左右萌出
- 萌牙期可能出现流口水、烦躁、发热
- 提供安全的牙胶缓解不适

## 二、6个月-2岁口腔护理

### 1. 刷牙开始
- 第一颗牙萌出后开始刷牙
- 使用儿童专用牙刷和含氟牙膏
- 每日早晚各刷牙一次

### 2. 刷牙方法
- 家长帮助刷牙，直到孩子能独立完成
- 采用圆弧刷牙法
- 清洁所有牙齿表面和牙龈

### 3. 饮食注意
- 减少含糖食物和饮料
- 避免睡前喂食含糖食物
- 多喝水，保持口腔湿润

## 三、2-5岁口腔护理

### 1. 自主刷牙
- 鼓励孩子自己刷牙
- 家长监督并协助完成
- 培养良好的刷牙习惯

### 2. 氟化物使用
- 定期使用含氟牙膏
- 必要时咨询牙医是否需要涂氟
- 控制牙膏用量（豌豆大小）

### 3. 饮食管理
- 减少甜食和粘性食物
- 多吃富含钙和维生素的食物
- 饭后漱口

## 四、定期口腔检查

### 1. 首次检查
- 第一颗牙萌出后6个月内进行首次检查
- 最迟不超过1岁

### 2. 定期检查
- 每3-6个月检查一次
- 及时发现问题并处理
- 建立儿童口腔健康档案

### 3. 预防措施
- 涂氟：每3-6个月一次
- 窝沟封闭：乳磨牙萌出后进行
- 预防龋齿和牙周疾病

## 五、常见口腔问题

### 1. 龋齿
- 症状：牙齿变黑、有洞、疼痛
- 预防：定期刷牙、控制糖分、涂氟
- 治疗：及时补牙

### 2. 牙龈问题
- 症状：牙龈红肿、出血
- 原因：口腔卫生不良、维生素缺乏
- 处理：改善口腔卫生、补充维生素

### 3. 牙齿发育异常
- 畸形牙、多生牙、牙齿缺失
- 及时咨询牙医
- 必要时进行矫正

## 六、家长教育

### 1. 树立榜样
- 家长坚持刷牙
- 让孩子看到刷牙的重要性

### 2. 培养兴趣
- 使用卡通牙刷和牙膏
- 播放刷牙儿歌
- 游戏化刷牙

### 3. 安全注意
- 使用儿童专用牙刷
- 避免吞咽牙膏
- 监督孩子刷牙
''',
            'source': '综合整理自国家卫生健康委、中国牙病防治基金会资料',
        },
        {
            'title': '儿童皮肤护理指南',
            'content': '''
## 一、新生儿皮肤护理（0-1个月）

### 1. 皮肤特点
- 皮肤娇嫩，屏障功能不完善
- 容易受到刺激和感染
- 注意保湿和防护

### 2. 日常护理
- 每日清洁：使用温和的婴儿沐浴露
- 保湿：清洁后立即涂抹婴儿润肤霜
- 尿布更换：及时更换尿布，清洁臀部

### 3. 常见问题
- 新生儿痤疮：通常自行消退，保持清洁即可
- 粟丘疹：白色小颗粒，无需特殊处理
- 脱皮：正常现象，加强保湿

## 二、婴儿皮肤护理（1-12个月）

### 1. 日常护理
- 每周洗澡2-3次即可
- 使用温和无刺激的洗护用品
- 保持皮肤清洁干燥

### 2. 湿疹护理
- 湿疹是常见的皮肤问题
- 保持皮肤湿润是关键
- 避免接触过敏原

### 3. 尿布疹护理
- 及时更换尿布
- 清洁臀部后晾干
- 使用护臀霜保护皮肤

## 三、幼儿皮肤护理（1-3岁）

### 1. 日常护理
- 每日清洁皮肤
- 注意防晒
- 保持皮肤滋润

### 2. 防晒措施
- 避免阳光强烈时外出
- 使用儿童专用防晒霜
- 穿戴防晒衣物和帽子

### 3. 蚊虫叮咬处理
- 使用驱蚊液
- 叮咬后冷敷缓解瘙痒
- 避免搔抓，防止感染

## 四、常见皮肤问题

### 1. 湿疹
- 症状：皮肤发红、瘙痒、干燥、脱屑
- 护理：保持皮肤湿润、避免刺激、穿宽松棉质衣物
- 治疗：遵医嘱使用外用药膏

### 2. 尿布疹
- 症状：臀部皮肤发红、出现红疹
- 护理：及时更换尿布、保持臀部干燥、使用护臀霜
- 治疗：严重时就医

### 3. 痱子
- 症状：皮肤出现小红疹、瘙痒
- 护理：保持皮肤清洁干燥、穿宽松衣物、避免过热
- 治疗：使用痱子粉或炉甘石洗剂

### 4. 荨麻疹
- 症状：皮肤出现风团、瘙痒
- 护理：避免搔抓、查找过敏原
- 治疗：遵医嘱使用抗过敏药物

### 5. 接触性皮炎
- 症状：皮肤发红、瘙痒、出现皮疹
- 原因：接触过敏原或刺激物
- 处理：避免接触、遵医嘱用药

## 五、护肤品选择

### 1. 选择原则
- 成分简单，无香精、色素
- 温和无刺激
- 适合儿童肤质

### 2. 注意事项
- 先在耳后或手臂内侧试用
- 观察有无过敏反应
- 选择正规品牌

### 3. 防晒产品
- SPF30+，PA+++
- 物理防晒为主
- 专门为儿童设计

## 六、家长注意事项

### 1. 保持清洁
- 定期清洁皮肤
- 衣物勤换洗
- 保持环境清洁

### 2. 避免刺激
- 避免使用成人护肤品
- 避免过度清洁
- 避免摩擦皮肤

### 3. 及时就医
- 皮肤问题持续不愈
- 出现感染迹象
- 不确定问题原因
''',
            'source': '综合整理自国家卫生健康委、中国医师协会皮肤科分会资料',
        },
        {
            'title': '儿童急救与安全指南',
            'content': '''
## 一、家庭急救准备

### 1. 急救包准备
- 体温计、血压计
- 消毒用品：碘伏、酒精、纱布、创可贴
- 常用药品：退烧药、抗过敏药、止泻药
- 紧急联系电话：120、110、儿科医生

### 2. 急救知识学习
- 学习心肺复苏（CPR）
- 掌握海姆立克急救法
- 了解常见急症处理方法

### 3. 预防措施
- 家中安装烟雾报警器
- 药品和危险物品上锁
- 插座使用防护盖

## 二、常见意外伤害处理

### 1. 窒息
- 表现：呼吸困难、面色发紫、无法发声
- 处理：立即拨打120，同时实施海姆立克急救法
- 预防：避免给3岁以下儿童吃坚果、果冻等食物

### 2. 烫伤
- 表现：皮肤发红、起水泡、疼痛
- 处理：立即用流动冷水冲洗15-30分钟，不要挑破水泡
- 预防：热水瓶放在高处，洗澡前先试水温

### 3. 外伤出血
- 表现：皮肤破损、出血
- 处理：按压止血，清洁伤口，包扎
- 预防：保持环境安全，避免尖锐物品

### 4. 溺水
- 表现：呼吸困难、咳嗽、面色发青
- 处理：立即拨打120，清除口鼻异物，进行人工呼吸
- 预防：加强看护，避免儿童单独接触水

### 5. 中毒
- 表现：呕吐、腹泻、意识模糊
- 处理：立即拨打120，保留中毒物品供医生参考
- 预防：药品、清洁剂上锁

## 三、常见急症处理

### 1. 高热惊厥
- 表现：体温超过39℃，出现抽搐
- 处理：保持呼吸道通畅，侧卧，不要强行按压肢体
- 预防：及时退烧，避免体温过高

### 2. 过敏性休克
- 表现：呼吸困难、面部肿胀、皮疹
- 处理：立即拨打120，使用肾上腺素笔（如有）
- 预防：了解过敏原，避免接触

### 3. 骨折脱位
- 表现：疼痛、肿胀、活动受限
- 处理：固定受伤部位，避免移动
- 预防：加强安全防护

## 四、居家安全

### 1. 防护措施
- 楼梯、阳台安装防护栏
- 窗户安装限位器
- 家具固定防倾倒

### 2. 厨房安全
- 刀具放在高处
- 灶台使用防烫罩
- 避免儿童进入厨房

### 3. 浴室安全
- 地面防滑处理
- 安装扶手
- 洗澡时全程看护

### 4. 电器安全
- 使用儿童安全插座
- 电线整理好
- 避免儿童接触电器

## 五、出行安全

### 1. 乘车安全
- 使用儿童安全座椅
- 不要将儿童单独留在车内
- 系好安全带

### 2. 步行安全
- 遵守交通规则
- 走人行横道
- 不要在马路上玩耍

### 3. 户外安全
- 避免阳光直射
- 注意蚊虫叮咬
- 不要去危险场所

## 六、家长注意事项

### 1. 加强看护
- 时刻关注孩子
- 不要让孩子离开视线
- 培养安全意识

### 2. 及时就医
- 不确定伤情时及时就医
- 不要自行处理严重外伤
- 记录受伤经过

### 3. 定期演练
- 进行家庭急救演练
- 确保所有家庭成员了解急救方法
- 更新急救知识
''',
            'source': '综合整理自国家卫生健康委、中国红十字会资料',
        },
        {
            'title': '儿童视力与听力保健指南',
            'content': '''
## 一、儿童视力保健

### 1. 新生儿视力筛查
- 出生后进行先天性白内障筛查
- 42天进行视力筛查
- 发现异常及时干预

### 2. 0-3岁视力发育
- 0-3个月：注视能力、追视能力
- 3-6个月：立体视觉开始发展
- 6-12个月：手眼协调能力发展
- 1-3岁：视力逐渐发育成熟

### 3. 视力保护
- 避免长时间近距离用眼
- 保持正确的用眼姿势
- 多进行户外活动
- 控制电子产品使用时间

### 4. 定期视力检查
- 6个月进行首次视力检查
- 每6-12个月复查一次
- 发现问题及时干预

### 5. 常见视力问题
- 近视：过早接触电子产品、缺乏户外活动
- 远视：正常生理现象，随年龄增长可能改善
- 斜视：及时就医，必要时手术矫正
- 弱视：3-6岁是最佳治疗时期

## 二、儿童听力保健

### 1. 新生儿听力筛查
- 出生后48小时内进行听力筛查
- 未通过者42天复查
- 3个月内确诊，6个月内干预

### 2. 0-3岁听力发育
- 0-3个月：对声音有反应
- 3-6个月：转头寻找声源
- 6-12个月：理解简单指令
- 1-3岁：语言能力快速发展

### 3. 听力保护
- 避免噪音环境
- 不要随意掏耳朵
- 洗澡时防止水进入耳朵
- 避免使用耳毒性药物

### 4. 定期听力检查
- 每年进行一次听力检查
- 发现听力下降及时就医
- 听力障碍儿童及时佩戴助听器

### 5. 常见听力问题
- 中耳炎：儿童常见疾病，及时治疗
- 外耳道炎：保持耳朵清洁干燥
- 听力损失：早发现、早干预
- 语言发育迟缓：排查听力问题

## 三、家长注意事项

### 1. 观察发育情况
- 注意孩子的眼神和反应
- 关注语言发展情况
- 发现异常及时就医

### 2. 创造良好环境
- 提供丰富的视觉刺激
- 多与孩子交流互动
- 避免噪音和强光刺激

### 3. 定期健康检查
- 纳入常规体检项目
- 记录检查结果
- 建立健康档案
''',
            'source': '综合整理自国家卫生健康委、中国残疾人联合会资料',
        },
        {
            'title': '儿童如厕训练指南',
            'content': '''
## 一、如厕训练准备

### 1. 生理准备
- 孩子能够控制大小便
- 大便规律，每天1-2次
- 尿布保持干燥2小时以上

### 2. 心理准备
- 对马桶感兴趣
- 愿意模仿大人上厕所
- 能够表达大小便需求

### 3. 物品准备
- 儿童专用马桶或马桶圈
- 小凳子
- 绘本和奖励贴纸

## 二、训练方法

### 1. 认识马桶阶段
- 让孩子观察大人上厕所
- 阅读如厕训练绘本
- 让孩子坐马桶玩耍

### 2. 练习阶段
- 定时让孩子坐马桶
- 鼓励孩子表达需求
- 不要强迫，耐心引导

### 3. 巩固阶段
- 白天不再使用尿布
- 夜间使用尿不湿过渡
- 逐渐减少夜间尿床

## 三、常见问题

### 1. 不愿意坐马桶
- 不要强迫
- 增加趣味性
- 家长陪同示范

### 2. 尿裤子
- 保持耐心
- 不要批评
- 及时更换衣物

### 3. 便秘
- 增加膳食纤维
- 多喝水
- 规律排便

### 4. 夜间尿床
- 睡前少喝水
- 夜间定时叫醒
- 使用尿床报警器

## 四、家长注意事项

### 1. 耐心引导
- 每个孩子发育不同
- 不要急于求成
- 给予鼓励和表扬

### 2. 避免压力
- 不要比较
- 不要批评指责
- 保持轻松愉快的氛围

### 3. 循序渐进
- 从白天开始
- 逐渐过渡到夜间
- 尊重孩子的节奏
''',
            'source': '综合整理自国家卫生健康委、美国儿科学会资料',
        },
    ]
    
    for knowledge in knowledge_base:
        save_markdown(knowledge['title'], knowledge['content'], knowledge['source'], '综合知识')

def generate_summary():
    summary = {
        'title': '育儿知识RAG知识库',
        'description': '收集自官方网站的育儿知识，包括母乳喂养、辅食添加、合理膳食、生长发育、疫苗接种、早期教育、常见疾病护理、心理健康、睡眠作息、口腔护理、皮肤护理、急救安全、视力听力、如厕训练等内容',
        'sources': [
            '国家卫生健康委员会',
            '联合国儿童基金会（UNICEF）中国办事处',
            '世界卫生组织（WHO）',
            '中国疾病预防控制中心',
            '中国妇幼保健协会',
            '中国营养学会',
            '健康中国',
            '美国儿科学会（AAP）',
            '美国CDC',
            '英国NHS',
            'Mayo Clinic',
        ],
        'categories': [],
        'documents': [],
    }
    
    for category in os.listdir(OUTPUT_DIR):
        category_path = os.path.join(OUTPUT_DIR, category)
        if os.path.isdir(category_path):
            summary['categories'].append(category)
            for filename in os.listdir(category_path):
                if filename.endswith('.md') and filename != 'Untitled.md':
                    summary['documents'].append({
                        'category': category,
                        'filename': filename,
                        'path': os.path.join(category, filename),
                    })
    
    summary_path = os.path.join(OUTPUT_DIR, 'summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n知识库摘要已生成: {summary_path}")
    print(f"总文档数: {len(summary['documents'])}")
    print(f"分类: {summary['categories']}")

def main():
    print("=== 育儿知识爬虫 ===")
    print(f"输出目录: {OUTPUT_DIR}\n")
    
    session = get_session()
    
    print("1. 爬取国家卫生健康委相关文章...")
    crawl_nhc_articles(session)
    
    print("\n2. 爬取UNICEF中国官网相关资料...")
    crawl_unicef_china(session)
    
    print("\n3. 爬取WHO官网相关资料...")
    crawl_who(session)
    
    print("\n4. 爬取中国疾控中心相关资料...")
    crawl_cdc(session)
    
    print("\n5. 爬取妇幼健康相关资料...")
    crawl_mohfw(session)
    
    print("\n6. 爬取国家卫生健康委更多育儿页面...")
    crawl_nhc_more(session)
    
    print("\n7. 爬取中国妇幼保健协会相关资料...")
    crawl_cmha(session)
    
    print("\n8. 爬取中国营养学会相关资料...")
    crawl_cns(session)
    
    print("\n9. 爬取健康中国相关资料...")
    crawl_health_cn(session)
    
    print("\n10. 爬取美国儿科学会(AAP)相关资料...")
    crawl_aap(session)
    
    print("\n11. 爬取美国CDC相关资料...")
    crawl_cdc_gov(session)
    
    print("\n12. 爬取英国NHS相关资料...")
    crawl_nhs_uk(session)
    
    print("\n13. 爬取Mayo Clinic相关资料...")
    crawl_mayo_clinic(session)
    
    print("\n14. Selenium深度搜索爬取...")
    driver = get_selenium_driver()
    if driver:
        search_keywords = [
            '婴幼儿喂养指南', '儿童生长发育', '疫苗接种时间表',
            '婴儿睡眠训练', '儿童口腔护理', '儿童皮肤护理',
            '儿童急救知识', '儿童心理健康', '早期教育方法',
            '儿童视力保护', '儿童听力保健', '如厕训练方法',
        ]
        crawl_selenium_search(driver, search_keywords, max_pages=2)
        crawl_selenium_cmha(driver)
        driver.quit()
    else:
        print("Selenium不可用，跳过深度搜索")
    
    print("\n15. 添加本地整理的知识...")
    add_local_knowledge()
    
    print("\n16. 生成知识库摘要...")
    generate_summary()
    
    print("\n=== 爬虫任务完成 ===")

if __name__ == '__main__':
    main()