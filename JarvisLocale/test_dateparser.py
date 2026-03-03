import dateparser
from dateparser.search import search_dates

def test_parsing():
    test_cases = [
        "domani alle 15:00",
        "5 marzo 2026 alle 17",
        "il 25 ottobre alle 18:30",
        "martedi 5 marzo 2026 alle 17:00",
        "il 5 devo fare un esame alle 15",
    ]
    
    print("Testing WITHOUT language enforcement:")
    for text in test_cases:
        res = dateparser.parse(text, settings={'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future'})
        print(f"'{text}' -> {res}")
        
    print("\nTesting WITH language enforcement:")
    for text in test_cases:
        res = dateparser.parse(text, languages=['it'], settings={'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future'})
        print(f"'{text}' -> {res}")

    print("\nTesting WITH search_dates:")
    for text in test_cases:
        res = search_dates(text, languages=['it'], settings={'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future'})
        print(f"'{text}' -> {res}")

if __name__ == "__main__":
    test_parsing()
