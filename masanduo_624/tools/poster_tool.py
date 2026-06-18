# -*- coding: utf-8 -*-
"""
马三多 - 海报生成工具 v1.0
调用 EasyClaw Seedream 5.0 Lite 生成电商海报/促销图
"""

import subprocess
import os
import uuid
from datetime import datetime

# EasyClaw 内置图像生成脚本路径
IMAGE_GEN_SCRIPT = r"C:\Program Files (x86)\easyclaw\resources\cfmind\skills\image-gen\scripts\generate_image.py"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "posters")

# 常见机型的产品名（用于海报 prompt）
PHONE_PRODUCT_NAMES = {
    "16 Pro Max": "iPhone 16 Pro Max",
    "16 Pro": "iPhone 16 Pro",
    "16": "iPhone 16",
    "15 Pro Max": "iPhone 15 Pro Max",
    "15 Pro": "iPhone 15 Pro",
    "15": "iPhone 15",
    "14 Pro Max": "iPhone 14 Pro Max",
    "14 Pro": "iPhone 14 Pro",
    "14": "iPhone 14",
}


def generate_poster(product_name="", main_selling_points="", style="电商主图", aspect_ratio="1:1"):
    """
    生成手机租机海报

    Args:
        product_name: 机型名称，如 "iPhone 16 Pro Max"
        main_selling_points: 核心卖点，如 "月供低至299元 零首付"
        style: 风格 - 电商主图 / 小红书 / 朋友圈 / 抖音封面
        aspect_ratio: 比例 - 1:1 / 3:4 / 9:16

    Returns:
        dict: {"success": bool, "path": str, "message": str}
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"poster_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(OUTPUT_DIR, filename)

    # 构建专业电商海报 prompt
    prompt = _build_poster_prompt(product_name, main_selling_points, style)
    
    # 比例 → 尺寸
    size_map = {
        "1:1": "2048x2048",
        "3:4": "1728x2304",
        "9:16": "1600x2848",
        "16:9": "2848x1600",
    }
    size = size_map.get(aspect_ratio, "2048x2048")

    try:
        cmd = [
            "python",
            IMAGE_GEN_SCRIPT,
            "--prompt", prompt,
            "--filename", filepath,
            "--aspect-ratio", aspect_ratio,
            "--size", size,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=OUTPUT_DIR)
        
        if result.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return {
                "success": True,
                "path": filepath,
                "filename": filename,
                "message": f"海报已生成：{filename}",
                "prompt": prompt,
            }
        else:
            return {
                "success": False,
                "message": f"生成失败",
                "stderr": result.stderr[:500] if result.stderr else "",
                "stdout": result.stdout[:500] if result.stdout else "",
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "生成超时（120秒）"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _build_poster_prompt(product_name, selling_points, style):
    """构建海报 prompt"""
    product = PHONE_PRODUCT_NAMES.get(product_name, product_name or "智能手机")
    
    style_prompts = {
        "电商主图": (
            "professional product photography, "
            "smartphone floating on pure white background, "
            "studio lighting, soft shadows, clean composition, "
            "premium flagship phone, 85% product ratio, "
            "high-end commercial photography, sharp details, "
            "no text, no watermark"
        ),
        "小红书": (
            "lifestyle flat lay photography, "
            "smartphone on marble desk with coffee cup, "
            "warm natural lighting, aesthetic Xiaohongshu style, "
            "soft pastel tones, cozy vibe, 3:4 vertical, "
            "no text, no watermark"
        ),
        "朋友圈": (
            "modern tech lifestyle, hand holding smartphone, "
            "urban city background, golden hour lighting, "
            "warm tones, daily life aesthetic, WeChat moments style, "
            "no text, no watermark"
        ),
        "抖音封面": (
            "bold dynamic composition, smartphone closeup, "
            "vibrant neon accent lighting, Douyin cover style, "
            "high saturation, visual impact, 9:16 vertical full frame, "
            "tech futuristic vibe, no text, no watermark"
        ),
    }
    
    style_prompt = style_prompts.get(style, style_prompts["电商主图"])
    
    prompt = f"{product}, {style_prompt}"
    if selling_points:
        # 卖点翻译成视觉元素注入
        visual_elements = []
        if "月供" in selling_points or "首付" in selling_points:
            visual_elements.append("highlighting affordability with golden warm accents")
        if "新机" in selling_points or "全新" in selling_points:
            visual_elements.append("pristine unboxing aesthetic")
        if visual_elements:
            prompt += ", " + ", ".join(visual_elements)
    
    return prompt
