# -*- coding: utf-8 -*-
"""私有镜像补全执行器（替代原 fork 逻辑；由 fork-runner.yml 调用，文件名保持不变）。
对 repos.txt 每个上游: 创建 H1kBai/owner__repo 私有仓 -> bare clone 上游 -> push --mirror。
断点=账号已存在该仓且 size>0; 温和限速; 280分钟让位。绝不调用 fork API。"""
import json, os, subprocess, sys, time, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")

TOK = os.environ["GH_TOKEN"]
ME = "H1kBai"
BUDGET = 280 * 60

def api(path, method="GET", data=None):
    req = urllib.request.Request("https://api.github.com" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + TOK, "User-Agent": "mirror-bot",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        b = r.read()
        return r.status, json.loads(b) if b else {}
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b)
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"message": type(e).__name__}

def repo_info(name):
    st, r = api("/repos/%s/%s" % (ME, name))
    return (st, r) if st == 200 else (st, {})

def mirror_one(owner_repo, name):
    """创建私有仓(若缺) + 推送完整镜像。返回状态串"""
    st, _ = api("/user/repos", "POST", {"name": name, "private": True,
                                        "description": "mirror of " + owner_repo})
    created = (st == 201)
    if st not in (201, 422):
        return "CREATE-FAIL %s" % st
    d = "m_%s" % name.replace("/", "_")
    subprocess.run(["rm", "-rf", d], cwd="/tmp")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_GLOBAL="/tmp/mgitcfg")
    with open("/tmp/mgitcfg", "w") as f:
        f.write("[credential]
	helper =
[user]
	name = %s
	email = %s@users.noreply.github.com
" % (ME, ME))
    c = subprocess.run(["git", "clone", "--bare", "https://github.com/%s.git" % owner_repo, d],
                       cwd="/tmp", capture_output=True, text=True, timeout=900, env=env)
    if c.returncode != 0:
        subprocess.run(["rm", "-rf", d], cwd="/tmp")
        return "CLONE-FAIL[%d] %s" % (c.returncode, c.stderr.strip().replace("
", " | ")[:150])
    p = subprocess.run(["git", "push", "--mirror",
        "https://%s@github.com/%s/%s.git" % (TOK, ME, name)],
        cwd="/tmp/" + d, capture_output=True, text=True, timeout=900, env=env)
    subprocess.run(["rm", "-rf", d], cwd="/tmp")
    if p.returncode != 0:
        return "PUSH-FAIL[%d] %s" % (p.returncode, p.stderr.strip().replace("
", " | ")[:150])
    # 确认转私
    api("/repos/%s/%s" % (ME, name), "PATCH", {"private": True})
    return "OK" + ("(新建)" if created else "(补推)")

repos = [l.strip() for l in open("repos.txt") if l.strip()]
have = {}
page = 1
while page <= 12:
    st, lst = api("/user/repos?per_page=100&page=%d&type=owner" % page)
    if st != 200 or not lst:
        break
    for r in lst:
        have[r["name"].lower()] = r.get("size", 0)
    page += 1

todo, empty, done = [], [], 0
for r in repos:
    key = r.replace("/", "__").lower()
    if key not in have:
        todo.append(r)
    elif have[key] == 0:
        empty.append(r)
    else:
        done += 1
print("总 %d | 已完成 %d | 待创建 %d | 待补推空仓 %d" % (len(repos), done, len(todo), len(empty)), flush=True)

fails = []
t0 = time.time()
work = [(r, "create") for r in todo] + [(r, "refill") for r in empty]
for i, (r, kind) in enumerate(work, 1):
    if time.time() - t0 > BUDGET:
        print("TIME-UP 剩余 %d, 下个调度续跑" % (len(work) - i + 1), flush=True)
        sys.exit(0)
    name = r.replace("/", "__")
    try:
        s = mirror_one(r, name)
    except subprocess.TimeoutExpired:
        s = "TIMEOUT"
    except Exception as e:
        s = "ERR " + type(e).__name__
    if not s.startswith("OK"):
        fails.append((r, s))
    print("[%d/%d][%s] %s -> %s" % (i, len(work), kind, r, s), flush=True)
    time.sleep(45)

print("FAILS: %d" % len(fails), flush=True)
for r, s in fails:
    print("  FAIL %s %s" % (r, s), flush=True)
# 完成判定: 重查 size
left = 0
for r in repos:
    key = r.replace("/", "__").lower()
    st, info = repo_info(r.replace("/", "__"))
    if st != 200 or info.get("size", 0) == 0:
        left += 1
print("DONE 剩余未完成 %d" % left, flush=True)
if left == 0:
    print("DONE-ALL 全部私有镜像完成", flush=True)
