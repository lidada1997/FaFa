import random
from time import time, localtime, sleep
import cityinfo
from requests import get, post
from datetime import datetime, date, timezone, timedelta
from zhdate import ZhDate
import sys
import os

# 北京时区（GitHub Actions 的 ubuntu runner 默认 UTC）
BEIJING_TZ = timezone(timedelta(hours=8))


def wait_until_push_time(target_hour=8, target_minute=0):
    """等到北京时间指定时刻再推送；若已过该时刻则立即推送。
    用于规避 GitHub Actions cron 的延迟：cron 提前到目标时刻前触发，
    这里精确等待到目标时刻再发送，把不可控的 cron 延迟转化为可控的程序内等待。"""
    now = datetime.now(BEIJING_TZ)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if now >= target:
        print(f"当前北京时间 {now.strftime('%Y-%m-%d %H:%M:%S')}，已过 {target_hour:02d}:{target_minute:02d}，立即推送")
        return
    delta = int((target - now).total_seconds())
    print(f"当前北京时间 {now.strftime('%H:%M:%S')}，等待 {delta} 秒（约 {delta // 60} 分钟）到 {target_hour:02d}:{target_minute:02d} 再推送")
    sleep(delta)


def get_access_token():
    # appId
    app_id = config["app_id"]
    # appSecret
    app_secret = config["app_secret"]
    post_url = ("https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={}&secret={}"
                .format(app_id, app_secret))
    try:
        access_token = get(post_url).json()['access_token']
    except KeyError:
        print("获取access_token失败，请检查app_id和app_secret是否正确")
        os.system("pause")
        sys.exit(1)
    # print(access_token)
    return access_token


def get_weather(province, city):
    # 城市id
    try:
        city_id = cityinfo.cityInfo[province][city]["AREAID"]
    except KeyError:
        print("推送消息失败，请检查省份或城市是否正确")
        os.system("pause")
        sys.exit(1)
    # city_id = 101280101
    # 毫秒级时间戳
    t = (int(round(time() * 1000)))
    headers = {
        "Referer": "http://www.weather.com.cn/weather1d/{}.shtml".format(city_id),
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'
    }
    url = "http://d1.weather.com.cn/dingzhi/{}.html?_={}".format(city_id, t)
    response = get(url, headers=headers)
    response.encoding = "utf-8"
    response_data = response.text.split(";")[0].split("=")[-1]
    response_json = eval(response_data)
    # print(response_json)
    weatherinfo = response_json["weatherinfo"]
    # 天气
    weather = weatherinfo["weather"]
    # 最高气温
    temp = weatherinfo["temp"]
    # 最低气温
    tempn = weatherinfo["tempn"]
    return weather, temp, tempn


def get_birthday(birthday, year, today):
    birthday_year = birthday.split("-")[0]
    # 判断是否为农历生日
    if birthday_year[0] == "r":
        r_mouth = int(birthday.split("-")[1])
        r_day = int(birthday.split("-")[2])
        # 今年生日
        birthday = ZhDate(year, r_mouth, r_day).to_datetime().date()
        year_date = birthday
    else:
        # 获取国历生日的今年对应月和日
        birthday_month = int(birthday.split("-")[1])
        birthday_day = int(birthday.split("-")[2])
        # 今年生日
        year_date = date(year, birthday_month, birthday_day)
    # 计算生日年份，如果还没过，按当年减，如果过了需要+1
    if today > year_date:
        if birthday_year[0] == "r":
            # 获取农历明年生日的月和日
            r_last_birthday = ZhDate((year + 1), r_mouth, r_day).to_datetime().date()
            birth_date = date((year + 1), r_last_birthday.month, r_last_birthday.day)
        else:
            birth_date = date((year + 1), birthday_month, birthday_day)
        birth_day = str(birth_date.__sub__(today)).split(" ")[0]
    elif today == year_date:
        birth_day = 0
        birth_date = year_date
    else:
        birth_date = year_date
        birth_day = str(birth_date.__sub__(today)).split(" ")[0]
    next_date_str = "{}月{}日".format(birth_date.month, birth_date.day)
    return birth_day, next_date_str


def get_ciba():
    url = "http://open.iciba.com/dsapi/"
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'
    }
    r = get(url, headers=headers)
    note_en = r.json()["content"]
    note_ch = r.json()["note"]
    return note_ch, note_en


def get_weibo_hot(limit=5):
    url = "https://weibo.com/ajax/side/hotSearch"
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://weibo.com/hot/search',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    }
    try:
        r = get(url, headers=headers, timeout=5)
        data = r.json()
        items = data.get("data", {}).get("realtime", [])
        if not items:
            return []
        results = []
        for idx, item in enumerate(items):
            keyword = item.get("note") or item.get("word")
            if not keyword:
                continue
            # 用稳定序号 1/2/3...，避免微博 realpos 缺失导致无序号
            results.append("{}. {}".format(idx + 1, keyword))
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def get_dress_advice(weather, max_temp, min_temp):
    """根据天气描述和气温生成穿衣/出行建议（一条字符串）"""
    try:
        t_low = int(min_temp)
        t_high = int(max_temp)
    except (ValueError, TypeError):
        t_low, t_high = 20, 25
    tips = []
    # 穿衣建议（按最低温，更贴近早晚出门体感）
    if t_low <= 0:
        tips.append("严寒，建议穿羽绒服、保暖内衣，戴围巾手套")
    elif t_low <= 5:
        tips.append("寒冷，建议穿羽绒服或厚棉衣")
    elif t_low <= 10:
        tips.append("偏冷，建议穿厚外套或棉衣")
    elif t_low <= 15:
        tips.append("微凉，建议穿外套加毛衣")
    elif t_low <= 20:
        tips.append("舒适偏凉，建议穿薄外套")
    elif t_low <= 25:
        tips.append("舒适，短袖加薄外套即可")
    elif t_low <= 30:
        tips.append("温暖，短袖为主")
    else:
        tips.append("炎热，注意防晒降温，穿透气短袖")
    # 出行提醒（按天气关键词）
    w = weather or ""
    if "雨" in w:
        tips.append("今天有雨，出门记得带伞")
    if "雪" in w:
        tips.append("今天有雪，路面湿滑，注意出行安全")
    if "雾" in w or "霾" in w:
        tips.append("能见度较低，驾车出行注意安全")
    if t_high >= 35:
        tips.append("高温天气，注意防暑降温、多喝水")
    if "大风" in w or "沙" in w:
        tips.append("风力较大或有沙尘，注意防护")
    return "；".join(tips)


def send_message(to_user, access_token, city_name, weather, max_temperature, min_temperature, note_ch, note_en, weibo_hot_list):
    url = "https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={}".format(access_token)
    week_list = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"]
    year = localtime().tm_year
    month = localtime().tm_mon
    day = localtime().tm_mday
    today = datetime.date(datetime(year=year, month=month, day=day))
    week = week_list[today.isoweekday() % 7]
    # 获取认识的日子的日期格式
    together_year = int(config["together_date"].split("-")[0])
    together_month = int(config["together_date"].split("-")[1])
    together_day = int(config["together_date"].split("-")[2])
    together_date = date(together_year, together_month, together_day)
    # 获取认识的日期差
    together_days = str(today.__sub__(together_date)).split(" ")[0]
    # 获取在一起的日子的日期格式
    love_year = int(config["love_date"].split("-")[0])
    love_month = int(config["love_date"].split("-")[1])
    love_day = int(config["love_date"].split("-")[2])
    love_date = date(love_year, love_month, love_day)
    # 获取在一起的日期差
    love_days = str(today.__sub__(love_date)).split(" ")[0]
    # 获取结婚日的日期格式
    wedding_year = int(config["wedding_date"].split("-")[0])
    wedding_month = int(config["wedding_date"].split("-")[1])
    wedding_day = int(config["wedding_date"].split("-")[2])
    wedding_date = date(wedding_year, wedding_month, wedding_day)
    # 获取结婚的日期差
    wedding_days = str(today.__sub__(wedding_date)).split(" ")[0]
    # 获取所有生日数据
    birthdays = {}
    for k, v in config.items():
        if k[0:5] == "birth":
            birthdays[k] = v
    # 微博热搜文本（整体一块），便于在模板里用 {{weibo_hot.DATA}} 一次性展示全部
    if weibo_hot_list:
        weibo_hot_text = "\n".join(weibo_hot_list)
    else:
        weibo_hot_text = "暂无微博热搜数据"

    data = {
        "touser": to_user,
        "template_id": config["template_id"],
        "url": "http://weixin.qq.com/download",
        "data": {
            "date": {
                "value": "{} {}".format(today, week)
            },
            "city": {
                "value": city_name
            },
            "weather": {
                "value": weather
            },
            "min_temperature": {
                "value": min_temperature
            },
            "max_temperature": {
                "value": max_temperature
            },
            "together_day": {
                "value": together_days
            },
            "together_date": {
                "value": together_days
            },
            "love_day": {
                "value": love_days
            },
            "wedding_date": {
                "value": wedding_days
            },
            "note_en": {
                "value": note_en
            },
            "note_ch": {
                "value": note_ch
            },
            "weibo_hot": {
                "value": weibo_hot_text
            }
        }
    }
    # ?????????????????
    for idx in range(5):
        value = weibo_hot_list[idx] if idx < len(weibo_hot_list) else ""
        data["data"][f"weibo_hot[{idx}]"] = {"value": value}
        data["data"][f"weibo_hot_{idx + 1}"] = {"value": value}
    # 穿衣/出行建议（需在公众号模板里新增 {{dress_advice.DATA}} 字段）
    data["data"]["dress_advice"] = {"value": get_dress_advice(weather, max_temperature, min_temperature)}
    birthday_summary_lines = []
    for key, value in birthdays.items():
        # 获取距离下次生日的时间及下次生日的具体日期
        birth_day, next_date_str = get_birthday(value["birthday"], year, today)
        if birth_day == 0:
            birthday_data = "今天{}生日哦，祝{}生日快乐！".format(value["name"], value["name"])
        else:
            birthday_data = "距离{}的生日还有{}天（{}）".format(value["name"], birth_day, next_date_str)
        # 将生日数据插入data
        data["data"][key] = {"value": birthday_data}
        birthday_summary_lines.append(birthday_data)
    if birthday_summary_lines:
        data["data"]["birthday"] = {"value": "\n".join(birthday_summary_lines)}
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'
    }
    response = post(url, headers=headers, json=data).json()
    if response["errcode"] == 40037:
        print("推送消息失败，请检查模板id是否正确")
    elif response["errcode"] == 40036:
        print("推送消息失败，请检查模板id是否为空")
    elif response["errcode"] == 40003:
        print("推送消息失败，请检查微信号是否正确")
    elif response["errcode"] == 0:
        print("推送消息成功")
    else:
        print(response)


if __name__ == "__main__":
    # cron 会提前到北京时间 7:30 左右触发，这里精确等到 8:00 再发送
    wait_until_push_time(8, 0)
    try:
        with open("config.txt", encoding="utf-8") as f:
            config = eval(f.read())
    except FileNotFoundError:
        print("推送消息失败，请检查config.txt文件是否与程序位于同一路径")
        os.system("pause")
        sys.exit(1)
    except SyntaxError:
        print("推送消息失败，请检查配置文件格式是否正确")
        os.system("pause")
        sys.exit(1)

    # 获取accessToken
    accessToken = get_access_token()
    # 接收的用户
    users = config["user"]
    # 传入省份和市获取天气信息
    province, city = config["province"], config["city"]
    weather, max_temperature, min_temperature = get_weather(province, city)
    # 获取词霸每日金句
    note_ch, note_en = get_ciba()
    # 获取微博热搜
    weibo_hot_list = get_weibo_hot(5)
    # 公众号推送消息
    for user in users:
        send_message(user, accessToken, city, weather, max_temperature, min_temperature, note_ch, note_en, weibo_hot_list)
    os.system("pause")
