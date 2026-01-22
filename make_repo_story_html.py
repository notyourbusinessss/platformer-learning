import json
import subprocess
from datetime import datetime
from pathlib import Path

def sh(*cmd: str) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()

def build_data():
    # hash | parents | author | author_email | unix_time | subject
    fmt = "%H|%P|%an|%ae|%at|%s"
    raw = sh("git", "log", "--all", "--date-order", f"--pretty=format:{fmt}")

    commits = []
    for line in raw.splitlines():
        h, parents, an, ae, at, subj = line.split("|", 5)
        commits.append({
            "hash": h,
            "parents": parents.split() if parents else [],
            "author": an,
            "email": ae,
            "time": int(at),
            "subject": subj,
        })

    # Oldest -> newest for storytelling
    commits.sort(key=lambda c: c["time"])

    # Tags (optional milestones)
    tags = {}
    try:
        tags_raw = sh("git", "show-ref", "--tags", "-d")
        for line in tags_raw.splitlines():
            sha, ref = line.split()
            tag = ref.split("/")[-1].replace("^{}", "")
            tags.setdefault(sha, []).append(tag)
    except Exception:
        pass

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "commits": commits,
        "tags": tags,
    }

HTML_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Repo Story (Standalone)</title>
  <style>
    body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }
    #topbar { padding: 10px 12px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid #ddd; }
    #info { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 60vw; }
    #wrap { width: 100vw; height: calc(100vh - 52px); }
    canvas { display:block; width:100%; height:100%; }
    .muted { opacity: 0.75; }
  </style>
</head>
<body>
  <div id="topbar">
    <div><b>Repo Story</b> <span class="muted" id="count"></span></div>
    <input id="slider" type="range" min="0" max="0" value="0" style="flex: 1" />
    <button id="play">Play</button>
    <button id="reset">Reset</button>
    <div id="info" class="muted"></div>
  </div>
  <div id="wrap"><canvas id="c"></canvas></div>

<script>
  // Embedded data (no server needed)
  const data = __DATA_JSON__;
</script>

<script>
const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const slider = document.getElementById("slider");
const playBtn = document.getElementById("play");
const resetBtn = document.getElementById("reset");
const info = document.getElementById("info");
const count = document.getElementById("count");

let commits = data.commits || [];
let tags = data.tags || {};
let pos = new Map();
let playTimer = null;
let visibleN = 0;

let hashToIndex = new Map(commits.map((c,i)=>[c.hash,i]));

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * devicePixelRatio);
  canvas.height = Math.floor(rect.height * devicePixelRatio);
  draw();
}
window.addEventListener("resize", resize);

function assignLanes() {
  const laneOf = new Map();
  const used = [];

  function allocLane() {
    for (let i=0;i<used.length;i++) if (!used[i]) { used[i]=true; return i; }
    used.push(true); return used.length-1;
  }

  for (const c of commits) {
    let lane = null;
    const p0 = c.parents[0];
    if (p0 && laneOf.has(p0)) lane = laneOf.get(p0);
    if (lane === null) lane = allocLane();
    laneOf.set(c.hash, lane);
  }

  const laneCount = Math.max(1, ...Array.from(laneOf.values()).map(v=>v+1));

  pos.clear();
  for (let i=0;i<commits.length;i++) {
    const c = commits[i];
    const lane = laneOf.get(c.hash) ?? 0;
    pos.set(c.hash, { x: i, y: lane, laneCount });
  }
}

let zoom = 1.0, panX = 0, panY = 0;
let dragging = false, lastMouse = null;

function toScreen(px, py, laneCount) {
  const W = canvas.width, H = canvas.height;
  const margin = 40 * devicePixelRatio;
  const usableW = W - margin*2;
  const usableH = H - margin*2;

  const maxX = Math.max(1, visibleN-1);
  const sx = margin + ((px / maxX) * usableW) * zoom + panX;
  const sy = margin + ((py / Math.max(1,laneCount-1)) * usableH) * zoom + panY;
  return { sx, sy };
}

function draw() {
  ctx.setTransform(1,0,0,1,0,0);
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0,0,canvas.width,canvas.height);

  // edges
  ctx.lineWidth = 1 * devicePixelRatio;
  ctx.strokeStyle = "#999";

  for (let i=0;i<visibleN;i++) {
    const c = commits[i];
    const pc = pos.get(c.hash);
    if (!pc) continue;

    for (const p of c.parents) {
      const parentIndex = hashToIndex.get(p);
      if (parentIndex === undefined || parentIndex >= visibleN) continue;

      const pp = pos.get(p);
      if (!pp) continue;

      const a = toScreen(pc.x, pc.y, pc.laneCount);
      const b = toScreen(pp.x, pp.y, pp.laneCount);

      ctx.beginPath();
      ctx.moveTo(a.sx, a.sy);
      ctx.lineTo(b.sx, b.sy);
      ctx.stroke();
    }
  }

  // nodes
  for (let i=0;i<visibleN;i++) {
    const c = commits[i];
    const pc = pos.get(c.hash);
    const { sx, sy } = toScreen(pc.x, pc.y, pc.laneCount);

    const hasTag = !!tags[c.hash];
    const r = (hasTag ? 4.2 : 3.0) * devicePixelRatio;

    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI*2);
    ctx.fillStyle = hasTag ? "#111" : "#333";
    ctx.fill();
  }
}

function setVisible(n) {
  visibleN = Math.max(0, Math.min(n, commits.length));
  slider.value = visibleN;
  count.textContent = `(${visibleN}/${commits.length})`;
  draw();
}

function togglePlay() {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
    playBtn.textContent = "Play";
    return;
  }
  playBtn.textContent = "Pause";
  playTimer = setInterval(()=>{
    if (visibleN >= commits.length) {
      togglePlay();
      return;
    }
    setVisible(visibleN + 1);
  }, 40);
}

playBtn.addEventListener("click", togglePlay);
resetBtn.addEventListener("click", ()=>{
  if (playTimer) togglePlay();
  zoom = 1.0; panX = 0; panY = 0;
  setVisible(Math.min(50, commits.length));
});
slider.addEventListener("input", ()=> setVisible(parseInt(slider.value, 10)));

canvas.addEventListener("mousedown", (e)=>{ dragging = true; lastMouse = { x:e.clientX, y:e.clientY }; });
window.addEventListener("mouseup", ()=> dragging=false);
window.addEventListener("mousemove", (e)=>{
  if (!dragging) return;
  panX += (e.clientX - lastMouse.x) * devicePixelRatio;
  panY += (e.clientY - lastMouse.y) * devicePixelRatio;
  lastMouse = { x:e.clientX, y:e.clientY };
  draw();
});
canvas.addEventListener("wheel", (e)=>{
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.92 : 1.08;
  zoom = Math.max(0.2, Math.min(zoom * factor, 5));
  draw();
}, { passive:false });

function start() {
  slider.max = commits.length;
  assignLanes();
  resize();
  setVisible(Math.min(50, commits.length));
}
start();
</script>
</body>
</html>
"""

def main():
    data = build_data()
    data_json = json.dumps(data)

    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json)

    out = Path("repo_story_standalone.html")
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} (commits: {len(data['commits'])})")
    print("Open it by double-clicking, or: open repo_story_standalone.html")

if __name__ == "__main__":
    main()
