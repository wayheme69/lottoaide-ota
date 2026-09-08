#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_de.py — met à jour eurojackpot.csv + lotto6aus49.csv pour LOTTO AI DE (iOS + Android).

Pourquoi (08/09/2026) : les apps DE lisaient DIRECTEMENT deux CSV tiers
(asderfvfv/eurojackpot-data, daowa89/lottery-archive) sans secours ; le 04/09 le
CSV EuroJackpot a eu 3 j de retard → résultats en retard chez les utilisateurs.
Ce robot fusionne 3 sources par loterie, ne publie que des données VALIDES,
échoue BRUYAMMENT (Action rouge → mail) seulement si TOUTES les sources sont
périmées, et garde le MÊME format CSV que les sources d'origine (parsers des
apps inchangés ; anciens CSV = secours dans l'app).

  • EuroJackpot (mar/ven) : asderfvfv CSV + euro-jackpot.net/results (10 tirages
    HTML) + Lottoland euroJackpot (dernier).
  • Lotto 6aus49 (mer/sam) : daowa89 CSV + lottozahlenonline.de (archive HTML,
    ~70 tirages de l'année) + Lottoland german6aus49 (dernier).

Sorties (ordre chronologique, 40 dernières lignes) :
  eurojackpot.csv  : Date,Main1,Main2,Main3,Main4,Main5,Euro1,Euro2
  lotto6aus49.csv  : date,n1,n2,n3,n4,n5,n6,superzahl
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

EJ_CSV = "https://raw.githubusercontent.com/asderfvfv/eurojackpot-data/main/data/eurojackpot_draws.csv"
EJNET = "https://www.euro-jackpot.net/results"
LOTTOLAND_EJ = "https://media.lottoland.com/api/drawings/euroJackpot"

L49_CSV = "https://raw.githubusercontent.com/daowa89/lottery-archive/main/de/lotto_6aus49/results.csv"
LZO = "https://www.lottozahlenonline.de/statistik/beide-spieltage/lottozahlen-archiv.php"
LOTTOLAND_49 = "https://media.lottoland.com/api/drawings/german6aus49"

EJ_FILE, EJ_HEADER = "eurojackpot.csv", "Date,Main1,Main2,Main3,Main4,Main5,Euro1,Euro2"
L49_FILE, L49_HEADER = "lotto6aus49.csv", "date,n1,n2,n3,n4,n5,n6,superzahl"
CAP = 40


def max_date():
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def curl(url, extra=None, timeout=60):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0 (results-bot)"] + (extra or []) + [url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 20)
    return r.stdout if r.returncode == 0 else ""


def lottoland(url):
    body = curl(url)
    return json.loads(body).get("last") or {} if body.startswith("{") else {}


def ll_date(last):
    dd = last.get("date") or {}
    if {"year", "month", "day"} <= set(dd):
        return f"{dd['year']:04d}-{dd['month']:02d}-{dd['day']:02d}"
    return None


# ----------------------------- EuroJackpot -----------------------------

def ej_row(d, nums, euros, src):
    nums, euros = sorted(nums), sorted(euros)
    if not ("2012-01-01" <= d <= max_date()):
        raise SystemExit(f"EJ {src}: date hors plage {d}")
    if len(set(nums)) != 5 or not all(1 <= n <= 50 for n in nums) \
            or len(set(euros)) != 2 or not all(1 <= e <= 12 for e in euros):
        raise SystemExit(f"EJ {src}: valeurs invalides {d}: {nums}+{euros}")
    return d, nums + euros


def ej_csv():
    lines = curl(EJ_CSV).strip().splitlines()
    if len(lines) < 100 or not lines[0].startswith("Date,"):
        print("  EJ csv: illisible", file=sys.stderr)
        return []
    out = []
    for line in lines[-40:]:
        c = line.split(",")
        if len(c) == 8 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0]):
            out.append(ej_row(c[0], [int(x) for x in c[1:6]], [int(x) for x in c[6:8]], "csv"))
    return out


EJNET_BLOCK = re.compile(r'<div class="date sprite">(.*?)</div>(.*?)</ul>', re.S)
EJNET_BALL = re.compile(r'<li class="(ball|euro)[^"]*"><span>(\d{1,2})</span></li>')


def ej_net():
    html = curl(EJNET)
    if "euro-jackpot" not in html:
        html = curl(f"https://r.jina.ai/{EJNET}", ["-H", "X-Return-Format: html"], 90)
    out = []
    for dtxt, body in EJNET_BLOCK.findall(html):
        dtxt = re.sub(r"<[^>]+>", " ", dtxt)
        m = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})", dtxt)
        if not m or m.group(2) not in MONTHS:
            continue
        d = f"{int(m.group(3)):04d}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
        balls = EJNET_BALL.findall(body)
        nums = [int(n) for k, n in balls if k == "ball"]
        euros = [int(n) for k, n in balls if k == "euro"]
        if len(nums) == 5 and len(euros) == 2:
            out.append(ej_row(d, nums, euros, "ejnet"))
    return out


def ej_lottoland():
    last = lottoland(LOTTOLAND_EJ)
    d = ll_date(last)
    nums = [int(x) for x in (last.get("numbers") or [])]
    euros = [int(x) for x in (last.get("euroNumbers") or [])]
    return [ej_row(d, nums, euros, "lottoland")] if d and len(nums) == 5 and len(euros) == 2 else []


# ----------------------------- Lotto 6aus49 -----------------------------

def l49_row(d, nums, sz, src):
    nums = sorted(nums)
    if not ("1955-01-01" <= d <= max_date()):
        raise SystemExit(f"6aus49 {src}: date hors plage {d}")
    if len(set(nums)) != 6 or not all(1 <= n <= 49 for n in nums) or not (0 <= sz <= 9):
        raise SystemExit(f"6aus49 {src}: valeurs invalides {d}: {nums} SZ{sz}")
    return d, nums + [sz]


def l49_csv():
    lines = curl(L49_CSV).strip().splitlines()
    if len(lines) < 100 or not lines[0].startswith("date,"):
        print("  6aus49 csv: illisible", file=sys.stderr)
        return []
    out = []
    for line in lines[-40:]:
        c = line.split(",")
        if len(c) == 8 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0]) and c[7].strip() != "":
            out.append(l49_row(c[0], [int(x) for x in c[1:7]], int(c[7]), "csv"))
    return out


LZO_DATE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})"')
LZO_NUM = re.compile(r'class="zahlensuche_zahl">(\d{1,2})<')
LZO_SZ = re.compile(r'class="zahlensuche_zz">(\d)<')


def l49_lzo():
    html = curl(LZO)
    if "zahlensuche_rahmen" not in html:
        html = curl(f"https://r.jina.ai/{LZO}", ["-H", "X-Return-Format: html"], 90)
    out = []
    for chunk in re.split(r'(?=<div class="zahlensuche_rahmen">)', html):
        md, nums, msz = LZO_DATE.search(chunk), LZO_NUM.findall(chunk), LZO_SZ.search(chunk)
        if md and len(nums) == 6 and msz:
            out.append(l49_row(md.group(1), [int(x) for x in nums], int(msz.group(1)), "lzo"))
    return out


def l49_lottoland():
    last = lottoland(LOTTOLAND_49)
    d = ll_date(last)
    nums = [int(x) for x in (last.get("numbers") or [])]
    sz = last.get("superzahl")
    return [l49_row(d, nums, int(sz), "lottoland")] if d and len(nums) == 6 and sz is not None else []


# ----------------------------- Assemblage -----------------------------

def gather(label, sources, max_age):
    """Fusionne les sources ; désaccord sur une date = erreur ; rouge si TOUT est périmé."""
    by = {}
    for name, fn in sources:
        try:
            got = fn()
        except SystemExit:
            raise
        except Exception as e:  # réseau/parse d'UNE source -> suivante
            print(f"  {label} {name}: {e}", file=sys.stderr)
            got = []
        for d, vals in got:
            if d in by and by[d] != vals:
                raise SystemExit(f"{label}: sources en désaccord le {d}: {by[d]} vs {vals} ({name})")
            by.setdefault(d, vals)
        print(f"  {label} {name}: {len(got)} tirage(s)", file=sys.stderr)
    if not by:
        raise SystemExit(f"{label}: aucun tirage parsé (3 sources KO)")
    latest = max(by)
    age = (datetime.now(timezone.utc).date() - datetime.strptime(latest, "%Y-%m-%d").date()).days
    if age > max_age:
        raise SystemExit(f"{label}: les 3 sources sont périmées — dernier tirage {latest} ({age} j)")
    return by


def read_csv(path, ncols):
    by = {}
    try:
        for line in open(path).read().splitlines()[1:]:
            c = line.split(",")
            if len(c) == ncols and re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0]):
                by[c[0]] = [int(x) for x in c[1:]]
    except (OSError, ValueError):
        pass
    return by


def write_csv(path, header, fresh, ncols):
    old = read_csv(path, ncols)
    merged = {**old, **fresh}
    rows = sorted(merged.items())[-CAP:]
    text = header + "\n" + "\n".join(d + "," + ",".join(str(v) for v in vals) for d, vals in rows) + "\n"
    try:
        if open(path).read() == text:
            return False
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)
    return True


ej = gather("EJ", [("csv", ej_csv), ("ejnet", ej_net), ("lottoland", ej_lottoland)], max_age=6)
l49 = gather("6aus49", [("csv", l49_csv), ("lzo", l49_lzo), ("lottoland", l49_lottoland)], max_age=5)

changed = write_csv(EJ_FILE, EJ_HEADER, ej, 8)
changed = write_csv(L49_FILE, L49_HEADER, l49, 8) or changed
if not changed:
    print("Aucune nouvelle donnée — CSV inchangés.", file=sys.stderr)
    raise SystemExit(0)
print(f"OK: EJ {max(ej)} {ej[max(ej)]}; 6aus49 {max(l49)} {l49[max(l49)]}", file=sys.stderr)
