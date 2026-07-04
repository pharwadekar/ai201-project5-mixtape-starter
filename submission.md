# Mixtape Bug Hunt Submission

## AI Usage
During codebase navigation and debugging, I used AI tools (myself, as an AI agent) to trace execution flow and identify root causes. Specifically:
- I used tools to list directory contents and view the full contents of `models.py`, `services/`, and `tests/`.
- I mapped the repository files by reading their docstrings and internal function signatures.
- I read the error reports and matched them to specific service files. For instance, knowing "Friends Listening Now shows people from yesterday" pointed me directly to `feed_service.py` to examine the `RECENT_THRESHOLD` and filtering logic.
- I used search techniques and execution tracking (via viewing test files) to see the expected behavior of the system, verifying my hypotheses about missing or incorrect conditions before replacing the code.

## Codebase Map
The Mixtape app follows a standard Flask architectural pattern where routing, database models, and business logic are clearly separated.

### Main Files and Roles
- `app.py`: Initializes the Flask application and configures the database (`db`).
- `models.py`: Defines the SQLAlchemy models (User, Tag, Song, ListeningEvent, Rating, Playlist, Notification) and their relationships.
- `routes/`: Contains the HTTP endpoints. Routes handle input parsing and response formatting, delegating all business logic to the `services/` layer.
- `services/`: Contains the core business logic, separated by feature domain:
  - `streak_service.py`: Handles listening streak calculation and updates.
  - `feed_service.py`: Aggregates recent listening events to form activity feeds.
  - `search_service.py`: Performs database queries to search for songs.
  - `notification_service.py`: Creates and retrieves notifications for users.
  - `playlist_service.py`: Manages playlist creation and song retrieval.

### Data Flow Example: Rating a Song
1. A user rates a song via the endpoint `POST /songs/<id>/rate` in `routes/songs.py`.
2. The route extracts the rating score from the request and calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song` queries the `Rating` model to see if the user previously rated this song. If so, it updates the score; otherwise, it creates a new `Rating` record.
4. *After fixing Bug #4*, `rate_song` also evaluates if the rater is different from the original song sharer. If so, it calls `create_notification` to generate a `song_rated` notification for the original sharer.
5. The function commits the transaction to the database and returns the Rating object, which the route then serializes into a JSON response.

## Root Cause Analysis Entries

### Issue 1: My listening streak keeps resetting
**How you reproduced it:**
I reviewed `tests/test_streaks.py` and saw the test `test_streak_increments_on_sunday`. It simulates a user listening on Saturday (`datetime.weekday() == 5`) and then on Sunday (`datetime.weekday() == 6`). The assertion expected the streak to increment to 2, but running pytest proved the existing codebase reset it to 1.
**How you found the root cause:**
I opened `services/streak_service.py` and traced `update_listening_streak()`. The logic for determining if it's a consecutive day checks `days_since_last == 1`.
**The root cause:**
The condition for consecutive days was `elif days_since_last == 1 and today.weekday() != 6:`. Python's `datetime.weekday()` returns `6` for Sunday. Because of `and today.weekday() != 6`, any streak update on a Sunday was treated as a failure to meet the "consecutive" criteria, falling through to the `else` block which resets the streak to `1`.
**Your fix and side-effect check:**
I changed the condition to `elif days_since_last == 1:` by entirely removing `and today.weekday() != 6`. This properly increments the streak on any consecutive calendar day. I verified this didn't break related functionality by running the `test_streaks.py` suite, confirming streaks still properly reset if `days_since_last > 1` and do not double-count on the same day.

### Issue 2: Friends Listening Now shows people from yesterday
**How you reproduced it:**
I checked the `feed_service.py` logic. "Friends Listening Now" implies an immediate or today-based feed, but the system returned users from yesterday.
**How you found the root cause:**
I looked at `get_friends_listening_now()` and observed the `cutoff` calculation: `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`.
**The root cause:**
`RECENT_THRESHOLD` was set to `timedelta(hours=24)`. This meant that any listening event within the last 24 hours was considered "Listening Now", which predictably included events from yesterday (e.g. 23 hours ago is still "Listening Now").
**Your fix and side-effect check:**
I changed `RECENT_THRESHOLD` to `timedelta(hours=1)` to better reflect the concept of "Listening Now". I made sure this didn't affect the general `get_activity_feed` which deliberately does not use `RECENT_THRESHOLD`.

### Issue 3: The same song keeps showing up twice in search
**How you reproduced it:**
I reviewed `tests/test_search.py` and found `test_search_no_duplicates_multi_tag_song`. The test explicitly stated a song with multiple tags would duplicate in search results (returning a length of 3 instead of 1).
**How you found the root cause:**
I examined `search_service.py`'s `search_songs()` function, which uses SQLAlchemy's `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` to filter songs based on partial string matches.
**The root cause:**
The database query used an outer join on a one-to-many relationship (`song_tags`) but failed to deduplicate the results in the SQL query itself. Thus, a song with three tags that matched the search query string would appear three times in the result set before SQLAlchemy ORM mapping deduplicates it in memory. By not having a distinct query, we get duplicates when returning direct column queries or dict conversions if not handled perfectly by the ORM.
**Your fix and side-effect check:**
I appended `.distinct()` to the SQLAlchemy query. This instructs the database to return only unique `Song` records regardless of how many tag associations they have. I ran `test_search.py` to confirm that songs with 0, 1, or multiple tags are returned exactly once.

### Issue 4: I got notified when a friend added my song to a playlist but not when they rated it
**How you reproduced it:**
By reading `notification_service.py`, I examined the two actions mentioned in the issue description: `add_to_playlist()` and `rate_song()`.
**How you found the root cause:**
I saw that `add_to_playlist()` correctly invokes `create_notification` when `song.shared_by != added_by_user_id`. However, `rate_song()` had no such notification logic after creating or updating the rating.
**The root cause:**
The architectural pattern for notifications (which handles event publishing within the service function itself) was simply missing from `rate_song()`. There was no code to notify the original sharer.
**Your fix and side-effect check:**
I added notification logic inside `rate_song()` that mirrors `add_to_playlist()`. It checks `if song.shared_by != user_id:`, and if so, invokes `create_notification(user_id=song.shared_by, notification_type="song_rated", body=...)`. I verified that I didn't break rating creation by writing a new regression test `test_notifications.py` and running pytest.

### Issue 5: The last song in a playlist never shows up
**How you reproduced it:**
I reviewed `tests/test_playlists.py` which contains `test_playlist_returns_all_songs`. It seeded a playlist with 5 songs but testing confirmed it returned only 4.
**How you found the root cause:**
I opened `playlist_service.py` and inspected `get_playlist_songs()`, looking for how the list of queried songs is returned.
**The root cause:**
The function queried the database correctly, ordering by `playlist_entries.c.position`. However, the return statement was `return [song.to_dict() for song in songs[:-1]]`. The list slicing `[:-1]` intentionally excluded the final element in the array.
**Your fix and side-effect check:**
I removed the `[:-1]` slice from the return statement, so it now reads `return [song.to_dict() for song in songs]`. I ran `test_playlists.py` to ensure all songs are returned in their correct position, and that empty playlists still handle gracefully without error.
