def validate_api_secret(secret: str):
    # دالة مستقلة للتحقق من شروط كلمة السر (api_secret)
    return len(secret) >= 12
