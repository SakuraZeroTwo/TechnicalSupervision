from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import datetime
import os

def create_word_report(data: dict, image_path: str) -> str:
    """
    根据分析数据和图片生成 Word 报告.

    Args:
        data (dict): 包含报告所需内容的字典.
                     例如: {'description': '...', 'analysis': '...', 'suggestions': '...'}
        image_path (str): 要插入报告中的图片路径.

    Returns:
        str: 生成的 .docx 文件路径.
    """
    document = Document()

    # --- 标题 ---
    title = document.add_heading('电力设备巡检报告', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # --- 元数据 ---
    document.add_paragraph(f"报告日期: {datetime.date.today().strftime('%Y-%m-%d')}")
    document.add_paragraph(f"报告编号: EPIR-{datetime.date.today().strftime('%Y%m%d')}")
    document.add_paragraph("-" * 20)

    # --- 问题描述 ---
    document.add_heading('1. 问题描述', level=1)
    document.add_paragraph(data.get('description', '无'))

    # --- 问题照片 ---
    document.add_heading('2. 问题照片', level=1)
    try:
        document.add_picture(image_path, width=Inches(5.0))
    except FileNotFoundError:
        document.add_paragraph("图片文件未找到。")

    # --- 原因分析 ---
    document.add_heading('3. 原因分析 (VLM)', level=1)
    document.add_paragraph(data.get('analysis', '无'))

    # --- 监督意见 ---
    document.add_heading('4. 监督意见', level=1)
    document.add_paragraph(data.get('suggestions', '无'))

    # --- 相关条例 ---
    document.add_heading('5. 相关技术细则', level=1)
    document.add_paragraph(data.get('regulations', '无'))

    # --- 保存文件 ---
    output_filename = f"report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    output_path = os.path.join('static', 'reports', output_filename)

    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    document.save(output_path)
    return output_path
