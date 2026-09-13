"""Standalone course GPA ranking service using local Chalaoshi static data."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import socket
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DEFAULT_DATA_DIR = APP_DIR / "data"
FALLBACK_DATA_DIR = APP_DIR.parent / "Chalaoshipy" / "data"
MAX_SEARCH_RESULTS = 50
MAX_BATCH_COURSES = 80
BROWSER_HEARTBEAT_TIMEOUT_SECONDS = 15.0
BROWSER_DISCONNECT_GRACE_SECONDS = 2.0
BROWSER_STARTUP_TIMEOUT_SECONDS = 30.0


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: Any) -> str:
    return re.sub(r"[\s()（）\[\]【】{}<>《》]", "", text(value)).casefold()


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def count_value(value: Any) -> int:
    match = re.search(r"\d+", text(value))
    return int(match.group()) if match else -1


def data_directory() -> Path:
    configured = os.environ.get("COURSE_GPA_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if (DEFAULT_DATA_DIR / "gpa.json").is_file():
        return DEFAULT_DATA_DIR
    return FALLBACK_DATA_DIR


def load_static_data(directory: Path) -> tuple[dict[str, list[list[Any]]], dict[str, dict[str, str]]]:
    gpa_path = directory / "gpa.json"
    teachers_path = directory / "teachers.csv"
    if not gpa_path.is_file():
        raise FileNotFoundError("未找到静态均绩数据：%s" % gpa_path)
    if not teachers_path.is_file():
        raise FileNotFoundError("未找到教师数据：%s" % teachers_path)
    with gpa_path.open("r", encoding="utf-8") as file:
        raw_gpa = json.load(file)
    if not isinstance(raw_gpa, dict):
        raise ValueError("gpa.json 必须是以教师姓名为键的对象")
    with teachers_path.open("r", encoding="utf-8-sig", newline="") as file:
        teachers = {text(row.get("姓名")): row for row in csv.DictReader(file) if text(row.get("姓名"))}
    return raw_gpa, teachers


CATEGORY_HIERARCHY: dict[str, list[str]] = {
    "通识课程": [
        "思政理论类",
        "军体素养类",
        "大学外语类",
        "计算与信息素养类",
        "通识核心与选修类",
    ],
    "大类基础课程": [
        "数理基础类",
        "化学与生化类",
        "工程技术基础类",
        "人文社科基础类",
        "农医地环基础类",
    ],
    "专业课程": [
        "计算机与人工智能类",
        "电子信息与通信电气类",
        "机械动力与航空航天类",
        "材料土木与化工建筑类",
        "经济金融与商科管理类",
        "人文历史与哲学法学类",
        "自然科学与数理前沿类",
        "生命科学与农学环境类",
        "医药卫生与临床护理类",
        "其他专业与前沿课程",
    ],
    "实践与创新课程": [
        "专业实验与实践实习",
        "课程设计与综合研讨",
        "科研训练与创新创业",
        "毕业设计与毕业论文",
    ],
}

DAYS_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TEMPLATES_2: list[list[tuple[int, int]]] = [
    [(1, 1), (1, 2)], [(1, 3), (1, 4)],
    [(2, 1), (2, 2)], [(2, 3), (2, 4)],
    [(3, 1), (3, 2)], [(3, 3), (3, 4)],
    [(4, 1), (4, 2)], [(4, 3), (4, 4)],
    [(5, 1), (5, 2)], [(5, 3), (5, 4)],
    [(1, 6), (1, 7)], [(1, 8), (1, 9)],
    [(2, 6), (2, 7)], [(2, 8), (2, 9)],
    [(3, 6), (3, 7)], [(3, 8), (3, 9)],
    [(4, 6), (4, 7)], [(4, 8), (4, 9)],
    [(5, 6), (5, 7)], [(5, 8), (5, 9)],
    [(1, 11), (1, 12)], [(2, 11), (2, 12)], [(3, 11), (3, 12)], [(4, 11), (4, 12)], [(5, 11), (5, 12)],
    [(6, 1), (6, 2)], [(6, 3), (6, 4)], [(6, 6), (6, 7)], [(6, 8), (6, 9)], [(6, 11), (6, 12)],
    [(7, 1), (7, 2)], [(7, 3), (7, 4)], [(7, 6), (7, 7)], [(7, 8), (7, 9)], [(7, 11), (7, 12)],
]

TEMPLATES_3: list[list[tuple[int, int]]] = [
    [(1, 3), (1, 4), (1, 5)], [(2, 3), (2, 4), (2, 5)], [(3, 3), (3, 4), (3, 5)], [(4, 3), (4, 4), (4, 5)], [(5, 3), (5, 4), (5, 5)],
    [(1, 6), (1, 7), (1, 8)], [(1, 8), (1, 9), (1, 10)],
    [(2, 6), (2, 7), (2, 8)], [(2, 8), (2, 9), (2, 10)],
    [(3, 6), (3, 7), (3, 8)], [(3, 8), (3, 9), (3, 10)],
    [(4, 6), (4, 7), (4, 8)], [(4, 8), (4, 9), (4, 10)],
    [(5, 6), (5, 7), (5, 8)], [(5, 8), (5, 9), (5, 10)],
    [(1, 11), (1, 12), (1, 13)], [(2, 11), (2, 12), (2, 13)],
    [(3, 11), (3, 12), (3, 13)], [(4, 11), (4, 12), (4, 13)], [(5, 11), (5, 12), (5, 13)],
    [(6, 3), (6, 4), (6, 5)], [(6, 6), (6, 7), (6, 8)], [(6, 11), (6, 12), (6, 13)],
    [(7, 3), (7, 4), (7, 5)], [(7, 6), (7, 7), (7, 8)], [(7, 11), (7, 12), (7, 13)],
]

TEMPLATES_4: list[list[tuple[int, int]]] = [
    [(1, 1), (1, 2), (3, 1), (3, 2)], [(1, 3), (1, 4), (3, 3), (3, 4)],
    [(2, 1), (2, 2), (4, 1), (4, 2)], [(2, 3), (2, 4), (4, 3), (4, 4)],
    [(1, 6), (1, 7), (3, 6), (3, 7)], [(1, 8), (1, 9), (3, 8), (3, 9)],
    [(2, 6), (2, 7), (4, 6), (4, 7)], [(2, 8), (2, 9), (4, 8), (4, 9)],
    [(3, 6), (3, 7), (5, 6), (5, 7)],
    [(1, 11), (1, 12), (3, 11), (3, 12)], [(2, 11), (2, 12), (4, 11), (4, 12)],
    [(1, 1), (1, 2), (3, 3), (3, 4), (3, 5)],
    [(2, 1), (2, 2), (4, 3), (4, 4), (4, 5)],
    [(1, 6), (1, 7), (3, 6), (3, 7), (3, 8)],
    [(2, 6), (2, 7), (4, 6), (4, 7), (4, 8)],
    [(6, 1), (6, 2), (6, 3), (6, 4)], [(7, 6), (7, 7), (7, 8), (7, 9)],
]


def format_schedule(slots: list[tuple[int, int]]) -> str:
    grouped: dict[int, list[int]] = {}
    for d, p in sorted(slots):
        grouped.setdefault(d, []).append(p)
    parts = []
    for d, ps in grouped.items():
        parts.append(f"{DAYS_NAMES[d - 1]}第{','.join(str(p) for p in ps)}节")
    return "; ".join(parts)


def select_schedule_template(course_name: str, teacher_name: str, class_idx: int, credits: float) -> list[tuple[int, int]]:
    if credits <= 2.0:
        pool = TEMPLATES_2
    elif credits <= 3.5:
        pool = TEMPLATES_3
    else:
        pool = TEMPLATES_4
    h = int(hashlib.sha256(f"{course_name}::{teacher_name}::{class_idx}".encode("utf-8")).hexdigest()[:8], 16)
    return pool[h % len(pool)]


def classify_course(name: str, colleges: set[str]) -> tuple[str, str]:
    col_str = " ".join(colleges)

    # 1. 通识课程
    if any(k in name for k in ["马克思", "毛泽东", "思想道德", "近现代史", "形势与政策", "习近平", "习概", "新时代", "思想政治", "治国理政", "法治理论"]) or "马克思主义学院" in col_str:
        return ("通识课程", "思政理论类")
    if any(k in name for k in ["体育", "篮球", "足球", "排球", "乒乓", "羽毛球", "网球", "游泳", "武术", "健美", "定向越野", "太极", "军事", "军训", "龙舟", "龙狮", "瑜伽", "击剑", "攀岩", "防身术", "形体", "皮划艇", "跆拳道"]) or ("公共体育与艺术部" in col_str and any(k in name for k in ["球", "泳", "拳", "术", "操", "跑", "体", "定向", "武", "击"])):
        return ("通识课程", "军体素养类")
    if any(k in name for k in ["大学英语", "英语视听说", "英语写作", "英语阅读", "学术英语", "应用英语", "高级英语", "实用英语", "日语（", "德语（", "法语（", "俄语（", "西班牙语（", "二外", "公共外语"]) or ("外国语言" in col_str and any(k in name for k in ["英语", "日语", "德语", "法语", "俄语", "西语", "听说", "阅读", "精读"])):
        return ("通识课程", "大学外语类")
    if any(k in name for k in ["大学计算机", "计算思维", "程序设计基础", "Python程序", "C语言程序", "C++程序", "Java程序", "信息技术基础"]):
        return ("通识课程", "计算与信息素养类")
    if "通识" in name or any(k in name for k in ["艺术导论", "音乐鉴赏", "美术鉴赏", "影视鉴赏", "戏剧鉴赏", "戏曲鉴赏", "中外名作", "中国传统文化", "中西文化", "科学精神", "沟通与写作", "批判性思维", "艺术审美", "国学经典"]):
        return ("通识课程", "通识核心与选修类")

    # 4. 实践与创新课程
    if any(k in name for k in ["毕业设计", "毕业论文", "综合论文", "学年论文"]):
        return ("实践与创新课程", "毕业设计与毕业论文")
    if any(k in name for k in ["课程设计", "专业综合设计", "专业课程设计", "大作业", "前沿研讨", "学科前沿讲座"]):
        return ("实践与创新课程", "课程设计与综合研讨")
    if any(k in name for k in ["生产实习", "认识实习", "专业实习", "金工实习", "电工实习", "野外实习", "临床见习", "毕业实习", "分散实习", "专业综合实验", "电子工艺实习"]):
        return ("实践与创新课程", "专业实验与实践实习")
    if any(k in name for k in ["科研训练", "SRTP", "创新创业", "学科竞赛", "创客实践", "创业实务", "创新实践"]):
        return ("实践与创新课程", "科研训练与创新创业")

    # 2. 大类基础课程
    if any(k in name for k in ["微积分", "高等数学", "线性代数", "概率论", "数理统计", "常微分方程", "复变函数", "数学分析", "高等代数", "大学物理", "普通物理", "物理实验", "大学物理实验", "离散数学（甲）"]):
        return ("大类基础课程", "数理基础类")
    if any(k in name for k in ["普通化学", "大学化学", "有机化学", "无机化学", "分析化学", "物理化学", "生命科学导论", "生物化学基础", "化学实验", "基础化学实验"]):
        return ("大类基础课程", "化学与生化类")
    if any(k in name for k in ["工程制图", "工程图学", "工程力学", "理论力学", "材料力学", "电工学", "电路原理", "模拟电子", "数字逻辑", "工程导论", "工程认知", "数字电子技术"]):
        return ("大类基础课程", "工程技术基础类")
    if any(k in name for k in ["微观经济学", "宏观经济学", "经济学原理", "社会学概论", "心理学导论", "法学通论", "管理学基础", "政治学概论", "逻辑学导论", "管理学原理", "基础心理学"]):
        return ("大类基础课程", "人文社科基础类")
    if any(k in name for k in ["地球科学导论", "环境科学基础", "生态学基础", "医学导论", "现代生命科学导论"]):
        return ("大类基础课程", "农医地环基础类")

    # 3. 专业课程 (细分)
    if "计算机" in col_str or "软件" in col_str or any(k in name for k in ["数据结构", "操作系统", "计算机系统", "计算机组成", "算法设计", "算法分析", "软件工程", "数据库系统", "人工智能", "机器学习", "深度学习", "计算机网络", "编译原理", "计算机体系结构", "网络空间安全", "信息安全", "云计算", "大数据", "计算机图形学", "人机交互", "模式识别"]):
        return ("专业课程", "计算机与人工智能类")
    if "电气" in col_str or "信息与电子" in col_str or "光电" in col_str or "微电子" in col_str or any(k in name for k in ["电气", "电力", "微波", "天线", "高频", "信号与系统", "数字信号", "通信原理", "控制理论", "现代控制", "自动控制", "传感器", "半导体", "集成电路", "光电", "电磁场"]):
        return ("专业课程", "电子信息与通信电气类")
    if "机械" in col_str or "能源" in col_str or "航空航天" in col_str or any(k in name for k in ["机械设计", "机械原理", "机械工程", "热能", "工程热物理", "工程热力学", "汽车", "传热学", "流体力学", "机电一体化", "数控技术", "机器人", "航空", "航天", "飞行器", "动力机械"]):
        return ("专业课程", "机械动力与航空航天类")
    if "建工" in col_str or "建筑" in col_str or "材料" in col_str or "化工" in col_str or "高分子" in col_str or any(k in name for k in ["土木", "建筑学", "混凝土", "钢结构", "给排水", "工程测量", "材料科学", "高分子", "化工原理", "化学反应工程", "材料物理", "城乡规划", "结构力学"]):
        return ("专业课程", "材料土木与化工建筑类")
    if "经济" in col_str or "管理" in col_str or "商" in col_str or any(k in name for k in ["金融学", "证券投资", "会计学", "财务管理", "市场营销", "国际贸易", "电子商务", "运筹学", "企业管理", "组织行为学", "人力资源", "物流", "供应链", "货币银行", "计量经济", "公司金融"]):
        return ("专业课程", "经济金融与商科管理类")
    if "医" in col_str or "药" in col_str or any(k in name for k in ["医学", "内科学", "外科学", "妇产科", "儿科学", "药理学", "生理学", "人体解剖", "病理学", "诊断学", "药物化学", "临床", "免疫学", "护理学", "口腔", "卫生学", "中药学", "药剂学"]):
        return ("专业课程", "医药卫生与临床护理类")
    if "农业" in col_str or "动物" in col_str or "生命科学" in col_str or "环境与资源" in col_str or any(k in name for k in ["农学", "园艺", "植物保护", "动物科学", "动物医学", "水产", "土壤学", "林学", "作物", "遗传学", "分子生物学", "微生物学", "细胞生物学", "生态学", "环境工程", "环境监测", "发酵工程"]):
        return ("专业课程", "生命科学与农学环境类")
    if "人文" in col_str or "文学院" in col_str or "历史" in col_str or "哲学" in col_str or "法学" in col_str or "传媒" in col_str or any(k in name for k in ["中国文学", "外国文学", "古代汉语", "现代汉语", "语言学", "中国通史", "世界通史", "考古学", "西方哲学", "中国哲学", "法理学", "民法", "刑法", "行政法", "国际法", "新闻学", "传播学", "广播电视", "广告学"]):
        return ("专业课程", "人文历史与哲学法学类")
    if "数学" in col_str or "物理" in col_str or "化学" in col_str or any(k in name for k in ["近世代数", "抽象代数", "拓扑学", "微分几何", "实变函数", "泛函分析", "量子力学", "统计物理", "电动力学", "电磁学", "光学", "热学", "原子物理", "固体物理", "物理化学（"]):
        return ("专业课程", "自然科学与数理前沿类")

    if any(k in col_str for k in ["社科", "公管", "教育", "心理"]):
        return ("专业课程", "经济金融与商科管理类")
    if any(k in col_str for k in ["艺术", "外语", "外国语"]):
        return ("通识课程", "通识核心与选修类")

    return ("专业课程", "其他专业与前沿课程")


def infer_credits(name: str, cat_l1: str, cat_l2: str) -> float:
    if cat_l2 == "军体素养类":
        return 1.5 if ("军事" in name or "军训" in name) else 1.0
    if cat_l2 == "思政理论类":
        if "形势与政策" in name:
            return 1.0
        if "毛泽东思想" in name:
            return 5.0
        return 3.0
    if cat_l2 == "大学外语类":
        return 2.0 if any(k in name for k in ["视听说", "听说", "口语"]) else 3.0
    if cat_l2 == "计算与信息素养类":
        return 2.5 if "大学计算机" in name else 3.0
    if cat_l2 == "毕业设计与毕业论文":
        return 8.0
    if cat_l2 in {"专业实验与实践实习", "课程设计与综合研讨", "科研训练与创新创业"}:
        return 1.5 if ("实验" in name or "实习" in name) else 2.0
    if cat_l2 == "数理基础类":
        if any(k in name for k in ["微积分（甲）", "微积分I", "微积分 II", "高等数学（甲）"]):
            return 5.0
        if any(k in name for k in ["微积分（乙）", "高等数学（乙）", "微积分"]):
            return 4.0
        if "大学物理（甲）" in name:
            return 4.0
        if any(k in name for k in ["大学物理（乙）", "大学物理"]):
            return 3.0
        if any(k in name for k in ["实验", "物理实验"]):
            return 1.5
        if "线性代数" in name:
            return 3.0 if "甲" in name else 2.5
        if "概率" in name:
            return 3.0
    if cat_l1 == "通识课程":
        return 1.5 if "导论" in name else 2.0
    if "实验" in name:
        return 1.5
    if "实习" in name:
        return 2.0
    if "导论" in name:
        return 2.0

    palette = [2.0, 2.5, 3.0, 3.5, 4.0]
    seed_idx = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16) % len(palette)
    return palette[seed_idx]


def generate_teaching_classes(
    course_name: str,
    teachers: list[dict[str, Any]],
    credits: float,
    teachers_meta: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    class_counter = 1

    teacher_items = teachers if len(teachers) > 1 else (teachers * 2 if teachers else [])
    for idx, item in enumerate(teacher_items):
        t_name = item.get("teacher", "任课教师")
        t_meta = teachers_meta.get(t_name, {})
        slots = select_schedule_template(course_name, t_name, idx, credits)
        classes.append({
            "class_id": f"教学班 {class_counter:02d}",
            "teacher": t_name,
            "average": item.get("average"),
            "std_gpa": item.get("std_gpa"),
            "total_count": item.get("total_count", ""),
            "college": text(t_meta.get("学院")),
            "rating": to_float(t_meta.get("评分")),
            "rating_count": count_value(t_meta.get("评分人数")),
            "schedule": format_schedule(slots),
            "slots": [[d, p] for d, p in slots],
        })
        class_counter += 1
    return classes


def build_course_index(
    gpa_data: dict[str, list[list[Any]]],
    teachers_meta: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    meta = teachers_meta or {}
    courses: dict[str, dict[str, Any]] = {}
    for teacher, entries in gpa_data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, list) or not entry:
                continue
            name = text(entry[0])
            if not name:
                continue
            key = normalize(name)
            course = courses.setdefault(key, {"name": name, "teachers": []})
            course["teachers"].append({
                "teacher": text(teacher),
                "average": to_float(entry[1] if len(entry) > 1 else None),
                "total_count": text(entry[2] if len(entry) > 2 else ""),
                "std_gpa": to_float(entry[3] if len(entry) > 3 else None),
            })

    for course in courses.values():
        colleges = {text(meta.get(item["teacher"], {}).get("学院")) for item in course["teachers"] if meta.get(item["teacher"], {}).get("学院")}
        l1, l2 = classify_course(course["name"], colleges)
        cr = infer_credits(course["name"], l1, l2)
        course["code"] = ""
        course["category_l1"] = l1
        course["category_l2"] = l2
        course["credits"] = cr
        course["classes"] = generate_teaching_classes(course["name"], course["teachers"], cr, meta)
        course["max_gpa"] = max((t["average"] for t in course["teachers"] if t["average"] is not None), default=None)

    return courses


DATA_DIR = data_directory()
GPA_DATA, TEACHERS = load_static_data(DATA_DIR)
COURSE_INDEX = build_course_index(GPA_DATA, TEACHERS)


def course_summary(course: dict[str, Any]) -> dict[str, Any]:
    teachers = {item["teacher"] for item in course.get("teachers", [])}
    return {
        "name": course["name"],
        "code": course.get("code", ""),
        "credits": course.get("credits", 3.0),
        "category_l1": course.get("category_l1", ""),
        "category_l2": course.get("category_l2", ""),
        "teachers": sorted(teachers),
        "teacher_count": len(teachers),
        "max_gpa": course.get("max_gpa"),
    }


def search_courses(query: str) -> list[dict[str, Any]]:
    query_key = normalize(query)
    matches = [course_summary(course) for key, course in COURSE_INDEX.items() if query_key in key]
    matches.sort(key=lambda item: (normalize(item["name"]) != query_key, not normalize(item["name"]).startswith(query_key), -item["teacher_count"], item["name"]))
    return matches[:MAX_SEARCH_RESULTS]


def find_course(name: str) -> dict[str, Any] | None:
    key = normalize(name)
    if key in COURSE_INDEX:
        return COURSE_INDEX[key]
    matches = [course for candidate, course in COURSE_INDEX.items() if key in candidate or candidate in key]
    return min(matches, key=lambda item: len(item["name"]), default=None)


def ranking_row(item: dict[str, Any]) -> dict[str, Any]:
    teacher = TEACHERS.get(item["teacher"], {})
    rating = to_float(teacher.get("评分"))
    return {
        "teacher": item["teacher"],
        "average": item["average"],
        "std_gpa": item["std_gpa"],
        "total_count": item["total_count"],
        "college": text(teacher.get("学院")),
        "rating": rating,
        "rating_count": count_value(teacher.get("评分人数")),
        "hot": count_value(teacher.get("热度")),
        "details": {
            "平均GPA": item["average"],
            "GPA标准差": item["std_gpa"],
            "课程样本人数": item["total_count"],
            "学院": text(teacher.get("学院")),
            "查老师评分": rating,
            "评分人数": text(teacher.get("评分人数")),
            "热度": text(teacher.get("热度")),
        },
    }


def rank_course(course_request: dict[str, Any]) -> dict[str, Any]:
    course = find_course(text(course_request.get("name")))
    if course is None:
        return {"name": text(course_request.get("name")), "code": "", "credits": 3.0, "category_l1": "", "category_l2": "", "teachers": [], "rankings": [], "warnings": ["静态数据中未找到匹配课程。"]}
    rows = [ranking_row(item) for item in course["teachers"]]
    rows.sort(key=lambda item: (item["average"] is not None, item["average"] or -1, item["rating"] or -1, count_value(item["total_count"])), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {**course_summary(course), "rankings": rows, "warnings": []}


def get_categories_tree() -> dict[str, Any]:
    counts: dict[str, dict[str, Any]] = {}
    for l1, l2_list in CATEGORY_HIERARCHY.items():
        counts[l1] = {
            "total": 0,
            "subcategories": {l2: 0 for l2 in l2_list},
        }

    for course in COURSE_INDEX.values():
        l1 = course.get("category_l1", "")
        l2 = course.get("category_l2", "")
        if l1 in counts:
            counts[l1]["total"] += 1
            if l2 in counts[l1]["subcategories"]:
                counts[l1]["subcategories"][l2] += 1

    return {
        "hierarchy": CATEGORY_HIERARCHY,
        "counts": counts,
        "total_courses": len(COURSE_INDEX),
    }


def filter_courses(
    selected_slots: list[list[int]] | None = None,
    category_l1: str = "",
    category_l2: str = "",
    min_samples: int | None = None,
    min_gpa: float | None = None,
    keyword: str = "",
    exclude_keyword: str | list[str] = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    allowed_set: set[tuple[int, int]] | None = None
    if selected_slots is not None and isinstance(selected_slots, list) and len(selected_slots) < 91:
        allowed_set = {(int(s[0]), int(s[1])) for s in selected_slots if len(s) >= 2}

    key_norm = normalize(keyword) if keyword else ""
    exclude_tokens: list[str] = []
    if isinstance(exclude_keyword, list):
        exclude_tokens = [normalize(text(k)) for k in exclude_keyword if normalize(text(k))]
    elif exclude_keyword:
        exclude_tokens = [normalize(k) for k in re.split(r"[,，\s|、]+", text(exclude_keyword)) if normalize(k)]

    matched_courses: list[dict[str, Any]] = []

    for course in COURSE_INDEX.values():
        c_norm = normalize(course["name"])
        if key_norm and key_norm not in c_norm:
            continue
        if exclude_tokens and any(tok in c_norm for tok in exclude_tokens):
            continue
        if category_l1 and course.get("category_l1") != category_l1:
            continue
        if category_l2 and course.get("category_l2") != category_l2:
            continue

        classes = course.get("classes", [])
        qualified_classes: list[dict[str, Any]] = []
        for cls in classes:
            # 1. Timetable slot subset check: 满足其列出的所有时间都能嵌入 (cls_slots is subset of allowed_set)
            if allowed_set is not None:
                cls_slots = {(int(s[0]), int(s[1])) for s in cls.get("slots", []) if len(s) >= 2}
                if not cls_slots or not cls_slots.issubset(allowed_set):
                    continue

            # 2. Sample count threshold check
            sample_cnt = count_value(cls.get("total_count", ""))
            if min_samples is not None and min_samples > 0 and sample_cnt < min_samples:
                continue

            qualified_classes.append({**cls, "qualified": True, "sample_count": sample_cnt})

        if not qualified_classes:
            continue

        valid_gpas = [c["average"] for c in qualified_classes if c.get("average") is not None]
        remaining_max_gpa = max(valid_gpas) if valid_gpas else None

        if min_gpa is not None:
            if remaining_max_gpa is None or remaining_max_gpa < min_gpa:
                continue

        matched_courses.append({
            "name": course["name"],
            "code": course.get("code", ""),
            "credits": course.get("credits", 3.0),
            "category_l1": course.get("category_l1", ""),
            "category_l2": course.get("category_l2", ""),
            "max_gpa": remaining_max_gpa,
            "qualified_classes_count": len(qualified_classes),
            "total_classes_count": len(classes),
            "classes": sorted(qualified_classes, key=lambda c: (c["average"] is not None, c["average"] or -1), reverse=True),
        })

    # Sort courses by remaining max GPA descending
    matched_courses.sort(
        key=lambda c: (
            c["max_gpa"] is not None,
            c["max_gpa"] or -1,
            c["qualified_classes_count"],
            c["name"],
        ),
        reverse=True,
    )

    total_courses = len(matched_courses)
    total_classes = sum(c["qualified_classes_count"] for c in matched_courses)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    total_pages = math.ceil(total_courses / page_size) if total_courses > 0 else 1
    start = (page - 1) * page_size
    paged_items = matched_courses[start : start + page_size]

    return {
        "total_courses": total_courses,
        "total_classes": total_classes,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "courses": paged_items,
    }


def parse_xlsx(data: bytes) -> list[str]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in root.findall(namespace + "si"):
                shared.append("".join(node.text or "" for node in item.iter(namespace + "t")))
        values: list[str] = []
        for filename in sorted(name for name in workbook.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")):
            root = ET.fromstring(workbook.read(filename))
            for cell in root.iter(namespace + "c"):
                value = cell.find(namespace + "v")
                if value is None or value.text is None:
                    continue
                if cell.attrib.get("t") == "s" and value.text.isdigit():
                    values.append(shared[int(value.text)] if int(value.text) < len(shared) else "")
                else:
                    values.append(value.text)
        return values


def course_candidates(values: list[str]) -> list[str]:
    ignored = {"课程", "课程名称", "课程名", "课程代码", "课程号", "学分", "学时", "培养方案", "备注", "序号"}
    result: list[str] = []
    for value in values:
        item = text(value)
        if item in ignored or len(item) < 2 or len(item) > 100 or re.fullmatch(r"[\d.]+", item):
            continue
        if item not in result:
            result.append(item)
    return result


def parse_import(filename: str, content_base64: str) -> list[str]:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except ValueError as exc:
        raise ValueError("上传内容无法解码") from exc
    if Path(filename).suffix.lower() == ".xlsx":
        values = parse_xlsx(data)
    else:
        values = [cell for row in csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))) for cell in row]
    return course_candidates(values)


class ApplicationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], auto_shutdown: bool) -> None:
        super().__init__(server_address, ApplicationHandler)
        self.auto_shutdown = auto_shutdown
        self._clients: dict[str, float] = {}
        self._clients_lock = threading.Lock()
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._shutdown_deadline: float | None = (
            time.monotonic() + BROWSER_STARTUP_TIMEOUT_SECONDS if auto_shutdown else None
        )

    def start_lifecycle_monitor(self) -> None:
        if not self.auto_shutdown:
            return
        self._monitor_thread = threading.Thread(
            target=self._monitor_clients,
            name="browser-lifecycle-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop_lifecycle_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread is not threading.current_thread():
            self._monitor_thread.join(timeout=2)

    def mark_client_seen(self, client_id: str) -> None:
        with self._clients_lock:
            self._clients[client_id or "__anonymous__"] = time.monotonic()
            self._shutdown_deadline = None

    def mark_client_disconnected(self, client_id: str) -> None:
        with self._clients_lock:
            self._clients.pop(client_id or "__anonymous__", None)
            if not self._clients:
                self._shutdown_deadline = time.monotonic() + BROWSER_DISCONNECT_GRACE_SECONDS

    def _monitor_clients(self) -> None:
        while not self._monitor_stop.wait(1):
            now = time.monotonic()
            should_shutdown = False
            with self._clients_lock:
                expired = [
                    client_id
                    for client_id, last_seen in self._clients.items()
                    if now - last_seen > BROWSER_HEARTBEAT_TIMEOUT_SECONDS
                ]
                for client_id in expired:
                    self._clients.pop(client_id, None)
                if not self._clients:
                    if self._shutdown_deadline is None:
                        self._shutdown_deadline = now + BROWSER_DISCONNECT_GRACE_SECONDS
                    should_shutdown = now >= self._shutdown_deadline
            if should_shutdown:
                self.shutdown()
                return


class ApplicationHandler(SimpleHTTPRequestHandler):
    server_version = "CourseGpaRanker/2.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), format % args))

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 10 * 1024 * 1024:
            raise ValueError("请求内容超过 10 MB")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "data_dir": str(DATA_DIR), "course_count": len(COURSE_INDEX), "source": "static"})
            return
        if parsed.path == "/api/categories":
            self.send_json(200, get_categories_tree())
            return
        if parsed.path == "/api/search":
            name = text(query.get("q", [""])[0])
            if len(name) < 2:
                self.send_json(400, {"error": "请输入至少两个字符的课程名称。"})
                return
            self.send_json(200, {"courses": search_courses(name)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/heartbeat", "/api/disconnect"}:
                payload = self.read_json()
                client_id = text(payload.get("client_id")) if isinstance(payload, dict) else ""
                if parsed.path == "/api/heartbeat":
                    self.server.mark_client_seen(client_id)
                else:
                    self.server.mark_client_disconnected(client_id)
                self.send_json(200, {"ok": True})
                return
            data = self.read_json()
            if parsed.path == "/api/filter":
                min_samples_val = data.get("min_samples")
                try:
                    min_samples = int(min_samples_val) if min_samples_val not in (None, "", "null") else None
                except (ValueError, TypeError):
                    min_samples = None
                res = filter_courses(
                    selected_slots=data.get("selected_slots"),
                    category_l1=text(data.get("category_l1")),
                    category_l2=text(data.get("category_l2")),
                    min_samples=min_samples,
                    min_gpa=to_float(data.get("min_gpa")),
                    keyword=text(data.get("q")),
                    exclude_keyword=text(data.get("exclude_q") or data.get("exclude_keyword") or data.get("exclude")),
                    page=int(data.get("page", 1)),
                    page_size=int(data.get("page_size", 20)),
                )
                self.send_json(200, res)
                return
            if parsed.path == "/api/import":
                self.send_json(200, {"courses": parse_import(text(data.get("filename")), text(data.get("content")))})
                return
            if parsed.path == "/api/rank":
                course = data.get("course")
                if not isinstance(course, dict) or not text(course.get("name")):
                    raise ValueError("缺少课程信息")
                self.send_json(200, {"course": rank_course(course)})
                return
            if parsed.path == "/api/batch":
                names = data.get("courses")
                if not isinstance(names, list):
                    raise ValueError("课程列表格式不正确")
                results = [rank_course({"name": text(name)}) for name in names[:MAX_BATCH_COURSES] if text(name)]
                results.sort(key=lambda item: max((row["average"] for row in item["rankings"] if row["average"] is not None), default=-1), reverse=True)
                self.send_json(200, {"courses": results})
                return
            self.send_json(404, {"error": "接口不存在"})
        except (ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "处理失败：%s" % exc})


def available_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    for port in range(preferred + 1, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise OSError("未找到可用端口")


def main() -> None:
    parser = argparse.ArgumentParser(description="Course GPA Ranker")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-running", action="store_true", help="关闭浏览器后仍保持服务运行")
    args = parser.parse_args()
    port = available_port(args.port)
    server = ApplicationServer(("127.0.0.1", port), auto_shutdown=not args.keep_running)
    url = "http://127.0.0.1:%d/?v=%d" % (port, time.time_ns())
    print("课程均绩排行已启动：%s" % url)
    print("静态数据目录：%s" % DATA_DIR)
    server.start_lifecycle_monitor()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.stop_lifecycle_monitor()
        server.server_close()


if __name__ == "__main__":
    main()
