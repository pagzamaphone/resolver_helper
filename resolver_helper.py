#!/usr/bin/env python3
"""Interactive Kattis CLICS downloader and ICPC Resolver launcher.

Place this file beside resolver.sh / resolver.bat and awards.json, then run:
    python3 resolver_helper.py
No third-party Python packages are required.
"""
from __future__ import annotations
import argparse, base64, getpass, hashlib, json, os, platform, re, shutil, socket, ssl, subprocess, sys, time, traceback, zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent
HELPER_VERSION = "2.2.1"
ARGS = None
CONFIG = ROOT / ".resolver-helper.json"
AWARDS = ROOT / "awards.json"
SITES = ROOT / "sites.json"
COLLECTIONS = ["judgement-types", "languages", "problems", "groups", "organizations", "teams", "persons", "accounts", "state", "submissions", "judgements", "runs", "clarifications", "awards", "commentary", "scoreboard"]
ASSET_FIELDS = {"logo", "country_flag", "country_subdivision_flag", "photo", "video", "banner"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

def load_config():
    try: return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return {}

def atomic_write_text(path, text):
    path=Path(path); temp=path.with_name(path.name+".download")
    temp.write_text(text,encoding="utf-8")
    os.replace(temp,path)

def save_config(c):
    atomic_write_text(CONFIG, json.dumps(c, indent=2) + "\n")
    try: os.chmod(CONFIG, 0o600)
    except OSError: pass

def ask(label, old=None, secret=False):
    hint = f" [{old}]" if old and not secret else (" [saved; Enter to reuse]" if old else "")
    value = (getpass.getpass if secret else input)(f"{label}{hint}: ").strip()
    return value or old

def confirm(msg, default=True):
    suffix = " [Y/n] " if default else " [y/N] "
    ans = input(msg + suffix).strip().lower()
    return default if not ans else ans in ("y", "yes")

def normalized_api(host):
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")): host = "https://" + host
    if host.endswith("/api/clics"): return host + "/"
    return host + "/api/clics/"

class Client:
    def __init__(self, api, user, key): self.api, self.user, self.key = api, user, key
    def request(self, url, timeout=30, accept="application/json"):
        token = base64.b64encode(f"{self.user}:{self.key}".encode()).decode()
        req = Request(url, headers={"Authorization": "Basic " + token, "Accept": accept, "User-Agent": "resolver-helper/1.0"})
        return urlopen(req, timeout=timeout, context=ssl.create_default_context())
    def json(self, url):
        with self.request(url) as r: return json.load(r)
    def bytes(self, url):
        with self.request(url, accept="*/*") as r: return r.read()
    def text(self, url):
        with self.request(url, accept="text/html") as r:
            return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")

def safe_id(x):
    s = str(x)
    if not s or s in (".", "..") or "/" in s or "\\" in s: raise ValueError(f"Unsafe API id: {s!r}")
    return s

def choose_contest(client, remembered):
    contests = client.json(urljoin(client.api, "contests"))
    if not isinstance(contests, list) or not contests: raise RuntimeError("No contests were returned by this account.")
    print("\nAvailable contests:")
    for i, c in enumerate(contests, 1): print(f"  {i}. {c.get('name', c.get('id'))} ({c.get('id')})")
    default = next((i for i,c in enumerate(contests,1) if c.get("id") == remembered), 1)
    raw = input(f"Contest number [{default}]: ").strip()
    try: selected = contests[(int(raw) if raw else default)-1]
    except (ValueError, IndexError): raise RuntimeError("Invalid contest selection.")
    print(f"Selected: {selected.get('name')} ({selected.get('id')})")
    if not confirm("Use this contest?"): return choose_contest(client, remembered)
    return selected

def write_json(path, obj): atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

def file_refs(obj, trail=()):
    if isinstance(obj, dict):
        for k,v in obj.items():
            if k in ASSET_FIELDS and isinstance(v, list):
                for ref in v:
                    if isinstance(ref, dict) and ref.get("href"): yield trail+(k,), ref
            yield from file_refs(v, trail+(k,))
    elif isinstance(obj, list):
        for i,v in enumerate(obj): yield from file_refs(v, trail+(str(i),))

def asset_name(field, ref, used):
    mime_ext = {"image/png":".png", "image/jpeg":".jpg", "image/svg+xml":".svg"}.get(ref.get("mime"), "")
    preferred = {"country_flag":"country_flag", "country_subdivision_flag":"subdivision_flag", "photo":"photo", "video":"video", "banner":"banner", "logo":"logo"}.get(field, field)
    size = ref.get("width")
    name = preferred + (f".{size}" if size and preferred == "logo" else "") + mime_ext
    n=2; stem, ext = Path(name).stem, Path(name).suffix
    while name in used: name=f"{stem}.{n}{ext}"; n+=1
    used.add(name); return name

def download_assets(client, contest_url, collection, data, package):
    if not isinstance(data, list): data = [data]
    count = 0
    for item in data:
        if not isinstance(item, dict) or "id" not in item: continue
        item_dir = package / collection / safe_id(item["id"]); used=set()
        for trail, ref in file_refs(item):
            field = trail[-1]; item_dir.mkdir(parents=True, exist_ok=True)
            name = asset_name(field, ref, used)
            url = urljoin(contest_url + "/", ref["href"])
            try: (item_dir/name).write_bytes(client.bytes(url)); count += 1
            except Exception as e: print(f"  Warning: asset failed {url}: {e}")
    return count

def download_feed(client, url, path):
    token = base64.b64encode(f"{client.user}:{client.key}".encode()).decode()
    req = Request(url, headers={"Authorization":"Basic "+token,"Accept":"application/x-ndjson","User-Agent":"resolver-helper/1.0"})
    lines=[]
    try:
        with urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            try: r.fp.raw._sock.settimeout(3.0)
            except Exception: pass
            while True:
                try: raw=r.readline()
                except (socket.timeout, TimeoutError):
                    if lines: break
                    raise
                if not raw: break
                text=raw.decode("utf-8").strip()
                if text:
                    json.loads(text); lines.append(text)
    except (socket.timeout, TimeoutError):
        if not lines: raise RuntimeError("Event feed timed out before returning data.")
    atomic_write_text(path, "\n".join(lines)+"\n")
    return len(lines)

def clean_folder_part(value, fallback="unknown"):
    text = str(value or fallback).strip()
    text = re.sub(r"[/:\\]", "-", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^A-Za-z0-9 ._()&+#'@-]", "_", text)
    return text[:100].strip(" .") or fallback

def site_for_team(team, groups_by_id):
    """Use the first matching site/group name; prefer a group whose type is site."""
    groups = [groups_by_id.get(str(g)) for g in team.get("group_ids", [])]
    groups = [g for g in groups if isinstance(g, dict)]
    selected = next((g for g in groups if str(g.get("type", "")).lower() == "site"), None)
    selected = selected or (groups[0] if groups else None)
    return (selected or {}).get("name") or (selected or {}).get("id") or "unknown-site"

def prepare_photo_staging(package, teams, groups, contest_id):
    staging = ROOT / "staging-photos" / contest_id
    staging.mkdir(parents=True, exist_ok=True)
    groups_by_id = {str(g.get("id")): g for g in groups if isinstance(g, dict) and g.get("id") is not None}
    manifest = {}
    for team in teams:
        if not isinstance(team, dict) or team.get("id") is None:
            continue
        tid = safe_id(team["id"])
        name = clean_folder_part(team.get("name") or team.get("display_name"), "unnamed-team")
        site = clean_folder_part(site_for_team(team, groups_by_id), "unknown-site")
        folder = staging / f"{clean_folder_part(tid)} - {name} - {site}"
        folder.mkdir(exist_ok=True)
        manifest[tid] = folder
    write_json(staging / "team-photo-folders.json", {
        tid: folder.name for tid, folder in sorted(manifest.items())
    })
    return staging, manifest

def validate_photo(path):
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            width,height=im.size
            if width < 1 or height < 1: return False,"zero-size image"
            if getattr(im,"is_animated",False): return False,"animated images are not supported"
        return True,f"{width}x{height}"
    except ImportError:
        try:
            head=path.read_bytes()[:16]
            ok=(head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n") or
                head.startswith((b"GIF87a",b"GIF89a")) or (head.startswith(b"RIFF") and b"WEBP" in head))
            return (ok,"signature verified" if ok else "unrecognized image signature")
        except OSError as e: return False,str(e)
    except Exception as e: return False,str(e)

def convert_photo_to_jpeg(source, destination):
    """Normalize any supported staging image to an RGB JPEG for Resolver."""
    temp=destination.with_name(destination.name+".convert")
    try:
        try:
            from PIL import Image, ImageOps
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
            with Image.open(source) as image:
                image=ImageOps.exif_transpose(image)
                if getattr(image,"is_animated",False): image.seek(0)
                if image.mode in ("RGBA","LA"):
                    background=Image.new("RGB",image.size,"white")
                    background.paste(image.convert("RGB"),(0,0),image.getchannel("A"))
                    image=background
                else: image=image.convert("RGB")
                image.thumbnail((2000,2000))
                image.save(temp,format="JPEG",quality=90,optimize=True)
            temp.replace(destination); return
        except (ImportError,OSError) as pillow_error:
            if sys.platform=="darwin" and shutil.which("sips"):
                result=subprocess.run(["sips","-s","format","jpeg",str(source),"--out",str(temp)],capture_output=True,text=True)
                if result.returncode==0 and temp.exists(): temp.replace(destination); return
            raise RuntimeError(f"Could not convert {source.name} to JPEG: {pillow_error}")
    finally:
        if temp.exists(): temp.unlink()

def install_staged_photos(package, manifest):
    installed=[]; skipped=[]; empty=[]; multiple=[]
    for tid, folder in manifest.items():
        candidates = sorted((f for f in folder.iterdir() if f.is_file() and f.name != ".DS_Store"),key=lambda f:f.name.casefold())
        if not candidates: empty.append(tid); continue
        supported=[f for f in candidates if f.suffix.lower() in PHOTO_EXTENSIONS]
        if not supported:
            skipped.append((tid,candidates[0].name,"no supported image")); continue
        if len(supported)>1: multiple.append((tid,supported[0].name,[x.name for x in supported[1:]]))
        source=supported[0]; ok,detail=validate_photo(source)
        if not ok: skipped.append((tid,source.name,detail)); continue
        destination_dir=package/"teams"/tid; destination_dir.mkdir(parents=True,exist_ok=True)
        for old in destination_dir.glob("photo.*"):
            if old.is_file(): old.unlink()
        destination=destination_dir/"photo.jpg"
        try:
            convert_photo_to_jpeg(source,destination)
            installed.append((tid,source.name,destination.name,detail+"; converted to JPEG"))
        except RuntimeError as error:
            skipped.append((tid,source.name,str(error)))
    return {"installed":installed,"skipped":skipped,"empty":empty,"multiple":multiple}

def load_award_policy():
    defaults = {"top_overall": 3, "top_per_site": True, "top_per_school": True,
                "require_solve_for_site_school": True, "first_to_solve": True,
                "last_accepted": True, "biggest_comeback": True, "freeze_breaker": True,
                "cleanest_run": True, "persistence_award": True, "fastest_start": True,
                "cleanest_run_minimum_solves": 3, "biggest_comeback_minimum_places": 3,
                "persistence_minimum_rejected_attempts": 3,
                "suppress_duplicate_fastest_start": True, "fun_awards_require_finalized": True,
                "expected_to_advance": True, "expected_to_advance_count": 4,
                "major_site_placements": True, "major_site_minimum_teams": 6,
                "major_site_places": 3, "most_submissions": True}
    if not AWARDS.exists():
        write_json(AWARDS, defaults)
        print(f"  created default award policy: {AWARDS}")
        return defaults
    obj=json.loads(AWARDS.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        print("  NOTE: legacy team-specific awards.json detected; using automatic award policy instead")
        return defaults
    if not isinstance(obj, dict): raise ValueError("awards.json must be a JSON object containing award policy settings.")
    policy=defaults.copy(); policy.update(obj)
    policy["top_overall"]=max(0, min(20, int(policy.get("top_overall", 3))))
    policy["expected_to_advance_count"]=max(0,min(100,int(policy.get("expected_to_advance_count",4))))
    policy["major_site_minimum_teams"]=max(1,int(policy.get("major_site_minimum_teams",6)))
    policy["major_site_places"]=max(1,min(10,int(policy.get("major_site_places",3))))
    return policy

def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "unknown"

def contest_time_seconds(value):
    """Convert CLICS contest-time values such as 0:20:00.000 to seconds."""
    if value is None or value == "": return 0.0
    if isinstance(value, (int, float)): return float(value)
    text=str(value).strip()
    try: return float(text)
    except ValueError: pass
    sign=-1.0 if text.startswith("-") else 1.0
    if text[:1] in "+-": text=text[1:]
    parts=text.split(":")
    if len(parts) not in (2,3):
        raise ValueError(f"Unsupported contest time value: {value!r}")
    try:
        numbers=[float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Unsupported contest time value: {value!r}") from exc
    if len(numbers)==3:
        hours,minutes,seconds=numbers
    else:
        hours=0.0; minutes,seconds=numbers
    return sign * (hours*3600.0 + minutes*60.0 + seconds)

class KattisTeamsPageParser(HTMLParser):
    """Extract team name and 'Competing at site' from Kattis' judge teams table."""
    def __init__(self):
        super().__init__(); self.headers=[]; self.rows=[]; self.in_row=False
        self.cell_depth=0; self.cell_text=[]; self.cells=[]; self.in_header=False
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag=="tr": self.in_row=True; self.cells=[]
        elif self.in_row and tag in ("td","th"):
            self.cell_depth=1; self.cell_text=[]; self.in_header=(tag=="th")
        elif self.cell_depth: self.cell_depth+=1
    def handle_endtag(self,tag):
        tag=tag.lower()
        if self.cell_depth:
            self.cell_depth-=1
            if self.cell_depth==0 and tag in ("td","th"):
                text=" ".join("".join(self.cell_text).split())
                self.cells.append(text)
        if tag=="tr" and self.in_row:
            if self.cells:
                normalized=[x.strip().lower() for x in self.cells]
                if any("competing at site" in x for x in normalized): self.headers=self.cells[:]
                else: self.rows.append(self.cells[:])
            self.in_row=False; self.cell_depth=0
    def handle_data(self,data):
        if self.cell_depth: self.cell_text.append(data)

def fetch_kattis_site_assignments(client, host, contest_id, teams):
    """Read the same Kattis judge Teams page shown in the browser and match rows to CLICS teams."""
    url=f"{host.rstrip('/')}/contests/{contest_id}/teams"
    try: html=client.text(url)
    except HTTPError as e:
        print(f"  site discovery: Kattis Teams page returned HTTP {e.code}; using Contest API groups only")
        return []
    except Exception as e:
        print(f"  site discovery: could not read Kattis Teams page ({e}); using Contest API groups only")
        return []
    parser=KattisTeamsPageParser(); parser.feed(html)
    if not parser.headers:
        print("  site discovery: Teams page did not expose a readable 'Competing at site' table")
        return []
    headers=[x.strip().lower() for x in parser.headers]
    try: name_col=next(i for i,x in enumerate(headers) if x=="name" or "team name" in x)
    except StopIteration: name_col=0
    try: site_col=next(i for i,x in enumerate(headers) if "competing at site" in x)
    except StopIteration: return []
    by_name={}
    for team in teams:
        if not isinstance(team,dict) or team.get("id") is None: continue
        for value in (team.get("name"),team.get("display_name")):
            if value: by_name.setdefault(" ".join(str(value).split()).casefold(),[]).append(str(team["id"]))
    site_members={}; unmatched=[]; ambiguous=[]
    for cells in parser.rows:
        if max(name_col,site_col)>=len(cells): continue
        name=" ".join(cells[name_col].split()); site=" ".join(cells[site_col].split())
        if not name or not site: continue
        matches=by_name.get(name.casefold(),[])
        if len(matches)==1: site_members.setdefault(site,[]).append(matches[0])
        elif len(matches)>1: ambiguous.append(name)
        else: unmatched.append(name)
    result=[]
    for site in sorted(site_members,key=str.casefold):
        result.append({"id":"kattis-site-"+slug(site),"name":site,"team_ids":sorted(set(site_members[site])),"group_ids":[],"source":"kattis-teams-page"})
    print(f"  site discovery: found {len(result)} sites and matched {sum(len(x['team_ids']) for x in result)} teams from Kattis")
    if unmatched: print(f"  site discovery warning: {len(unmatched)} Kattis team rows did not match CLICS team names")
    if ambiguous: print(f"  site discovery warning: {len(ambiguous)} duplicate team names were ambiguous")
    return result

def load_site_config():
    """Load optional site overrides. Kattis type=site groups remain the first source."""
    if not SITES.exists(): return []
    obj=json.loads(SITES.read_text(encoding="utf-8"))
    sites=obj.get("sites", []) if isinstance(obj,dict) else obj
    if not isinstance(sites,list): raise ValueError("sites.json must contain a sites array.")
    seen=set(); result=[]
    for site in sites:
        if not isinstance(site,dict) or not site.get("id") or not site.get("name"):
            raise ValueError("Each sites.json entry needs id and name.")
        sid=str(site["id"])
        if sid in seen: raise ValueError(f"Duplicate site id in sites.json: {sid}")
        seen.add(sid)
        result.append({"id":sid,"name":str(site["name"]),
                       "group_ids":[str(x) for x in site.get("group_ids",[])],
                       "team_ids":[str(x) for x in site.get("team_ids",[])]})
    return result

def resolve_team_sites(teams, groups, configured_sites):
    """Return site definitions and team-to-site assignments, with explicit config overriding API groups."""
    groups_by_id={str(g.get("id")):g for g in groups if isinstance(g,dict) and g.get("id") is not None}
    sites={}; assignment={}
    # Standard CLICS/Kattis source: team.group_ids -> group.type == site.
    for gid,g in groups_by_id.items():
        if str(g.get("type","")).strip().lower()=="site":
            sites[gid]={"id":gid,"name":str(g.get("name") or gid),"source":"kattis"}
    for team in teams:
        if not isinstance(team,dict) or team.get("id") is None: continue
        tid=str(team["id"])
        for gid_value in team.get("group_ids",[]):
            gid=str(gid_value)
            if gid in sites: assignment.setdefault(tid,[]).append(gid)
    # Local mappings supplement Kattis and override membership for explicitly listed teams.
    configured_team_ids=set()
    for site in configured_sites:
        sid=site["id"]; sites[sid]={"id":sid,"name":site["name"],"source":site.get("source","sites.json")}
        mapped=set(site["team_ids"])
        for gid in site["group_ids"]:
            for team in teams:
                if isinstance(team,dict) and str(gid) in [str(x) for x in team.get("group_ids",[])]:
                    mapped.add(str(team.get("id")))
        for tid in mapped:
            configured_team_ids.add(tid); assignment[tid]=[sid]
    return sites, assignment, configured_team_ids

def generate_awards(policy, scoreboard, teams, groups, organizations, configured_sites):
    rows = scoreboard.get("rows", []) if isinstance(scoreboard, dict) else []
    teams_by_id={str(t.get("id")):t for t in teams if isinstance(t,dict) and t.get("id") is not None}
    groups_by_id={str(g.get("id")):g for g in groups if isinstance(g,dict) and g.get("id") is not None}
    orgs_by_id={str(o.get("id")):o for o in organizations if isinstance(o,dict) and o.get("id") is not None}
    site_defs, team_sites, configured_team_ids=resolve_team_sites(teams,groups,configured_sites)
    ranked=[]
    for api_index,row in enumerate(rows):
        if not isinstance(row,dict) or row.get("team_id") is None: continue
        tid=str(row["team_id"])
        if tid not in teams_by_id: continue
        score=row.get("score") or {}
        solved=int(score.get("num_solved") or 0)
        total_time=contest_time_seconds(score.get("total_time"))
        # Use the official CLICS rank first. API order is only a final fallback.
        try: official_rank=int(row.get("rank"))
        except (TypeError,ValueError): official_rank=10**9
        ranked.append((official_rank, -solved, total_time, api_index, tid, solved, row))
    ranked.sort(key=lambda x: x[:5])

    audit=[]
    for order,entry in enumerate(ranked,1):
        official_rank,_,total_time,api_index,tid,solved,row=entry
        team=teams_by_id[tid]
        oid=str(team.get("organization_id") or "")
        org=orgs_by_id.get(oid,{})
        school=org.get("formal_name") or org.get("name") or oid or "NO ORGANIZATION"
        site_names=[site_defs[sid]["name"] for sid in team_sites.get(tid,[]) if sid in site_defs]
        audit.append({"resolved_order":order,"official_rank":None if official_rank==10**9 else official_rank,
                      "api_row":api_index+1,"team_id":tid,"team_name":team.get("name") or team.get("display_name"),
                      "solved":solved,"total_time":total_time,"organization_id":oid or None,
                      "school":school,"sites":site_names,"awards":[]})
    audit_by_tid={r["team_id"]:r for r in audit}
    awards=[]
    labels=["Winner", "Second Place", "Third Place"]
    for place,entry in enumerate(ranked[:policy["top_overall"]],1):
        tid=entry[4]
        aid="winner" if place == 1 else f"overall-place-{place}"
        citation=labels[place-1] if place <= len(labels) else f"Overall Place {place}"
        awards.append({"id":aid,"citation":citation,"team_ids":[tid],"display_mode":"detail"})
        audit_by_tid[tid]["awards"].append(citation)
    require_solve=bool(policy.get("require_solve_for_site_school", True))
    eligible=[entry for entry in ranked if entry[5] > 0 or not require_solve]
    # Physical-site awards. Major sites receive explicit placements; smaller sites retain one top-team award.
    site_entries={sid:[] for sid in site_defs}
    for entry in ranked:
        tid=entry[4]
        for sid in team_sites.get(tid,[]):
            if sid in site_defs: site_entries.setdefault(sid,[]).append(entry)
    if policy.get("top_per_site", True):
        minimum=int(policy.get("major_site_minimum_teams",6))
        places=int(policy.get("major_site_places",3))
        placement_labels=["First","Second","Third"]
        for sid,entries in sorted(site_entries.items(),key=lambda x:site_defs[x[0]]["name"].casefold()):
            name=site_defs[sid]["name"]
            if policy.get("major_site_placements",True) and len(entries) >= minimum:
                # A major site's placement awards only go to teams with at least one solve.
                solved_entries=[entry for entry in entries if entry[5] > 0]
                for place,entry in enumerate(solved_entries[:places],1):
                    tid=entry[4]
                    label=placement_labels[place-1] if place <= 3 else f"Place {place}"
                    citation=f"{label} Place at {name} Site" if place <= 3 else f"{label} at {name} Site"
                    awards.append({"id":f"site-{sid}-place-{place}","citation":citation,
                                   "team_ids":[tid],"display_mode":"detail"})
                    audit_by_tid[tid]["awards"].append(citation)
            else:
                eligible_entries=[entry for entry in entries if entry in eligible]
                if eligible_entries:
                    tid=eligible_entries[0][4]; citation=f"Top Team at {name} Site"
                    awards.append({"id":f"group-winner-{sid}","citation":citation,
                                   "team_ids":[tid],"display_mode":"detail"})
                    audit_by_tid[tid]["awards"].append(citation)

    # Select one school winner per organization in official scoreboard order.
    school_winners=[]; claimed=set()
    for entry in eligible:
        tid=entry[4]; team=teams_by_id[tid]; oid=team.get("organization_id")
        if oid is None or str(oid) in claimed: continue
        oid=str(oid); claimed.add(oid); school_winners.append(entry)
        if policy.get("top_per_school", True):
            org=orgs_by_id.get(oid,{})
            name=org.get("formal_name") or org.get("name") or oid
            citation=f"Top Team from {name}"
            awards.append({"id":f"organization-winner-{oid}","citation":citation,
                           "team_ids":[tid],"display_mode":"detail"})
            audit_by_tid[tid]["awards"].append(citation)

    # Expected to Advance: the top N entries from the one-team-per-school list.
    if policy.get("expected_to_advance",True):
        count=int(policy.get("expected_to_advance_count",4))
        advancing=[entry[4] for entry in school_winners[:count]]
        if advancing:
            citation=f"Expected to Advance (Top {len(advancing)} One per School)"
            awards.append({"id":"expected-to-advance","citation":citation,
                           "team_ids":advancing,"display_mode":"list"})
            for tid in advancing: audit_by_tid[tid]["awards"].append(citation)
    return awards, audit

def generate_fun_awards(policy, submissions, judgements, judgement_types, problems,
                        teams, scoreboard, contest, state):
    """Generate submission-based awards and an evidence audit."""
    if not isinstance(submissions,list) or not isinstance(judgements,list):
        return [], [{"status":"skipped","reason":"submissions or judgements unavailable"}]
    jt={str(x.get("id")):x for x in judgement_types if isinstance(x,dict) and x.get("id") is not None}
    solved_types={k for k,v in jt.items() if v.get("solved") is True}
    penalty_types={k for k,v in jt.items() if v.get("penalty") is True}
    latest={}
    for index,j in enumerate(judgements):
        if not isinstance(j,dict) or j.get("submission_id") is None: continue
        sid=str(j["submission_id"])
        key=(contest_time_seconds(j.get("end_contest_time") or j.get("start_contest_time")), index)
        if sid not in latest or key > latest[sid][0]: latest[sid]=(key,j)
    records=[]
    for index,sub in enumerate(submissions):
        if not isinstance(sub,dict) or sub.get("id") is None: continue
        sid=str(sub["id"]); pair=latest.get(sid)
        if not pair: continue
        judgement=pair[1]; jtid=str(judgement.get("judgement_type_id"))
        records.append({"submission_id":sid,"team_id":str(sub.get("team_id")),
                        "problem_id":str(sub.get("problem_id")),
                        "time":contest_time_seconds(sub.get("contest_time")),
                        "time_raw":sub.get("contest_time"),"accepted":jtid in solved_types,
                        "penalty":jtid in penalty_types,"judgement_type_id":jtid,"index":index})
    records.sort(key=lambda r:(r["time"],r["index"],r["submission_id"]))
    teams_by_id={str(t.get("id")):t for t in teams if isinstance(t,dict) and t.get("id") is not None}
    problem_names={str(x.get("id")):x.get("name") or x.get("label") or str(x.get("id")) for x in problems if isinstance(x,dict)}
    rows=scoreboard.get("rows",[]) if isinstance(scoreboard,dict) else []
    final_rank={str(r.get("team_id")):int(r.get("rank") or 10**9) for r in rows if isinstance(r,dict) and r.get("team_id") is not None}
    final_solved={str(r.get("team_id")):int((r.get("score") or {}).get("num_solved") or 0) for r in rows if isinstance(r,dict) and r.get("team_id") is not None}
    awards=[]; audit=[]
    def add(aid,citation,tid,reason,display="detail",**evidence):
        awards.append({"id":aid,"citation":citation,"team_ids":[tid],"display_mode":display})
        audit.append({"id":aid,"citation":citation,"team_id":tid,
                      "team_name":(teams_by_id.get(tid) or {}).get("name"),"reason":reason,**evidence})
    accepted=[r for r in records if r["accepted"]]
    first_by_problem={}
    for r in accepted: first_by_problem.setdefault(r["problem_id"],r)
    fastest=accepted[0] if accepted else None
    if policy.get("first_to_solve",True):
        for pid,r in first_by_problem.items():
            name=problem_names.get(pid,pid); citation=f"First to Solve {name}"
            if fastest is r and policy.get("fastest_start",True) and policy.get("suppress_duplicate_fastest_start",True):
                citation += " and Fastest Start"
            add(f"first-to-solve-{pid}",citation,r["team_id"],"earliest accepted submission for this problem",
                "pause",problem_id=pid,contest_time=r["time_raw"])
    if fastest and policy.get("fastest_start",True) and not policy.get("suppress_duplicate_fastest_start",True):
        add("fastest-start","Fastest Start",fastest["team_id"],"earliest accepted submission in the contest",
            contest_time=fastest["time_raw"],problem_id=fastest["problem_id"])
    if accepted and policy.get("last_accepted",True):
        r=accepted[-1]
        add("last-accepted","Last Accepted Submission",r["team_id"],"latest accepted contest submission",
            contest_time=r["time_raw"],problem_id=r["problem_id"])
    attempts={}; team_rejected={}
    persistence=[]
    for r in records:
        key=(r["team_id"],r["problem_id"]); info=attempts.setdefault(key,{"wrong":0,"solved":False})
        if info["solved"]: continue
        if r["accepted"]:
            info["solved"]=True; persistence.append((info["wrong"],r))
        elif r["penalty"]:
            info["wrong"]+=1; team_rejected[r["team_id"]]=team_rejected.get(r["team_id"],0)+1
    if policy.get("cleanest_run",True):
        candidates=[(team_rejected.get(tid,0),-solved,final_rank.get(tid,10**9),tid)
                    for tid,solved in final_solved.items() if solved >= int(policy.get("cleanest_run_minimum_solves",3))]
        if candidates:
            wrong,negsolved,rank,tid=min(candidates)
            add("cleanest-run",f"Cleanest Run: {wrong} rejected submission{'s' if wrong != 1 else ''}",tid,
                "fewest rejected submissions among qualifying teams",rejected_submissions=wrong,
                solved=-negsolved,final_rank=rank)
    minimum=int(policy.get("persistence_minimum_rejected_attempts",3))
    eligible_persistence=[x for x in persistence if x[0] >= minimum]
    if policy.get("persistence_award",True) and eligible_persistence:
        wrong,r=max(eligible_persistence,key=lambda x:(x[0],x[1]["time"],-final_rank.get(x[1]["team_id"],10**9)))
        name=problem_names.get(r["problem_id"],r["problem_id"])
        add("persistence-award",f"Persistence Award: Solved {name} after {wrong} rejected attempts",
            r["team_id"],"most rejected attempts before an eventual solve",problem_id=r["problem_id"],
            rejected_attempts=wrong,accepted_contest_time=r["time_raw"])
    finalized=bool(state.get("finalized")) if isinstance(state,dict) else False
    require_final=bool(policy.get("fun_awards_require_finalized",True))
    freeze_value=(contest or {}).get("scoreboard_freeze_duration") if isinstance(contest,dict) else None
    duration_value=(contest or {}).get("duration") if isinstance(contest,dict) else None
    if (not require_final or finalized) and freeze_value and duration_value:
        freeze_start=contest_time_seconds(duration_value)-contest_time_seconds(freeze_value)
        frozen={tid:{"solved":0,"time":0.0} for tid in teams_by_id}
        by_pair={}
        for r in records:
            if r["time"] >= freeze_start: continue
            key=(r["team_id"],r["problem_id"]); x=by_pair.setdefault(key,{"wrong":0,"solved":False})
            if x["solved"]: continue
            if r["accepted"]:
                x["solved"]=True; frozen[r["team_id"]]["solved"]+=1
                frozen[r["team_id"]]["time"]+=r["time"]+x["wrong"]*1200
            elif r["penalty"]: x["wrong"]+=1
        ordered=sorted(teams_by_id,key=lambda tid:(-frozen[tid]["solved"],frozen[tid]["time"],tid))
        frozen_rank={tid:i+1 for i,tid in enumerate(ordered)}
        gains=[(frozen_rank.get(tid,10**9)-rank,tid,frozen_rank.get(tid),rank)
               for tid,rank in final_rank.items() if tid in frozen_rank]
        gains=[g for g in gains if g[0] >= int(policy.get("biggest_comeback_minimum_places",3))]
        if policy.get("biggest_comeback",True) and gains:
            gain,tid,fr,rr=max(gains,key=lambda x:(x[0],-x[3]))
            add("biggest-comeback",f"Biggest Comeback: Gained {gain} places",tid,
                "largest improvement from freeze rank to final rank",frozen_rank=fr,final_rank=rr,places_gained=gain)
        post={}
        for r in accepted:
            if r["time"] >= freeze_start: post.setdefault((r["team_id"],r["problem_id"]),r)
        counts={}
        for tid,pid in post: counts[tid]=counts.get(tid,0)+1
        if policy.get("freeze_breaker",True) and counts:
            tid=max(counts,key=lambda x:(counts[x],-final_rank.get(x,10**9)))
            add("freeze-breaker",f"Freeze Breaker: {counts[tid]} post-freeze solve{'s' if counts[tid] != 1 else ''}",tid,
                "most accepted problems submitted after the freeze",post_freeze_solves=counts[tid],final_rank=final_rank.get(tid))
    else:
        for aid in ("biggest-comeback","freeze-breaker"):
            if policy.get(aid.replace("-","_"),True):
                audit.append({"id":aid,"status":"skipped","reason":"requires finalized results and contest freeze metadata"})

    # Joke award: count every submitted solution, regardless of judgement or correctness.
    if policy.get("most_submissions",True):
        submission_counts={}
        for sub in submissions:
            if not isinstance(sub,dict) or sub.get("team_id") is None: continue
            tid=str(sub["team_id"])
            if tid in teams_by_id: submission_counts[tid]=submission_counts.get(tid,0)+1
        if submission_counts:
            maximum=max(submission_counts.values())
            winners=sorted(tid for tid,count in submission_counts.items() if count==maximum)
            citation=f"Most Submissions: {maximum} Total Submission{'s' if maximum != 1 else ''}"
            awards.append({"id":"most-submissions","citation":citation,
                           "team_ids":winners,"display_mode":"detail" if len(winners)==1 else "list"})
            audit.append({"id":"most-submissions","citation":citation,"team_ids":winners,
                          "team_names":[(teams_by_id.get(tid) or {}).get("name") for tid in winners],
                          "submission_count":maximum,
                          "reason":"highest total submission count, regardless of judgement or correctness",
                          "tie":len(winners)>1})
    return awards,audit

def sanitize_languages(data):
    """Remove null command objects rejected by Resolver 2.7.1444."""
    removed=0
    items=data if isinstance(data,list) else [data]
    for language in items:
        if not isinstance(language,dict): continue
        for command in ("compiler", "runner"):
            if command in language and language[command] is None:
                del language[command]
                removed += 1
    return removed

def patch_awards(src, dst, awards, valid_team_ids):
    events=[]; insert_at=None; removed_language_nulls=0
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        ev=json.loads(line)
        if ev.get("type") == "awards":
            if insert_at is None: insert_at=len(events)
            continue
        # Event-feed snapshots may contain one language object or a list.
        if ev.get("type") == "languages":
            removed_language_nulls += sanitize_languages(ev.get("data"))
        events.append(ev)
    if insert_at is None:
        insert_at = next((i for i,e in enumerate(events) if e.get("type") in ("state","submissions")), len(events))
    replacement=[]; rejected=[]
    for original in awards:
        award=dict(original)
        requested=[str(t) for t in award.get("team_ids", [])]
        accepted=[t for t in requested if t in valid_team_ids]
        missing=[t for t in requested if t not in valid_team_ids]
        if missing: rejected.append((str(award.get("id")), missing))
        if not accepted: continue
        award["team_ids"]=accepted
        replacement.append({"type":"awards","id":award["id"],"data":award})
    events[insert_at:insert_at]=replacement
    atomic_write_text(dst, "\n".join(json.dumps(e,separators=(",",":"),ensure_ascii=False) for e in events)+"\n")
    return len(replacement), rejected, removed_language_nulls

def resolver_command(package, test):
    sh=ROOT/"resolver.sh"; bat=ROOT/"resolver.bat"
    flags=[]
    if test: flags.append("--test")
    if sh.exists(): return [str(sh), str(package), *flags]
    if bat.exists(): return [str(bat), str(package), *flags]
    raise RuntimeError("resolver.sh or resolver.bat was not found beside this script.")

def phase(number,total,title): print(f"\n[{number}/{total}] {title}")

def parse_args():
    p=argparse.ArgumentParser(description="Download a Kattis contest, build awards/photos, validate, and run ICPC Resolver.")
    p.add_argument("--download-only",action="store_true",help="build and validate the package without launching Resolver")
    p.add_argument("--validate-only",metavar="PACKAGE",help="validate an existing package directory")
    p.add_argument("--launch-only",metavar="PACKAGE",help="launch an existing validated package")
    p.add_argument("--no-popup",action="store_true",help="use terminal prompts without opening Finder/dialogs")
    p.add_argument("--diagnose",action="store_true",help="create a sanitized diagnostic zip")
    p.add_argument("--self-test",action="store_true",help="run built-in offline tests")
    p.add_argument("--version",action="version",version=f"resolver-helper {HELPER_VERSION}")
    return p.parse_args()

def preflight():
    phase(1,6,"Preflight checks")
    checks=[]
    checks.append((sys.version_info >= (3,10),f"Python {platform.python_version()}","Python 3.10 or newer is required"))
    resolver=ROOT/("resolver.bat" if os.name=="nt" else "resolver.sh")
    checks.append((resolver.exists(),resolver.name,f"Missing {resolver.name} beside this script"))
    java=shutil.which("java")
    java_text="Java not found"
    if java:
        try:
            cp=subprocess.run([java,"-version"],capture_output=True,text=True,timeout=10)
            java_text=(cp.stderr or cp.stdout).splitlines()[0]
        except Exception as e: java_text=f"Java check failed: {e}"
    checks.append((bool(java),java_text,"Install Java 17 or newer"))
    writable=os.access(ROOT,os.W_OK)
    checks.append((writable,"Resolver directory writable","Resolver directory is not writable"))
    try: free=shutil.disk_usage(ROOT).free; disk_ok=free >= 1024**3
    except OSError: free=0; disk_ok=False
    checks.append((disk_ok,f"{free/1024**3:.1f} GB free", "At least 1 GB free disk space is required"))
    failures=[]
    for ok,label,fix in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
        if not ok: failures.append(fix)
    if failures: raise RuntimeError("Preflight failed:\n  - "+"\n  - ".join(failures))

def validate_package(package):
    package=Path(package); failures=[]; warnings=[]; stats={}
    def load(name,default):
        path=package/name
        if not path.exists(): failures.append(f"missing {name}"); return default
        try: return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e: failures.append(f"invalid {name}: {e}"); return default
    teams=load("teams.json",[]); problems=load("problems.json",[]); submissions=load("submissions.json",[])
    judgements=load("judgements.json",[]); awards=load("awards.json",[]); scoreboard=load("scoreboard.json",{})
    tids={str(x.get("id")) for x in teams if isinstance(x,dict) and x.get("id") is not None}
    pids={str(x.get("id")) for x in problems if isinstance(x,dict) and x.get("id") is not None}
    sids={str(x.get("id")) for x in submissions if isinstance(x,dict) and x.get("id") is not None}
    award_ids=[]
    for a in awards:
        if not isinstance(a,dict): failures.append("non-object award"); continue
        award_ids.append(str(a.get("id")))
        missing=[str(t) for t in a.get("team_ids",[]) if str(t) not in tids]
        if missing: failures.append(f"award {a.get('id')} has unknown teams: {', '.join(missing)}")
    if len(award_ids)!=len(set(award_ids)): failures.append("duplicate award IDs")
    for x in submissions:
        if str(x.get("team_id")) not in tids: failures.append(f"submission {x.get('id')} has unknown team")
        if str(x.get("problem_id")) not in pids: failures.append(f"submission {x.get('id')} has unknown problem")
    for x in judgements:
        if str(x.get("submission_id")) not in sids: failures.append(f"judgement {x.get('id')} has unknown submission")
    feed=package/"event-feed.ndjson"
    feed_count=0
    if not feed.exists(): failures.append("missing event-feed.ndjson")
    else:
        for no,line in enumerate(feed.read_text(encoding="utf-8").splitlines(),1):
            if not line.strip(): continue
            try: json.loads(line); feed_count+=1
            except Exception as e: failures.append(f"event feed line {no}: {e}")
    if not (scoreboard.get("rows") if isinstance(scoreboard,dict) else None): warnings.append("scoreboard contains no rows")
    stats={"teams":len(tids),"problems":len(pids),"submissions":len(sids),"judgements":len(judgements),"awards":len(awards),"event_feed_events":feed_count}
    report={"helper_version":HELPER_VERSION,"package":str(package),"stats":stats,"failures":failures,"warnings":warnings}
    write_json(package/"validation-report.json",report)
    print("\nPackage validation")
    for k,v in stats.items(): print(f"  [OK] {k.replace('_',' ').title()}: {v}")
    for w in warnings: print(f"  [WARN] {w}")
    for f in failures: print(f"  [FAIL] {f}")
    return not failures,report

def diagnostic_bundle():
    stamp=time.strftime("%Y%m%d-%H%M%S"); out=ROOT/f"resolver-helper-diagnostics-{stamp}.zip"
    cfg=load_config().copy()
    for key in ("key","api_key","password","token"): cfg.pop(key,None)
    diagnostic={"helper_version":HELPER_VERSION,"platform":platform.platform(),"python":platform.python_version(),"config":cfg,
                "files":sorted(x.name for x in ROOT.iterdir())}
    temp=ROOT/f".diagnostics-{stamp}.json"; write_json(temp,diagnostic)
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.write(temp,temp.name)
        for path in ROOT.glob("*-package/validation-report.json"): z.write(path,arcname=f"{path.parent.name}/{path.name}")
        for path in ROOT.glob("logs/*.log"):
            if path.is_file(): z.write(path,arcname=f"logs/{path.name}")
    temp.unlink(missing_ok=True); print(f"Wrote sanitized diagnostics: {out}"); return out

def run_self_tests():
    assert contest_time_seconds("0:20:00.000")==1200.0
    assert safe_id("abc-123")=="abc-123"
    try: safe_id("../bad"); raise AssertionError("unsafe ID accepted")
    except ValueError: pass
    sample=[{"id":"1","name":"A","group_ids":["g"]}]
    sites,assigned,_=resolve_team_sites(sample,[{"id":"g","name":"North","type":"site"}],[])
    assert assigned=={"1":["g"]} and sites["g"]["name"]=="North"
    print("All offline self-tests passed.")

def open_folder(path):
    if ARGS and ARGS.no_popup: return
    try:
        if sys.platform=="darwin": subprocess.run(["open",str(path)],check=False)
        elif os.name=="nt": subprocess.run(["explorer",str(path)],check=False)
        elif shutil.which("xdg-open"): subprocess.run(["xdg-open",str(path)],check=False)
    except OSError: pass

def promote_package(building,final):
    backup=None
    if final.exists():
        backup=ROOT/f"{final.name}-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(final,backup)
    os.replace(building,final)
    backups=sorted(ROOT.glob(f"{final.name}-backup-*"),key=lambda x:x.stat().st_mtime,reverse=True)
    for old in backups[3:]: shutil.rmtree(old,ignore_errors=True)
    return backup

def main():
    global ARGS
    ARGS=parse_args()
    if ARGS.self_test: run_self_tests(); return
    if ARGS.diagnose: diagnostic_bundle(); return
    if ARGS.validate_only:
        ok,_=validate_package(Path(ARGS.validate_only)); raise SystemExit(0 if ok else 1)
    if ARGS.launch_only:
        package=Path(ARGS.launch_only); ok,_=validate_package(package)
        if not ok: raise RuntimeError("Package validation failed; Resolver was not launched")
        raise SystemExit(subprocess.call(resolver_command(package,test=False),cwd=ROOT))
    print(f"ICPC Resolver Helper {HELPER_VERSION}")
    preflight()
    phase(2,6,"Connect to Kattis")
    cfg=load_config()
    while True:
        host=ask("Kattis host (for example https://ncna26.kattis.com)", cfg.get("host"))
        user=ask("API user", cfg.get("user"))
        key=ask("API key", cfg.get("key"), secret=True)
        if not all((host,user,key)): print("Host, API user, and key are required."); continue
        api=normalized_api(host); print(f"API base: {api}")
        if confirm("Use these Kattis settings?"): break
    client=Client(api,user,key)
    contest=choose_contest(client,cfg.get("contest_id")); cid=safe_id(contest["id"])
    cfg.update(host=host.rstrip("/"),user=user,key=key,contest_id=cid); save_config(cfg)
    base=urljoin(api, f"contests/{cid}")
    package=ROOT/f"{cid}-package"; package.mkdir(exist_ok=True)
    print(f"\nRefreshing package: {package}")
    contest_data=client.json(base); write_json(package/"contest.json", contest_data)
    state={}; assets=0; teams=[]; groups=[]; organizations=[]; scoreboard={}; contest_data={}
    submissions=[]; judgements=[]; judgement_types=[]; problems=[]
    for name in COLLECTIONS:
        try:
            data=client.json(base+f"/{name}")
            if name=="languages":
                collection_language_fixes=sanitize_languages(data)
                if collection_language_fixes:
                    print(f"  sanitized {collection_language_fixes} null language command field(s) in languages.json")
            write_json(package/f"{name}.json",data)
            if name=="state" and isinstance(data,dict): state=data
            if name=="teams" and isinstance(data,list): teams=data
            if name=="groups" and isinstance(data,list): groups=data
            if name=="organizations" and isinstance(data,list): organizations=data
            if name=="scoreboard" and isinstance(data,dict): scoreboard=data
            if name=="submissions" and isinstance(data,list): submissions=data
            if name=="judgements" and isinstance(data,list): judgements=data
            if name=="judgement-types" and isinstance(data,list): judgement_types=data
            if name=="problems" and isinstance(data,list): problems=data
            if name in ("organizations","teams"): assets += download_assets(client,base,name,data,package)
            print(f"  downloaded {name}")
        except HTTPError as e:
            if e.code in (403,404): print(f"  skipped {name} (HTTP {e.code})")
            else: raise
    phase(4,6,"Prepare team photos")
    staging, photo_manifest = prepare_photo_staging(package, teams, groups, cid)
    photo_message = (
        "Team photo staging folders are ready.\n\n"
        f"Location: {staging}\n\n"
        "Copy photos into the appropriate team folders now. "
        "Leave a folder empty when no photo is available. "
        "The first supported image alphabetically will be converted to JPEG and copied into the Resolver package."
    )
    print("\n" + "=" * 72)
    print(photo_message)
    print("=" * 72)
    # On macOS, show a visible modal dialog and open the staging directory in Finder.
    if sys.platform == "darwin":
        try:
            open_folder(staging)
            if not (ARGS and ARGS.no_popup): subprocess.run([
                "osascript", "-e",
                'display dialog ' + json.dumps(photo_message) +
                ' with title "ICPC Resolver Helper - Team Photos" buttons {"Continue"} default button "Continue" with icon note'
            ], check=False)
        except OSError as e:
            print(f"  Could not show the macOS photo dialog: {e}")
    while not confirm("Have you finished placing team photos in the staging folders?", default=False):
        print(f"Photo processing is paused. Add photos under: {staging}")
        if sys.platform == "darwin":
            open_folder(staging)
    photo_result=install_staged_photos(package, photo_manifest)
    print("\nTeam photo summary")
    print(f"  Installed: {len(photo_result['installed'])}")
    print(f"  Empty folders: {len(photo_result['empty'])}")
    print(f"  Invalid/skipped: {len(photo_result['skipped'])}")
    print(f"  Multiple-image folders: {len(photo_result['multiple'])}")
    for tid,chosen,ignored in photo_result["multiple"]: print(f"    {tid}: selected {chosen}; ignored {', '.join(ignored)}")
    for tid,name,reason in photo_result["skipped"]: print(f"    skipped {tid}/{name}: {reason}")
    if not confirm("Continue with these photo selections?",default=True): raise RuntimeError("Cancelled after photo review")
    phase(5,6,"Generate awards and validate")
    raw=package/"event-feed.ndjson"; feed_count=download_feed(client,base+"/event-feed",raw)
    print(f"  downloaded event feed ({feed_count} events) and {assets} API assets")
    award_policy=load_award_policy()
    automatic_sites=fetch_kattis_site_assignments(client,host,cid,teams)
    configured_sites=automatic_sites + load_site_config()
    discovered_site_defs, discovered_team_sites, _=resolve_team_sites(teams,groups,configured_sites)
    valid_team_ids_for_sites={str(t.get("id")) for t in teams if isinstance(t,dict) and t.get("id") is not None}
    mapped_team_ids={tid for tid,site_ids in discovered_team_sites.items() if site_ids}
    unmatched_site_ids=sorted(valid_team_ids_for_sites-mapped_team_ids)
    mapping_pct=(100.0*len(mapped_team_ids)/len(valid_team_ids_for_sites)) if valid_team_ids_for_sites else 0.0
    print(f"  site mapping coverage: {len(mapped_team_ids)}/{len(valid_team_ids_for_sites)} teams ({mapping_pct:.1f}%)")
    multi_site={tid:ids for tid,ids in discovered_team_sites.items() if len(set(ids))>1}
    if multi_site:
        raise RuntimeError("Site mapping assigned teams to multiple sites: "+", ".join(sorted(multi_site)))
    if mapping_pct < 95.0:
        raise RuntimeError(f"Site mapping coverage is only {mapping_pct:.1f}%; refusing to generate potentially wrong site awards")
    if unmatched_site_ids:
        print("  WARNING: unmatched site team IDs: "+", ".join(unmatched_site_ids))
        if not confirm("Generate site awards with incomplete mappings?",default=False):
            raise RuntimeError("Cancelled because site mappings were incomplete")
    awards, award_audit=generate_awards(award_policy,scoreboard,teams,groups,organizations,configured_sites)
    fun_awards, fun_audit=generate_fun_awards(award_policy,submissions,judgements,judgement_types,
                                              problems,teams,scoreboard,contest_data,state)
    awards.extend(fun_awards)
    write_json(package/"awards.json",awards)
    write_json(package/"award-debug.json",award_audit)
    write_json(package/"fun-award-debug.json",fun_audit)
    site_defs, team_sites, _=resolve_team_sites(teams,groups,configured_sites)
    site_report=[]
    teams_by_id_report={str(t.get("id")):t for t in teams if isinstance(t,dict) and t.get("id") is not None}
    for sid,site in sorted(site_defs.items(),key=lambda x:x[1]["name"].casefold()):
        members=[]
        for tid,site_ids in team_sites.items():
            if sid in site_ids:
                team=teams_by_id_report.get(tid,{})
                row=next((r for r in scoreboard.get("rows",[]) if str(r.get("team_id"))==tid),{}) if isinstance(scoreboard,dict) else {}
                score=row.get("score") or {}
                members.append({"team_id":tid,"team_name":team.get("name"),"organization_id":team.get("organization_id"),
                                "official_rank":row.get("rank"),"num_solved":score.get("num_solved"),"total_time":score.get("total_time")})
        members.sort(key=lambda x:(x["official_rank"] is None,x["official_rank"] if x["official_rank"] is not None else 10**9,str(x["team_id"])))
        site_awards=[a for a in awards if a.get("id")==f"group-winner-{sid}" or str(a.get("id","")).startswith(f"site-{sid}-place-")]
        site_report.append({**site,"award_count":len(site_awards),
                            "award_recipients":[{"award_id":a.get("id"),"citation":a.get("citation"),"team_ids":a.get("team_ids",[])} for a in site_awards],
                            "selection_basis":"official scoreboard rank","teams":members})
    write_json(package/"site-debug.json",site_report)
    print(f"  generated {len(awards)} awards: top {award_policy['top_overall']} overall, top team per site, and top team per school")
    site_award_count=sum(1 for a in awards if str(a.get("id","")).startswith("group-winner-") or str(a.get("id","")).startswith("site-"))
    print(f"  generated {len(fun_awards)} submission-based fun awards")
    print(f"  generated {site_award_count} site placement awards from {len(site_defs)} mapped sites")
    print(f"  award audits written to {package / 'award-debug.json'} {package / 'fun-award-debug.json'}, and {package / 'site-debug.json'}")
    valid_team_ids={str(t["id"]) for t in teams if isinstance(t,dict) and t.get("id") is not None}
    fixed=package/"event-feed.fixed.ndjson"
    award_count, rejected_awards, language_fixes=patch_awards(raw,fixed,awards,valid_team_ids)
    # Resolver package convention: event-feed.ndjson is the active feed; keep the original as a timestamped backup.
    backup=package/f"event-feed.kattis.{time.strftime('%Y%m%d-%H%M%S')}.ndjson"
    shutil.copy2(raw,backup); shutil.copy2(fixed,raw)
    print(f"  replaced Kattis award events with {award_count} automatically generated awards")
    if language_fixes:
        print(f"  removed {language_fixes} null language command field(s) that Resolver 2.7.1444 cannot parse")
    if rejected_awards:
        print("  WARNING: awards.json contains team IDs not in this contest; those assignments were removed:")
        for award_id, missing in rejected_awards:
            print(f"    {award_id}: {', '.join(missing)}")
    finalized=bool(state.get("finalized"))
    if not finalized:
        print("\nWARNING: Results are not finalized. Resolver will run in TEST mode.")
    cmd=resolver_command(package, test=not finalized)
    print("Running:", " ".join(cmd))
    if ARGS.download_only:
        print("Package built and validated; --download-only skipped Resolver launch.")
        return
    if confirm("Launch ICPC Resolver now?"):
        raise SystemExit(subprocess.call(cmd,cwd=ROOT))
    print("Package is ready; Resolver was not launched.")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nCancelled."); raise SystemExit(130)
    except (HTTPError,URLError,RuntimeError,ValueError,json.JSONDecodeError) as e:
        print(f"\nERROR: {e}",file=sys.stderr); raise SystemExit(1)
