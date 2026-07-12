"""
JARVIS voice assistant for Windows.

Features:
- Wake phrase: "Hey Jarvis"
- Opens configured games, programs, folders, and files
- Searches the internet and speaks the best search result
- Opens normal web searches in your default browser
- Uses an allow-list instead of running arbitrary spoken commands

Python 3.10+ recommended.
"""

from __future__ import annotations

import html
import os
import re
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Final

import pyttsx3
import speech_recognition as sr
from ddgs import DDGS


# =========================
# SETTINGS YOU CAN CHANGE
# =========================

WAKE_PHRASE: Final[str] = "hey jarvis"
SPEECH_LANGUAGE: Final[str] = "en-GB"
SEARCH_REGION: Final[str] = "uk-en"
OPEN_TOP_SEARCH_RESULT: Final[bool] = False

HOME = Path.home()
PROGRAM_FILES = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
PROGRAM_FILES_X86 = Path(
    os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
)

# Jarvis will ONLY open items listed here.
# Add your own games/files using this format:
# "name you will say": r"C:\full\path\to\game-or-file.exe",
#
# Steam games can also use:
# "game name": "steam://rungameid/STEAM_APP_ID",
OPENABLE_ITEMS: dict[str, str | Path] = {
    "desktop": HOME / "Desktop",
    "documents": HOME / "Documents",
    "downloads": HOME / "Downloads",
    "pictures": HOME / "Pictures",
    "steam": PROGRAM_FILES_X86 / "Steam" / "steam.exe",

    # EXAMPLES — remove the # and replace the path:
    # "minecraft": r"C:\Path\To\MinecraftLauncher.exe",
    # "vrchat": "steam://rungameid/438100",
    # "my blender project": r"C:\Users\YourName\Documents\avatar.blend",
    # "my homework": r"C:\Users\YourName\Documents\homework.docx",
}

WEBSITES: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "spotify": "https://open.spotify.com",
}


# =========================
# VOICE SETUP
# =========================

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8
recognizer.non_speaking_duration = 0.5

try:
    microphone = sr.Microphone()
except (AttributeError, OSError) as exc:
    print("\nMicrophone setup failed.")
    print('Install microphone support with: py -m pip install "SpeechRecognition[audio]"')
    print(f"Details: {exc}")
    sys.exit(1)

try:
    voice_engine = pyttsx3.init()
    voice_engine.setProperty("rate", 175)
    voice_engine.setProperty("volume", 1.0)

    # Prefer an installed English voice when possible.
    for installed_voice in voice_engine.getProperty("voices"):
        searchable = (
            f"{installed_voice.name} {installed_voice.id} "
            f"{getattr(installed_voice, 'languages', '')}"
        ).lower()
        if "english" in searchable or "en-gb" in searchable or "en_" in searchable:
            voice_engine.setProperty("voice", installed_voice.id)
            break
except Exception as exc:
    voice_engine = None
    print(f"Text-to-speech could not start: {exc}")


def speak(message: str) -> None:
    """Print and speak a message."""
    message = message.strip()
    if not message:
        return

    print(f"JARVIS: {message}")

    if voice_engine is not None:
        try:
            voice_engine.say(message)
            voice_engine.runAndWait()
        except Exception as exc:
            print(f"Text-to-speech error: {exc}")


def listen(timeout: float = 5, phrase_time_limit: float = 8) -> str:
    """Listen once and return recognised lowercase text."""
    try:
        with microphone as source:
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )

        text = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
        text = text.lower().strip()
        print(f"YOU: {text}")
        return text

    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        print(f"Speech recognition internet error: {exc}")
        return ""
    except OSError as exc:
        print(f"Microphone error: {exc}")
        time.sleep(1)
        return ""


# =========================
# OPENING LOCAL ITEMS
# =========================

def normalise_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def open_target(target: str | Path) -> tuple[bool, str]:
    """
    Open a configured target.

    Uses os.startfile on Windows so Windows chooses the correct program.
    """
    target_text = os.path.expandvars(os.path.expanduser(str(target))).strip()

    if target_text.startswith(("http://", "https://")):
        webbrowser.open_new_tab(target_text)
        return True, "website"

    if "://" in target_text:
        try:
            os.startfile(target_text)  # type: ignore[attr-defined]
            return True, "link"
        except OSError as exc:
            return False, str(exc)

    path = Path(target_text)

    if not path.exists():
        return False, f"I could not find this path: {path}"

    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True, "local item"
    except OSError as exc:
        return False, str(exc)


def open_named_item(spoken_name: str) -> bool:
    """Open an allow-listed program, game, folder, file, or website."""
    name = normalise_name(spoken_name)

    if name in WEBSITES:
        webbrowser.open_new_tab(WEBSITES[name])
        speak(f"Opening {name}.")
        return True

    target = OPENABLE_ITEMS.get(name)
    if target is None:
        speak(
            f"I do not have {name} in my safe open list. "
            "Add its path near the top of the Python file."
        )
        return False

    success, details = open_target(target)
    if success:
        speak(f"Opening {name}.")
        return True

    speak(f"I could not open {name}. {details}")
    return False


# =========================
# INTERNET SEARCH
# =========================

def clean_search_text(text: str, maximum_length: int = 550) -> str:
    """Make a search snippet easier for text-to-speech."""
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= maximum_length:
        return text

    shortened = text[:maximum_length].rsplit(" ", 1)[0]
    return shortened + "..."


def google_search_url(query: str) -> str:
    encoded_query = urllib.parse.quote_plus(query)
    return f"https://www.google.com/search?q={encoded_query}"


def open_web_search(query: str) -> None:
    webbrowser.open_new_tab(google_search_url(query))
    speak(f"Searching the internet for {query}.")


def answer_from_internet(query: str) -> None:
    """
    Search the web and speak the most useful result snippet.

    This does not execute code from search results and does not download files.
    """
    query = query.strip()
    if not query:
        speak("What would you like me to search for?")
        return

    print(f"Searching the internet for: {query}")

    try:
        results = DDGS(timeout=10).text(
            query,
            region=SEARCH_REGION,
            safesearch="moderate",
            max_results=5,
        )
    except Exception as exc:
        print(f"Web search error: {exc}")
        webbrowser.open_new_tab(google_search_url(query))
        speak("The answer search failed, so I opened a normal web search instead.")
        return

    useful_results = [
        result
        for result in results
        if result.get("body") and result.get("href")
    ]

    if not useful_results:
        webbrowser.open_new_tab(google_search_url(query))
        speak("I could not find a clear spoken answer, so I opened the search results.")
        return

    best = useful_results[0]
    title = clean_search_text(str(best.get("title", "Search result")), 120)
    answer = clean_search_text(str(best.get("body", "")))
    source_url = str(best.get("href", ""))

    print("\nTOP RESULT")
    print(f"Title: {title}")
    print(f"Source: {source_url}")
    print(f"Answer: {answer}\n")

    speak(answer)

    if OPEN_TOP_SEARCH_RESULT and source_url:
        webbrowser.open_new_tab(source_url)


# =========================
# COMMAND HANDLING
# =========================

def remove_command_prefix(command: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if command.startswith(prefix):
            return command[len(prefix):].strip()
    return command.strip()


def handle_command(command: str) -> bool:
    """
    Handle one command.

    Returns False when Jarvis should shut down.
    """
    command = normalise_name(command)

    if not command:
        speak("I did not hear a command.")
        return True

    if command in {
        "stop",
        "exit",
        "quit",
        "shut down",
        "shutdown",
        "goodbye",
        "stop listening",
    }:
        speak("Shutting down. Goodbye.")
        return False

    if command in {"help", "what can you do", "commands"}:
        speak(
            "I can open configured games, programs, folders and files, "
            "open websites, tell the time, and search the internet for answers."
        )
        print(
            "\nEXAMPLE COMMANDS:\n"
            "- Hey Jarvis, open Steam\n"
            "- Hey Jarvis, open Downloads\n"
            "- Hey Jarvis, search for Minecraft shaders\n"
            "- Hey Jarvis, what is a black hole\n"
            "- Hey Jarvis, what time is it\n"
            "- Hey Jarvis, stop listening\n"
        )
        return True

    if command in {"what time is it", "tell me the time", "time"}:
        current_time = datetime.now().strftime("%I:%M %p").lstrip("0")
        speak(f"It is {current_time}.")
        return True

    if command in {"what is the date", "tell me the date", "date"}:
        current_date = datetime.now().strftime("%A, %d %B %Y")
        speak(f"Today is {current_date}.")
        return True

    if command.startswith(("open ", "launch ", "start ")):
        item_name = remove_command_prefix(command, ("open ", "launch ", "start "))
        open_named_item(item_name)
        return True

    if command.startswith(
        (
            "search the internet for ",
            "search online for ",
            "search for ",
            "google ",
            "look up ",
        )
    ):
        query = remove_command_prefix(
            command,
            (
                "search the internet for ",
                "search online for ",
                "search for ",
                "google ",
                "look up ",
            ),
        )
        open_web_search(query)
        return True

    # Questions are answered using web search snippets.
    question_starters = (
        "what ",
        "who ",
        "when ",
        "where ",
        "why ",
        "how ",
        "which ",
        "tell me about ",
        "explain ",
        "is ",
        "are ",
        "can ",
        "could ",
        "should ",
    )
    if command.startswith(question_starters):
        answer_from_internet(command)
        return True

    # Anything Jarvis does not understand becomes an internet question.
    speak("I do not recognise that as a local command. I will search for an answer.")
    answer_from_internet(command)
    return True


def extract_command_after_wake_phrase(heard_text: str) -> str | None:
    """Return text after 'hey jarvis', or None if the wake phrase was absent."""
    wake_match = re.search(r"\bhey\s+jarvis\b", heard_text)
    if wake_match is None:
        return None
    return heard_text[wake_match.end():].strip(" ,.!?")


def main() -> None:
    print("=" * 58)
    print("JARVIS VOICE ASSISTANT")
    print('Wake phrase: "Hey Jarvis"')
    print('Say "Hey Jarvis, help" to hear the command list.')
    print("=" * 58)

    speak("Jarvis is online.")

    print("Calibrating the microphone. Keep quiet for one second...")
    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
    except OSError as exc:
        print(f"Microphone calibration warning: {exc}")

    running = True

    while running:
        heard = listen(timeout=5, phrase_time_limit=8)
        if not heard:
            continue

        command = extract_command_after_wake_phrase(heard)
        if command is None:
            continue

        if not command:
            speak("Yes?")
            command = listen(timeout=6, phrase_time_limit=12)

        if command:
            running = handle_command(command)
        else:
            speak("I did not hear anything.")

    print("Jarvis has stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis stopped with the keyboard.")
