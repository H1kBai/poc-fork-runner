# -*- coding: utf-8 -*-
"""GitHub Actions 版 fork 执行器。
断点=账号现有 fork 的上游; 90s/个; 403递增冷却; 300分钟让位给下个调度。"""
import json, os, sys, time, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")

TOK = os.environ["GH_TOKEN"]
ME = "H1kBai"
BUDGET = 300 * 60

def api(path, method="GET", data=None):
    req = urllib.request.Request("https://api.github.com" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + TOK, "User-Agent": "fork-runner",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        b = r.read()
        return r.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b)
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"message": type(e).__name__}

def to_private(full):
    for _ in range(6):
        st, _b = api("/repos/" + full, "PATCH", {"private": True})
        if st == 200:
            return True
        if st == 404:
            time.sleep(10)
            continue
        time.sleep(5)
    return False

repos = [l.strip() for l in open("repos.txt") if l.strip()]
done = set()
page = 1
while page <= 10:
    st, lst = api("/user/repos?per_page=100&page=%d&type=owner" % page)
    if st != 200 or not lst:
        break
    for r in lst:
        if r.get("fork") and r.get("parent"):
            done.add(r["parent"]["full_name"].lower())
    page += 1
pending = [r for r in repos if r.lower() not in done]
print("总 %d | 断点 %d | 本次待处理 %d" % (len(repos), len(done), len(pending)), flush=True)
if not pending:
    print("DONE-ALL", flush=True)
    sys.exit(0)

n_ok = n_gone = n_bad = 0
t0 = time.time()
cool = 300
for i, repo in enumerate(pending, 1):
    if time.time() - t0 > BUDGET:
        print("TIME-UP 成功%d 剩余约%d 下个调度续跑" % (n_ok, len(pending) - i + 1), flush=True)
        sys.exit(0)
    st, body = api("/repos/%s/forks" % repo, "POST", {"default_branch_only": True})
    while st == 403 and "empty" not in str(body.get("message", "")).lower():
        print("  RATE 冷却%ds: %s" % (cool, repo), flush=True)
        time.sleep(cool)
        cool = min(cool + 300, 3600)
        st, body = api("/repos/%s/forks" % repo, "POST", {"default_branch_only": True})
    if st in (200, 202):
        full = body.get("full_name", ME + "/" + repo.split("/", 1)[1])
        priv = to_private(full)
        n_ok += 1
        cool = max(300, cool - 300)
        print("OK %d/%d %s -> %s %s" % (i, len(pending), repo, full,
              "[私]" if priv else "[转私失败!]"), flush=True)
    elif st == 404:
        n_gone += 1
        print("404 %s 失联" % repo, flush=True)
    elif st == 422:
        to_private(ME + "/" + repo.split("/", 1)[1])
        n_ok += 1
        print("422 %s 已存在转私" % repo, flush=True)
    elif st == 403:
        n_bad += 1
        print("EMPTY %s 空仓库" % repo, flush=True)
    else:
        n_bad += 1
        print("ERR %s -> %s %s" % (repo, st, str(body.get("message", ""))[:60]), flush=True)
    time.sleep(90)

left = len(pending) - n_ok - n_gone - n_bad
print("DONE 本次成功%d 失联%d 其他失败%d 剩余%d" % (n_ok, n_gone, n_bad, left), flush=True)
if left == 0:
    print("DONE-ALL", flush=True)
