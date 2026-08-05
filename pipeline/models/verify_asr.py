"""Verify every ASR file against the repo, and re-fetch anything wrong.

Two files were already found bad by accident: one never downloaded, one
truncated to a third of its size. Both surfaced only as confusing errors deep
inside model loading, and the download log said 403/403 because it counted
attempts, not bytes. `curl -C -` compounded it - on a partial file it resumes,
and on a file that is partial for any other reason it happily leaves it partial.

So the download counter is not evidence. This asks the repo for the true size
of every file and compares, which is.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ID = "ai4bharat/indic-conformer-600m-multilingual"
LOCAL = HERE / "ai4bharat" / "indic-conformer-600m-multilingual"


def token() -> str:
    from dotenv import load_dotenv
    load_dotenv(HERE.parent / ".env")
    return os.environ.get("HF_TOKEN", "")


def remote_sizes(paths: list[str], tok: str) -> dict[str, int]:
    """paths-info gives real sizes, including for LFS files."""
    out: dict[str, int] = {}
    url = f"https://huggingface.co/api/models/{REPO_ID}/paths-info/main"
    for i in range(0, len(paths), 200):
        body = json.dumps({"paths": paths[i:i + 200]}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"})
        for item in json.load(urllib.request.urlopen(req, timeout=90)):
            size = item.get("size")
            if item.get("lfs"):
                size = item["lfs"].get("size", size)
            out[item["path"]] = size
    return out


def main() -> int:
    tok = token()
    req = urllib.request.Request(
        f"https://huggingface.co/api/models/{REPO_ID}?full=1",
        headers={"Authorization": f"Bearer {tok}"})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    paths = [s["rfilename"] for s in d["siblings"]]
    print(f"repo lists {len(paths)} files; fetching true sizes ...", flush=True)
    sizes = remote_sizes(paths, tok)

    bad: list[tuple[str, int, int]] = []
    for p in paths:
        want = sizes.get(p)
        if want is None:
            continue
        f = LOCAL / p
        have = f.stat().st_size if f.exists() else -1
        if have != want:
            bad.append((p, have, want))

    print(f"\n{len(bad)} file(s) wrong:")
    for p, have, want in bad[:20]:
        state = "missing" if have < 0 else f"{have} of {want} bytes"
        print(f"   {p}   ({state})")
    if len(bad) > 20:
        print(f"   ... and {len(bad) - 20} more")

    if not bad:
        print("\nall files match the repo. model tree is complete.")
        return 0

    print(f"\nre-fetching {len(bad)} file(s) ...", flush=True)
    ok = 0
    for p, _, want in bad:
        f = LOCAL / p
        f.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{REPO_ID}/resolve/main/{p}"
        try:
            # No resume: a partial file is exactly what got us here.
            r = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(r, timeout=600) as resp, open(f, "wb") as out:
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
            got = f.stat().st_size
            mark = "ok" if got == want else f"STILL WRONG ({got} vs {want})"
            print(f"   {p}  {mark}", flush=True)
            ok += got == want
        except Exception as e:
            print(f"   {p}  FAILED {str(e)[:80]}", flush=True)

    print(f"\nrepaired {ok}/{len(bad)}")
    return 0 if ok == len(bad) else 1


if __name__ == "__main__":
    raise SystemExit(main())
