import urllib.request
from bs4 import BeautifulSoup

req = urllib.request.Request('https://www.jobmaster.co.il/jobs/?q=python', headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
soup = BeautifulSoup(html, 'html.parser')

for job in soup.select('.JobItem')[:3]:
    title = job.select_one('.CardHeader')
    company = job.select_one('.companyNameLink')
    if not company:
        company = job.select_one('.companyName')
    print("Title:", title.text.strip() if title else "None")
    print("Company:", company.text.strip() if company else "None")
    a = job.select_one('a')
    print("Link:", a['href'] if a else "None")
    print("---")
