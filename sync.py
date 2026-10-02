#!/usr/bin/env python3
"""把 iCloud / Outlook 的公开日历同步成冰箱日历能读的 JSON。

放在 calendar-data 仓库 的根目录，由同仓库的 .github/workflows/sync.yml 定时运行。
读取 main.json 里的 settings.icsUrl / settings.outlookUrl，
写出 icloud.json / outlook.json：{"updatedAt": ISO, "items": [{d,t,s,e,ad,l}]}。
展开范围：过去 30 天到未来 180 天；时间统一换算成温哥华时间；重复日程会被展开成一条条。
也可以本地测试：python3 sync.py --test 某个.ics
依赖：pip install icalendar recurring-ical-events
"""
import sys, os, json, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import icalendar, recurring_ical_events

TZ = ZoneInfo("America/Vancouver")
FEEDS = [("icloud", "icsUrl"), ("outlook", "outlookUrl")]
REFRESH_HOURS = 24  # 内容没变也至少每天写一次，页面上能看出同步还活着


def fetch(src):
    if src.startswith(("webcal://", "http://", "https://")):
        url = "https://" + src.split("://", 1)[1]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (fridge-calendar sync)"})
        return urllib.request.urlopen(req, timeout=60).read()
    return open(src, "rb").read()


def expand(raw, now=None):
    cal = icalendar.Calendar.from_ical(raw)
    now = now or dt.datetime.now(TZ)
    start, end = (now - dt.timedelta(days=30)).date(), (now + dt.timedelta(days=180)).date()
    items = []
    for ev in recurring_ical_events.of(cal).between(start, end + dt.timedelta(days=1)):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        title = (str(ev.get("SUMMARY", "") or "").strip() or "（无标题）")[:80]
        loc = str(ev.get("LOCATION", "") or "").strip()[:80]
        ds = ev["DTSTART"].dt
        de = ev["DTEND"].dt if ev.get("DTEND") else None
        if isinstance(ds, dt.datetime):
            ds = (ds if ds.tzinfo else ds.replace(tzinfo=TZ)).astimezone(TZ)
            if isinstance(de, dt.datetime):
                de = (de if de.tzinfo else de.replace(tzinfo=TZ)).astimezone(TZ)
            else:
                de = ds
            day = ds.date()
            while day <= de.date():
                first, last = day == ds.date(), day == de.date()
                if not (last and not first and de.time() == dt.time(0)):  # 结束在午夜的不算进第二天
                    items.append({"d": day.isoformat(), "t": title, "l": loc, "ad": not first and not last,
                                  "s": ds.strftime("%H:%M") if first else ("00:00" if last else ""),
                                  "e": de.strftime("%H:%M") if last and de > ds else ""})
                day += dt.timedelta(days=1)
        else:  # 全天；DTEND 是不含的那一天
            de = de if isinstance(de, dt.date) and de > ds else ds + dt.timedelta(days=1)
            day = ds
            while day < de:
                items.append({"d": day.isoformat(), "t": title, "l": loc, "ad": True, "s": "", "e": ""})
                day += dt.timedelta(days=1)
    lo, hi = start.isoformat(), end.isoformat()
    items = [i for i in items if lo <= i["d"] <= hi]
    items.sort(key=lambda i: (i["d"], not i["ad"], i["s"], i["t"]))
    return items[:1500]


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        items = expand(fetch(sys.argv[2]))
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return
    if not os.path.exists("main.json"):
        print("main.json 还不存在，跳过。")
        return
    settings = json.load(open("main.json", encoding="utf-8")).get("settings") or {}
    now = dt.datetime.now(dt.timezone.utc)
    for name, key in FEEDS:
        out, url = name + ".json", (settings.get(key) or "").strip()
        if not url:
            if os.path.exists(out):
                os.remove(out)
                print(f"{name}: 链接已清空，删除 {out}")
            continue
        try:
            items = expand(fetch(url))
        except Exception as e:  # 一个源失败不影响另一个；保留上次的结果
            print(f"::warning::{name} 同步失败：{type(e).__name__}: {str(e)[:200]}")
            continue
        old = None
        if os.path.exists(out):
            try:
                old = json.load(open(out, encoding="utf-8"))
            except Exception:
                old = None
        if old and old.get("items") == items:
            try:
                age = now - dt.datetime.fromisoformat(old["updatedAt"])
            except Exception:
                age = dt.timedelta(days=9)
            if age < dt.timedelta(hours=REFRESH_HOURS):
                print(f"{name}: {len(items)} 条，没有变化")
                continue
        json.dump({"updatedAt": now.isoformat(), "items": items}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{name}: {len(items)} 条 -> {out}")


if __name__ == "__main__":
    main()
