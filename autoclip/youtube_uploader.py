import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError


YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

CREDENTIALS_DIR = Path(__file__).resolve().parent.parent / "credentials"
CLIENT_SECRETS_FILE = CREDENTIALS_DIR / "client_secret.json"
TOKEN_FILE = CREDENTIALS_DIR / "youtube_token.json"


class YouTubeUploader:
    """
    Handles YouTube OAuth 2.0 authentication and automated YouTube Shorts publishing.
    """

    def __init__(self):
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        self.credentials: Optional[Credentials] = self._load_credentials()

    def _load_credentials(self) -> Optional[Credentials]:
        """Loads and refreshes OAuth credentials from token file if valid."""
        if not TOKEN_FILE.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), YOUTUBE_SCOPES)
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                except google.auth.exceptions.RefreshError:
                    print("[YouTube] Refresh token expired or revoked.")
                    return None
            return creds if creds and creds.valid else None
        except Exception as e:
            print(f"[YouTube] Error reading token file: {e}")
            return None

    def is_authenticated(self) -> bool:
        """Returns True if valid authenticated credentials are available."""
        self.credentials = self._load_credentials()
        return self.credentials is not None and self.credentials.valid

    def has_client_secret(self) -> bool:
        """Returns True if client_secret.json is configured."""
        return CLIENT_SECRETS_FILE.exists() and CLIENT_SECRETS_FILE.stat().st_size > 0

    def get_channel_info(self) -> Optional[Dict[str, Any]]:
        """Retrieves profile information for the connected YouTube channel."""
        if not self.is_authenticated():
            return None

        try:
            youtube = build("youtube", "v3", credentials=self.credentials)
            res = youtube.channels().list(mine=True, part="snippet,statistics").execute()
            items = res.get("items", [])
            if not items:
                return None

            item = items[0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})

            return {
                "channel_id": item.get("id"),
                "title": snippet.get("title", "My YouTube Channel"),
                "custom_url": snippet.get("customUrl", ""),
                "description": snippet.get("description", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "subscribers": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "connected": True
            }
        except Exception as e:
            print(f"[YouTube] Failed to fetch channel info: {e}")
            return None

    def start_oauth_flow(self, port: int = 8080) -> Dict[str, Any]:
        """
        Launches Google OAuth 2.0 flow in the default browser to connect the user's YouTube account.
        """
        if not self.has_client_secret():
            raise FileNotFoundError(
                f"Missing credentials/client_secret.json. Please download it from Google Cloud Console."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE),
            scopes=YOUTUBE_SCOPES
        )

        try:
            creds = flow.run_local_server(
                port=port,
                prompt="consent",
                access_type="offline"
            )
        except OSError:
            # Fallback to random free port if port is already taken
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                access_type="offline"
            )

        with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

        self.credentials = creds
        channel_info = self.get_channel_info()
        return {
            "status": "success",
            "message": "YouTube channel connected successfully!",
            "channel": channel_info
        }

    def disconnect(self) -> bool:
        """Removes saved token and disconnects YouTube account."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        self.credentials = None
        return True

    def upload_short(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "22",
        privacy_status: str = "public"
    ) -> Dict[str, Any]:
        """
        Uploads a vertical short video to the user's authenticated YouTube channel.
        - Appends #Shorts to title and description.
        - Sets appropriate vertical metadata for YouTube Shorts shelf.
        """
        if not self.is_authenticated():
            raise PermissionError("YouTube account is not connected. Please connect your channel first.")

        if not video_path.exists():
            raise FileNotFoundError(f"Video file to upload does not exist: {video_path}")

        # Ensure #Shorts is present in title for proper algorithm categorization
        formatted_title = title.strip()
        if "#shorts" not in formatted_title.lower():
            if len(formatted_title) > 90:
                formatted_title = formatted_title[:90].strip() + " #Shorts"
            else:
                formatted_title = f"{formatted_title} #Shorts"

        tag_list = list(tags) if tags else []
        if "Shorts" not in tag_list:
            tag_list.append("Shorts")
        if "YouTubeShorts" not in tag_list:
            tag_list.append("YouTubeShorts")

        body = {
            "snippet": {
                "title": formatted_title[:100],
                "description": description[:5000],
                "tags": tag_list,
                "categoryId": category_id,
                "defaultLanguage": "en"
            },
            "status": {
                "privacyStatus": privacy_status.lower(),  # "public", "unlisted", "private"
                "selfDeclaredMadeForKids": False,
                "embeddable": True
            }
        }

        youtube = build("youtube", "v3", credentials=self.credentials)
        media = MediaFileUpload(
            str(video_path),
            chunksize=2 * 1024 * 1024,
            resumable=True,
            mimetype="video/mp4"
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        print(f"[YouTube] Starting upload: '{formatted_title}' ({privacy_status})...")

        response = None
        retry_count = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    print(f"[YouTube] Uploading: {progress}%...")
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    retry_count += 1
                    if retry_count > 5:
                        raise e
                    time.sleep(2 ** retry_count)
                else:
                    err_str = str(e)
                    if "uploadLimitExceeded" in err_str:
                        raise RuntimeError(
                            "YouTube Daily Upload Limit Reached: Your channel has reached YouTube's daily upload limit "
                            "(typically 5–10 uploads per 24 hours for standard/new channels). "
                            "To unlock higher daily limits (50–100+ videos/day), go to YouTube Studio > Settings > Channel > "
                            "Feature Eligibility and enable 'Advanced Features' (via video verification or phone/ID). "
                            "Otherwise, the limit resets automatically after 24 hours."
                        ) from e
                    elif "quotaExceeded" in err_str:
                        raise RuntimeError(
                            "YouTube API Quota Reached: The daily 10,000 units project quota for YouTube Data API v3 has been reached. "
                            "This quota resets automatically at midnight Pacific Time (PT)."
                        ) from e
                    raise e

        video_id = response.get("id")
        short_url = f"https://youtube.com/shorts/{video_id}"
        watch_url = f"https://www.youtube.com/watch?v={video_id}"

        print(f"[YouTube] ✅ Upload complete! Live Short: {short_url}")

        ch_info = self.get_channel_info() or {}
        return {
            "status": "success",
            "video_id": video_id,
            "short_url": short_url,
            "watch_url": watch_url,
            "title": formatted_title,
            "privacy_status": privacy_status,
            "channel_title": ch_info.get("title", "My Channel"),
            "channel_handle": ch_info.get("custom_url", ""),
            "published_at": response.get("snippet", {}).get("publishedAt", "")
        }


if __name__ == "__main__":
    uploader = YouTubeUploader()
    if uploader.is_authenticated():
        info = uploader.get_channel_info()
        print(f"✅ Already connected to: {info.get('title')} ({info.get('subscribers')} subs)")
    else:
        print("🚀 Launching Google OAuth consent in your browser...")
        res = uploader.start_oauth_flow()
        print("Result:", res)
