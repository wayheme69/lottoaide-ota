#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quoten_de.py — fabrique de_results.json pour LOTTO AI DE v6 : les 30 derniers tirages
(numéros pris dans eurojackpot.csv / lotto6aus49.csv, déjà validés par update_de.py)
+ les VRAIES quotes officielles par classe (Gewinnquoten), gardées d'un passage à l'autre.

  Source principale : API officielle lotto.de (archive par date, les deux jeux) —
    entities.lotto/draws/{ms} et entities.eurojackpot/draw/{ms} ({ms} = minuit Berlin).
  Secours :
  • Eurojackpot : page du tirage sur euro-jackpot.net (tableau « Gewinner insgesamt »).
  • Lotto 6aus49 : lottozahlenonline.de/lotto-gewinnquoten.php (quotes du DERNIER tirage).
  Dans tous les cas, les numéros de la source doivent être ceux du CSV, sinon on ignore.
  Quotes 6aus49 : samedi publiées le lundi, mercredi le jeudi (lotto.de).

Clés des classes : Lotto « 6+1 » … « 2+1 » (9 classes), Eurojackpot « 5+2 » … « 2+1 » (12).
Une classe sans gagnant (« Unbesetzt ») → montant null.
Ce script n'échoue JAMAIS le workflow : en cas de souci il garde les quotes déjà connues.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

N = 30
OUT = "de_results.json"


def curl(url, timeout=60):
    for target, extra in ((url, []), (f"https://r.jina.ai/{url}", ["-H", "X-Return-Format: html"])):
        r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0 (results-bot)"] + extra + [target],
                           capture_output=True, text=True, timeout=timeout + 20)
        if r.returncode == 0 and len(r.stdout) > 2000 and "Gewinn" in r.stdout:
            return r.stdout
    return ""


def read_csv(path, nmain):
    rows = []
    for line in open(path).read().splitlines()[1:]:
        c = line.split(",")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0]) and len(c) >= 1 + nmain:
            nums = [int(x) for x in c[1:1 + nmain]]
            bonus = [int(x) for x in c[1 + nmain:] if x.strip() != ""]
            rows.append((c[0], sorted(nums), sorted(bonus)))
    return sorted(rows)[-N:]


def money(s):
    s = s.replace("&euro;", "").replace("€", "").strip()
    if not re.search(r"\d", s):
        return None
    return round(float(s.replace(".", "").replace(",", ".")), 2)


def cells(html):
    t = re.sub(r"&shy;|&nbsp;", "", html)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", t, re.S)]


def lottode(game, d):
    """Quotes officielles lotto.de pour le tirage du jour d (ISO) ; None si absentes."""
    y, m, dd = (int(x) for x in d.split("-"))
    ms = int(datetime(y, m, dd, tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)
    path = f"entities.lotto/draws/{ms}" if game == "lotto" else f"entities.eurojackpot/draw/{ms}"
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (results-bot)",
                        f"https://www.lotto.de/api/stats/{path}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip().startswith(("{", "[")):
        return None
    j = json.loads(r.stdout)
    x = j[0] if isinstance(j, list) and j else j
    if not isinstance(x, dict) or not x.get("oddsCollection"):
        return None
    coll = x.get("drawNumbersCollection") or []
    if game == "lotto":
        nums = sorted(n["drawNumber"] for n in coll)
        bonus = [x.get("superNumber")]
        keys = ["6+1", "6+0", "5+1", "5+0", "4+1", "4+0", "3+1", "3+0", "2+1"]
    else:
        nums = sorted(n["drawNumber"] for n in coll if n.get("drawNumberType") == 0)
        bonus = sorted(n["drawNumber"] for n in coll if n.get("drawNumberType") == 1)
        keys = ["5+2", "5+1", "5+0", "4+2", "4+1", "3+2", "4+0", "2+2", "3+1", "3+0", "1+2", "2+1"]
    pay, win = {}, {}
    for o in x["oddsCollection"]:
        c = o.get("winningClass")
        if isinstance(c, int) and 1 <= c <= len(keys):
            k = keys[c - 1]
            win[k] = int(o.get("numberOfWinners") or 0)
            pay[k] = round(float(o["odds"]), 2) if win[k] > 0 and o.get("odds") else None
    if len(pay) != len(keys):
        return None
    return nums, bonus, pay, win


EJ_KEYS = {"5 Richtige + 2 Eurozahlen": "5+2", "5 Richtige + 1 Eurozahl": "5+1", "5 Richtige": "5+0",
           "4 Richtige + 2 Eurozahlen": "4+2", "4 Richtige + 1 Eurozahl": "4+1", "3 Richtige + 2 Eurozahlen": "3+2",
           "4 Richtige": "4+0", "2 Richtige + 2 Eurozahlen": "2+2", "3 Richtige + 1 Eurozahl": "3+1",
           "3 Richtige": "3+0", "1 Richtige + 2 Eurozahlen": "1+2", "2 Richtige + 1 Eurozahl": "2+1"}


def ej_quoten(d, nums, euros):
    y, m, dd = d.split("-")
    h = curl(f"https://www.euro-jackpot.net/de/gewinnzahlen/{dd}-{m}-{y}")
    if not h:
        return None
    balls = sorted(int(x) for x in re.findall(r'<li class="ball[^"]*"><span>(\d+)</span>', h)[:5])
    eur = sorted(int(x) for x in re.findall(r'<li class="euro[^"]*"><span>(\d+)</span>', h)[:2])
    if balls != nums or eur != euros:
        print(f"  EJ {d}: numéros de la page ≠ CSV ({balls}+{eur}) — ignoré", file=sys.stderr)
        return None
    tables = re.findall(r"<table.*?</table>", h, re.S)
    if not tables:
        return None
    c = cells(tables[0])
    pay, win = {}, {}
    for i, lab in enumerate(c):
        if lab in EJ_KEYS and i + 2 < len(c):
            k = EJ_KEYS[lab]
            w = c[i + 2].replace(".", "")
            win[k] = int(w) if w.isdigit() else 0
            pay[k] = money(c[i + 1]) if win[k] > 0 else None
    if len(pay) != 12:
        print(f"  EJ {d}: tableau incomplet ({len(pay)} classes) — ignoré", file=sys.stderr)
        return None
    return pay, win


L_KEYS = {"6 Richtige + Sz": "6+1", "6 Richtige": "6+0", "5 Richtige + Sz": "5+1", "5 Richtige": "5+0",
          "4 Richtige + Sz": "4+1", "4 Richtige": "4+0", "3 Richtige + Sz": "3+1", "3 Richtige": "3+0",
          "2 Richtige + Sz": "2+1"}


def lotto_quoten():
    h = curl("https://www.lottozahlenonline.de/lotto-gewinnquoten.php")
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    m = re.search(r"Lotto Gewinnquoten vom (\d{2})\.(\d{2})\.(\d{4})", txt)
    tables = re.findall(r"<table.*?</table>", h, re.S)
    if not m or not tables:
        return None, None
    d = f"{m[3]}-{m[2]}-{m[1]}"
    c = cells(tables[0])
    pay, win = {}, {}
    for i, lab in enumerate(c):
        if lab in L_KEYS and i + 2 < len(c):
            k = L_KEYS[lab]
            w = c[i + 1].replace(".", "")
            win[k] = int(w) if w.isdigit() else 0
            pay[k] = money(c[i + 2]) if win[k] > 0 else None
    return (d, (pay, win)) if len(pay) == 9 else (None, None)


def main():
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    known = {g: {e["date"]: e for e in old.get(g, [])} for g in ("lotto6aus49", "eurojackpot")}

    ej = read_csv("eurojackpot.csv", 5)
    lo = read_csv("lotto6aus49.csv", 6)

    out = {"source": "Gewinnzahlen und Quoten: lotto.de (offiziell), Ersatz: euro-jackpot.net, lottozahlenonline.de",
           "eurojackpot": [], "lotto6aus49": []}
    fetched = 0
    for d, nums, bonus in reversed(ej):
        e = {"date": d, "numbers": nums, "bonus": bonus}
        prev = known["eurojackpot"].get(d)
        if prev and prev.get("payouts") and prev["numbers"] == nums:
            e["payouts"], e["winners"] = prev["payouts"], prev.get("winners")
        elif fetched < 30:
            fetched += 1
            q = None
            try:
                r = lottode("eurojackpot", d)
                if r and r[0] == nums and r[1] == bonus:
                    q = (r[2], r[3])
                elif r:
                    print(f"  EJ {d}: lotto.de numéros ≠ CSV — ignoré", file=sys.stderr)
            except Exception as ex:
                print(f"  EJ {d} lotto.de: {ex}", file=sys.stderr)
            if not q:
                try:
                    q = ej_quoten(d, nums, bonus)
                except Exception as ex:
                    print(f"  EJ {d}: {ex}", file=sys.stderr)
            if q:
                e["payouts"], e["winners"] = q
        out["eurojackpot"].append(e)

    try:
        qd, q = lotto_quoten()
    except Exception as ex:
        print(f"  6aus49 quoten: {ex}", file=sys.stderr); qd, q = None, None
    fetched = 0
    for d, nums, bonus in reversed(lo):
        e = {"date": d, "numbers": nums, "bonus": bonus}
        prev = known["lotto6aus49"].get(d)
        if prev and prev.get("payouts") and prev["numbers"] == nums:
            e["payouts"], e["winners"] = prev["payouts"], prev.get("winners")
        elif fetched < 30:
            fetched += 1
            try:
                r = lottode("lotto", d)
                if r and r[0] == nums and r[1] == bonus:
                    e["payouts"], e["winners"] = r[2], r[3]
            except Exception as ex:
                print(f"  6aus49 {d} lotto.de: {ex}", file=sys.stderr)
        if not e.get("payouts") and d == qd and q:
            e["payouts"], e["winners"] = q
        out["lotto6aus49"].append(e)

    text = json.dumps(out, ensure_ascii=False, indent=1)
    try:
        if open(OUT).read() == text:
            print("de_results.json inchangé", file=sys.stderr); return
    except OSError:
        pass
    open(OUT, "w").write(text)
    n_ej = sum(1 for e in out["eurojackpot"] if e.get("payouts"))
    n_lo = sum(1 for e in out["lotto6aus49"] if e.get("payouts"))
    print(f"de_results.json écrit — EJ {len(out['eurojackpot'])} tirages ({n_ej} avec quotes), "
          f"6aus49 {len(out['lotto6aus49'])} ({n_lo} avec quotes)", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:   # ne jamais casser le workflow des CSV
        print(f"quoten_de: {ex}", file=sys.stderr)
