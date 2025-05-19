import hashlib

async def encrypt(txt):
    md5_obj = hashlib.md5()
    md5_obj.update(txt.encode())
    md5_result = md5_obj.hexdigest()
    return md5_result

async def sha256(txt):
    sha256_obj = hashlib.sha256()
    sha256_obj.update(txt.encode())
    sha256_result = sha256_obj.hexdigest()
    return sha256_result