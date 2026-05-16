import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

url = "https://www.ssgmce.ac.in/vihang/"

response = requests.get(url)
html = response.text

soup = BeautifulSoup(html, "html.parser")

# Remove scripts and styles
for tag in soup(["script", "style", "nav", "footer"]):
    tag.decompose()

clean_html = str(soup)

markdown = md(clean_html)

with open("vihang.md", "w", encoding="utf-8") as f:
    f.write(markdown)

print("Website converted to vihang.md")
