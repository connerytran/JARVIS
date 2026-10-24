
import random
import re
from pathlib import Path
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv
import psutil
import subprocess
import time

from _macos import osascript

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
SCOPE = "user-modify-playback-state user-read-playback-state"
TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".cache"  # repo root, so the login survives running from any directory
TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{22}")  # the only shape allowed into the AppleScript in play_song

SPOTIFY = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    cache_path=str(TOKEN_CACHE_PATH),
    )
)


def _spotify_device() -> str:
    """Get the first available Spotify device. If no device is found, return None."""
    
    if not any(p.info['name'] == "Spotify" for p in psutil.process_iter(['name'])):
        subprocess.Popen(["open", "-a", "Spotify"])  # Start Spotify if it's not running

    start = time.time()
    while time.time() - start < 10:  # Wait up to 10 seconds
        devices = SPOTIFY.devices().get('devices', [])
        if devices:
            return devices[0]['id']  # Return the first available device ID
        time.sleep(1)
    return None



def search_song(song_name: str=None, artist_name: str=None):
    """ONLY SEARCHES for songs on Spotify. ALWAYS call this before play_song to get a valid URI.
    After getting results, immediately pick the best matching URI and call play_song — do NOT ask the user to confirm or choose.
    Best match = closest song name + artist name to what the user requested.
    BE SURE TO CALL play_song WITH THE URI OF THE SONG YOU WANT TO PLAY AFTER
    Args:
      song_name: The name of the song to search for
      artist_name: The name of the artist of the song
    """
    try:
        query = f" {song_name} {artist_name}" if song_name and artist_name else f" {song_name}" if song_name else f" {artist_name}"
        results = SPOTIFY.search(q=query, type="track", limit=5)
        if not results['tracks']['items']:
            return {"status": "error", "message": f"Could not find songs for: '{song_name}' by '{artist_name}' on Spotify."}
        
        tracks = results['tracks']['items']
        search_results = {}
        for track in tracks:
            search_results[track['uri']] = {
                "song_name": track['name'],
                "artist_name": track['artists'][0]['name'],
                "album_name": track['album']['name'],
            }

        return {
            "status": "success",
            "Search Results": search_results
        }
        
    except Exception as e:
        return {"status": "error", "message": f"An error occurred: {str(e)}"}



def play_song(song_uid: str = None) -> dict:
    """ ALWAYS USE search_song BEFORE THIS TO GET A VALID SONG UID.
    Play a song on Spotify and queue shuffled songs from the artist after. 
    Args:
      song_uid: The URI of the song to play. Example: "spotify:track:xxxxxxxxxxxxxxxxx"
    """
    # The uri goes into an AppleScript string below; anything but a well-formed track uri could break out of it.
    if not song_uid or not TRACK_URI.fullmatch(song_uid):
        return {"status": "error", "message": f"'{song_uid}' is not a valid Spotify track URI. Call search_song first to get one."}

    try:
        track = SPOTIFY.track(song_uid)
        artist_id = track['artists'][0]['id']

        # Start it in the Spotify app on this Mac via AppleScript. The Web API's start_playback is silently
        # ignored by the Mac app (it stops the current song and never loads the new one).
        osascript(f'tell application "Spotify" to play track "{song_uid}"', timeout=10)  # launches Spotify if needed, so allow for a cold start

        # Confirm it's actually playing before reporting success (or queueing, which needs an active device).
        # Asks the app itself rather than the Web API, whose playback state lags by about a second.
        started = False
        for _ in range(6):
            time.sleep(0.5)
            try:
                now_id, state, now_name = osascript('tell application "Spotify" to (id of current track) & "|" & (player state as string) & "|" & (name of current track)').split("|", 2)
            except (RuntimeError, ValueError):
                continue  # app still starting up
            if state == "playing" and (now_id == song_uid or now_name == track['name']):  # name fallback: Spotify can relink a track to a different id
                started = True
                break
        if not started:
            return {"status": "error", "message": f"Spotify didn't start playing '{track['name']}'."}

        # SPOTIFY.clear_queue()  # TODO no way to clear queue,

        # queue up to 20 songs from the same artist, excluding the currently playing track, shuffled in random order
        # albums = SPOTIFY.artist_albums(artist_id, album_type='album', limit=5)
        # queue_uris = []
        # for album in albums['items']:
        #     for t in SPOTIFY.album_tracks(album['id'])['items']:
        #         if t['uri'] != track['uri']:
        #             queue_uris.append(t['uri'])

        # random.shuffle(queue_uris)
        # for uri in queue_uris[:5]:
        #     SPOTIFY.add_to_queue(uri)

        return {"status": "success", "message": f"Playing '{track['name']}' by '{track['artists'][0]['name']}'."}

    except Exception as e:
        return {"status": "error", "message": f"An error occurred: {str(e)}"}




def pause_song() -> dict:
    """Pause the currently playing song on Spotify. Checks if a song is currently playing before attempting to pause.
    If no song is playing, it will return a message indicating that there is nothing to pause."""

    try:
        playback = SPOTIFY.current_playback()
        if playback and playback['is_playing']:
            SPOTIFY.pause_playback(device_id=_spotify_device())
            return {
                "status": "success",
                "message": f"Paused the song {playback['item']['name']} by {playback['item']['artists'][0]['name']} on Spotify."
            }
        else:
            return {
                "status": "error",
                "message": "No song is currently playing on Spotify to pause."
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to pause song: {str(e)}"
        }




def resume_song() -> dict:
    """Resume the currently paused song on Spotify. Checks if a song is currently paused before attempting to resume. 
    If no song is paused, it will return a message indicating that there is nothing to resume."""
    try:
        SPOTIFY.start_playback(device_id=_spotify_device())
        playback = SPOTIFY.current_playback()
        return {
            "status": "success",
            "message": f"Resumed. Playing {playback['item']['name']} by {playback['item']['artists'][0]['name']}."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to resume song: {str(e)}"
        }
    



def skip_song() -> dict:
    """Skip to the next song on Spotify"""

    try:
        playback = SPOTIFY.current_playback()
        if playback and playback['is_playing']:
            SPOTIFY.next_track(device_id=_spotify_device())
            return {
                "status": "success",
                "message": "Skipped to the next song on Spotify."
            }
        else:
            return {
                "status": "error",
                "message": "No song is currently playing on Spotify to skip."
            }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to skip song: {str(e)}"
        }  


def previous_song() -> dict:
    """Skip to the previous song on Spotify"""

    try:
        playback = SPOTIFY.current_playback()
        if playback and playback['is_playing']:
            SPOTIFY.previous_track(device_id=_spotify_device())
            return {
                "status": "success",
                "message": "Went back to the previous song on Spotify."
            }
        else:
            return {
                "status": "error",
                "message": "No song is currently playing on Spotify to go back from."
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to go back to the previous song: {str(e)}"
        }



TOOLS = [search_song, play_song, pause_song, resume_song, skip_song, previous_song]