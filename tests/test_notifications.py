"""
tests/test_notifications.py — Mixtape

Tests for notification logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song

@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

def test_rate_song_creates_notification_for_sharer(app):
    """Rating a song should notify the original sharer."""
    with app.app_context():
        # Setup users and song
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Test Song", artist="Test Artist", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        # Rate the song
        rate_song(rater.id, song.id, 5)

        # Check for notification
        notifications = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert "rated your song" in notifications[0].body
