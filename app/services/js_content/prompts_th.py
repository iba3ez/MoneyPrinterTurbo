from __future__ import annotations

from .models import BrandProfile, ContentBrief


THAI_CONTENT_SYSTEM_PROMPT = """
คุณคือ AI Content Strategist และ Video Storyboard Director สำหรับคอนเทนต์ภาษาไทย
หน้าที่คือสร้างคอนเทนต์สั้นที่กระชับ เป็นธรรมชาติ ไม่เวิ่นเว้อ และเหมาะกับแพลตฟอร์มโซเชียล
ห้ามสร้างข้อมูลเท็จ ห้ามอ้างสเปก ราคา หรือข้อเท็จจริงที่ผู้ใช้ไม่ได้ให้มา
ผลลัพธ์ต้องเป็น JSON เท่านั้น ห้ามมี markdown ห้ามมีข้อความอธิบายนอก JSON
""".strip()


def build_thai_storyboard_prompt(brief: ContentBrief, brand: BrandProfile) -> str:
    brief.validate()
    brand.validate()

    source_notes = "\n".join(f"- {item}" for item in brief.source_notes) or "- ไม่มีข้อมูลเพิ่มเติม"
    visual_notes = "\n".join(f"- {item}" for item in brand.visual_notes) or "- ใช้ภาพสะอาด อ่านง่ายบนมือถือ"
    forbidden = "\n".join(f"- {item}" for item in brand.forbidden_phrases) or "- ไม่มี"

    return f"""{THAI_CONTENT_SYSTEM_PROMPT}

BRAND
name: {brand.name}
language: {brand.language}
tone: {brand.tone}
audience: {brand.audience}
cta: {brand.cta}
watermark: {brand.watermark}
visual_notes:
{visual_notes}
forbidden_phrases:
{forbidden}

CONTENT BRIEF
topic: {brief.topic}
objective: {brief.objective}
platform: {brief.platform}
aspect_ratio: {brief.aspect_ratio}
duration_seconds: {brief.duration_seconds}
product_name: {brief.product_name}
price: {brief.price}
source_notes:
{source_notes}

TASK
สร้าง hook, title, cta และ storyboard แบบ scene-by-scene จำนวน 3-8 scene
แต่ละ scene ต้องมี narration, on_screen_text, visual_prompt, camera, transition และ duration_seconds
ให้รวม duration_seconds ใกล้เคียง {brief.duration_seconds} วินาที
ภาษา narration และ on_screen_text ให้เป็นภาษาไทยธรรมชาติ
visual_prompt เขียนให้ชัดพอสำหรับระบบสร้างภาพหรือวิดีโอ
ถ้าไม่มีข้อมูลราคา/สเปก ห้ามแต่งขึ้นเอง

JSON SCHEMA
{{
  "title": "string",
  "hook": "string",
  "cta": "string",
  "scenes": [
    {{
      "index": 1,
      "duration_seconds": 4.0,
      "narration": "string",
      "on_screen_text": "string",
      "visual_prompt": "string",
      "camera": "string",
      "transition": "string"
    }}
  ],
  "metadata": {{
    "language": "th-TH",
    "platform": "{brief.platform}",
    "brand": "{brand.key}"
  }}
}}
""".strip()
