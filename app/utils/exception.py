from fastapi import Request, HTTPException

class RedirectToHomeException(HTTPException):
    def __init__(self):
        super().__init__(status_code=307, detail="Redirecting to /")


def verify_global_password_cookie(request: Request):
    if request.cookies.get("pending_global_password") == "1":
        raise RedirectToHomeException()