import webbrowser
from urllib.parse import quote_plus
from langchain_core.tools import tool

@tool
def weather_action(
    city: str,
    time: str = "today"
) -> str:
    """
    Weather report action.
    Opens a Google weather search and returns a confirmation.
    """

    if not city or not isinstance(city, str):
        return "Sir, the city is missing for the weather report."

    city = city.strip()
    time = time.strip() if time else "today"

    search_query = f"weather in {city} {time}"
    encoded_query = quote_plus(search_query)
    url = f"https://www.google.com/search?q={encoded_query}"

    try:
        webbrowser.open(url)
    except Exception:
        return f"Sir, I couldn't open the browser for the weather report."

    msg = f"Showing the weather for {city}, {time}, sir."
    return msg


def _speak_and_log(message: str, player=None):
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass