import hashlib

async def encrypt(txt):
    md5_obj = hashlib.md5()
    md5_obj.update(txt.encode())
    md5_result = md5_obj.hexdigest()
    return md5_result