
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
SCOPE = "user-modify-playback-state user-read-playback-state"

def main():
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
        )
    )



    song_name = "SWORD"
    artist_name = "WISP"


    print(f"Searching for '{song_name}' by '{artist_name}'...")
    results = sp.search(q=f"{song_name} {artist_name}", type="track", limit=1)

    if results['tracks']['items']:
        track = results['tracks']['items'][0]
        track_uri = track['uri']
        
        print(f"Found: {track['name']} by {track['artists'][0]['name']}")
        print(f"Playing now.")
        
        sp.start_playback(uris=[track_uri])
    else:
        print("Song not found")

if __name__ == "__main__":
    main()
