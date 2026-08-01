import pyotp


def generate_otp(secret: str) -> str:
    return pyotp.TOTP(secret.strip()).now()
