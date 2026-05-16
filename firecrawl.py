from firecrawl import FirecrawlApp

app = FirecrawlApp(api_key="YOUR_API_KEY")

data = app.scrape_url(
    "https://www.ssgmce.ac.in/vihang/",
    formats=["markdown"]
)

print(data["markdown"])
