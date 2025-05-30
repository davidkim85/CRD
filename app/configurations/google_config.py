from urllib.parse import urlencode
import httpx
from app.configurations.config import GOOGLE_CLIENT_ID, GOOGLE_REDIRECT_URI, GOOGLE_CLIENT_SECRET


def get_google_login_url():
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def get_google_user_info(code: str):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        user_resp = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                     headers={"Authorization": f"Bearer {access_token}"})
        return user_resp.json()
