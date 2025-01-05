import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
from collections import defaultdict
import time
import json

VERSION = "0.1"

# Error handling decorator
def retry_on_error(max_retries=3, delay=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        st.error(f"Failed after {max_retries} attempts: {str(e)}")
                        raise e
                    st.warning(f"Attempt {attempt + 1} failed, retrying...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

class PlaylistCustomization:
    def __init__(self):
        self.name_template = "My {} Collection"
        self.public = True
        self.description_template = "Auto-generated {} playlist"
        
    def show_options(self):
        with st.sidebar:
            st.markdown("---")  # Separator
            with st.expander("⚙️ Playlist Settings"):
                st.markdown("### Configuration")
                self.name_template = st.text_input(
                    "Playlist Name Template", 
                    self.name_template,
                    help="Use {} where you want the category name to appear"
                )
                self.public = st.checkbox(
                    "Make Playlists Public", 
                    self.public,
                    help="Public playlists can be seen by anyone"
                )
                self.description_template = st.text_area(
                    "Description Template", 
                    self.description_template,
                    help="Use {} where you want the category name to appear"
                )
            st.markdown("---")  # Separator

class GenreManager:
    def __init__(self):
        self.default_categories = {
            'Rock': ['rock', 'metal', 'punk', 'grunge', 'alternative'],
            'EDM': ['electronic', 'edm', 'house', 'techno', 'dance'],
            'Hip Hop': ['hip hop', 'rap', 'trap'],
            'Pop': ['pop', 'dance pop'],
            'Jazz': ['jazz', 'swing'],
            'Classical': ['classical', 'orchestra'],
            'R&B': ['r&b', 'soul', 'funk']
        }
        
    def show_category_editor(self):
        with st.sidebar:
            with st.expander("🎵 Genre Categories"):
                st.markdown("### Category Editor")
                if st.button("Edit Genre Rules"):
                    categories_json = st.text_area(
                        "Edit Categories (JSON)", 
                        json.dumps(self.default_categories, indent=2),
                        height=300,
                        help="Edit the genre mapping rules in JSON format"
                    )
                    try:
                        self.default_categories = json.loads(categories_json)
                        st.success("Categories updated successfully!")
                    except json.JSONDecodeError:
                        st.error("Invalid JSON format")

@retry_on_error(max_retries=3)
def get_spotify_client():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=st.secrets["spotify"]["client_id"],
        client_secret=st.secrets["spotify"]["client_secret"],
        redirect_uri=st.secrets["spotify"]["redirect_uri"],
        scope="user-library-read playlist-modify-public"
    ))

@retry_on_error(max_retries=3)
def get_liked_songs(sp):
    results = []
    offset = 0
    while True:
        items = sp.current_user_saved_tracks(limit=50, offset=offset)['items']
        if not items:
            break
        results.extend(items)
        offset += 50
    return results

@retry_on_error(max_retries=3)
def get_track_genres(sp, track):
    artists = track['track']['artists']
    genres = []
    for artist in artists:
        artist_info = sp.artist(artist['id'])
        genres.extend(artist_info['genres'])
    return list(set(genres))

def show_song_preview(sp, track_id):
    try:
        track_info = sp.track(track_id)
        preview_url = track_info['preview_url']
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"🎵 {track_info['name']} - {track_info['artists'][0]['name']}")
        with col2:
            if preview_url:
                st.audio(preview_url)
            else:
                st.write("No preview available")
    except Exception as e:
        st.error(f"Error loading preview: {str(e)}")

@retry_on_error(max_retries=3)
def analyze_library(sp):
    with st.spinner('Fetching your liked songs...'):
        liked_songs = get_liked_songs(sp)
    
    songs_data = []
    progress_bar = st.progress(0)
    
    for i, item in enumerate(liked_songs):
        track = item['track']
        genres = get_track_genres(sp, item)
        
        songs_data.append({
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'genres': genres,
            'id': track['id'],
            'added_at': item['added_at']
        })
        
        # Update progress
        progress_bar.progress((i + 1) / len(liked_songs))
    
    progress_bar.empty()
    return pd.DataFrame(songs_data)

def check_duplicates(songs_data):
    duplicates = defaultdict(list)
    for song in songs_data:
        key = (song['name'].lower(), song['artist'].lower())
        duplicates[key].append(song)
    
    real_duplicates = {k: v for k, v in duplicates.items() if len(v) > 1}
    return real_duplicates

@retry_on_error(max_retries=3)
def remove_duplicates(sp, duplicates):
    for duplicate_group in duplicates.values():
        if len(duplicate_group) > 1:
            # Keep the oldest (first added) track
            duplicate_group.sort(key=lambda x: x['added_at'])
            # Remove the rest
            for song in duplicate_group[1:]:
                sp.current_user_saved_tracks_delete([song['id']])
                st.write(f"Removed duplicate: {song['name']} by {song['artist']}")

@retry_on_error(max_retries=3)
def create_playlist(sp, name, description="", public=True):
    user_id = sp.current_user()['id']
    playlist = sp.user_playlist_create(user_id, name, public=public, description=description)
    return playlist['id']

@retry_on_error(max_retries=3)
def add_songs_to_playlist(sp, playlist_id, song_ids):
    for i in range(0, len(song_ids), 100):
        chunk = song_ids[i:i + 100]
        sp.playlist_add_items(playlist_id, chunk)

def suggest_categorization(df, genre_categories):
    def categorize_song(genres):
        for category, keywords in genre_categories.items():
            if any(any(keyword in genre.lower() for keyword in keywords) for genre in genres):
                return category
        return 'Other'
    
    df['category'] = df['genres'].apply(categorize_song)
    return df

def show_category_songs(sp, categorized_df, category):
    st.write(f"### Songs in {category}")
    category_songs = categorized_df[categorized_df['category'] == category]
    
    for _, song in category_songs.iterrows():
        with st.expander(f"{song['name']} - {song['artist']}"):
            show_song_preview(sp, song['id'])
            new_category = st.selectbox(
                "Reassign category",
                options=sorted(categorized_df['category'].unique()),
                key=f"category_{song['id']}",
                index=sorted(list(categorized_df['category'].unique())).index(category)
            )
            if new_category != category:
                categorized_df.loc[categorized_df['id'] == song['id'], 'category'] = new_category
                st.success("Category updated!")
                time.sleep(1)  # Give user time to see the success message
                st.rerun()

@retry_on_error(max_retries=3)
def get_existing_playlists(sp, name_template):
    user_playlists = sp.current_user_playlists()
    script_playlists = {}
    template_start = name_template.split("{}")[0]
    template_end = name_template.split("{}")[1]
    
    for playlist in user_playlists['items']:
        if playlist['name'].startswith(template_start) and playlist['name'].endswith(template_end):
            category = playlist['name'].replace(template_start, "").replace(template_end, "")
            script_playlists[category] = playlist['id']
    return script_playlists

def main():
    st.set_page_config(
        page_title="Spotify Library Organizer",
        page_icon="🎵",
        initial_sidebar_state="collapsed",
        menu_items={
            'About': "A tool to organize your Spotify Liked Songs into genre-based playlists."
        }
    )

    # Custom CSS for Spotify branding
    st.markdown("""
        <style>
            /* Decoration/header gradient - Spotify colors */
            [data-testid="stDecoration"] {
                background-image: linear-gradient(90deg, #1DB954, #135831);
            }
            
            /* Progress bar - Spotify green */
            .stProgress > div > div > div > div {
                background-color: #1DB954;
            }
            
            /* Progress bar background */
            .stProgress > div > div > div {
                background-color: #282828;
            }
            
            /* Footer styling */
            .footer {
                position: fixed;
                bottom: 0;
                left: 0;
                width: 100%;
                background-color: #282828;
                padding: 10px;
                text-align: center;
                font-size: 12px;
                color: #B3B3B3;
            }
            
            /* Version number styling */
            .version {
                font-size: 10px;
                color: #B3B3B3;
            }
            /* Sidebar styling */
            [data-testid="stSidebar"] {
                background-color: #121212;
                width: 21rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # Initialize components
    playlist_customization = PlaylistCustomization()
    genre_manager = GenreManager()

    # Show customization options in sidebar
    playlist_customization.show_options()
    genre_manager.show_category_editor()

    # About section
    with st.sidebar.expander("ℹ️ About"):
            st.markdown("""
                ### Spotify Library Organizer
                
                This tool helps you organize your Spotify Liked Songs into genre-based playlists.
                
                **Features:**
                - Detect and remove duplicates
                - Automatic genre categorization
                - Customizable playlist settings
                - Manual category adjustments
                
                **Version:** {}
            """.format(VERSION))

    st.title("🎵 Spotify Library Organizer")
    st.write("Organize your Liked Songs into genre-based playlists!")

    # Initialize session state
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'sp' not in st.session_state:
        st.session_state.sp = None
    if 'step' not in st.session_state:
        st.session_state.step = 'start'
    if 'df' not in st.session_state:
        st.session_state.df = None

    # Authentication
    if not st.session_state.authenticated:
        st.write("Please authenticate with Spotify to continue.")
        if st.button("Connect to Spotify"):
            try:
                st.session_state.sp = get_spotify_client()
                st.session_state.authenticated = True
                st.rerun()
            except Exception as e:
                st.error(f"Authentication failed: {str(e)}")
                st.info("Please check your credentials in .streamlit/secrets.toml")
    else:
        sp = st.session_state.sp

        if st.session_state.step == 'start':
            if st.button("Analyze Library"):
                with st.spinner('Analyzing your library...'):
                    st.session_state.df = analyze_library(sp)
                    st.session_state.step = 'check_duplicates'
                st.rerun()

        elif st.session_state.step == 'check_duplicates':
            duplicates = check_duplicates(st.session_state.df.to_dict('records'))
            
            if duplicates:
                st.warning("Duplicates found!")
                for key, songs in duplicates.items():
                    st.write(f"\n'{key[0]}' by {key[1]}:")
                    for song in songs:
                        st.write(f"- Added on: {song['added_at']}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Remove Duplicates"):
                        with st.spinner('Removing duplicates...'):
                            remove_duplicates(sp, duplicates)
                            st.session_state.df = analyze_library(sp)
                        st.success("Duplicates removed!")
                with col2:
                    if st.button("Skip Duplicate Removal"):
                        st.session_state.step = 'categorize'
                        st.rerun()
            else:
                st.success("No duplicates found!")
                st.session_state.step = 'categorize'
                st.rerun()

        elif st.session_state.step == 'categorize':
            categorized_df = suggest_categorization(st.session_state.df, genre_manager.default_categories)
            existing_playlists = get_existing_playlists(sp, playlist_customization.name_template)

            st.write("### Song Categories")
            for category in sorted(categorized_df['category'].unique()):
                count = len(categorized_df[categorized_df['category'] == category])
                status = "📌 Existing playlist" if category in existing_playlists else "🆕 No playlist yet"
                st.write(f"{category}: {count} tracks {status}")
                
                if st.button(f"View {category} songs", key=f"view_{category}"):
                    show_category_songs(sp, categorized_df, category)

            selected_categories = st.multiselect(
                "Select categories to create/update playlists for:",
                [cat for cat in sorted(categorized_df['category'].unique()) if cat != 'Other']
            )

            if selected_categories and st.button("Create/Update Selected Playlists"):
                with st.spinner('Processing playlists...'):
                    for category in selected_categories:
                        category_songs = categorized_df[categorized_df['category'] == category]
                        song_ids = category_songs['id'].tolist()

                        if category in existing_playlists:
                            playlist_id = existing_playlists[category]
                            results = sp.playlist_tracks(playlist_id)
                            current_tracks = [item['track']['id'] for item in results['items']]
                            new_tracks = [id for id in song_ids if id not in current_tracks]

                            if new_tracks:
                                add_songs_to_playlist(sp, playlist_id, new_tracks)
                                st.success(f"Added {len(new_tracks)} new songs to existing '{category}' playlist!")
                            else:
                                st.info(f"No new songs to add to '{category}' playlist!")
                        else:
                            playlist_name = playlist_customization.name_template.format(category)
                            playlist_description = playlist_customization.description_template.format(category)
                            playlist_id = create_playlist(
                                sp, 
                                playlist_name, 
                                description=playlist_description,
                                public=playlist_customization.public
                            )
                            add_songs_to_playlist(sp, playlist_id, song_ids)
                            st.success(f"Created '{playlist_name}' with {len(song_ids)} songs!")
                    
                    st.session_state.step = 'complete'
                    st.rerun()

        elif st.session_state.step == 'complete':
            st.success("✨ All done! Your playlists have been created/updated.")
            if st.button("Start Over"):
                st.session_state.step = 'start'
                st.session_state.df = None
                st.rerun()
    
    # Footer
    st.markdown("""
        <div class="footer">
            <p>
                <span class="version">v {}</span><br>
                This application is not affiliated with, maintained, authorized, endorsed, or sponsored by Spotify.<br>
                Spotify® is a trademark of Spotify AB.
            </p>
        </div>
    """.format(VERSION), unsafe_allow_html=True)

if __name__ == "__main__":
    main()
