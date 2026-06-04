
import random
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
SCOPE = "user-modify-playback-state user-read-playback-state"

SPOTIFY = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE
    )
)



def play_song(song_name: str, artist_name: str):
    """Play a song on Spotify and queue shuffled songs from the artist after.
    Args:
      song_name: The name of the song to play
      artist_name: The name of the artist of the song
    """
    try:
        results = SPOTIFY.search(q=f" {song_name} {artist_name}", type="track", limit=1)
        if not results['tracks']['items']:
            return {"status": "error", "message": f"Could not find '{song_name}' by '{artist_name}' on Spotify."}

        track = results['tracks']['items'][0]
        artist_id = track['artists'][0]['id']
        SPOTIFY.start_playback(uris=[track['uri']])

        # SPOTIFY.clear_queue()  # TODO no way to clear queue, 

        # queue up to 20 songs from the same artist, excluding the currently playing track, shuffled in random order
        albums = SPOTIFY.artist_albums(artist_id, album_type='album', limit=5)
        queue_uris = []
        for album in albums['items']:
            for t in SPOTIFY.album_tracks(album['id'])['items']:
                if t['uri'] != track['uri']:
                    queue_uris.append(t['uri'])

        random.shuffle(queue_uris)
        for uri in queue_uris[:20]:
            SPOTIFY.add_to_queue(uri)

        return {"status": "success", "message": f"Playing '{track['name']}' by '{track['artists'][0]['name']}'."}

    except Exception as e:
        return {"status": "error", "message": f"An error occurred: {str(e)}"}




def pause_song() -> None:
    """Pause the currently playing song on Spotify. Checks if a song is currently playing before attempting to pause.
    If no song is playing, it will return a message indicating that there is nothing to pause."""

    try:
        playback = SPOTIFY.current_playback()
        if playback and playback['is_playing']:
            SPOTIFY.pause_playback()
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




def resume_song() -> None:
    """Resume the currently paused song on Spotify. Checks if a song is currently paused before attempting to resume. 
    If no song is paused, it will return a message indicating that there is nothing to resume."""
    try:
        playback = SPOTIFY.current_playback()
        if playback and not playback['is_playing']:
            SPOTIFY.start_playback()
            return {
                "status": "success",
                "message": f"Resumed. Playing {playback['item']['name']} by {playback['item']['artists'][0]['name']}."
            }
        else:
            return {
                "status": "error",
                "message": "No song is currently paused on Spotify to resume."
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to resume song: {str(e)}"
        }
    



def skip_song() -> None:
    """Skip to the next song on Spotify"""

    try:
        playback = SPOTIFY.current_playback()
        if playback and playback['is_playing']:
            SPOTIFY.next_track()
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


# TODO
def previous_song() -> None:
    """Skip to the previous song on Spotify"""
    SPOTIFY.previous_track()



TOOLS = [play_song, pause_song, resume_song, skip_song, previous_song]