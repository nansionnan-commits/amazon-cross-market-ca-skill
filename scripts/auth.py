# -*- coding: utf-8 -*-
"""SP-API 认证与请求封装（张奥迪 NA 店）。

- 凭证动态读取自老板文件，不复制 secret 到工作区。
- LWA access_token 带缓存（提前 60s 过期）。
"""
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

CRED_FILE = r"D:\广告上传表格\sp-api-workbuddy奥迪.txt"
TOKEN_INDEX = 1          # 张奥迪 NA 店 = 文件里第 2 个 refresh_token
SELLER_ID = "A1ON6BNVRPOF3T"
NA_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"

# marketplace
US = "ATVPDKIKX0DER"
CA = "A2EUQ1WTGCTBG2"
MX = "A1AM78C64UM0Y8"
BR = "A2Q3Y263D00KWC"

_ctx = ssl._create_unverified_context()
_cache = {"token": None, "expire_at": 0.0}


def _parse_creds():
    with open(CRED_FILE, encoding="utf-8") as f:
        text = f.read()
    cid = re.search(r"client_id\s*-\s*(\S+)", text).group(1)
    cs = re.search(r"client_secret\s*-\s*(\S+)", text).group(1)
    tokens = re.findall(r"Atzr\|[^\s]+", text)
    return cid, cs, tokens


def get_access_token():
    if _cache["token"] and time.time() < _cache["expire_at"]:
        return _cache["token"]
    cid, cs, tokens = _parse_creds()
    rt = tokens[TOKEN_INDEX]
    url = "https://api.amazon.com/auth/o2/token"
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": cid,
        "client_secret": cs,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
        tok = json.loads(r.read().decode())
    _cache["token"] = tok["access_token"]
    _cache["expire_at"] = time.time() + tok.get("expires_in", 3600) - 60
    return _cache["token"]


def request(method, path_qs, body=None):
    """发起 SP-API 请求，返回 (status, json)。"""
    at = get_access_token()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{NA_ENDPOINT}{path_qs}", data=data, method=method)
    req.add_header("x-amz-access-token", at)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, context=_ctx, timeout=60) as r:
        return r.status, json.loads(r.read().decode())
